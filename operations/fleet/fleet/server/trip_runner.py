"""D-494 5 / D-517 1: the server trip loop — one running trip per robot, all stepped every 0.5 s.

Each tick reads the robot's Fleet map pose (D-494 3) and, on a lane segment, CORE's junction
state (D-494 4 / D-495) before anything is sent; lane places get CORE junction instructions,
free segments the D-463 point ahead as a goal. Every end of a trip stops the robot (``_halt``).
The protocol, the stop rules and why are in the D-494 implementation appendix (5항 trip 루프);
the robot-facing inputs are ports (``trip_ports``), the plan rules are pure
(``fleet.routing.execute``), and ``trip_guard`` keeps other Fleet motion off a trip robot.
D-517 2: a ``repeat`` trip plans its next lap before the lap's last place; D-517 3: after each
period ``traffic`` (``TrafficService``) computes the block table, which only holds back a junction
instruction into a refused block (M1 sends no authority).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import time
from typing import Awaitable, Callable, Iterable, Optional

import httpx

from fleet.hub.hub import HubError
from fleet.lane_route import STEP_M
from fleet.routing.cost import LEFT, RIGHT, STOP
from fleet.routing.execute import (advance_m, arc_id, ends_at_place, lane_action, plan_again, replan_hold, route_key,
                                    turn_target, unsupported)
from fleet.server.trip_ports import (LaneJunctionPort, MapPose, MapPosePort, TripCapsPort, TripConfig,  # noqa: F401
                                     OPEN, LiveTrip, TripError, junction_fields, pose_diagnostics, pose_view,
                                     record_bend_candidate)
from fleet.server.lane_traffic import PAST_PLACE_M, TrafficService
from fleet.swarm.transport import RobotApiError

_LOG = logging.getLogger(__name__)

LOCALIZED = "LOCALIZED"
#: CORE takes junction instructions only on CAMERA_LINE (IR_LINE: 409 JUNCTION_CAMERA_ONLY).
LINE_MODES = ("CAMERA_LINE",)
#: D-495 1: CORE is executing a junction manoeuvre; a new instruction would abort it.
MANOEUVRE = ("turning", "advancing", "reacquiring")
#: D-490 5: a plan may be started within this long on the same map version.
PLAN_TTL_S = 30.0
#: D-517 2/5: a failed lap check is tried again this often, this many times (D-438 rule budget),
#: before it is the resolver's or the operator's.
LAP_RETRY_S = 5.0
LAP_RETRIES = 2
#: CORE takes ``stop_after_m`` in [0, 2] (D-494 4).
MAX_STOP_AFTER_M = 2.0
_ROBOT_ERRORS = (RobotApiError, HubError, OSError, RuntimeError, ValueError, httpx.HTTPError)


async def _maybe(value):
    return await value if inspect.isawaitable(value) else value


class _GoalRefused(RuntimeError):
    """The console did not send the trip's goal (queued behind traffic, yielding, untrusted)."""


class _JunctionAborted(RuntimeError):
    """CORE answered our instruction by aborting its manoeuvre (D-495): never resent."""


def _code(exc: BaseException) -> str:
    return getattr(exc, "code", None) or type(exc).__name__


