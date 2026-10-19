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
import inspect
import logging
import math
import time
from typing import Awaitable, Callable, Iterable, Optional

import httpx

from core_common.link_retry import start_offset
from core_common.robot_body import nominal_body_for
from fleet.hub.hub import HubError
from fleet.routing.cost import STOP
from fleet.routing.execute import lane_action
from fleet.server.trip_geometry import pose_view
from fleet.server.trip_live import LiveTrip
from fleet.server.trip_ports import (LaneJunctionPort, MapPose, MapPosePort, TripCapsPort, TripConfig,  # noqa: F401
                                     TripError)
from fleet.traffic.lane_traffic import TrafficService
from fleet.traffic.trip_advice import AdviceSender
from fleet.traffic.trip_authority import AuthoritySender
from fleet.traffic.trip_lease import TripLease
from fleet.server.trip_admission import LOCALIZED, TripAdmission  # noqa: F401
from fleet.server.trip_halts import TripHalts, error_code as _code
from fleet.server.trip_laps import LAP_RETRIES, LAP_RETRY_S, convoy_refusal, stop_points  # noqa: F401
from fleet.server.trip_progress import MANOEUVRE, TripProgress  # noqa: F401
from fleet.server.trip_preview import observe
from fleet.server.trip_replan import TripReplan
from fleet.server.trip_steps import TripSteps
from fleet.swarm.transport import RobotApiError

_LOG = logging.getLogger(__name__)

#: D-490 5: a plan may be started within this long on the same map version.
PLAN_TTL_S = 30.0
_ROBOT_ERRORS = (RobotApiError, HubError, OSError, RuntimeError, ValueError, httpx.HTTPError)


async def _maybe(value):
    return await value if inspect.isawaitable(value) else value


