"""D-491 5: the server trip loop — one running trip on the site, stepped every 0.5 s.

A stored plan (``POST /api/fleet/robots/{id}/trip``) is started by a named operator. Each tick
reads the robot's Fleet map pose (D-491 3) and, on a lane segment, CORE's junction state
(D-491 4 / D-492), then:

- ``lane`` segment: within ``arm_distance_m`` of the segment's end place the action there goes
  to CORE (``left``/``right`` with the map's ``turn_deg``); a ``stop`` (last place, hand-over,
  replan hold) carries ``stop_after_m`` = the distance left to the place, because CORE counts
  it in odom from receipt. CORE keeps one instruction: nothing is sent while it executes or
  manoeuvres, and an armed one is refreshed only while CORE still shows it armed.
- ``free`` segment: the D-463 point ``STEP_M`` ahead becomes a navigation goal.

The next segment is current once CORE reports the instruction done (idle or a newer seq) near
the place, or once the pose projects onto the next lane and is closer to it. A pose that is not
LOCALIZED or is off the lane, CORE ``aborted``/``unresolved``/long ``waiting``, no progress
for ``stall_s``, a robot error and a loop error all end the trip and stop the robot at once
(``_halt``: lane junction ``stop`` and line-follow ``OFF``; free goal cancel; a free robot that
lost its pose is left to its deadman). Replanning (D-489 9) happens only at the next place and
holds there until an operator confirms. A Fleet restart turns an open trip into ``stopped``
(``restart``) and halts that robot once; it never starts again. The robot-facing inputs are
ports (``trip_ports``); the executability rules are pure (``fleet.routing.execute``).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import time
from typing import Awaitable, Callable, Optional

import httpx

from fleet.hub.hub import HubError
from fleet.lane_route import STEP_M
from fleet.routing.cost import LEFT, RIGHT, STOP
from fleet.routing.execute import arc_id, ends_at_place, lane_action, plan_body, theta, unsupported
from fleet.routing.snap import PlanError
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.trip_ports import (LaneJunctionPort, MapPose, MapPosePort, TripCapsPort, TripConfig,  # noqa: F401
                                     TripError)
from fleet.swarm.transport import RobotApiError

_LOG = logging.getLogger(__name__)

LOCALIZED = "LOCALIZED"
LINE_MODES = ("CAMERA_LINE", "IR_LINE")
#: D-492 1: CORE is executing a junction manoeuvre; a new instruction would abort it.
MANOEUVRE = ("turning", "advancing", "reacquiring")
OPEN = ("started", "running")
#: D-490 5: a plan may be started within this long on the same map version.
PLAN_TTL_S = 30.0
#: CORE takes ``stop_after_m`` in [0, 2] (D-491 4).
MAX_STOP_AFTER_M = 2.0
_ROBOT_ERRORS = (RobotApiError, HubError, OSError, RuntimeError, ValueError, httpx.HTTPError)


async def _maybe(value):
    return await value if inspect.isawaitable(value) else value


def _code(exc: BaseException) -> str:
    return getattr(exc, "code", None) or type(exc).__name__


class _Live:
    """Runtime state of the one open trip; ``view`` is what is stored and returned."""

    def __init__(self, view: dict, graph, request: dict) -> None:
        self.view = view
        self.graph = graph
        self.request = request
        #: The last instruction CORE accepted: index, action, place, seq, at.
        self.sent: Optional[dict] = None
        self.first_seq: Optional[int] = None
        self.last_goal: Optional[tuple[float, float]] = None
        self.replan_pending = False
        self.waiting_since: Optional[float] = None
        self.junction: dict = {}
        self.best_progress = -math.inf
        self.progress_at: Optional[float] = None

    @property
    def segments(self) -> list:
        return self.view["plan"]["segments"]

    @property
    def open(self) -> bool:
        return self.view["state"] in OPEN

    def arc(self, index: int):
        return self.graph.arcs[arc_id(self.segments[index])]

    def place(self, index: int) -> Optional[str]:
        return ends_at_place(self.graph, self.segments[index])

    def progress(self, index: int, s: float) -> float:
        """Metres along the whole plan."""
        done = sum(seg["s_to"] - seg["s_from"] for seg in self.segments[:index])
        return done + s - self.segments[index]["s_from"]


class TripRunner:
    def __init__(self, *, store, routing_config, caps: TripCapsPort, poses: MapPosePort,
                 junction: LaneJunctionPort, goal: Callable[..., Awaitable[dict]],
                 cancel_goal: Callable[[str], Awaitable[dict]],
                 blocked: Callable[[], frozenset] = frozenset, clock: Callable[[], float] = time.time,
                 config: TripConfig = TripConfig()) -> None:
        self._store = store
        self._routing = routing_config
        self._caps, self._poses, self._junction = caps, poses, junction
        self._goal, self._cancel_goal = goal, cancel_goal
        #: Edges an operator or the traffic layer closed; a remaining one means "replan" (D-489 9).
        self._blocked = blocked
        self._clock = clock
        self.config = config
        self._live: Optional[_Live] = None
        self._lock = asyncio.Lock()
        self._refresh_warned_at = -math.inf
        #: D-491 5: never resume after a restart; ``run`` stops each of these robots once.
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
            caps = await self._call(self._caps.caps_for(robot_id), "TRIP_ROBOT_CAPS_UNKNOWN")
            if caps is None:
                raise TripError(422, "TRIP_ROBOT_CAPS_UNKNOWN")
            refused = unsupported(graph, plan["segments"], kind=caps.kind, modes=caps.modes,
                                  junction_turn=caps.junction_turn, config=self._routing,
                                  max_turn_deg=self.config.max_turn_deg)
            if refused is not None:
                raise TripError(422, "TRIP_MODE_UNSUPPORTED", refused)
            if self.running() is not None:
                raise TripError(409, "TRIP_BUSY", {"trip_id": self.running()["trip_id"]})
            if any(graph.arcs[arc_id(seg)].drive_mode == "lane" for seg in plan["segments"]):
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
                    "hold": None, "pose": _pose_view(pose), "created_at": now, "updated_at": now,
                    "caps": {"kind": caps.kind, "modes": sorted(caps.modes), "max_speed": caps.max_speed,
                             "junction_turn": caps.junction_turn}}
            live = _Live(view, graph, row["request"])
            self._live = live
            if not plan["segments"]:  # D-489 부록 4: already there
                view["state"] = "arrived"
            else:
                self._describe(live)
            self._save(live)
            return live.view

    async def cancel(self, trip_id: str, principal_id: str) -> dict:
        """Immediate: no wait for a tick in flight (that tick halts again if its send lands after)."""
        live = self._open(trip_id)
        live.view.update(state="canceled", reason=None)
        live.view["detail"]["canceled_by"] = principal_id
        live.view["detail"].update(await self._halt(live))
        self._save(live)
        return live.view

    async def _after_send(self, live: _Live) -> None:
        """A send that was in flight when the trip closed (cancel) is stopped again."""
        if not live.open:
            live.view["detail"].update(await self._halt(live))
            self._save(live)

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
            live.last_goal, live.replan_pending = None, False
            self._describe(live)
            self._save(live)
            return live.view

    # ---- loop ---------------------------------------------------------------------------

    async def run(self) -> None:
        """Never returns while the app lives; every failure ends at most the one trip."""
        await self._halt_restarted()
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
            robot_id = live.view["robot_id"]
            pose = await self._pose(robot_id)
            if not live.open:
                return
            live.view["pose"] = _pose_view(pose)
            if pose is None or pose.state != LOCALIZED:
                await self._stop(live, "stopped", "pose", {"pose_state": pose.state if pose else None,
                                                           **_pose_diagnostics(pose)}, halt_free=False)
                return
            try:
                if live.arc(live.view["segment_index"]).drive_mode == "lane":
                    live.junction = await self._call(self._junction.junction_state(robot_id)) or {}
                if not live.open:
                    return
                failed = self._junction_failed(live)
                if failed is not None:
                    await self._stop(live, "stopped", "junction", failed)
                    return
                index, s, off = self._locate(live, pose)
                if off is not None:
                    await self._stop(live, "stopped", "pose", {"off_lane_m": round(off, 3),
                                                               **_pose_diagnostics(pose)}, halt_free=False)
                    return
                if live.view["state"] == "started":
                    live.view["state"] = "running"
                if index != live.view["segment_index"]:
                    live.view["segment_index"] = index
                    live.last_goal = None
                self._describe(live)
                remaining = live.segments[index]["s_to"] - s
                last = index == len(live.segments) - 1
                lane = live.arc(index).drive_mode == "lane"
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
            except RobotApiError as exc:
                lane = live.arc(live.view["segment_index"]).drive_mode == "lane"
                code = "TRIP_ROBOT_JUNCTION_UNSUPPORTED" if lane and exc.status == 404 else exc.code
                await self._stop(live, "failed", code, {"status": exc.status})
                return
            except (HubError, OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
                await self._stop(live, "failed", "TRIP_ROBOT_UNREACHABLE", {"kind": _code(exc)})
                return
            # after the step, so the last place's stop has gone out before "arrived"
            if last and live.view["hold"] is None and remaining <= (
                    self.config.arrive_lane_m if lane else self.config.arrive_free_m):
                live.view["state"] = "arrived"
                self._save(live)
                return
            if self._stalled(live, index, s):
                await self._stop(live, "stopped", "stall", {"stall_s": self.config.stall_s,
                                                            "progress_m": round(live.best_progress, 3)})
                return
            self._save(live)

    # ---- steps --------------------------------------------------------------------------

    async def _step_lane(self, live: _Live, index: int, remaining: float) -> None:
        place = live.place(index)
        if place is None or remaining > self.config.arm_distance_m:
            return
        action = (STOP if live.view["hold"] is not None
                  else lane_action(live.graph, live.segments, index, self._routing))
        state, sent, now = live.junction.get("state"), live.sent, self._clock()
        same = sent is not None and (sent["index"], sent["action"], sent["place"]) == (index, action, place)
        if state in MANOEUVRE:
            return  # a new instruction would abort CORE's turn
        if state == "executing" and (same or sent is None or sent["action"] != STOP):
            return  # CORE is carrying out an instruction; only our own held stop may be replaced
        if same:
            if action == STOP:
                return  # one stop per place: CORE counts its distance from receipt
            ours = live.junction.get("seq") == sent["seq"] and live.junction.get("place_id") == place
            if state == "armed" and not ours:
                pass  # someone else's instruction: ours again
            elif state in ("armed", None) and now - sent["at"] < self.config.junction_expires_s / 2:
                return
            elif state not in ("armed", None, "idle", "waiting"):
                return
        stop_after = min(max(remaining, 0.0), MAX_STOP_AFTER_M) if action == STOP else None
        turn = round(theta(live.graph, live.segments, index), 1) if action in (LEFT, RIGHT) else None
        if not live.open:
            return
        reply = await self._call(self._junction.send_junction(
            live.view["robot_id"], action, place, stop_after, self.config.junction_expires_s, turn_deg=turn)) or {}
        await self._after_send(live)
        if reply.get("accepted") is False:
            return  # CORE aborted a manoeuvre instead; the next tick reads 'aborted' and stops
        seq = reply.get("junction_seq")
        live.sent = {"index": index, "action": action, "place": place, "seq": seq, "at": now}
        if live.first_seq is None:
            live.first_seq = seq if isinstance(seq, int) else 0

    async def _step_free(self, live: _Live, index: int, s: float) -> None:
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
        await self._call(self._goal(live.view["robot_id"], x, y, yaw))
        live.last_goal = (x, y)
        await self._after_send(live)

    def _junction_failed(self, live: _Live) -> Optional[dict]:
        """D-492: CORE ``aborted``/``unresolved`` after our first instruction, or a long ``waiting``."""
        junction = live.junction
        state, now = junction.get("state"), self._clock()
        live.waiting_since = (live.waiting_since or now) if state == "waiting" else None
        ours = live.first_seq is not None and (junction.get("seq") or 0) >= live.first_seq
        if (state in ("aborted", "unresolved") and ours) or (
                state == "waiting" and now - live.waiting_since >= self.config.junction_wait_s):
            return {"junction_state": state, "junction_place": junction.get("place_id"),
                    "junction_reason": junction.get("reason")}
        return None

    def _locate(self, live: _Live, pose: MapPose) -> tuple[int, float, Optional[float]]:
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

    def _completed(self, live: _Live, index: int) -> bool:
        """CORE finished our instruction for this place: idle again, or a newer seq."""
        sent, junction = live.sent, live.junction
        if sent is None or sent["index"] != index or sent["action"] == STOP:
            return False
        seq = junction.get("seq")
        newer = isinstance(seq, int) and isinstance(sent["seq"], int) and seq > sent["seq"]
        return junction.get("state") == "idle" or newer

    def _stalled(self, live: _Live, index: int, s: float) -> bool:
        now = self._clock()
        progress = live.progress(index, s)
        if (live.progress_at is None or progress >= live.best_progress + self.config.stall_m
                or live.view["hold"] is not None or live.junction.get("state") in MANOEUVRE):
            live.best_progress = max(live.best_progress, progress)
            live.progress_at = now
            return False
        return now - live.progress_at >= self.config.stall_s

    def _needs_replan(self, live: _Live, index: int) -> bool:
        active = self._store.active()
        if active is None or active[0] != live.view["map_version"]:
            return True
        blocked = self._blocked()
        return any(seg["edge_id"] in blocked for seg in live.segments[index + 1:])

    def _replan(self, live: _Live, index: int) -> None:
        """D-489 9: plan again from just before the next place; a changed route holds there."""
        live.replan_pending = False
        segment, arc = live.segments[index], live.arc(index)
        x, y, yaw = arc.point_at(max(segment["s_to"] - 0.01, segment["s_from"]))
        request = live.request
        to = request["to"]
        goal = to if isinstance(to, str) else (to["x"], to["y"], to.get("yaw"))
        passed = {live.place(i) for i in range(index)}
        active = self._store.active()
        caps = live.view.get("caps") or {}
        try:
            if active is None:
                raise PlanError("TRIP_NO_ACTIVE_MAP")
            plan = plan_trip(active[2], PlanRequest(
                map_version=active[0], start_pose=(x, y, yaw), goal=goal,
                robot_kind=caps.get("kind"), drive_modes=frozenset(caps.get("modes") or ("lane", "free")),
                max_speed_mps=caps.get("max_speed"), via=tuple(v for v in request.get("via", ()) if v not in passed),
                arrive_yaw=request.get("arrive_yaw"), speed_cap=request.get("speed_cap"),
                blocked_edges=frozenset(self._blocked())), self._routing)
        except PlanError as exc:
            live.view["hold"] = {"reason": "replan", "plan": None, "code": exc.code, "detail": exc.detail}
            return
        body = plan_body(plan)
        refused = unsupported(active[2], body["segments"], kind=caps.get("kind"),
                              modes=frozenset(caps.get("modes") or ()), junction_turn=bool(caps.get("junction_turn")),
                              config=self._routing, max_turn_deg=self.config.max_turn_deg)
        if refused is not None:
            live.view["hold"] = {"reason": "replan", "plan": None, "code": "TRIP_MODE_UNSUPPORTED", "detail": refused}
            return
        old = [(s["edge_id"], s["forward"], s["s_to"]) for s in live.segments[index:]]
        new = [(s["edge_id"], s["forward"], s["s_to"]) for s in body["segments"]]
        if old == new and plan.map_version == live.view["map_version"]:
            return
        live.view["hold"] = {"reason": "replan", "map_version": plan.map_version,
                             "plan": {k: body[k] for k in ("segments", "places", "actions")},
                             "length_m": body["length_m"], "eta_s": body["eta_s"]}

    # ---- stopping -----------------------------------------------------------------------

    async def _stop(self, live: _Live, state: str, reason: str, detail: Optional[dict] = None, *,
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

    async def _halt(self, live: _Live) -> dict:
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
        if errors:
            sent["error"] = errors[-1]
        return sent

    async def _halt_restarted(self) -> None:
        restarted, self._restarted = self._restarted, []
        for trip in restarted:
            try:
                trip["detail"] = {**(trip.get("detail") or {}), **await self._halt_robot(
                    trip["robot_id"], trip.get("drive_mode") == "lane", trip.get("next_place"))}
                trip["updated_at"] = self._clock()
                self._store.put_trip(trip)
            except Exception:
                _LOG.exception("could not stop robot %s of a trip open before the restart", trip.get("robot_id"))

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
            if refresh is not None:  # one state/odom read per tick for the trip robot (D-491 3)
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

    def _open(self, trip_id: str) -> _Live:
        live = self._live
        if live is None or live.view["trip_id"] != trip_id:
            if self._store.trip(trip_id) is None:
                raise TripError(404, "TRIP_UNKNOWN")
            raise TripError(409, "TRIP_NOT_RUNNING")
        if not live.open:
            raise TripError(409, "TRIP_NOT_RUNNING", {"state": live.view["state"]})
        return live

    def _describe(self, live: _Live) -> None:
        index = live.view["segment_index"]
        live.view.update(current_edge=live.segments[index]["edge_id"], drive_mode=live.arc(index).drive_mode,
                         next_place=live.place(index),
                         next_action=STOP if live.view["hold"] else lane_action(live.graph, live.segments, index,
                                                                                self._routing))

    def _save(self, live: _Live) -> None:
        live.view["updated_at"] = self._clock()
        self._store.put_trip(live.view)


def _pose_diagnostics(pose) -> dict:
    # the provider's types are its own; the trip row stores JSON (a dataclass becomes its str)
    return json.loads(json.dumps({key: getattr(pose, key, None)
                                  for key in ("sightings_filtered_map_id", "odom_refused")}, default=str))


def _pose_view(pose: Optional[MapPose]) -> Optional[dict]:
    if pose is None:
        return None
    return {"x": round(pose.x, 3), "y": round(pose.y, 3), "yaw": round(pose.yaw, 3), "state": pose.state,
            "source": pose.source, "dead_reckon_m": round(pose.dead_reckon_m, 3), "age_s": round(pose.age_s, 2),
            "anchor_age_s": getattr(pose, "anchor_age_s", None)}
