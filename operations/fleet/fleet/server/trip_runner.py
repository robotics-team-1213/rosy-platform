"""D-494 5: the server trip loop — one running trip on the site, stepped every 0.5 s.

Each tick reads the robot's Fleet map pose (D-494 3) and, on a lane segment, CORE's junction
state (D-494 4 / D-495) before anything is sent; lane places get CORE junction instructions,
free segments the D-463 point ahead as a goal. Every end of a trip stops the robot (``_halt``).
The protocol, the stop rules and why are in the D-494 implementation appendix (5항 trip 루프);
the robot-facing inputs are ports (``trip_ports``), the plan rules are pure
(``fleet.routing.execute``), and ``trip_guard`` keeps other Fleet motion off a trip robot.
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
from fleet.routing.execute import arc_id, lane_action, replan_hold, theta, unsupported
from fleet.server.trip_ports import (LaneJunctionPort, MapPose, MapPosePort, TripCapsPort, TripConfig,  # noqa: F401
                                     OPEN, LiveTrip, TripError, junction_fields, pose_diagnostics, pose_view,
                                     record_bend_candidate)
from fleet.swarm.transport import RobotApiError

_LOG = logging.getLogger(__name__)

LOCALIZED = "LOCALIZED"
#: CORE takes junction instructions only on CAMERA_LINE (IR_LINE: 409 JUNCTION_CAMERA_ONLY).
LINE_MODES = ("CAMERA_LINE",)
#: D-495 1: CORE is executing a junction manoeuvre; a new instruction would abort it.
MANOEUVRE = ("turning", "advancing", "reacquiring")
#: D-490 5: a plan may be started within this long on the same map version.
PLAN_TTL_S = 30.0
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
                 roster: Optional[Callable[[], Iterable[str]]] = None) -> None:
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
        self._live: Optional[LiveTrip] = None
        self._lock = asyncio.Lock()
        self._refresh_warned_at = -math.inf
        #: D-494 5: never resume after a restart; ``run`` stops each robot (retried until it takes).
        self._restarted = store.trips(states=OPEN, limit=1000)
        for trip in self._restarted:
            trip.update(state="stopped", reason="restart", updated_at=clock())
            store.put_trip(trip)

    # ---- reads ------------------------------------------------------------------------

    def running(self) -> Optional[dict]:
        live = self._live
        return live.view if live is not None and live.open else None

    def robot_busy(self, robot_id: str) -> bool:
        """A running trip owns this robot's motion (other Fleet commands answer TRIP_ROBOT_BUSY)."""
        running = self.running()
        return running is not None and running["robot_id"] == robot_id

    def view(self, trip_id: str) -> Optional[dict]:
        live = self._live
        if live is not None and live.view["trip_id"] == trip_id:
            return live.view
        return self._store.trip(trip_id)

    def recent(self, limit: int = 20) -> list[dict]:
        return [self.view(t["trip_id"]) for t in self._store.trips(limit=limit)]

    # ---- operator actions -------------------------------------------------------------

    async def start(self, plan_id: str, principal_id: str) -> dict:
        async with self._lock:
            row = self._store.plan(plan_id)
            plan = (row or {}).get("result", {}).get("plan")
            if plan is None:
                raise TripError(404, "TRIP_PLAN_UNKNOWN")
            if self._store.trip(plan_id) is not None:
                raise TripError(409, "TRIP_ALREADY_STARTED")
            robot_id = row["robot_id"]
            if self._clock() - row["created_at"] > PLAN_TTL_S:
                raise TripError(422, "TRIP_PLAN_EXPIRED", {"ttl_s": PLAN_TTL_S})
            graph = self._graph_for(plan["map_version"])
            map_id = self._store.active()[1].map_id
            lane = any(graph.arcs[arc_id(seg)].drive_mode == "lane" for seg in plan["segments"])
            caps = await self._call(self._caps(robot_id), "TRIP_ROBOT_CAPS_UNKNOWN")
            if caps is None:
                raise TripError(422, "TRIP_ROBOT_CAPS_UNKNOWN")
            refused = unsupported(graph, plan["segments"], kind=caps.kind, modes=caps.modes,
                                  junction_turn=caps.junction_turn, config=self._routing,
                                  max_turn_deg=self.config.max_turn_deg)
            if refused is not None:
                raise TripError(422, "TRIP_MODE_UNSUPPORTED", refused)
            floor = caps.site_floor_map_id  # D-507 9: absent (older CORE) or null declares no floor
            if lane and floor is not None and floor != map_id:
                raise TripError(422, "TRIP_SITE_FLOOR_MISMATCH", {"site_floor_map_id": floor, "map_id": map_id})
            if self.running() is not None:
                raise TripError(409, "TRIP_BUSY", {"trip_id": self.running()["trip_id"]})
            engaged = self._engaged(robot_id)
            if engaged is not None:
                raise TripError(409, "TRIP_ROBOT_BUSY", {"reason": engaged})
            if lane:
                mode = await self._call(self._junction.line_follow_mode(robot_id), "TRIP_LINE_FOLLOW_NOT_ACTIVE")
                if mode not in LINE_MODES:
                    raise TripError(422, "TRIP_LINE_FOLLOW_NOT_ACTIVE", {"mode": mode})
            pose = await self._pose(robot_id)
            anchor_age = getattr(pose, "anchor_age_s", None)
            if pose is None or pose.state != LOCALIZED or anchor_age is None or \
                    anchor_age > self.config.start_anchor_age_s:
                raise TripError(422, "TRIP_POSE_UNTRUSTED", {"pose_state": pose.state if pose else None,
                                                             "anchor_age_s": anchor_age})
            graph = self._graph_for(plan["map_version"])  # the awaits above may have seen an activation
            now = self._clock()
            view = {"trip_id": plan_id, "plan_id": plan_id, "robot_id": robot_id, "started_by": principal_id,
                    "state": "started", "reason": None, "detail": {}, "map_version": plan["map_version"],
                    "plan": {k: plan[k] for k in ("segments", "places", "actions")}, "segment_index": 0,
                    "hold": None, "pose": pose_view(pose), "created_at": now, "updated_at": now,
                    "caps": {"kind": caps.kind, "modes": sorted(caps.modes), "max_speed": caps.max_speed,
                             "junction_turn": caps.junction_turn, "junction_pivot": caps.junction_pivot}}
            live = LiveTrip(view, graph, row["request"])
            self._live = live
            self._restarted = [t for t in self._restarted if t["robot_id"] != robot_id]  # this trip owns it
            if not plan["segments"]:  # D-489 부록 4: already there
                view["state"] = "arrived"
            else:
                self._describe(live)
            self._save(live)
            return live.view

    async def cancel(self, trip_id: str, principal_id: Optional[str], reason: Optional[str] = None) -> dict:
        """Immediate: no wait for a tick in flight (that tick halts again if its send lands after)."""
        live = self._open(trip_id)
        live.view.update(state="canceled", reason=reason)
        live.view["detail"]["canceled_by"] = principal_id
        live.view["detail"].update(await self._halt(live))
        self._save(live)
        return live.view

    async def _after_send(self, live: LiveTrip) -> None:
        """A send that was in flight when the trip closed (cancel) is stopped again."""
        if not live.open:
            live.view["detail"].update(await self._halt(live))
            self._save(live)

    async def cancel_robot(self, robot_id: str, reason: str) -> None:
        """The robot's trip ends canceled (``trip_guard``: an operator turned line-follow OFF)."""
        if self.robot_busy(robot_id):
            await self.cancel(self._live.view["trip_id"], None, reason)

    async def confirm_replan(self, trip_id: str, principal_id: str) -> dict:
        async with self._lock:
            live = self._open(trip_id)
            hold = live.view["hold"]
            if hold is None:
                raise TripError(409, "TRIP_NO_REPLAN")
            if hold.get("plan") is None:
                raise TripError(409, "TRIP_REPLAN_FAILED", {"code": hold.get("code")})
            active = self._store.active()
            if active is None or active[0] != hold["map_version"]:  # plan again at this place
                live.view["hold"], live.replan_pending = None, True
                self._save(live)
                raise TripError(409, "TRIP_MAP_CHANGED", {"map_version": active[0] if active else None})
            live.view.update(plan=hold["plan"], map_version=hold["map_version"], segment_index=0, hold=None)
            live.graph = active[2]
            live.view["detail"]["replan_confirmed_by"] = principal_id
            sent = live.sent
            live.replaceable = sent["seq"] if sent is not None and sent["action"] == STOP else None
            live.sent, live.last_goal, live.replan_pending = None, None, False
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
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOG.exception("trip loop tick failed")
                await self._loop_failed()
            await asyncio.sleep(self.config.period_s)

    async def _loop_failed(self) -> None:
        live = self._live
        if live is None or not live.open:
            return
        try:
            await self._stop(live, "failed", "TRIP_LOOP_ERROR")
        except Exception:  # the store itself failed: keep the in-memory row closed
            _LOG.exception("trip loop could not record its failure")
            live.view.update(state="failed", reason="TRIP_LOOP_ERROR")

    async def tick(self) -> None:
        async with self._lock:
            live = self._live
            if live is None or not live.open:
                return
            live.view["detail"].pop("bend_candidate", None)
            robot_id = live.view["robot_id"]
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
                remaining = live.segments[index]["s_to"] - s
                lane = live.arc(index).drive_mode == "lane"
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
        turn = round(theta(live.graph, live.segments, index), 1) if action in (LEFT, RIGHT) else None
        expect = junction_fields(live, index, action, remaining, self._store.active(), self.config)
        if not live.open:
            return
        if action in (LEFT, RIGHT) and (expect or {}).get("expect_in_m") is None:
            # D-507 2 (2026-10-08 user decision): without a window CORE could take any sighting,
            # a misread bend included, as this turn; stop the trip instead of sending it.
            await self._stop(live, "stopped", "junction_no_window",
                             {"junction_place": place, "junction_action": action, "junction_fields": expect})
            return
        try:
            reply = await self._call(self._junction.send_junction(
                live.view["robot_id"], action, place, stop_after, self.config.junction_expires_s,
                turn_deg=turn, expect=expect)) or {}
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
                or live.view["hold"] is not None or live.junction.get("state") in MANOEUVRE):
            live.best_progress = max(live.best_progress, progress)
            live.progress_at = now
            return False
        return now - live.progress_at >= self.config.stall_s

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

    def _open(self, trip_id: str) -> LiveTrip:
        live = self._live
        if live is None or live.view["trip_id"] != trip_id:
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