class TripRunner(TripAdmission, TripProgress, TripSteps, TripReplan):
    """Start checks: ``trip_admission``; progress predicates: ``trip_progress``; per-period steps: ``trip_steps``;
    replans and laps: ``trip_replan``."""

    def __init__(self, *, store, routing_config, caps: TripCapsPort, poses: MapPosePort,
                 junction: LaneJunctionPort, goal: Callable[..., Awaitable[dict]],
                 cancel_goal: Callable[[str], Awaitable[dict]],
                 blocked: Callable[[], frozenset] = frozenset, clock: Callable[[], float] = time.time,
                 config: TripConfig = TripConfig(),
                 engaged: Callable[[str], Optional[str]] = lambda _robot_id: None,
                 release_queue: Callable[[str], None] = lambda _robot_id: None,
                 roster: Optional[Callable[[], Iterable[str]]] = None,
                 traffic: Optional[TrafficService] = None, traffic_zones=None, authority: bool = False,
                 traffic_signals=(), signal_advice: bool = False, lease: Optional[dict] = None,
                 renew_lease: Optional[Callable[[str], Awaitable[None]]] = None) -> None:
        self._store = store
        self._routing = routing_config
        self._caps, self._poses, self._junction = caps, poses, junction
        self._goal, self._cancel_goal = goal, cancel_goal
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
                               lambda robot_id: self._release_queue(robot_id), self.robot_busy, roster)

    # ---- reads ------------------------------------------------------------------------

    def open_trips(self) -> list[dict]:
        return [live.view for live in self._live.values() if live.open]

    def running(self) -> Optional[dict]:
        """The most recently started open trip (the one-trip console reads it); ``open_trips`` has all."""
        views = self.open_trips()
        return max(views, key=lambda view: view["created_at"]) if views else None

    def robot_busy(self, robot_id: str) -> bool:
        """A running trip owns this robot's motion (other Fleet commands answer TRIP_ROBOT_BUSY)."""
        live = self._live.get(robot_id)
        return live is not None and live.open

    def leg_mode(self, robot_id: str) -> Optional[str]:
        """Drive mode (``lane``/``free``) of the open trip's current segment; None when it cannot be told."""
        live = self._live.get(robot_id)
        try:
            return live.arc(live.view["segment_index"]).drive_mode if live is not None and live.open else None
        except (KeyError, IndexError, TypeError):
            return None

    def convoy_refusal(self, robot_id: str, leader: str, **cycle) -> Optional[tuple]:
        return convoy_refusal(self._live, robot_id, leader, **cycle)

    def _find(self, trip_id: str) -> Optional[LiveTrip]:
        return next((live for live in self._live.values() if live.view["trip_id"] == trip_id), None)

    def view(self, trip_id: str) -> Optional[dict]:
        live = self._find(trip_id)
        return live.view if live is not None else self._store.trip(trip_id)

    def recent(self, limit: int = 20) -> list[dict]:
        return [self.view(t["trip_id"]) for t in self._store.trips(limit=limit)]

    # ---- operator actions -------------------------------------------------------------

    async def start(self, plan_id: str, principal_id: str, job_id: Optional[str] = None, start_token=None,
                    start_guard=None) -> dict:
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
            graph = self._graph_for(plan["map_version"])
            caps = await self._caps_checks(robot_id, graph, plan["segments"], repeat,
                                           plan["actions"][-1]["place_id"], detail=(notes := {}))
            body = nominal_body_for(caps.kind)
            if self.robot_busy(robot_id):
                raise TripError(409, "TRIP_BUSY", {"trip_id": self._live[robot_id].view["trip_id"]})
            if self.lease.job_of(robot_id) not in (None, job_id):  # D-763 6: a job holds it; before any turn
                raise TripError(409, "TRIP_ROBOT_BUSY", {"reason": "job", "owner_kind": "mission"})
            self._check_engaged(robot_id)
            await self._guard_start(robot_id, start_token, start_guard)
            start_at = (row.get("request") or {}).get("start_at")
            pose, enable, turns = await self._start_pose(
                robot_id, graph, plan["segments"], principal_id, start_at=start_at, caps=caps,
                start_token=start_token, start_guard=start_guard)
            await self._guard_start(robot_id, start_token, start_guard)
            pose_observed_at = self._clock()
            lease = await self.lease.open(robot_id, {"trip_id": plan_id, "started_by": principal_id, "job_id": job_id}, caps)
            try:
                self._check_start_token(robot_id, start_token)
                self._check_engaged(robot_id)
                graph = self._graph_for(plan["map_version"])  # the awaits above may have seen an activation
                caps_view = {"kind": caps.kind, "modes": sorted(caps.modes), "max_speed": caps.max_speed,
                             "junction_turn": caps.junction_turn, "junction_pivot": caps.junction_pivot,
                             "lane_arc": caps.lane_arc, "lane_arc_map_anchor": getattr(caps, "lane_arc_map_anchor", False),
                             "line_follow_authority": getattr(caps, "line_follow_authority", False),  # D-760 3: shrink
                             "line_follow_authority_shrink": getattr(caps, "line_follow_authority_shrink", False), "lane_instruction_stamp": getattr(caps, "lane_instruction_stamp", False), "line_follow_route_guide": getattr(caps, "line_follow_route_guide", False),
                             "line_follow_advice": getattr(caps, "line_follow_advice", False), "lane_turn_map_entry": getattr(caps, "lane_turn_map_entry", False),
                             "lane_bend": caps.lane_bend, "lane_bend_next_line": getattr(caps, "lane_bend_next_line", False), "lane_bend_map_entry": getattr(caps, "lane_bend_map_entry", False)}
                plan, request, lap_route, arcs, moved = stop_points(  # D-517 3: no stop inside a zone
                    self._store.active(), plan, row["request"], caps_view, frozenset(self._blocked()), self._routing,
                    self.config.max_turn_deg, self.traffic)
                if start_at is not None and moved is not None:
                    raise TripError(422, "TRIP_START_PLACE_MOVED", moved)
                leader = (request.get("convoy") or {}).get("leader")
                refused = leader and (self.convoy_refusal(robot_id, leader, arcs=arcs, segments=plan["segments"]) or (
                    self.authority.mode(caps) != "core" and ("TRIP_CONVOY_NO_AUTHORITY", {"leader": leader})))
                if refused:  # D-517 9 M3: a follower keeps its gap only through CORE authority
                    raise TripError(422, *refused)
                refused = self.traffic.signal_refusal(plan["segments"], self.authority.mode(caps))
                if refused:  # D-525 1/6: not from inside a signalled zone; crossing one needs CORE authority
                    raise TripError(422, *refused)
                if repeat:  # D-517 3: no await from this check to the trip opening
                    full = self.traffic.loop_full(arcs, self._live.values())
                    if full is not None:  # a convoy counts as 1 + N robots
                        raise TripError(422, "TRIP_CONVOY_LOOP_FULL" if leader else "TRIP_LOOP_FULL", full)
            except TripError:  # the lease opened for a trip that did not start
                if lease is not None:
                    await self.lease.release(robot_id, lease["lease_id"])
                raise
            now = self._clock()
            view = {"trip_id": plan_id, "plan_id": plan_id, "robot_id": robot_id, "started_by": principal_id,
                    "state": "started", "reason": None, "detail": notes, "map_version": plan["map_version"],
                    "plan": {k: plan[k] for k in ("segments", "places", "actions")}, "segment_index": 0,
                    "hold": None, "pose": pose_view(pose), "created_at": now, "updated_at": now,
                    "body_half_width_m": body.half_width_m if body is not None else None,
                    "pose_observed_at": pose_observed_at,
                    "repeat": repeat, "lap": 1 if repeat else None, "caps": caps_view,
                    "traffic_authority": self.authority.mode(caps), "convoy": leader and {"leader": leader},
                    "lease": lease, "stop_moved": moved}
            if enable:  # D-760 2: lease -> line ON -> first authority (CORE refuses one while OFF)
                view["detail"]["line_follow_started"] = False
            if turns:  # D-603: the alignment turns CORE made before this start
                view["detail"]["aligned"] = turns
            live = LiveTrip(view, graph, request)
            live.inherited = self.held_stops.pop(robot_id, None) if plan["segments"] else None  # D-763 7
            live.lap_route, live.lap_arcs = lap_route, arcs
            self._live[robot_id] = live
            self.halts.restarted = [t for t in self.halts.restarted if t["robot_id"] != robot_id]  # this trip owns it
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
        try:
            await self._call(self._junction.start_camera_line(live.view["robot_id"]))
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
        live.view["detail"].update(await self._halt(live))
        self._save(live)
        return live.view

    def close_all(self, reason: str) -> list[LiveTrip]:
        """E-stop (D-517 1): every open trip ends now, before any await, so no step sends after it."""
        self._stop_epoch += 1
        self.held_stops.clear()  # CORE leaves line following: no arrival stop is held any more
        closed = [live for live in self._live.values() if live.open]
        for live in closed:
            live.view.update(state="canceled", reason=reason)
            live.view["detail"]["canceled_by"] = None
        return closed

    async def halt_closed(self, lives: list[LiveTrip]) -> None:
        """Stop the robots of ``close_all`` at once (each halt bounded) and record each trip."""
        async def halt(live: LiveTrip) -> None:
            try:
                live.view["detail"].update(await self._halt(live))
            finally:
                self._save(live)

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
        if self.robot_busy(robot_id):
            await self.cancel(self._live[robot_id].view["trip_id"], None, reason)

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

    async def tick(self) -> None:
        """One period (D-517 7): every open trip steps at once, each under its own lock and its own
        bounded robot calls. A robot still in its last step is left to finish and skips this
        period, so a slow robot never holds another back; then the block table is computed."""
        self.lease.period(self._live.values())  # D-541 7: renews first, from their own slot
        for robot_id, live in list(self._live.items()):
            task = self._inflight.get(robot_id)
            if live.open and (task is None or task.done()):
                self._inflight[robot_id] = asyncio.ensure_future(self._tick_robot(live))
        self.traffic.watch(self._inflight, self.robot_busy, lambda r: self._call(self._poses.arbitrated_pose(r)))
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
        if halt_free or live.arc(live.view["segment_index"]).drive_mode == "lane":
            live.view["detail"].update(await self._halt(live))
        self._save(live)

    async def _lease_lost(self, live: LiveTrip, detail: dict) -> None:
        """D-541 7: closed before the lock, so a step in flight sends nothing more; free: goal cancelled."""
        if live.open:
            live.view.update(state="stopped", reason="lease_lost")
            live.view["detail"].update(detail)
            async with self._lock_for(live.view["robot_id"]):
                if live.arc(live.view["segment_index"]).drive_mode != "lane":
                    live.view["detail"].update(await self._halt(live))
                self._save(live)

    async def _halt(self, live: LiveTrip) -> dict:
        self.held_stops.pop(live.view["robot_id"], None)  # the halt's own stop is never a held arrival
        i = live.view["segment_index"]
        return await self.halts.halt_robot(live.view["robot_id"], live.arc(i).drive_mode == "lane", live.place(i))

    # ---- helpers ------------------------------------------------------------------------

    async def _call(self, value, code: Optional[str] = None):
        """One bounded robot/provider call; with ``code`` a failure is that start refusal."""
        try:
            return await asyncio.wait_for(_maybe(value), self.config.port_timeout_s)
        except _ROBOT_ERRORS as exc:
            if code is None:
                raise
            raise TripError(422, code, {"error": _code(exc)}) from exc

    def _graph_for(self, version):
        active = self._store.active()
        if active is None or active[0] != version:
            raise TripError(422, "TRIP_MAP_CHANGED", {"map_version": active[0] if active else None})
        return active[2]

    async def map_pose(self, robot_id: str) -> Optional[MapPose]:
        """The trip map pose (D-494 3) after one forced state read; None when it cannot be read."""
        try:
            if (refresh := getattr(self._poses, "refresh", None)) is not None:  # one forced state/odom read per tick (D-494 3)
                await self._call(refresh(robot_id, force_rest=True, **self._after(self._poses, robot_id)))
            self._unread.discard(robot_id)
        except (HubError, OSError, httpx.TransportError):  # D-760 4/8: only no answer is an unread state
            self._unread.add(robot_id)
            if self._clock() - self._refresh_warned_at >= 30.0:
                self._refresh_warned_at = self._clock()
                _LOG.warning("state refresh for %s failed (repeats muted 30 s)", robot_id, exc_info=True)
        try:
            return await self._call(self._poses.arbitrated_pose(robot_id))
        except Exception:  # a pose that cannot be read is no pose
            _LOG.exception("map pose for %s failed", robot_id)  # falls through to None

    def _lock_for(self, robot_id: str) -> asyncio.Lock:
        return self._locks.setdefault(robot_id, asyncio.Lock())

    def _open(self, trip_id: str) -> LiveTrip:
        live = self._find(trip_id)
        if live is None:
            if self._store.trip(trip_id) is None:
                raise TripError(404, "TRIP_UNKNOWN")
            raise TripError(409, "TRIP_NOT_RUNNING")
        if not live.open:
            raise TripError(409, "TRIP_NOT_RUNNING", {"state": live.view["state"]})
        return live

    def _describe(self, live: LiveTrip) -> None:
        index = live.view["segment_index"]
        live.view.update(current_edge=live.segments[index]["edge_id"], drive_mode=live.arc(index).drive_mode,
                         next_place=live.place(index),
                         next_action=STOP if live.view["hold"] else lane_action(live.graph, live.segments, index,
                                                                                self._routing))

    def _save(self, live: LiveTrip) -> None:
        if not live.open:
            live.view["detail"].pop("bend_candidate", None)
            self.lease.close(live)  # D-541 7: DELETE after the halt
            self.authority.forget(live.view["robot_id"], live.view["detail"].get("stop_sent") is True)  # MEDIUM-2
        live.view["updated_at"] = self._clock()
        self._store.put_trip(live.view)
