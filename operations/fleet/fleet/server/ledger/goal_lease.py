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
import time
import uuid
from contextlib import nullcontext
from typing import Callable, Optional

logger = logging.getLogger("fleet.goal_lease")

SOURCES = ("operator", "dispatch", "yield", "trip")


class NavigationStopped(RuntimeError):
    """A changed stop token invalidated this navigation continuation."""


def goal_lease_supported(caps: Optional[dict]) -> bool:
    """The robot's rosy.controls/1 base announces ``goal_lease: true``. An older CORE would
    ignore ``lease_ttl_s``, so without it a Fleet goal is unbounded."""
    items = (((caps or {}).get("controls") or {}).get("items") or []) if isinstance(caps, dict) else []
    return any(isinstance(item, dict) and item.get("kind") == "base_velocity"
               and item.get("goal_lease") is True for item in items)


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
                   task_id: Optional[str] = None) -> dict:
        """Send one navigation goal; leased with the capability (a lease is renewed by correlation
        id, so a goal without an attempt id gets one), otherwise exactly as before. ``source``
        defaults to ``dispatch`` with an attempt id, else ``operator``."""
        source = source or ("dispatch" if correlation_id is not None else "operator")
        if source not in SOURCES:
            raise ValueError(f"unknown goal lease source {source!r}")
        self._submission_generation[robot_id] = self._submission_generation.get(robot_id, 0)+1
        stop = self.stop_token(robot_id)
        self.pop(robot_id, None)
        options = {}
        lease = {"state": "unbounded"}
        if self.ttl_s > 0 and goal_lease_supported(caps):
            correlation_id = correlation_id or f"fleet-lease-{uuid.uuid4().hex}"
            options["lease_ttl_s"] = self.ttl_s
            lease = {"state": "leased", "correlation_id": correlation_id,
                     "ttl_s": self.ttl_s, "source": source, "task_id": task_id}
        if correlation_id is not None:
            options["correlation_id"] = correlation_id
        guard = nullcontext()
        if self.prepare_send is not None:
            guard = await self.prepare_send(task_id, correlation_id, robot_id, client, options, stop)
        elif task_id is not None and self.admit_attempt is not None:
            self.admit_attempt(task_id, correlation_id)
        self.pending[robot_id] = self.pending.get(robot_id, 0) + 1
        try:
            try:
                with guard:
                    result = await client.navigation_goal(x, y, yaw, **options)
                    if task_id is not None and self.bind_native_receipt is not None:
                        self.bind_native_receipt(task_id, correlation_id, robot_id, result,
                                                 expected_boot_id=options.get('expected_boot_id'))
            except (Exception, asyncio.CancelledError):
                if stop != self.stop_token(robot_id):
                    try:
                        await client.navigation_cancel()
                    except Exception:
                        logger.exception("late goal cancel for %s failed", robot_id)
                raise
            if (stop != self.stop_token(robot_id)
                    and not (isinstance(result, dict) and result.get("accepted") is False)):
                try:
                    await client.navigation_cancel()
                except Exception:
                    logger.exception("late accepted goal cancel for %s failed", robot_id)
                raise NavigationStopped("navigation goal overlapped a stop; result remains unknown")
        finally:
            self.pending[robot_id] -= 1
            if not self.pending[robot_id]:
                del self.pending[robot_id]
        if not isinstance(result, dict) or type(result.get("accepted")) is not bool:
            raise RuntimeError("missing navigation goal acknowledgement")
        if result["accepted"] and self.ttl_s > 0:
            self[robot_id] = lease
        return result

    def clear(self) -> None:
        self._stop_epoch += 1
        self._stop_generation.clear()
        super().clear()

    async def cancel(self, robot_id: str, client) -> dict:
        """``navigation_cancel`` for the console: the lease stops first, whether the cancel lands or not."""
        self._stop_generation[robot_id] = self._stop_generation.get(robot_id, 0) + 1
        self.pop(robot_id, None)
        return await client.navigation_cancel()

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
