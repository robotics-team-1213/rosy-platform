"""D-494 5 / D-517 1: the server trip loop — one running trip per robot, all stepped every 0.5 s.

Each tick reads the robot's Fleet map pose (D-494 3) and, on a lane segment, CORE's junction
state (D-494 4 / D-495) before anything is sent; lane places get CORE junction instructions,
free segments the D-463 point ahead as a goal. Every end of a trip stops the robot (``_halt``).
The protocol, the stop rules and why are in the D-494 implementation appendix (5항 trip 루프);
the robot-facing inputs are ports (``trip_ports``), the plan rules are pure
(``fleet.routing.execute``), and ``trip_guard`` keeps other Fleet motion off a trip robot.
D-517 2: a ``repeat`` trip plans its next lap before the lap's last place; D-517 3: after each
period ``traffic`` (``TrafficService``) computes the block table, which only holds back a junction
instruction into a refused block (M1 sends no authority). Laps: ``trip_laps``; halts: ``trip_halts``.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from contextlib import nullcontext
from typing import Awaitable, Callable, Iterable, Optional

import httpx

from core_common.link_retry import start_offset
from core_common.robot_body import nominal_body_for
from fleet.hub.hub import HubError
from fleet.routing.cost import STOP  # noqa: F401
from fleet.routing.execute import lane_action  # noqa: F401
from fleet.server.trip_admission import LOCALIZED, TripAdmission, cached_battery, start_check  # noqa: F401
from fleet.server.trip_geometry import pose_view  # noqa: F401
from fleet.server.trip_halts import TripHalts, error_code as _code, halt_unconfirmed
from fleet.server.trip_laps import LAP_RETRIES, LAP_RETRY_S, convoy_refusal, stop_points  # noqa: F401
from fleet.server.trip_live import LiveTrip
from fleet.server.trip_ports import (LaneJunctionPort, MapPose, MapPosePort, TripCapsPort, TripConfig,  # noqa: F401
                                     TripError)
from fleet.server.trip_preview import observe
from fleet.server.trip_progress import MANOEUVRE, TripProgress  # noqa: F401
from fleet.server.trip_replan import TripReplan
from fleet.server.trip_runner_helpers import (  # noqa: F401
    TripRunnerHelpers, _ROBOT_ERRORS, _build_started_view, _caps_view,
    _check_start_traffic, _maybe,
)
from fleet.server.trip_station_align import StationAlign
from fleet.server.trip_steps import TripSteps
from fleet.server.named_stop_map_pose import commissioned_stop, precision_line_fence
from fleet.swarm.dispatch_guard import dispatch_guard
from fleet.swarm.transport import RobotApiError
from fleet.traffic.lane_traffic import TrafficService
from fleet.traffic.trip_advice import AdviceSender
from fleet.traffic.trip_authority import AuthoritySender
from fleet.traffic.trip_lease import TripLease

_LOG = logging.getLogger(__name__)

#: D-490 5: a plan may be started within this long on the same map version.
PLAN_TTL_S = 30.0


class TripRunner(TripRunnerHelpers, TripAdmission, TripProgress, TripSteps, TripReplan, StationAlign):
    """Start checks: ``trip_admission``; progress predicates: ``trip_progress``; per-period steps: ``trip_steps``;
    replans and laps: ``trip_replan``; read queries and helpers: ``trip_runner_helpers``."""

    def __init__(self, *, store, routing_config, caps: TripCapsPort, poses: MapPosePort,
                 junction: LaneJunctionPort, goal: Callable[..., Awaitable[dict]],
                 cancel_goal: Callable[[str], Awaitable[dict]],
                 route: Optional[Callable[..., Awaitable[dict]]] = None,
                 blocked: Callable[[], frozenset] = frozenset, clock: Callable[[], float] = time.time,
                 config: TripConfig = TripConfig(),
                 engaged: Callable[[str], Optional[str]] = lambda _robot_id: None,
                 release_queue: Callable[[str], None] = lambda _robot_id: None,
                 roster: Optional[Callable[[], Iterable[str]]] = None,
                 traffic: Optional[TrafficService] = None, traffic_zones=None, authority: bool = False,
                 traffic_signals=(), signal_advice: bool = False, lease: Optional[dict] = None,
                 renew_lease: Optional[Callable[[str], Awaitable[None]]] = None,
                 battery: Optional[Callable[[str], Awaitable[Optional[dict]]]] = None,
                 align_gate: Callable[[str], Optional[str]] = lambda _place: None) -> None:
        self._store = store
        #: Arrival alignment (trip_station_align): place id -> None (may turn) or the reason it may not.
        self._align_gate = align_gate
        #: D-1003: the pose port's robot snapshot (the read its map pose came from); free goals go out in the
        #: robot's own Nav2 map frame. A port without one (test plants) keeps the site frame as is.
        self._robot_state = getattr(poses, "state", None)
        #: D-1010: a port without robot snapshots (D-1003 6) may declare its poses and the robot's
        #: goals one frame; an undeclared port proves nothing, so an unproven free goal stops the trip.
        self._poses_in_robot_frame = bool(getattr(poses, "poses_in_robot_frame", False))
        #: Start admission reads the robot's battery evidence here (``{"battery", "age_s"}``). None: no source,
        #: so every start is refused TRIP_BATTERY_UNCONFIRMED (fail closed; there is no bypass default).
        self._battery = battery
        self._routing = routing_config
        self._caps, self._poses, self._junction = caps, poses, junction
        self._goal, self._route, self._cancel_goal = goal, route, cancel_goal
        self.navigation_readback = None
        self.named_stop_state = None
        self.confirm_named_precision = None
        self.check_named_correction = None
        self.auto_named_correction = None
        #: D-550 10: renews the robot's leased trip goal each step (console.renew_goal_leases).
        self._renew_lease = renew_lease
        #: Edges an operator or the traffic layer closed; a remaining one means "replan" (D-489 9).
        self._blocked = blocked
        self._clock = clock
        self.config = config
        #: Console motion the robot already has (``trip_guard.engaged``); a start refuses then.
        self._engaged, self._release_queue, self._roster = engaged, release_queue, roster
        #: D-517 1: robot id -> its trip (open, or the last one it ran).
        self._live: dict[str, LiveTrip] = {}
        self._aligning: set[str] = set()
        self._align_submitting: set[str] = set()
        self._align_outcome_unknown: set[str] = set()
        self._unconfirmed_align_stops: set[str] = set()
        self._stop_epoch = 0
        self._start_cancels: dict[str, int] = {}
        self.autonomous_robots: frozenset[str] = frozenset()
        self._locks: dict[str, asyncio.Lock] = {}
        self.charge_goal_ready = None  # Explicit charge-only native-readiness dependency.
        #: robot id -> its step still running; that robot skips periods until it ends (D-517 7).
        self._inflight: dict[str, asyncio.Future] = {}
        self.traffic = traffic if traffic is not None else TrafficService(store, config, zones=traffic_zones,
                                                                          signals=traffic_signals)
        self.authority = AuthoritySender(junction, authority, config.port_timeout_s, clock=clock)  # D-517 4 (M2)
        self.traffic.authority_reach, self._unread, self._read_after = self.authority.reach, set(), {}  # D-760 3; 4 state reads; 8 read fence
        self.advice = AdviceSender(junction, self.traffic, signal_advice)  # D-551, display only
        self.lease = TripLease(junction, time.monotonic, config.port_timeout_s, self._lease_lost, **(lease or {}))  # D-541 7
        self.held_stops: dict[str, tuple] = {}  # robot id -> (seq, place) of the stop its last lane arrival left held
        self._refresh_warned_at = -math.inf
        self.halts = TripHalts(store, junction, config, self._call, clock, cancel_goal,
                               lambda robot_id: self._release_queue(robot_id), self.robot_busy, roster,
                               lock_for=self._lock_for)

    # ---- operator actions -------------------------------------------------------------

    def _check_human_hold(self) -> None:
        check = getattr(self, "human_hold_fn", None)
        if callable(check) and check():
            raise TripError(409, "HUMAN_HOLD")

    async def start(self, plan_id: str, principal_id: str, job_id: Optional[str] = None, start_token=None,
                    start_guard=None, purpose: Optional[str] = None) -> dict:
        row = self._store.plan(plan_id)
        plan = (row or {}).get("result", {}).get("plan")
        if plan is None:
            raise TripError(404, "TRIP_PLAN_UNKNOWN")
        robot_id = row["robot_id"]
        start_token = self._start_token(robot_id) if start_token is None else start_token  # a job: before its plan
        async with self._lock_for(robot_id):
            if self._store.trip(plan_id) is not None:
                raise TripError(409, "TRIP_ALREADY_STARTED")
            if self._clock() - row["created_at"] > PLAN_TTL_S:
                raise TripError(422, "TRIP_PLAN_EXPIRED", {"ttl_s": PLAN_TTL_S})
            repeat = bool((row.get("request") or {}).get("repeat"))
            nav2 = (row.get("request") or {}).get("drive_mode") == "nav2"
            graph = self._graph_for(plan["map_version"])
            precision = commissioned_stop(graph, (row.get("request") or {}).get("to"))
            if nav2 and precision is not None:
                raise TripError(422, "PRECISION_STOP_REQUIRES_NAV2_TERMINAL")
            precision_scope = None
            if precision is not None:
                if not self._precision_terminal_matches(graph, plan["segments"], precision):
                    raise TripError(422, "PRECISION_STOP_REQUIRES_NAV2_TERMINAL")
                binding_id = plan.get("precision_binding_id")
                if binding_id is None:
                    binding_id = (self._store.map_bindings.active(robot_id) or {}).get("binding_id")
                if binding_id is None:
                    raise TripError(409, "TRIP_POSE_UNTRUSTED", {"reason": "APPROVED_SLAM_POSE_REQUIRED"})
                precision_scope = plan["map_version"], binding_id
            notes = {"drive_mode": "nav2"} if nav2 else {}
            caps = await self._caps_checks(robot_id, graph, plan["segments"], repeat,
                                           plan["actions"][-1]["place_id"], detail=notes, nav2=nav2)
            body = nominal_body_for(caps.kind)
            pending = self.halts.pending_handoffs.get(robot_id)
            if pending is not None:
                raise TripError(409, "TRIP_ROBOT_BUSY",
                                {"reason": "handoff_stop_unverified", "trip_id": pending["trip_id"]})
            prev_live = self._live.get(robot_id)
            if prev_live is not None and not prev_live.open and halt_unconfirmed(prev_live.view.get("detail")):
                raise TripError(409, "TRIP_ROBOT_BUSY",
                                {"reason": "prior_stop_unconfirmed", "trip_id": prev_live.view["trip_id"]})
            if robot_id in self._unconfirmed_align_stops:
                raise TripError(409, "TRIP_ROBOT_BUSY", {"reason": "prior_align_stop_unconfirmed"})
            if self.robot_busy(robot_id):
                raise TripError(409, "TRIP_BUSY", {"trip_id": self._live[robot_id].view["trip_id"]})
            if self.lease.job_of(robot_id) not in (None, job_id):  # D-763 6: a job holds it; before any turn
                raise TripError(409, "TRIP_ROBOT_BUSY", {"reason": "job", "owner_kind": "mission"})
            self._check_engaged(robot_id)
            self._check_human_hold()
            if purpose != "charge_return":  # D-1029: the way to a charger, like a charge_session job; CORE keeps 10 %/5 %
                await self._check_battery(robot_id)
            await self._guard_start(robot_id, start_token, start_guard)
            start_at = (row.get("request") or {}).get("start_at")
            pose, enable, turns = await self._start_pose(
                robot_id, graph, plan["segments"], principal_id, start_at=start_at, caps=caps,
                start_token=start_token, start_guard=start_guard, nav2=nav2,
                precision_scope=precision_scope)
            await self._guard_start(robot_id, start_token, start_guard)
            pose_observed_at = self._clock()
            lease = await self.lease.open(robot_id, {"trip_id": plan_id, "started_by": principal_id, "job_id": job_id,
                                                  "purpose": purpose}, caps)
            try:
                await self._guard_start(robot_id, start_token, start_guard)
                self._check_engaged(robot_id)
                graph = self._graph_for(plan["map_version"])  # the awaits above may have seen an activation
                caps_view = _caps_view(caps)
                plan, request, lap_route, arcs, moved = stop_points(  # D-517 3: no stop inside a zone
                    self._store.active(), plan, row["request"], caps_view, frozenset(self._blocked()), self._routing,
                    self.config.max_turn_deg, self.traffic)
                if start_at is not None and moved is not None:
                    raise TripError(422, "TRIP_START_PLACE_MOVED", moved)
                if precision is not None and not self._precision_terminal_matches(graph, plan["segments"], precision):
                    raise TripError(422, "PRECISION_STOP_REQUIRES_NAV2_TERMINAL")
                leader = _check_start_traffic(self, robot_id, plan, request, arcs, caps, repeat)
            except BaseException:  # the lease opened for a trip that did not start
                if lease is not None:
                    await self.lease.release(robot_id, lease["lease_id"])
                raise
            view = _build_started_view(
                plan_id=plan_id, robot_id=robot_id, principal_id=principal_id, notes=notes,
                plan=plan, pose=pose, now=self._clock(), body=body,
                pose_observed_at=pose_observed_at, repeat=repeat, caps_view=caps_view,
                traffic_authority="hold_back" if nav2 else self.authority.mode(caps), leader=leader,
                lease=lease, moved=moved, enable=enable, turns=turns)
            if purpose is not None:  # D-1029: renews carry it too (CORE refuses a changed purpose)
                view["purpose"] = purpose
            if precision_scope is not None:
                view["detail"]["precision_binding_id"] = precision_scope[1]
            live = LiveTrip(view, graph, request)
            live.inherited = self.held_stops.pop(robot_id, None) if plan["segments"] else None  # D-763 7
            live.lap_route, live.lap_arcs = lap_route, arcs
            self._live[robot_id] = live
            self.halts.clear_robot(robot_id)  # this trip owns it
            if not plan["segments"]:  # D-489 부록 4: already there
                view["state"] = "arrived"
            else:
                self._describe(live)
            self._save(live)
            if enable:  # D-601 A: last, lease held and the trip open, so every end turns it OFF again
                await self._start_line(live)
            return live.view

    async def _start_line(self, live: LiveTrip) -> None:
        """D-601 A: turn CORE's camera line on (it moves at once; the first tick, under this lock after
        the start, sends the next place's instruction). A refusal ends the trip failed and answers the start."""
        robot_id = live.view["robot_id"]
        fence = nullcontext()
        if live.view["detail"].get("precision_binding_id"):
            pose = await self._progress_pose(live, robot_id)
            if pose is None:
                detail = {"reason": "APPROVED_SLAM_POSE_REQUIRED"}
                await self._stop(live, "failed", "TRIP_POSE_UNTRUSTED", detail)
                raise TripError(409, "TRIP_POSE_UNTRUSTED", detail)
            geometry = start_check(live.graph, live.segments, pose.x, pose.y, pose.yaw,
                                   self.config.start_heading_tol_deg)
            if geometry["code"]:
                await self._stop(live, "failed", geometry["code"], geometry)
                raise TripError(409, geometry["code"], geometry)
            check = precision_line_fence(self, live, pose)
            fence = dispatch_guard(check, paths={"/api/v1/line-follow/mode"})
        try:
            with fence:
                if live.view["detail"].get("precision_binding_id"):
                    check()
                await self._call(self._junction.start_camera_line(robot_id))
        except _ROBOT_ERRORS as exc:
            detail = {"error": _code(exc), "status": getattr(exc, "status", None)}
            await self._stop(live, "failed", "TRIP_LINE_FOLLOW_START_FAILED", detail)
            if detail["status"] is None:  # review M: a timed-out PUT may still land after our OFF
                # ponytail: one more OFF after one call bound; a read-back loop if CORE is ever slower
                await asyncio.sleep(self.config.port_timeout_s)
                live.view["detail"].update(await self._halt(live))
                self._save(live)
            raise TripError(409, "TRIP_LINE_FOLLOW_START_FAILED", detail) from exc
        live.view["detail"]["line_follow_started"] = True
        await self._after_send(live)  # a cancel or E-stop that landed meanwhile stops it again
        self._save(live)

    async def cancel(self, trip_id: str, principal_id: Optional[str], reason: Optional[str] = None) -> dict:
        """Immediate: no wait for a tick in flight (that tick halts again if its send lands after)."""
        live = self._open(trip_id)
        live.view.update(state="canceled", reason=reason)
        live.view["detail"]["canceled_by"] = principal_id
        live.view["detail"]["stop_sent"] = False
        halted = await self._halt(live)
        live.view["detail"].update(halted)
        if halted.get("stop_sent") and "error" not in halted:
            live.view["detail"].pop("error", None)
        self._save(live)
        return live.view

    async def retry_halt(self, trip_id: str) -> dict:
        """Re-send robot stop for a canceled trip whose prior halt did not confirm."""
        live = next((lv for lv in self._live.values() if lv.view.get("trip_id") == trip_id), None)
        if live is not None:
            robot_id = live.view["robot_id"]
            async with self._lock_for(robot_id):
                if self._live.get(robot_id) is not live:
                    return {"error": "TRIP_NOT_RUNNING"}
                halted = await self._halt(live)
                live.view["detail"].update(halted)
                if halted.get("stop_sent") and "error" not in halted:
                    live.view["detail"].pop("error", None)
                self._save(live)
                return live.view
        trip = self._store.trip(trip_id)
        if trip is not None and trip.get("state") in ("canceled", "stopped") and halt_unconfirmed(trip.get("detail")):
            robot_id = trip["robot_id"]
            async with self._lock_for(robot_id):
                current = self._live.get(robot_id)
                if current is not None and current.view.get("trip_id") != trip_id:
                    return {"error": "TRIP_NOT_RUNNING"}
                trip = self._store.trip(trip_id)
                if trip is None or trip.get("state") not in ("canceled", "stopped"):
                    return {"error": "TRIP_NOT_RUNNING"}
                detail = dict(trip.get("detail") or {})
                if not halt_unconfirmed(detail):
                    self.halts.clear_trip(trip_id)
                    return trip
                halted = await self.halts.halt_robot(
                    robot_id, trip.get("drive_mode") == "lane", trip.get("next_place"),
                    handoff_pending=bool(detail.get("named_stop_handoff_pending")),
                )
                detail.update(halted)
                if halted.get("stop_sent") and "error" not in halted:
                    detail.pop("error", None)
                updated = {**trip, "detail": detail, "updated_at": self._clock()}
                self._store.put_trip(updated)
                if not halt_unconfirmed(detail):
                    self.halts.clear_trip(trip_id)
                return updated
        return {"error": "TRIP_NOT_RUNNING"}

    def aligning_robots(self) -> list[str]:
        return sorted(self._aligning | self._align_submitting | self._align_outcome_unknown | self._unconfirmed_align_stops)

    async def halt_aligning(self, robot_ids: Iterable[str], *, estop_confirmed_robots: Iterable[str] = ()) -> list[str]:
        """Stop in-flight pre-live alignment rotations without acquiring per-robot start locks."""
        terminal_states = frozenset({"done", "aborted", "stopped", "idle", "failed", "canceled"})
        estopped = set(estop_confirmed_robots)
        unconfirmed: list[str] = []
        for robot_id in sorted(set(robot_ids)):
            try:
                res = await self._call(self._junction.rotate_stop(robot_id))
            except Exception:
                self._unconfirmed_align_stops.add(robot_id)
                unconfirmed.append(robot_id)
                continue
            terminal = isinstance(res, dict) and (res.get("state") in terminal_states or res.get("stopped") is True)
            if robot_id in self._align_submitting:
                self._unconfirmed_align_stops.add(robot_id)
                unconfirmed.append(robot_id)
            elif robot_id in self._align_outcome_unknown:
                # Unkeyed DELETE cannot distinguish an old turn from a delayed POST; require confirmed E-stop latch.
                if robot_id in estopped:
                    self._align_outcome_unknown.discard(robot_id)
                    self._unconfirmed_align_stops.discard(robot_id)
                else:
                    self._unconfirmed_align_stops.add(robot_id)
                    unconfirmed.append(robot_id)
            elif terminal or robot_id in estopped:
                self._unconfirmed_align_stops.discard(robot_id)
            else:
                self._unconfirmed_align_stops.add(robot_id)
                unconfirmed.append(robot_id)
        return unconfirmed

    def close_all(self, reason: str) -> list[LiveTrip]:
        """E-stop (D-517 1): every open trip ends now, before any await, so no step sends after it."""
        self._stop_epoch += 1
        self.held_stops.clear()  # CORE leaves line following: no arrival stop is held any more
        closed = [live for live in self._live.values() if live.open]
        for live in closed:
            live.view.update(state="canceled", reason=reason)
            live.view["detail"]["canceled_by"] = None
            live.view["detail"]["stop_sent"] = False
        return closed

    async def halt_closed(self, lives: list[LiveTrip]) -> None:
        """Stop the robots of ``close_all`` at once (each halt bounded) and record each trip."""
        async def halt(live: LiveTrip) -> None:
            prev_detail = dict(live.view.get("detail") or {})
            halted = await self._halt(live)
            detail = {**prev_detail, **halted}
            if halted.get("stop_sent") and "error" not in halted:
                detail.pop("error", None)
            live.view["detail"] = detail
            try:
                self._save(live)
            except Exception as exc:
                live.view["detail"] = {**prev_detail, "stop_sent": False, "error": f"SAVE_FAILED:{_code(exc)}"}
                raise

        for result in await asyncio.gather(*(halt(live) for live in lives), return_exceptions=True):
            if isinstance(result, BaseException):
                _LOG.error("could not record a trip ended by the E-stop", exc_info=result)

    async def _after_send(self, live: LiveTrip) -> None:
        """A send that was in flight when the trip closed (cancel) is stopped again."""
        if not live.open:
            live.view["detail"].update(await self._halt(live))
            self._save(live)

    async def cancel_robot(self, robot_id: str, reason: str) -> None:
        """The robot's trip ends canceled (``trip_guard``: an operator turned line-follow OFF)."""
        self._start_cancels[robot_id] = self._start_cancels.get(robot_id, 0) + 1
        live = self._live.get(robot_id)
        if live is not None and live.open:
            await self.cancel(live.view["trip_id"], None, reason)

    # ---- loop ---------------------------------------------------------------------------

    async def run(self) -> None:
        """Never returns while the app lives; every failure ends at most the one trip."""
        restart = asyncio.create_task(self.halts.run_restart()) if self.halts.restarted else None
        try:
            await self._loop()
        finally:
            if restart is not None:
                restart.cancel()

    async def _loop(self) -> None:
        # D-432: the first tick runs at once; one random offset after it keeps the 0.5 s loop out of
        # lockstep with Fleet's other periodic loops (gather, lane compliance, tether).
        offset = start_offset(self.config.period_s)
        while True:
            started = time.monotonic()
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # the steps catch their own; this is the traffic table
                _LOG.exception("trip loop tick failed")
            await asyncio.sleep(max(0.0, self.config.period_s + offset - (time.monotonic() - started)))
            offset = 0.0

    async def _loop_failed(self, live: LiveTrip) -> None:
        if not live.open:
            return
        try:
            await self._stop(live, "failed", "TRIP_LOOP_ERROR")
        except Exception:  # the store itself failed: keep the in-memory row closed
            _LOG.exception("trip loop could not record its failure")
            live.view.update(state="failed", reason="TRIP_LOOP_ERROR")

    async def map_pose(self, robot_id: str) -> Optional[MapPose]:
        """The trip map pose (D-494 3) after one forced state read; None when it cannot be read."""
        try:
            if (refresh := getattr(self._poses, "refresh", None)) is not None:  # one forced state/odom read per tick (D-494 3)
                await self._call(refresh(robot_id, force_rest=True, **self._after(self._poses, robot_id)))
            self._unread.discard(robot_id)
        except RobotApiError as exc:
            if exc.status != 429:  # D-760 8: non-rate-limit CORE errors still fail the read
                raise
            self._unread.add(robot_id)
            if self._clock() - self._refresh_warned_at >= 30.0:
                self._refresh_warned_at = self._clock()
                _LOG.warning("state refresh for %s rate-limited (repeats muted 30 s)", robot_id, exc_info=True)
        except (HubError, OSError, httpx.TransportError):  # D-760 4/8: only no answer is an unread state
            self._unread.add(robot_id)
            if self._clock() - self._refresh_warned_at >= 30.0:
                self._refresh_warned_at = self._clock()
                _LOG.warning("state refresh for %s failed (repeats muted 30 s)", robot_id, exc_info=True)
        try:
            return await self._call(self._driving_pose(robot_id))
        except Exception:  # a pose that cannot be read is no pose
            _LOG.exception("map pose for %s failed", robot_id)  # falls through to None

    def _driving_pose(self, robot_id: str):
        """D-989 allowlist: the trip loop is the consumer that may drive on an auto-locate anchor."""
        return getattr(self._poses, "driving_pose", self._poses.arbitrated_pose)(robot_id)

    async def tick(self) -> None:
        """One period (D-517 7): every open trip steps at once, each under its own lock and its own
        bounded robot calls. A robot still in its last step is left to finish and skips this
        period, so a slow robot never holds another back; then the block table is computed."""
        self.lease.period(self._live.values())  # D-541 7: renews first, from their own slot
        for robot_id, live in list(self._live.items()):
            task = self._inflight.get(robot_id)
            if live.open and (task is None or task.done()):
                self._inflight[robot_id] = asyncio.ensure_future(self._tick_robot(live))
        self.halts.watch_handoff_stops(self._inflight)
        self.traffic.watch(self._inflight, self.robot_busy, lambda r: self._call(self._driving_pose(r)))
        pending = [task for task in self._inflight.values() if not task.done()]
        if pending:
            await asyncio.wait(pending, timeout=self.config.period_s)
        self._inflight = {robot_id: task for robot_id, task in self._inflight.items() if not task.done()}
        self.traffic.period(self._live.values())
        slow = self.authority.busy()  # an authority still out from an earlier period: no advice beside it
        settled = [live for r, live in self._live.items() if r not in self._inflight]  # mid-step: none
        self.authority.period(self._live.values(), set(self._inflight))  # mid-step: nothing (Safety-Review MEDIUM-3)
        self.advice.period(settled, slow)  # after the authority, own in-flight slot: never delays it
        observe(self._live.values(), self._inflight, self.traffic, self._store, self._routing, self.config, self._clock())

    async def _tick_robot(self, live: LiveTrip) -> None:
        """Every failure ends at most this one trip."""
        try:
            async with self._lock_for(live.view["robot_id"]):
                if live.open:
                    live.waited = False  # set by _waiting, which writes view.wait's answer in one go (D-763 8)
                    await self._step(live)
                    if not live.waited:  # a step that returned before _waiting shows no answer, not the last one
                        (live.view.get("wait") or {}).update(waiting=None, bound_s=None, over_bound=None)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOG.exception("trip loop step failed for %s", live.view["robot_id"])
            await self._loop_failed(live)

    # ---- stopping -----------------------------------------------------------------------

    async def _stop(self, live: LiveTrip, state: str, reason: str, detail: Optional[dict] = None, *,
                    halt_free: bool = True) -> None:
        """End the trip and stop the robot (a free robot that lost its pose keeps its deadman).

        A trip already closed (a cancel that landed mid-tick) keeps its state; the robot is
        still stopped again.
        """
        live.at, live.at_stamp = None, None
        if live.open:
            live.view.update(state=state, reason=reason)
            live.view["detail"].update(detail or {})
        if halt_free or live.segment_is_lane(live.view["segment_index"]):
            live.view["detail"].update(await self._halt(live))
        self._save(live)

    async def _lease_lost(self, live: LiveTrip, detail: dict) -> None:
        """D-541 7: closed before the lock, so a step in flight sends nothing more; free: goal cancelled."""
        if live.open:
            live.view.update(state="stopped", reason="lease_lost")
            live.view["detail"].update(detail)
            async with self._lock_for(live.view["robot_id"]):
                if not live.segment_is_lane(live.view["segment_index"]) or live.view["detail"].get("camera_lane_fallback"):
                    live.view["detail"].update(await self._halt(live))
                self._save(live)

    async def _halt(self, live: LiveTrip) -> dict:
        self.held_stops.pop(live.view["robot_id"], None)  # the halt's own stop is never a held arrival
        i = live.view["segment_index"]
        camera = live.view["detail"].get("camera_lane_fallback")
        return await self.halts.halt_robot(
            live.view["robot_id"], not camera and live.segment_is_lane(i), live.place(i),
            handoff_pending=bool(camera or live.view["detail"].get("named_stop_handoff_pending")))
