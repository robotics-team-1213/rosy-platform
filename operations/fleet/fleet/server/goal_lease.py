"""D-550 10: Fleet navigation goal leases — send ``lease_ttl_s`` and renew it (default off).

Kept out of ``console.py`` (size budget). ``GoalLeases`` is the console's ``robot_id -> lease``
table: ``{"state": "leased", "correlation_id", "ttl_s", "source", "task_id"}`` or
``{"state": "unbounded"}`` (leases on, robot without the capability: Rule M display).

One renewer per goal source (D-550 10), each only while its reason to move holds:

- ``operator`` (console goal, intent, D-463 route, queued release): the console loop, only while a
  named operator console sent ``POST /api/fleet/goal-lease/presence`` within the last ttl.
- ``dispatch`` (D-316 attempt): the console loop, only while that attempt is open in the task store.
- ``yield`` (bay goal of ``_make_room``): the console loop, only while that robot is still yielding.
- ``trip``: the trip loop, each step.

Renewal of a goal stops on a console cancel (also the internal route/trust/hold cancels), an
E-stop, or CORE's 409 or 403. Fleet stopping stops it all: CORE cancels each goal within ttl.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from typing import Callable, Optional

from fleet.server.named_stop_motion import (NamedStopMotion, _is_unreachable, current_repark_alignment,
                                             verify_release_proof)
from fleet.swarm.api.ports import RobotApiError
from fleet.swarm.dispatch_guard import dispatch_guard
from fleet.swarm.motion_ingress import PREPARED_GOALS, starts_or_sustains_motion
from fleet.swarm.navigation_transport import goal_lease_supported

logger = logging.getLogger("fleet.goal_lease")

SOURCES = ("operator", "dispatch", "yield", "trip")
HANDOFF_LEASE_TTL_S = 5.0  # D-550 10 CORE maximum; handoff must expire even with no reply.
_prepared_wire = ContextVar("prepared_stop_wire", default=None)
_repark_wire = ContextVar("named_stop_repark_wire", default=None)
_REPARK_PATH = "/api/v1/motion/repark/run"


class CustodyReleaseRefused(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class NavigationStopped(RuntimeError):
    """A changed stop token invalidated this navigation continuation."""


class GoalLeases(dict):
    def __init__(self, ttl_s: float, clients: dict, clock: Callable[[], float] = time.monotonic,
                 yielding: Callable[[str], bool] = lambda _robot_id: False) -> None:
        super().__init__()
        #: ``fleet.goal_lease_ttl_s``; 0 = off: no lease field is ever sent, nothing is shown.
        self.ttl_s = ttl_s
        self._clients = clients  # the console's live roster dict
        self._clock = clock
        self._yielding = yielding
        #: ``(task_id, attempt_id) -> bool``: the D-316 attempt is still open. Set by app.py when
        #: there is a task store; without one a dispatch lease is never renewed (it expires).
        self.attempt_open: Optional[Callable[[str, str], bool]] = None
        self.admit_attempt: Optional[Callable[[str, str], None]] = None
        self.bind_native_receipt = None
        self.native_required = None
        self.prepare_send = None
        self.selected_context = None
        self._present_at: Optional[float] = None
        self.pending: dict[str, int] = {}
        self._stop_epoch = 0
        self._stop_generation: dict[str, int] = {}
        self._submission_generation: dict[str, int] = {}
        self._named_stop_motion: NamedStopMotion | None = None
        self._named_stop_store = None
        self._custody_since = 0.0
        self._custody_missing = ""
        self.motion_epoch = 0
        self._motion_requests = 0
        self._uncertain_motion: set[str] = set()

    @contextmanager
    def motion_wire(self, robot_id, method, path, body):
        if method.upper() == "POST" and path in PREPARED_GOALS:
            permit = _prepared_wire.get()
            if permit is None or permit[0] is not self or permit[1:] != (robot_id, (body or {}).get("plan_id")):
                raise RobotApiError(robot_id, 409, "NAMED_STOP_SITE_RESERVED", "prepared motion needs the site reservation")
            yield
            return
        claim = self._named_stop_motion
        if (path == "/api/v1/navigation/goal/lease" and claim is not None and claim.robot_id == robot_id
                and (body or {}).get("correlation_id") == claim.correlation_id):
            yield
            return
        if method.upper() == "POST" and path == _REPARK_PATH:
            permit = _repark_wire.get()
            if (claim is None or permit is None or permit[0] is not self or permit[1] is not claim
                    or claim.robot_id != robot_id or permit[2] is not body
                    or claim.repark_correlation_id != body.get("correlation_id")):
                raise RobotApiError(robot_id, 409, "NAMED_STOP_SITE_RESERVED", "repark needs the exact site reservation")
            yield
            return
        if not starts_or_sustains_motion(method, path, body):
            yield
            return
        def unresolved():
            self._uncertain_motion.add(robot_id)
            self.motion_epoch += 1

        try:
            with self.motion_request():
                yield unresolved
        except NavigationStopped as exc:
            raise RobotApiError(robot_id, 409, "NAMED_STOP_SITE_RESERVED", str(exc)) from exc

    @contextmanager
    def motion_request(self):
        self.check_motion()
        self.motion_epoch += 1
        self._motion_requests += 1
        try:
            yield
        finally:
            self._motion_requests -= 1

    def restore_named_stop(self, store) -> None:
        self._named_stop_motion = store.current()
        self._named_stop_store = store
        self._note_custody()

    def _note_custody(self) -> None:
        self._custody_since, self._custody_missing = self._clock(), "no readback yet"

    def way_out(self, robot_id: str) -> str:
        return ("Wait for CORE to prove the robot stopped, or release custody with "
                f"POST /api/fleet/robots/{robot_id}/named-stop-custody/release (reservation_id, reason, "
                "and optional physical_isolation when isolated/offline).")

    def _bind_discovered_run(self, claim: NamedStopMotion, repark: str | None, known_run: str | None) -> bool:
        run = claim.repark_run_id if repark is not None else claim.run_id
        if known_run is not None or run is None or self._named_stop_store is None:
            return True
        bind = self._named_stop_store.bind_repark_run if repark is not None else self._named_stop_store.bind_run
        try:
            if bind(claim):
                return True
        except sqlite3.Error:
            pass
        if repark is not None:
            claim.repark_run_id = None
        else:
            claim.run_id = None
        claim.stopped_epoch = claim.terminal_at = claim.zero_at = None
        return False

    async def release_by_operator(self, robot_id: str, reservation_id: str, actor: str, reason: str, *,
                                  stop, audit, physical_isolation=None) -> dict:
        """Fail-closed operator release: require live CORE stop proof or uncontradicted physical isolation."""
        claim = self._named_stop_motion
        if claim is None or claim.robot_id != robot_id or claim.reservation_id != reservation_id:
            raise CustodyReleaseRefused("NAMED_STOP_CLAIM_CHANGED", "no such claim for this robot and reservation_id")
        if robot_id in self.pending:
            raise CustodyReleaseRefused("ROBOT_REQUEST_IN_FLIGHT", f"Fleet has a request in flight to {robot_id}")
        repark = claim.repark_correlation_id
        known_run = claim.repark_run_id if repark is not None else claim.run_id
        snapshot = (claim.run_id, repark, claim.repark_run_id)
        self.pending[robot_id] = 1  # holds off other sends and reconciler for the entire release
        stop_error, stop_responded = None, False
        try:
            if robot_id not in self._clients:
                self._stop_generation[robot_id] = self._stop_generation.get(robot_id, 0) + 1
                self.pop(robot_id, None)
                try:
                    await stop(robot_id)
                except Exception as exc:
                    stop_error = exc
                stops = "absent"
            else:
                try:
                    receipt = await stop(robot_id)
                    stop_responded = True
                except Exception as exc:
                    stop_error = exc
                    stops = f"failed: {exc!r}"
                    stop_responded = not _is_unreachable(exc)
                else:
                    if (not isinstance(receipt, dict) or receipt.get("canceled") is False
                            or receipt.get("accepted") is False or receipt.get("navigation") == "NAVIGATING"):
                        stop_error = RuntimeError(f"navigation cancel unconfirmed: {receipt!r}")
                        stops = f"unconfirmed: {receipt!r}"
                    else:
                        stops = "ok"
            if self._named_stop_motion is not claim:
                raise CustodyReleaseRefused("NAMED_STOP_CLAIM_CHANGED", "the claim ended or changed meanwhile")
            try:
                proof = await verify_release_proof(
                    claim, self._clients.get(robot_id), physical_isolation,
                    cancel_error=stop_error, stop_responded=stop_responded, refuse=CustodyReleaseRefused)
            finally:
                bound = self._bind_discovered_run(claim, repark, known_run)
            if not bound:
                raise CustodyReleaseRefused("NAMED_STOP_RELEASE_NOT_STORED", "could not persist discovered run_id")
            if (self._named_stop_motion is not claim or claim.repark_correlation_id != snapshot[1]
                    or (snapshot[0] is not None and claim.run_id != snapshot[0])
                    or (snapshot[2] is not None and claim.repark_run_id != snapshot[2])):
                raise CustodyReleaseRefused("NAMED_STOP_CLAIM_CHANGED", "the claim ended or changed meanwhile")
            try:
                audit(stops, proof)
            except Exception as exc:
                logger.exception("named-stop custody release of %s not audited", robot_id)
                raise CustodyReleaseRefused("AUDIT_UNAVAILABLE", "the release could not be audited; nothing was released") from exc
            self._release_named_stop(claim, f"operator {actor} released it ({proof}): {reason}; stop {stops}")
            if self._named_stop_motion is not None:
                raise CustodyReleaseRefused("NAMED_STOP_RELEASE_NOT_STORED", "the site journal did not record the release")
            return {"released": True, "reservation_id": reservation_id, "stop": stops, "proof": proof}
        finally:
            self.pending.pop(robot_id, None)

    def holds_custody(self, robot_id: str) -> bool:
        claim = self._named_stop_motion
        return claim is not None and claim.robot_id == robot_id

    def custody_view(self, robot_id: str) -> Optional[dict]:
        """The site-wide named-stop claim as the console shows it on its robot's row."""
        claim = self._named_stop_motion
        if claim is None or claim.robot_id != robot_id:
            return None
        return {"reservation_id": claim.reservation_id, "age_s": round(self._clock() - self._custody_since, 1),
                "missing_proof": self._custody_missing, "motion_refused_site_wide": True,
                "operator_action": self.way_out(robot_id)}

    def _reserve_named_stop(self, claim: NamedStopMotion) -> None:
        store = self._named_stop_store
        try:
            if store is not None and not store.claim(claim):
                self._named_stop_motion = store.current()
                raise NavigationStopped("a named stop already holds the persisted site reservation")
        except sqlite3.Error as exc:
            raise NavigationStopped("named-stop reservation could not be durably stored") from exc
        self._named_stop_motion = claim
        self._note_custody()

    def _release_named_stop(self, claim: NamedStopMotion, reason: str) -> None:
        if self._named_stop_motion is not claim:
            return
        try:
            if self._named_stop_store is not None and not self._named_stop_store.release(claim):
                return
        except sqlite3.Error:
            return
        self._named_stop_motion = None
        logger.warning("named-stop custody of %s released: %s", claim.robot_id, reason)

    def check_motion(self) -> None:
        if self._named_stop_motion is not None:
            raise NavigationStopped("a named stop still holds the site navigation reservation")

    def named_repark_armed(self, robot_id) -> bool:
        claim = self._named_stop_motion
        return claim is not None and claim.robot_id == robot_id and claim.repark_correlation_id is not None

    async def send_named_repark(self, robot_id, client, body, *, ready):
        claim = self._named_stop_motion
        store = self._named_stop_store
        if (claim is None or store is None or claim.robot_id != robot_id or claim.run_id is None
                or claim.repark_correlation_id is not None or self._clients.get(robot_id) is not client
                or robot_id in self.pending or body.get("expected_nav_run_id") != claim.run_id
                or body.get("expected_boot_id") != claim.boot_id
                or body.get("expected_nav_correlation_id") != claim.correlation_id):
            raise NavigationStopped("the original named-stop reservation is required for repark")
        stop = self.stop_token(robot_id)
        body = dict(body, correlation_id=f"repark-{claim.reservation_id}")

        def check_ready():
            self.check_stop(robot_id, stop)
            if (self._named_stop_motion is not claim or self._clients.get(robot_id) is not client
                    or ready() is not True):
                raise NavigationStopped("the named-stop repark admission changed")

        check_ready()
        try:
            if not store.arm_repark(claim, body["correlation_id"]):
                raise NavigationStopped("repark reservation no longer belongs to this request")
        except sqlite3.Error as exc:
            raise NavigationStopped("repark reservation could not be durably stored") from exc
        claim.repark_correlation_id = body["correlation_id"]
        claim.stopped_epoch = claim.terminal_at = claim.zero_at = None
        self.pending[robot_id] = 1
        permit = _repark_wire.set((self, claim, body))
        try:
            with dispatch_guard(check_ready, paths={_REPARK_PATH}):
                # Once armed only exact readback can close custody, including failures and lost replies.
                try:
                    result = await client._post(_REPARK_PATH, body)
                finally:
                    if stop != self.stop_token(robot_id):  # a stop raced the POST: end what may have started
                        await self._stop_repark(robot_id, client)
            if stop != self.stop_token(robot_id):
                raise NavigationStopped("repark overlapped a stop; result remains unknown")
            return result
        finally:
            _repark_wire.reset(permit)
            self.pending.pop(robot_id, None)

    async def confirm_named_precision(self, robot_id, operation, *, ready):
        claim = self._named_stop_motion
        client = self._clients.get(robot_id)
        if claim is None:
            store = self._named_stop_store
            if store is None or client is None or robot_id in self.pending:
                return False
            motion_epoch = self.motion_epoch
            stop = self.stop_token(robot_id)
            try:
                result = store.repark_completion(robot_id, operation)
                current = result is not None and await current_repark_alignment(client, result, ready)
            except Exception:
                return False
            if (current and self._named_stop_motion is None and self._clients.get(robot_id) is client
                    and motion_epoch == self.motion_epoch and stop == self.stop_token(robot_id)):
                return result
            return False
        if (claim.robot_id != robot_id or not claim.precision_required
                or client is None or claim.run_id is None or claim.repark_correlation_id is not None
                or robot_id in self.pending or claim.operation(operation)["result"] != "SUCCEEDED"):
            return False
        stop = self.stop_token(robot_id)
        try:
            stopped = await claim.stopped(client, aligned=ready)
        except Exception:
            return False
        if not stopped or not claim.nav_succeeded:
            return False
        if (self._named_stop_motion is not claim or claim.repark_correlation_id is not None
                or self._clients.get(robot_id) is not client or stop != self.stop_token(robot_id)):
            return False
        self._release_named_stop(claim, "precision stop aligned and CORE proved Nav2 stopped")
        return self._named_stop_motion is None

    async def _reconcile_named_stop(self) -> None:
        claim = self._named_stop_motion
        if claim is None or claim.robot_id in self.pending:
            return
        client = self._clients.get(claim.robot_id)
        repark = claim.repark_correlation_id
        known_run = claim.repark_run_id if repark is not None else claim.run_id
        if client is None:  # no client does not prove a stop: a missing credential or a config edit also empties the roster
            self._custody_missing = "this Fleet has no client for the robot (not on its roster)"
            return
        new_boot = False
        try:
            stopped = await claim.stopped(client)
            self._custody_missing = claim.missing
        except Exception as exc:
            stopped = False
            self._custody_missing = f"CORE readback of the run failed: {exc!r}"
            if repark is not None:
                claim.stopped_epoch = claim.terminal_at = claim.zero_at = None
            try:  # a rebooted robot no longer knows the run, which is not a reason to hold forever
                new_boot = await claim.new_boot_stopped(client)
                self._custody_missing += "; robot reachable with another boot_id but not yet proved standing still"
            except Exception as exc2:
                self._custody_missing += f"; robot unreachable: {exc2!r}"
        if (self._named_stop_motion is not claim or self._clients.get(claim.robot_id) is not client
                or claim.repark_correlation_id != repark):
            return
        if not self._bind_discovered_run(claim, repark, known_run):
            return
        if new_boot:
            self._release_named_stop(claim, "robot runs a new boot_id and CORE shows it standing still with no owner run")
        elif stopped and (repark is not None or not claim.precision_required or not claim.nav_succeeded):
            self._release_named_stop(claim, "CORE proved the exact run stopped and measured zero velocity twice")

    def handover_token(self, robot_id: str) -> tuple[int, int, int]:
        """Observe even an unacknowledged new send; projection identity alone is insufficient."""
        return (*self.stop_token(robot_id), self._submission_generation.get(robot_id, 0))

    def operator_present(self) -> None:
        """A named operator's console is open (``POST /api/fleet/goal-lease/presence``)."""
        self._present_at = self._clock()

    def stop_token(self, robot_id: str) -> tuple[int, int]:
        return self._stop_epoch, self._stop_generation.get(robot_id, 0)

    def check_stop(self, robot_id: str, token: tuple[int, int]) -> None:
        if token != self.stop_token(robot_id):
            raise NavigationStopped("navigation pipeline overlapped a stop; result remains unknown")

    def view(self, robot_id: str, goal: Optional[dict]) -> Optional[dict]:
        """The console goal record with today's lease state (``goal_lease``); as is when none."""
        lease = self.get(robot_id)
        return goal if goal is None or lease is None else {**goal, "goal_lease": lease["state"]}

    async def send(self, robot_id: str, client, caps: Optional[dict], x: float, y: float, yaw: float,
                   correlation_id: Optional[str], source: Optional[str] = None,
                   task_id: Optional[str] = None, *, expected_map_grid_id: str | None = None,
                   line_handoff: dict | None = None, owner_epoch: dict | None = None,
                   plan_id: str | None = None, precision_required: bool = False) -> dict:
        """Send one navigation goal; leased with the capability (a lease is renewed by correlation
        id, so a goal without an attempt id gets one), otherwise exactly as before. ``source``
        defaults to ``dispatch`` with an attempt id, else ``operator``."""
        return await self._dispatch(
            robot_id, client, caps, lambda options: client.navigation_goal(x, y, yaw, **options),
            correlation_id, source, task_id, expected_map_grid_id=expected_map_grid_id,
            line_handoff=line_handoff, owner_epoch=owner_epoch, plan_id=plan_id,
            precision_required=precision_required)

    async def send_route(self, robot_id: str, client, caps: Optional[dict], points: list[dict],
                         correlation_id: Optional[str] = None, source: Optional[str] = None,
                         task_id: Optional[str] = None, *, expected_map_grid_id: str | None = None,
                         recheck=None) -> dict:
        """Send one D-1009 pass/stop route under the goal lease."""
        async def send(options):
            if recheck is not None:
                await recheck()
            return await client.navigation_route(points, **options)

        return await self._dispatch(robot_id, client, caps, send, correlation_id, source, task_id,
                                    expected_map_grid_id=expected_map_grid_id)

    async def _dispatch(self, robot_id: str, client, caps: Optional[dict], sender: Callable[[dict], object],
                        correlation_id: Optional[str], source: Optional[str] = None,
                        task_id: Optional[str] = None, *, expected_map_grid_id: str | None = None,
                        line_handoff: dict | None = None, owner_epoch: dict | None = None,
                        plan_id: str | None = None, precision_required: bool = False) -> dict:
        source = source or ("dispatch" if correlation_id is not None else "operator")
        self.check_motion()
        if source not in SOURCES:
            raise ValueError(f"unknown goal lease source {source!r}")
        supported = goal_lease_supported(caps)
        if plan_id is not None and not supported:
            raise NavigationStopped("NAMED_STOP_GOAL_LEASE_REQUIRED")
        ttl_s = self.ttl_s or (HANDOFF_LEASE_TTL_S if plan_id is not None else 0.0)
        gen = self._submission_generation[robot_id] = self._submission_generation.get(robot_id, 0) + 1
        stop = self.stop_token(robot_id)
        prev = self.pop(robot_id, None)
        options = {}
        if expected_map_grid_id is not None:
            options["expected_map_grid_id"] = expected_map_grid_id
        if plan_id is not None:
            options["plan_id"] = plan_id
        if owner_epoch is not None:
            options.update(owner_epoch)
        if line_handoff is not None:
            options["line_handoff"] = line_handoff
        lease = {"state": "unbounded"}
        if ttl_s > 0 and supported:
            correlation_id = correlation_id or f"fleet-lease-{uuid.uuid4().hex}"
            options["lease_ttl_s"] = ttl_s
            lease = {"state": "leased", "correlation_id": correlation_id,
                     "ttl_s": ttl_s, "source": source, "task_id": task_id}
        if correlation_id is not None:
            options["correlation_id"] = correlation_id
        claim = None

        def admit_wire():
            if claim is not None and self._named_stop_motion is claim:
                return
            self.check_motion()
            if claim is not None:
                if sum(self.pending.values()) != 1 or self._motion_requests:
                    raise NavigationStopped("another navigation submission is in progress")
                if self._uncertain_motion:
                    raise NavigationStopped("an earlier motion request has no confirmed outcome")
                self._reserve_named_stop(claim)

        guard = nullcontext()
        if self.prepare_send is not None:
            guard = await self.prepare_send(task_id, correlation_id, robot_id, client, options, stop)
        elif task_id is not None and self.admit_attempt is not None:
            self.admit_attempt(task_id, correlation_id)
        if plan_id is not None:
            boot = options.get("expected_boot_id")
            if not boot or not correlation_id:
                raise ValueError("NAMED_STOP_NATIVE_OWNER_REQUIRED")
            if precision_required and self._named_stop_store is None:
                raise NavigationStopped("precision stop requires the Fleet site journal")
            claim = NamedStopMotion(robot_id, boot, correlation_id, precision_required=precision_required)
        self.pending[robot_id] = self.pending.get(robot_id, 0) + 1
        permit = _prepared_wire.set((self, robot_id, plan_id) if claim is not None else None)
        try:
            try:
                with guard, dispatch_guard(admit_wire, paths={
                        "/api/v1/navigation/goal", "/api/v1/navigation/bound-goal", "/api/v1/navigation/line-handoff-goal",
                        "/api/v1/navigation/bound-route"}):
                    result = await sender(options)
                    if claim is not None and self._named_stop_motion is claim:
                        if not isinstance(result, dict) or result.get("accepted") is not True:
                            raise RuntimeError("missing named-stop admission acknowledgement")
                        claim.run_id = claim.operation(result.get("operation"))["run_id"]
                        if self._named_stop_store is not None and not self._named_stop_store.bind_run(claim):
                            raise NavigationStopped("accepted named-stop run could not be bound to its reservation")
                    if task_id is not None and self.bind_native_receipt is not None:
                        self.bind_native_receipt(task_id, correlation_id, robot_id, result,
                                                 expected_boot_id=options.get('expected_boot_id'))
            except (Exception, asyncio.CancelledError) as exc:
                if (claim is not None and self._named_stop_motion is claim and isinstance(exc, RobotApiError)
                        and exc.robot_id == robot_id and (exc.detail or {}).get("plan_id") == plan_id
                        and exc.detail.get("native_admitted") is False):
                    self._release_named_stop(claim, "CORE explicitly refused the goal before admission")
                if stop != self.stop_token(robot_id):
                    try:
                        await client.navigation_cancel()
                    except Exception:
                        logger.exception("late goal cancel for %s failed", robot_id)
                elif (prev is not None and getattr(exc, "code", None) == "NAVIGATION_ACTIVE"
                      and self._submission_generation.get(robot_id) == gen and robot_id not in self):
                    self[robot_id] = prev
                raise
            if (stop != self.stop_token(robot_id)
                    and not (isinstance(result, dict) and result.get("accepted") is False)):
                try:
                    await client.navigation_cancel()
                except Exception:
                    logger.exception("late accepted goal cancel for %s failed", robot_id)
                raise NavigationStopped("navigation goal overlapped a stop; result remains unknown")
        finally:
            _prepared_wire.reset(permit)
            self.pending[robot_id] -= 1
            if not self.pending[robot_id]:
                del self.pending[robot_id]
        if not isinstance(result, dict) or type(result.get("accepted")) is not bool:
            raise RuntimeError("missing navigation goal acknowledgement")
        if result["accepted"] and ttl_s > 0:
            self[robot_id] = lease
        return result

    def clear(self) -> None:
        self._stop_epoch += 1
        self._stop_generation.clear()
        super().clear()

    async def cancel(self, robot_id: str, client) -> dict:
        """``navigation_cancel`` for the console: the lease stops first, whether the cancel lands or not.
        A named-stop correction is a re-park, not a Nav2 goal, so it gets its own stop."""
        self._stop_generation[robot_id] = self._stop_generation.get(robot_id, 0) + 1
        self.pop(robot_id, None)
        claim = self._named_stop_motion
        repark_exc = None
        if claim is not None and claim.robot_id == robot_id and claim.repark_correlation_id is not None:
            try:
                await client.repark_stop()
            except Exception as exc:
                repark_exc = exc
                logger.exception("repark stop for %s failed", robot_id)
        result = await client.navigation_cancel()
        if repark_exc is not None:
            raise repark_exc
        return result

    async def _stop_repark(self, robot_id: str, client) -> None:
        try:
            await client.repark_stop()
        except Exception:
            logger.exception("repark stop for %s failed", robot_id)

    def _due(self, robot_id: str, lease: dict, renewer: str) -> bool:
        source = lease["source"]
        if renewer == "trip":
            return source == "trip"
        if source == "operator":
            return self._present_at is not None and self._clock() - self._present_at <= self.ttl_s
        if source == "dispatch":
            check = self.attempt_open
            return (check is not None and lease["task_id"] is not None
                    and check(lease["task_id"], lease["correlation_id"]))
        if source == "yield":
            return self._yielding(robot_id)
        return False

    async def renew(self, renewer: str = "console", robot_id: Optional[str] = None) -> None:
        """Renew each leased goal of ``renewer`` (``console``: operator, dispatch and yield goals;
        ``trip``: trip goals; only ``robot_id`` when given) whose source still holds. A 409 means
        the goal ended on the robot (arrived, failed, cancelled, replaced, expired), a 403 that this
        client did not send it (D-760 9; CORE expires it): renewal stops either way.
        Any other failure is left to CORE, which cancels the goal when its lease runs out."""
        if renewer == "console":
            await self._reconcile_named_stop()
        for rid, lease in list(self.items()):
            if lease["state"] != "leased" or robot_id not in (None, rid):
                continue
            client = self._clients.get(rid)
            try:
                if client is None or not self._due(rid, lease, renewer):
                    continue
                await client.navigation_goal_lease(lease["correlation_id"], lease["ttl_s"])
            except Exception as exc:  # RobotApiError carries .status; no import (D-430 §3 rule 1)
                status = getattr(exc, "status", None)
                if status in (403, 409) and self.get(rid) is lease:
                    # D-760 9: 403 = this client is not the goal's sender; CORE will expire it
                    self.pop(rid, None)
                    if status == 403:
                        logger.warning("goal lease renewal for %s refused (not the sender): %s", rid, exc)
                else:
                    logger.warning("goal lease renewal for %s failed: %s", rid, exc)