class TripRunner:
    def __init__(self, *, store, routing_config, caps: TripCapsPort, poses: MapPosePort,
                 junction: LaneJunctionPort, goal: Callable[..., Awaitable[dict]],
                 cancel_goal: Callable[[str], Awaitable[dict]],
                 blocked: Callable[[], frozenset] = frozenset, clock: Callable[[], float] = time.time,
                 config: TripConfig = TripConfig(),
                 engaged: Callable[[str], Optional[str]] = lambda _robot_id: None,
                 release_queue: Callable[[str], None] = lambda _robot_id: None,
                 roster: Optional[Callable[[], Iterable[str]]] = None,
                 traffic: Optional[TrafficService] = None) -> None:
        self._store = store
        self._routing = routing_config
        self._caps, self._poses, self._junction = caps, poses, junction
        self._goal, self._cancel_goal = goal, cancel_goal
        #: Edges an operator or the traffic layer closed; a remaining one means "replan" (D-489 9).
        self._blocked = blocked
        self._clock = clock
        self.config = config
        #: Console motion the robot already has (``trip_guard.engaged``); a start refuses then.
        self._engaged, self._release_queue, self._roster = engaged, release_queue, roster
        #: D-517 1: robot id -> its trip (open, or the last one it ran).
        self._live: dict[str, LiveTrip] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        #: robot id -> its step still running; that robot skips periods until it ends (D-517 7).
        self._inflight: dict[str, asyncio.Future] = {}
        #: Map poses read this period for robots the block table still pins without a trip (D-517 6).
        self._parked: dict[str, Optional[MapPose]] = {}
        self.traffic = traffic if traffic is not None else TrafficService(store, config)
        self._traffic_warned = False
        self._refresh_warned_at = -math.inf
        #: D-494 5: never resume after a restart; ``run`` stops each robot (retried until it takes).
        self._restarted = store.trips(states=OPEN, limit=1000)
        for trip in self._restarted:
            trip.update(state="stopped", reason="restart", updated_at=clock())
            store.put_trip(trip)

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

    def _find(self, trip_id: str) -> Optional[LiveTrip]:
        return next((live for live in self._live.values() if live.view["trip_id"] == trip_id), None)

    def view(self, trip_id: str) -> Optional[dict]:
        live = self._find(trip_id)
        return live.view if live is not None else self._store.trip(trip_id)

    def recent(self, limit: int = 20) -> list[dict]:
        return [self.view(t["trip_id"]) for t in self._store.trips(limit=limit)]

    # ---- operator actions -------------------------------------------------------------

    async def start(self, plan_id: str, principal_id: str) -> dict:
        row = self._store.plan(plan_id)
        plan = (row or {}).get("result", {}).get("plan")
        if plan is None:
            raise TripError(404, "TRIP_PLAN_UNKNOWN")
        robot_id = row["robot_id"]
        async with self._lock_for(robot_id):
            if self._store.trip(plan_id) is not None:
                raise TripError(409, "TRIP_ALREADY_STARTED")
            if self._clock() - row["created_at"] > PLAN_TTL_S:
                raise TripError(422, "TRIP_PLAN_EXPIRED", {"ttl_s": PLAN_TTL_S})
            repeat = bool((row.get("request") or {}).get("repeat"))
            graph = self._graph_for(plan["map_version"])
            caps = await self._caps_checks(robot_id, graph, plan["segments"], repeat)
            if self.robot_busy(robot_id):
                raise TripError(409, "TRIP_BUSY", {"trip_id": self._live[robot_id].view["trip_id"]})
            engaged = self._engaged(robot_id)
            if engaged is not None:
                raise TripError(409, "TRIP_ROBOT_BUSY", {"reason": engaged})
            pose = await self._pose_checks(robot_id, graph, plan["segments"])
            graph = self._graph_for(plan["map_version"])  # the awaits above may have seen an activation
            caps_view = {"kind": caps.kind, "modes": sorted(caps.modes), "max_speed": caps.max_speed,
                         "junction_turn": caps.junction_turn, "junction_pivot": caps.junction_pivot}
            lap_arcs = self._lap_arcs(plan["segments"], row["request"], caps_view) if repeat else ()
            if repeat:  # D-517 3: no await from this check to the trip opening
                full = self.traffic.loop_full(lap_arcs, self._live.values())
                if full is not None:
                    raise TripError(422, "TRIP_LOOP_FULL", full)
            now = self._clock()
            view = {"trip_id": plan_id, "plan_id": plan_id, "robot_id": robot_id, "started_by": principal_id,
                    "state": "started", "reason": None, "detail": {}, "map_version": plan["map_version"],
                    "plan": {k: plan[k] for k in ("segments", "places", "actions")}, "segment_index": 0,
                    "hold": None, "pose": pose_view(pose), "created_at": now, "updated_at": now,
                    "repeat": repeat, "lap": 1 if repeat else None, "caps": caps_view}
            live = LiveTrip(view, graph, row["request"])
            live.lap_route, live.lap_arcs = route_key(plan["segments"]), lap_arcs
            self._live[robot_id] = live
            self._restarted = [t for t in self._restarted if t["robot_id"] != robot_id]  # this trip owns it
            if not plan["segments"]:  # D-489 부록 4: already there
                view["state"] = "arrived"
            else:
                self._describe(live)
            self._save(live)
            return live.view

    def _lap_arcs(self, segments: list, request: dict, caps: dict) -> tuple[str, ...]:
        """D-517 3: the arcs of one lap, planned (as the next lap will be) from where ``segments`` end;
        the plan's own arcs when that lap cannot be planned now (the lap check then holds the robot)."""
        if not segments:
            return ()
        end = self._store.active()[2].arcs[arc_id(segments[-1])].point_at(segments[-1]["s_to"])
        body, _hold = plan_again(self._store.active(), end, request, caps, frozenset(self._blocked()), set(),
                                 self._routing, self.config.max_turn_deg)
        return tuple(arc_id(seg) for seg in (body or {"segments": segments})["segments"])

    async def _caps_checks(self, robot_id: str, graph, segments: list, repeat: bool):
        """D-494 start checks on the robot's capabilities; the caps, or ``TripError``."""
        map_id = self._store.active()[1].map_id
        lane = any(graph.arcs[arc_id(seg)].drive_mode == "lane" for seg in segments)
        caps = await self._call(self._caps(robot_id), "TRIP_ROBOT_CAPS_UNKNOWN")
        if caps is None:
            raise TripError(422, "TRIP_ROBOT_CAPS_UNKNOWN")
        refused = unsupported(graph, segments, kind=caps.kind, modes=caps.modes,
                              junction_turn=caps.junction_turn, config=self._routing,
                              max_turn_deg=self.config.max_turn_deg, repeat=repeat)
        if refused is not None:
            raise TripError(422, "TRIP_MODE_UNSUPPORTED", refused)
        floor = caps.site_floor_map_id  # D-507 9: absent (older CORE) or null declares no floor
        if lane and floor is not None and floor != map_id:
            raise TripError(422, "TRIP_SITE_FLOOR_MISMATCH", {"site_floor_map_id": floor, "map_id": map_id})
        return caps

    async def _pose_checks(self, robot_id: str, graph, segments: list) -> MapPose:
        """D-494 start checks on line following and the map pose; the pose, or ``TripError``."""
        if any(graph.arcs[arc_id(seg)].drive_mode == "lane" for seg in segments):
            mode = await self._call(self._junction.line_follow_mode(robot_id), "TRIP_LINE_FOLLOW_NOT_ACTIVE")
            if mode not in LINE_MODES:
                raise TripError(422, "TRIP_LINE_FOLLOW_NOT_ACTIVE", {"mode": mode})
        pose = await self._pose(robot_id)
        anchor_age = getattr(pose, "anchor_age_s", None)
        if pose is None or pose.state != LOCALIZED or anchor_age is None or                 anchor_age > self.config.start_anchor_age_s:
            raise TripError(422, "TRIP_POSE_UNTRUSTED", {"pose_state": pose.state if pose else None,
                                                         "anchor_age_s": anchor_age})
        return pose

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
        if self.robot_busy(robot_id):
            await self.cancel(self._live[robot_id].view["trip_id"], None, reason)

    async def confirm_replan(self, trip_id: str, principal_id: str) -> dict:
        async with self._lock_for(self._open(trip_id).view["robot_id"]):
            live = self._open(trip_id)
            hold = live.view["hold"]
            if hold is None:
                raise TripError(409, "TRIP_NO_REPLAN")
            if hold.get("plan") is None and hold.get("reason") == "lap":  # the operator retries the lap check
                if await self._retry_lap(live, live.view["segment_index"]):
                    self._describe(live)
                    self._save(live)
                    return live.view
                hold = live.view["hold"]
                if hold.get("plan") is not None:  # a changed lap: shown first, confirmed next
                    self._describe(live)
                    self._save(live)
                    return live.view
            if hold.get("plan") is None:
                raise TripError(409, "TRIP_REPLAN_FAILED", {"code": hold.get("code")})
            active = self._store.active()
            if active is None or active[0] != hold["map_version"]:  # plan again at this place
                live.view["hold"], live.replan_pending = None, True
                self._save(live)
                raise TripError(409, "TRIP_MAP_CHANGED", {"map_version": active[0] if active else None})
            live.view.update(plan=hold["plan"], map_version=hold["map_version"], segment_index=0, hold=None)
            live.graph = active[2]
            live.route_rev += 1
            if "lap_route" in hold:  # D-517 2: the operator took the changed lap
                live.lap_route = hold["lap_route"]
                live.lap_arcs = tuple(f"{edge}:{'fwd' if forward else 'rev'}"
                                      for edge, forward, _s in hold["lap_route"])
                live.view["lap"] += 1
            live.view["detail"]["replan_confirmed_by"] = principal_id
            sent = live.sent
            live.replaceable = sent["seq"] if sent is not None and sent["action"] == STOP else None
            live.sent, live.last_goal, live.replan_pending, live.at = None, None, False, None
            live.lap_start = 0
            self._describe(live)
            self._save(live)
            return live.view

    # ---- loop ---------------------------------------------------------------------------

    async def run(self) -> None:
        """Never returns while the app lives; every failure ends at most the one trip."""
        restart = asyncio.create_task(self._restart_halts()) if self._restarted else None
        try:
            await self._loop()
        finally:
            if restart is not None:
                restart.cancel()

    async def _loop(self) -> None:
        while True:
            started = time.monotonic()
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # the steps catch their own; this is the traffic table
                _LOG.exception("trip loop tick failed")
            await asyncio.sleep(max(0.0, self.config.period_s - (time.monotonic() - started)))

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
        for robot_id, live in list(self._live.items()):
            task = self._inflight.get(robot_id)
            if live.open and (task is None or task.done()):
                self._inflight[robot_id] = asyncio.ensure_future(self._tick_robot(live))
        for robot_id in self.traffic.pinned():  # an ended trip's robot blocks until a pose shows it left
            task = self._inflight.get(robot_id)
            if not self.robot_busy(robot_id) and (task is None or task.done()):
                self._inflight[robot_id] = asyncio.ensure_future(self._watch(robot_id))
        pending = [task for task in self._inflight.values() if not task.done()]
        if pending:
            await asyncio.wait(pending, timeout=self.config.period_s)
        self._inflight = {robot_id: task for robot_id, task in self._inflight.items() if not task.done()}
        poses, self._parked = self._parked, {}
        try:
            self.traffic.step(self._live.values(), poses)
            self._traffic_warned = False
        except Exception:  # the table is shown only (M1); a fault never ends a trip
            for live in self._live.values():  # no stale refusal holds a robot or hides a stall
                live.traffic = None
            if not self._traffic_warned:
                _LOG.exception("traffic table step failed (repeats muted until it works)")
            self._traffic_warned = True

    async def _watch(self, robot_id: str) -> None:
        """The map pose of a robot without a trip (hub cache, no forced REST read); none on failure."""
        try:
            self._parked[robot_id] = await self._call(self._poses.arbitrated_pose(robot_id))
        except Exception:  # an unread pose keeps the pins
            pass

    async def _tick_robot(self, live: LiveTrip) -> None:
        """Every failure ends at most this one trip."""
        try:
            async with self._lock_for(live.view["robot_id"]):
                if live.open:
                    await self._step(live)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOG.exception("trip loop step failed for %s", live.view["robot_id"])
            await self._loop_failed(live)

    async def _step(self, live: LiveTrip) -> None:
        robot_id = live.view["robot_id"]
        live.view["detail"].pop("bend_candidate", None)
        pose = await self._pose(robot_id)
        if not live.open:
            return
        live.see(pose)
        if pose is None or pose.state != LOCALIZED:
            await self._stop(live, "stopped", "pose", {"pose_state": pose.state if pose else None,
                                                       **pose_diagnostics(pose)}, halt_free=False)
            return
        try:
            if live.arc(live.view["segment_index"]).drive_mode == "lane":
                live.junction = await self._call(self._junction.junction_state(robot_id)) or {}
                sent = live.sent
                if sent is not None and live.junction.get("seq") == sent["seq"] and \
                        live.junction.get("state") in (*MANOEUVRE, "executing"):
                    sent["carried"] = True  # CORE took it on: never sent again
            else:  # a free segment: no stale lane ``waiting`` may end it
                live.junction = {}
            if not live.open:
                return
            index, s, off = self._locate(live, pose)
            live.at = (index, s)
            remaining = live.segments[index]["s_to"] - s
            lane = live.arc(index).drive_mode == "lane"
            if lane and self._traffic_holds(live, index):  # CORE waits at the junction for the block
                live.waiting_since = None
            failed = live.junction_end(self._clock(), remaining if lane else None, self.config)
            if failed is not None:
                await self._stop(live, "stopped", *failed)
                return
            if off is not None:
                await self._stop(live, "stopped", "pose", {"off_lane_m": round(off, 3),
                                                           **pose_diagnostics(pose)}, halt_free=False)
                return
            if live.view["state"] == "started":
                live.view["state"] = "running"
            if index != live.view["segment_index"]:
                live.view["segment_index"] = index
                live.last_goal = None
            record_bend_candidate(live, pose, self._store.active(), index, s)
            self._describe(live)
            last = index == len(live.segments) - 1
            if not last and not live.replan_pending and self._needs_replan(live, index):
                live.replan_pending = True
            if (live.replan_pending and live.view["hold"] is None and not last
                    and remaining <= self.config.arm_distance_m):
                self._replan(live, index)
                self._describe(live)
            if live.repeat and live.view["hold"] is None and self._lap_due(live, index, remaining):
                await self._next_lap(live, index)
                index = live.view["segment_index"]  # finished laps may have been dropped
                self._describe(live)
                last = index == len(live.segments) - 1
            elif self._lap_retry_due(live):
                await self._retry_lap(live, index)
                index = live.view["segment_index"]
                self._describe(live)
                last = index == len(live.segments) - 1
            if lane:
                await self._step_lane(live, index, remaining)
            else:
                await self._step_free(live, index, s)
        except _JunctionAborted as exc:
            await self._stop(live, "stopped", "junction", {"junction_state": "aborted",
                                                           "junction_seq": exc.args[0] if exc.args else None})
            return
        except _GoalRefused as exc:
            await self._stop(live, "failed", "TRIP_GOAL_REFUSED", {"goal_reason": str(exc) or None})
            return
        except RobotApiError as exc:
            lane = live.arc(live.view["segment_index"]).drive_mode == "lane"
            code = "TRIP_ROBOT_JUNCTION_UNSUPPORTED" if lane and exc.status == 404 else exc.code
            await self._stop(live, "failed", code, {"status": exc.status})
            return
        except (HubError, OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
            await self._stop(live, "failed", "TRIP_ROBOT_UNREACHABLE", {"kind": _code(exc)})
            return
        if not live.open:
            return  # canceled while the step was in flight
        # after the step, so the last place's stop has gone out before "arrived"
        if last and live.view["hold"] is None and self._arrived(live, index, remaining, lane):
            live.view["state"] = "arrived"
            if not lane:
                self._release_queue(robot_id)
            self._save(live)
            return
        if self._stalled(live, index, s):
            await self._stop(live, "stopped", "stall", {"stall_s": self.config.stall_s,
                                                        "progress_m": round(live.best_progress, 3)})
            return
        self._save(live)

    # ---- steps --------------------------------------------------------------------------

    async def _step_lane(self, live: LiveTrip, index: int, remaining: float) -> None:
        place = live.place(index)
        if place is None or remaining > self.config.arm_distance_m:
            return
        action = (STOP if live.view["hold"] is not None
                  else lane_action(live.graph, live.segments, index, self._routing))
        if action != STOP and self._traffic_holds(live, index):
            return  # D-517 3 (M1): nothing tells the robot to drive into a refused block
        state, sent, now = live.junction.get("state"), live.sent, self._clock()
        same = sent is not None and (sent["index"], sent["action"], sent["place"]) == (index, action, place)
        if state in MANOEUVRE:
            return  # a new instruction would abort CORE's turn
        if state == "executing" and live.junction.get("seq") != live.replaceable:
            return  # CORE is carrying out an instruction; only our own held replan stop may be replaced
        if same:
            if action == STOP or sent.get("carried") or sent.get("done"):
                return  # one stop per place (CORE measures it from receipt); a carried-out place is done
            ours = live.junction.get("seq") == sent["seq"] and live.junction.get("place_id") == place
            if state == "armed" and not ours:
                pass  # someone else's instruction: ours again
            elif state in ("armed", None) and now - sent["at"] < self.config.junction_expires_s / 2:
                return
            elif state not in ("armed", None, "idle", "waiting"):
                return
        stop_after = min(max(remaining, 0.0), MAX_STOP_AFTER_M) if action == STOP else None
        turn = round(turn_target(live.graph, live.segments, index), 1) if action in (LEFT, RIGHT) else None
        advance = advance_m(live.graph, live.segments, index) if turn is not None else None
        expect = junction_fields(live, index, action, remaining, self._store.active(), self.config)
        if not live.open:
            return
        try:
            reply = await self._call(self._junction.send_junction(
                live.view["robot_id"], action, place, stop_after, self.config.junction_expires_s,
                turn_deg=turn, advance_m=advance, expect=expect)) or {}
        except RobotApiError as exc:
            if exc.code == "JUNCTION_ODOM_STALE":  # D-507 2: no fresh odom at receipt; next tick sends again
                live.view["detail"]["junction_retry"] = exc.code
                return
            if exc.code != "JUNCTION_ALREADY_DONE":
                raise
            reply = {"already_done": True}  # CORE R1: this place's action already ran
        live.view["detail"].pop("junction_retry", None)
        await self._after_send(live)
        if reply.get("accepted") is False:  # CORE aborted a manoeuvre instead: an operator decides
            raise _JunctionAborted(reply.get("junction_seq"))
        seq = reply.get("junction_seq")
        live.replaceable = None
        live.sent = {"index": index, "action": action, "place": place, "seq": seq, "at": now,
                     "done": bool(reply.get("already_done"))}
        if live.first_seq is None:
            live.first_seq = seq if isinstance(seq, int) else 0

    async def _step_free(self, live: LiveTrip, index: int, s: float) -> None:
        segment = live.segments[index]
        arc = live.arc(index)
        if live.view["hold"] is not None:  # hold at the place: the goal is the place itself
            x, y, yaw = arc.point_at(segment["s_to"])
        elif s + STEP_M > segment["s_to"] and index + 1 < len(live.segments):
            nxt = live.segments[index + 1]
            x, y, yaw = live.arc(index + 1).point_at(min(nxt["s_from"] + s + STEP_M - segment["s_to"], nxt["s_to"]))
        else:
            x, y, yaw = arc.point_at(min(s + STEP_M, segment["s_to"]))
        if live.last_goal is not None and math.dist(live.last_goal, (x, y)) < self.config.goal_resend_m:
            return
        if not live.open:
            return
        reply = await self._call(self._goal(live.view["robot_id"], x, y, yaw)) or {}
        live.last_goal = (x, y)
        await self._after_send(live)
        if reply.get("accepted") is False or reply.get("queued"):
            raise _GoalRefused(reply.get("reason") or "")

    def _locate(self, live: LiveTrip, pose: MapPose) -> tuple[int, float, Optional[float]]:
        """``(segment index, s on it, off-lane distance or None)``; moves past finished segments."""
        index = live.view["segment_index"]
        while True:
            arc = live.arc(index)
            dist, s, _t = arc.project(pose.x, pose.y)
            if index + 1 >= len(live.segments) or live.view["hold"] is not None:
                break
            nxt, nxt_segment = live.arc(index + 1), live.segments[index + 1]
            nxt_dist, nxt_s, _t = nxt.project(pose.x, pose.y)
            onto_next = nxt_s > nxt_segment["s_from"] + self.config.advance_eps_m and nxt_dist < dist
            remaining = live.segments[index]["s_to"] - s
            if arc.drive_mode == "lane":
                done = self._completed(live, index) and remaining <= self.config.pass_window_m
            else:
                done = remaining <= self.config.advance_free_m
            if not (done or onto_next):
                break
            index += 1
        near = [dist] + ([live.arc(index + 1).project(pose.x, pose.y)[0]] if index + 1 < len(live.segments) else [])
        return index, s, (dist if min(near) > live.arc(index).width_m / 2 else None)

    def _completed(self, live: LiveTrip, index: int) -> bool:
        """CORE finished our instruction for this place: idle again, or a newer seq."""
        sent, junction = live.sent, live.junction
        if sent is None or sent["index"] != index or sent["action"] == STOP:
            return False
        if sent.get("done"):
            return True
        seq = junction.get("seq")
        newer = isinstance(seq, int) and isinstance(sent["seq"], int) and seq > sent["seq"]
        return bool(sent.get("carried")) and (junction.get("state") == "idle" or newer)

    def _arrived(self, live: LiveTrip, index: int, remaining: float, lane: bool) -> bool:
        """Free: within the D-463 ``DONE_M``. Lane: our stop for this place was accepted, and the
        robot is within ``arrive_lane_m``, or CORE holds that stop within ``pass_window_m``."""
        if not lane:
            return remaining <= self.config.arrive_free_m
        sent = live.sent
        if sent is None or (sent["index"], sent["action"]) != (index, STOP):
            return False
        holding = live.junction.get("seq") == sent["seq"] and live.junction.get("state") == "executing"
        return remaining <= self.config.arrive_lane_m or (holding and remaining <= self.config.pass_window_m)

    def _stalled(self, live: LiveTrip, index: int, s: float) -> bool:
        now = self._clock()
        progress = live.progress(index, s)
        if (live.progress_at is None or progress >= live.best_progress + self.config.stall_m
                or live.view["hold"] is not None or live.junction.get("state") in MANOEUVRE
                or (live.traffic or {}).get("waiting_for")):  # D-517 4: waiting for a block is no stall
            live.best_progress = max(live.best_progress, progress)
            live.progress_at = now
            return False
        return now - live.progress_at >= self.config.stall_s

    def _traffic_holds(self, live: LiveTrip, index: int) -> bool:
        """D-517 3 (M1): a refused block starts before the robot is ``PAST_PLACE_M`` past this
        segment's place, so the instruction would take it into that block."""
        refused = (live.traffic or {}).get("refused_at_m")
        return refused is not None and refused < live.progress(index, live.segments[index]["s_to"]) + PAST_PLACE_M

    def _lap_due(self, live: LiveTrip, index: int, remaining: float) -> bool:
        """At the lap's last place (within ``arm_distance_m``, before its action goes out) or past it."""
        tail = max((i for i in range(len(live.segments)) if live.place(i)), default=None)
        return tail is not None and (index > tail or (index == tail and remaining <= self.config.arm_distance_m))

    def _lap_retry_due(self, live: LiveTrip) -> bool:
        hold = live.view["hold"]
        return (hold is not None and hold.get("reason") == "lap" and hold.get("plan") is None
                and live.lap_tries <= LAP_RETRIES and self._clock() - live.lap_tried_at >= LAP_RETRY_S)

    async def _retry_lap(self, live: LiveTrip, index: int) -> bool:
        """Plan the failed lap again; True when it carries on (the held stop at the place may be replaced)."""
        hold, live.view["hold"] = live.view["hold"], None
        await self._next_lap(live, index)
        if live.view["hold"] is not None or not live.open:
            if live.view["hold"] is None:
                live.view["hold"] = hold
            return False
        sent = live.sent
        live.replaceable = sent["seq"] if sent is not None and sent["action"] == STOP else None
        live.sent, live.last_goal = None, None
        return True

    async def _next_lap(self, live: LiveTrip, index: int) -> None:
        """D-517 2: plan the next lap from this lap's end after the D-494 start checks (named operator
        only at the first start). The same route as the last lap carries on without a stop; a
        failed check or another route holds the robot at this lap's last place (``hold.reason: lap``)."""
        robot_id, segments = live.view["robot_id"], live.segments
        end = live.arc(len(segments) - 1).point_at(segments[-1]["s_to"])
        try:
            graph = self._graph_for(live.view["map_version"])
            await self._caps_checks(robot_id, graph, segments[index:], True)
            await self._pose_checks(robot_id, graph, segments[index:])
            body, hold = plan_again(self._store.active(), end, live.request, live.view["caps"] or {},
                                    frozenset(self._blocked()), set(), self._routing, self.config.max_turn_deg)
        except TripError as exc:
            body, hold = None, {"plan": None, "code": exc.code, "detail": exc.detail}
        if not live.open:
            return
        if body is not None:
            plan = {"segments": _joined(segments, body["segments"]),
                    "places": [*live.view["plan"]["places"], *body["places"]],
                    "actions": [*live.view["plan"]["actions"][:-1], *body["actions"]]}
            if route_key(body["segments"]) == live.lap_route:
                live.lap_tries = 0
                live.lap_arcs = tuple(arc_id(seg) for seg in body["segments"])
                # Keep this lap and the next one: earlier laps are dropped so the plan stays bounded.
                cut, live.lap_start = live.lap_start, len(plan["segments"]) - len(body["segments"]) - live.lap_start
                live.view.update(plan=_from(live.graph, plan, cut), lap=live.view["lap"] + 1)
                if cut:
                    _dropped(live, segments[:cut])
                return
            hold = {"map_version": body["map_version"], "lap_route": route_key(body["segments"]),
                    "plan": _from(live.graph, plan, index),
                    "length_m": body["length_m"], "eta_s": body["eta_s"]}
        if hold.get("plan") is None:
            live.lap_tries, live.lap_tried_at = live.lap_tries + 1, self._clock()
        live.view["hold"] = {**hold, "reason": "lap"}

    def _needs_replan(self, live: LiveTrip, index: int) -> bool:
        active = self._store.active()
        if active is None or active[0] != live.view["map_version"]:
            return True
        blocked = self._blocked()
        return any(seg["edge_id"] in blocked for seg in live.segments[index + 1:])

    def _replan(self, live: LiveTrip, index: int) -> None:
        """D-489 9: plan again from just before the next place; a changed route holds there."""
        live.replan_pending = False
        segment = live.segments[index]
        live.view["hold"] = replan_hold(
            self._store.active(), live.arc(index).point_at(max(segment["s_to"] - 0.01, segment["s_from"])),
            live.segments[index:], live.request, live.view.get("caps") or {}, frozenset(self._blocked()),
            {live.place(i) for i in range(index)}, live.view["map_version"], self._routing,
            self.config.max_turn_deg)

    # ---- stopping -----------------------------------------------------------------------

    async def _stop(self, live: LiveTrip, state: str, reason: str, detail: Optional[dict] = None, *,
                    halt_free: bool = True) -> None:
        """End the trip and stop the robot (a free robot that lost its pose keeps its deadman).

        A trip already closed (a cancel that landed mid-tick) keeps its state; the robot is
        still stopped again.
        """
        if live.open:
            live.view.update(state=state, reason=reason)
            live.view["detail"].update(detail or {})
        if halt_free or live.arc(live.view["segment_index"]).drive_mode == "lane":
            live.view["detail"].update(await self._halt(live))
        self._save(live)

    async def _halt(self, live: LiveTrip) -> dict:
        index = live.view["segment_index"]
        return await self._halt_robot(live.view["robot_id"], live.arc(index).drive_mode == "lane", live.place(index))

    async def _halt_robot(self, robot_id: str, lane: bool, place: Optional[str]) -> dict:
        """Best effort, every call bounded: lane -> junction ``stop`` then line-follow OFF; free -> cancel."""
        errors = []

        async def attempt(call) -> bool:
            try:
                await self._call(call)
                return True
            except Exception as exc:  # the halt must try every step whatever one of them raised
                errors.append(_code(exc))
                return False

        if lane:
            if place:
                await attempt(self._junction.send_junction(robot_id, STOP, place, 0.0, self.config.junction_expires_s))
            sent = {"stop_sent": await attempt(self._junction.hold(robot_id))}
        else:
            sent = {"stop_sent": await attempt(self._cancel_goal(robot_id))}
            try:
                self._release_queue(robot_id)
            except Exception as exc:  # the stop above is what matters
                errors.append(_code(exc))
        if errors:
            sent["error"] = errors[-1]
        return sent

    async def _restart_halts(self) -> None:
        """Outside the tick path: retry every ``restart_retry_s`` up to ``restart_attempts``."""
        for _attempt in range(int(self.config.restart_attempts)):
            await self._halt_restarted()
            if not self._restarted:
                return
            await asyncio.sleep(self.config.restart_retry_s)
        _LOG.warning("gave up stopping robots of trips open before the restart: %s",
                     sorted({trip["robot_id"] for trip in self._restarted}))
        self._restarted = []

    async def _halt_restarted(self) -> None:
        """Stop each robot whose trip was open before the restart, until the robot takes it or
        leaves the roster; a robot on a new trip is that trip's to stop."""
        roster = set(self._roster()) if self._roster is not None else None
        pending = []
        for trip in self._restarted:
            if roster is not None and trip["robot_id"] not in roster:
                continue
            if self.robot_busy(trip["robot_id"]):
                pending.append(trip)
                continue
            try:
                result = await self._halt_robot(trip["robot_id"], trip.get("drive_mode") == "lane",
                                                trip.get("next_place"))
                trip.update(detail={**(trip.get("detail") or {}), **result}, updated_at=self._clock())
                self._store.put_trip(trip)
            except Exception:
                _LOG.exception("could not stop robot %s of a trip open before the restart", trip.get("robot_id"))
                result = {}
            if not result.get("stop_sent"):
                pending.append(trip)
        self._restarted = pending

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

    async def _pose(self, robot_id: str) -> Optional[MapPose]:
        refresh = getattr(self._poses, "refresh", None)
        try:
            if refresh is not None:  # one state/odom read per tick for the trip robot (D-494 3)
                await self._call(refresh(robot_id, force_rest=True))  # past the 1 Hz hub cache
        except Exception:  # an unread state leaves the pose to age into DEGRADED/UNKNOWN
            if self._clock() - self._refresh_warned_at >= 30.0:
                self._refresh_warned_at = self._clock()
                _LOG.warning("state refresh for %s failed (repeats muted 30 s)", robot_id, exc_info=True)
        try:
            return await self._call(self._poses.arbitrated_pose(robot_id))
        except Exception:  # a pose that cannot be read is no pose
            _LOG.exception("map pose for %s failed", robot_id)
            return None

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
        live.view["updated_at"] = self._clock()
        self._store.put_trip(live.view)


def _from(graph, plan: dict, k: int) -> dict:
    """``plan`` from segment ``k`` on, without the places (and their actions) of the segments before it."""
    n = sum(1 for seg in plan["segments"][:k] if ends_at_place(graph, seg))
    return {**plan, "segments": plan["segments"][k:], "places": plan["places"][n:], "actions": plan["actions"][n:]}


def _dropped(live: LiveTrip, dropped: list) -> None:
    """Every index and plan metre the trip keeps moves with the segments dropped from its front."""
    cut = len(dropped)
    live.view["segment_index"] -= cut
    live.at = None if live.at is None else (live.at[0] - cut, live.at[1])
    if live.sent is not None:
        live.sent = {**live.sent, "index": live.sent["index"] - cut}
    live.best_progress -= sum(seg["s_to"] - seg["s_from"] for seg in dropped)
    live.trim_m += sum(live.graph.arcs[arc_id(seg)].length_m for seg in dropped)  # route metres (blocks)


def _joined(old: list, new: list) -> list:
    """``old`` then ``new``; a new lap starting where the old one ends on the same lane is one segment."""
    tail, first = old[-1], new[0]
    if (tail["edge_id"], tail["forward"]) == (first["edge_id"], first["forward"]) and             abs(first["s_from"] - tail["s_to"]) < 1e-3:
        return [*old[:-1], {**tail, "s_to": first["s_to"]}, *new[1:]]
    return [*old, *new]
