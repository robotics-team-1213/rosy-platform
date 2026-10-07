"""D-491 5: the server trip loop — one running trip on the site, stepped every 0.5 s.

A stored plan (``POST /api/fleet/robots/{id}/trip``) is started by a named operator. Each tick
projects the robot's Fleet map pose (D-491 3, ``MapPosePort``) onto the planned lanes:

- ``lane`` segment: within ``arm_distance_m`` of the segment's end place the action there goes
  to CORE through ``LaneJunctionPort`` (D-491 4); the last place is ``stop``.
- ``free`` segment: the D-463 point ``STEP_M`` ahead becomes a navigation goal.

A pose that is not LOCALIZED, or a robot more than half a lane width off its lane, ends the
trip as ``stopped`` (reason ``pose``) and nothing more is sent: a lane robot stops at its next
junction on its own (no instruction), a free robot is left to its deadman. Replanning
(D-489 9) happens only at the next place: the robot is held there until an operator confirms
the changed route. Trip rows live in the site map store; a Fleet restart turns a trip that
was still going into ``stopped`` (reason ``restart``) and never starts it again.

The three robot-facing inputs are ports so the CORE capability fields (branch a), the
junction API (branch b) and the Rosy Cam map pose (branch c) plug in when they land; until
then the default wiring returns None and ``start`` refuses with the D-491 codes.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol

import httpx

from fleet.hub.hub import HubError
from fleet.lane_route import STEP_M
from fleet.routing.cost import STOP, UTURN, classify, turn_deg
from fleet.routing.snap import PlanError
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.swarm.transport import RobotApiError

_LOG = logging.getLogger(__name__)

LOCALIZED, DEGRADED, UNKNOWN = "LOCALIZED", "DEGRADED", "UNKNOWN"
OPEN = ("started", "running")
TERMINAL = ("arrived", "stopped", "failed", "canceled")
#: D-490 5: a plan may be started within this long on the same map version.
PLAN_TTL_S = 30.0


@dataclass(frozen=True)
class TripCaps:
    """D-491 1 capability fields as Fleet reads them from the robot's capabilities."""

    kind: Optional[str]
    modes: frozenset
    max_speed: Optional[float]


@dataclass(frozen=True)
class MapPose:
    """D-491 3 ``map_pose`` output."""

    x: float
    y: float
    yaw: float
    state: str
    source: str
    dead_reckon_m: float
    age_s: float


class TripCapsPort(Protocol):
    def caps_for(self, robot_id: str) -> "Optional[TripCaps] | Awaitable[Optional[TripCaps]]": ...


class MapPosePort(Protocol):
    def arbitrated_pose(self, robot_id: str) -> "Optional[MapPose] | Awaitable[Optional[MapPose]]": ...


class LaneJunctionPort(Protocol):
    async def send_junction(self, robot_id: str, action: str, place_id: str, stop_after_m: Optional[float],
                            expires_s: float) -> dict: ...


class NoTripCaps:
    """Default until the D-491 1 provider lands: no robot has trip capabilities."""

    def caps_for(self, robot_id: str) -> None:
        return None


class NoMapPose:
    """Default until the D-491 3 provider lands: no robot has a trip pose."""

    def arbitrated_pose(self, robot_id: str) -> None:
        return None


class HttpLaneJunction:
    """D-491 4 through the console's robot clients (``HttpRobotClient.line_follow_junction``)."""

    def __init__(self, clients: Callable[[], Mapping[str, Any]]) -> None:
        self._clients = clients

    async def send_junction(self, robot_id: str, action: str, place_id: str, stop_after_m: Optional[float],
                            expires_s: float) -> dict:
        client = self._clients().get(robot_id)
        if client is None:
            raise HubError("UNKNOWN_ROBOT", robot_id)
        return await client.line_follow_junction(action, place_id, stop_after_m=stop_after_m, expires_s=expires_s)


@dataclass(frozen=True)
class TripConfig:
    period_s: float = 0.5
    #: D-491 5: the next place's action goes to CORE this far before the place.
    arm_distance_m: float = 0.6
    #: CORE keeps one junction instruction at most 30 s (D-491 4); it is re-sent at half this.
    junction_expires_s: float = 15.0
    #: A lane robot stops at its junction on its own; this close to the last place is arrival.
    arrive_lane_m: float = 0.15
    #: The D-463 ``DONE_M``: a free robot this close to the end has arrived.
    arrive_free_m: float = 0.05
    #: A free robot this close to a segment's end is on the next segment. A lane robot moves on
    #: only once past the place (its projection sits on the end): CORE keeps one instruction,
    #: so the next place's action must not replace this place's before the robot is through.
    advance_free_m: float = 0.05
    #: A free goal is sent again only when its point moved this much.
    goal_resend_m: float = 0.05


class TripError(Exception):
    def __init__(self, status: int, code: str, detail: Optional[dict] = None) -> None:
        super().__init__(code)
        self.status, self.code, self.detail = status, code, detail or {}


async def _maybe(value):
    return await value if inspect.isawaitable(value) else value


def _arc_id(segment: dict) -> str:
    return f"{segment['edge_id']}:{'fwd' if segment['forward'] else 'rev'}"


class _Live:
    """Runtime state of the one open trip; ``view`` is what is stored and returned."""

    def __init__(self, view: dict, graph, request: dict) -> None:
        self.view = view
        self.graph = graph
        self.request = request
        self.armed: Optional[tuple[int, str, float]] = None  # (segment index, action, sent at)
        self.last_goal: Optional[tuple[float, float]] = None
        self.replan_pending = False

    @property
    def segments(self) -> list:
        return self.view["plan"]["segments"]

    def arc(self, index: int):
        return self.graph.arcs[_arc_id(self.segments[index])]

    def ends_at_place(self, index: int) -> Optional[str]:
        arc, segment = self.arc(index), self.segments[index]
        return arc.end_place if math.isclose(segment["s_to"], arc.length_m, abs_tol=1e-3) else None


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
        for trip in store.trips(states=OPEN, limit=1000):  # D-491 5: never resume after a restart
            self._finish_row(trip, "stopped", "restart")

    # ---- reads ------------------------------------------------------------------------

    def running(self) -> Optional[dict]:
        live = self._live
        return live.view if live is not None and live.view["state"] in OPEN else None

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
            active = self._store.active()
            if active is None or active[0] != plan["map_version"]:
                raise TripError(422, "TRIP_MAP_CHANGED", {"map_version": active[0] if active else None})
            graph = active[2]
            caps = await _maybe(self._caps.caps_for(robot_id))
            if caps is None:
                raise TripError(422, "TRIP_ROBOT_CAPS_UNKNOWN")
            unsupported = self._unsupported(graph, plan["segments"], caps)
            if unsupported is not None:
                raise TripError(422, "TRIP_MODE_UNSUPPORTED", unsupported)
            if self.running() is not None:
                raise TripError(409, "TRIP_BUSY", {"trip_id": self.running()["trip_id"]})
            pose = await self._pose(robot_id)
            if pose is None or pose.state != LOCALIZED:
                raise TripError(422, "TRIP_POSE_UNTRUSTED", {"pose_state": pose.state if pose else None})
            now = self._clock()
            view = {"trip_id": plan_id, "plan_id": plan_id, "robot_id": robot_id, "started_by": principal_id,
                    "state": "started", "reason": None, "detail": {}, "map_version": plan["map_version"],
                    "plan": {k: plan[k] for k in ("segments", "places", "actions")}, "segment_index": 0,
                    "hold": None, "pose": _pose_view(pose), "created_at": now, "updated_at": now,
                    "caps": {"kind": caps.kind, "modes": sorted(caps.modes), "max_speed": caps.max_speed}}
            live = _Live(view, graph, row["request"])
            self._live = live
            if not plan["segments"]:  # D-489 부록 4: already there
                self._finish(live, "arrived", None)
            else:
                self._describe(live)
                self._save(live)
            return live.view

    async def cancel(self, trip_id: str, principal_id: str) -> dict:
        async with self._lock:
            live = self._open(trip_id)
            self._finish(live, "canceled", None, {"canceled_by": principal_id})
            index = live.view["segment_index"]
            sent: dict = {"stop_sent": True}
            try:
                if live.arc(index).drive_mode == "lane":
                    await self._junction.send_junction(live.view["robot_id"], STOP,
                                                       live.ends_at_place(index) or "", 0.0,
                                                       self.config.junction_expires_s)
                else:
                    await self._cancel_goal(live.view["robot_id"])
            except (RobotApiError, HubError, OSError, RuntimeError, httpx.HTTPError) as exc:
                sent = {"stop_sent": False, "error": getattr(exc, "code", type(exc).__name__)}
            live.view["detail"].update(sent)
            self._save(live)
            return live.view

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
            live.view["plan"] = hold["plan"]
            live.view["map_version"] = hold["map_version"]
            live.graph = active[2]
            live.view.update(segment_index=0, hold=None)
            live.view["detail"]["replan_confirmed_by"] = principal_id
            live.armed, live.last_goal, live.replan_pending = None, None, False
            self._describe(live)
            self._save(live)
            return live.view

    # ---- loop ---------------------------------------------------------------------------

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # a loop bug must not end every later trip; the trip itself fails
                _LOG.exception("trip loop tick failed")
                live = self._live
                if live is not None and live.view["state"] in OPEN:
                    self._finish(live, "failed", "TRIP_LOOP_ERROR")
            await asyncio.sleep(self.config.period_s)

    async def tick(self) -> None:
        async with self._lock:
            live = self._live
            if live is None or live.view["state"] not in OPEN:
                return
            pose = await self._pose(live.view["robot_id"])
            live.view["pose"] = _pose_view(pose)
            if pose is None or pose.state != LOCALIZED:
                self._finish(live, "stopped", "pose", {"pose_state": pose.state if pose else None})
                return
            index, s, off = self._locate(live, pose)
            if off is not None:
                self._finish(live, "stopped", "pose", {"off_lane_m": round(off, 3)})
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
            try:
                if lane:
                    await self._step_lane(live, index, remaining)
                else:
                    await self._step_free(live, index, s)
            except RobotApiError as exc:
                code = "TRIP_ROBOT_JUNCTION_UNSUPPORTED" if lane and exc.status == 404 else exc.code
                self._finish(live, "failed", code, {"status": exc.status})
                return
            except (HubError, OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
                self._finish(live, "failed", "TRIP_ROBOT_UNREACHABLE", {"kind": type(exc).__name__})
                return
            # after the step, so the last place's stop has gone out before "arrived"
            if last and live.view["hold"] is None and remaining <= (
                    self.config.arrive_lane_m if lane else self.config.arrive_free_m):
                self._finish(live, "arrived", None)
                return
            self._save(live)

    # ---- steps --------------------------------------------------------------------------

    async def _step_lane(self, live: _Live, index: int, remaining: float) -> None:
        place = live.ends_at_place(index)
        if place is None or remaining > self.config.arm_distance_m:
            return
        action = STOP if live.view["hold"] is not None else self._action(live, index)
        now = self._clock()
        if live.armed is not None and live.armed[:2] == (index, action) and \
                now - live.armed[2] < self.config.junction_expires_s / 2:
            return
        await self._junction.send_junction(live.view["robot_id"], action, place, 0.0 if action == STOP else None,
                                           self.config.junction_expires_s)
        live.armed = (index, action, now)

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
        await self._goal(live.view["robot_id"], x, y, yaw)
        live.last_goal = (x, y)

    def _locate(self, live: _Live, pose: MapPose) -> tuple[int, float, Optional[float]]:
        """``(segment index, s on it, off-lane distance or None)``; moves past ended segments."""
        index = live.view["segment_index"]
        while True:
            arc = live.arc(index)
            dist, s, _t = arc.project(pose.x, pose.y)
            ahead = self.config.advance_free_m if arc.drive_mode != "lane" else 1e-3  # s_to is rounded
            if (s < live.segments[index]["s_to"] - ahead or index + 1 >= len(live.segments)
                    or live.view["hold"] is not None
                    # a lane place is passed only after its action went out (a late confirm, a fast tick)
                    or (arc.drive_mode == "lane" and (live.armed is None or live.armed[0] < index))):
                break
            index += 1
        arc = live.arc(index)
        near = [dist] + ([live.arc(index + 1).project(pose.x, pose.y)[0]] if index + 1 < len(live.segments) else [])
        return index, s, (dist if min(near) > arc.width_m / 2 else None)

    def _action(self, live: _Live, index: int) -> str:
        if index + 1 >= len(live.segments) or live.arc(index + 1).drive_mode != "lane":
            return STOP  # the last place, or where the trip leaves the lane (D-491 4 has no hand-over)
        return classify(turn_deg(live.arc(index).end_tangent, live.arc(index + 1).start_tangent), self._routing)

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
        passed = {live.ends_at_place(i) for i in range(index)}
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
        old = [(s["edge_id"], s["forward"], s["s_to"]) for s in live.segments[index:]]
        new = [(s["edge_id"], s["forward"], s["s_to"]) for s in body["segments"]]
        if old == new and plan.map_version == live.view["map_version"]:
            return
        live.view["hold"] = {"reason": "replan", "map_version": plan.map_version,
                             "plan": {k: body[k] for k in ("segments", "places", "actions")},
                             "length_m": body["length_m"], "eta_s": body["eta_s"]}

    # ---- helpers ------------------------------------------------------------------------

    def _unsupported(self, graph, segments: list, caps: TripCaps) -> Optional[dict]:
        for i, segment in enumerate(segments):
            arc = graph.arcs.get(_arc_id(segment))
            if arc is None:
                return {"edge_id": segment["edge_id"], "reason": "UNKNOWN_EDGE"}
            if arc.drive_mode not in caps.modes or (arc.robot_kinds is not None and caps.kind not in arc.robot_kinds):
                return {"edge_id": segment["edge_id"], "drive_mode": arc.drive_mode}
            if arc.drive_mode != "lane":
                continue
            if i + 1 == len(segments) and not math.isclose(segment["s_to"], arc.length_m, abs_tol=1e-3):
                return {"edge_id": segment["edge_id"], "reason": "LANE_END_NOT_A_PLACE"}
            if i + 1 < len(segments) and classify(turn_deg(
                    arc.end_tangent, graph.arcs[_arc_id(segments[i + 1])].start_tangent), self._routing) == UTURN:
                return {"edge_id": segment["edge_id"], "reason": "LANE_UTURN"}
        return None

    async def _pose(self, robot_id: str) -> Optional[MapPose]:
        try:
            return await _maybe(self._poses.arbitrated_pose(robot_id))
        except Exception:  # a pose that cannot be read is no pose
            _LOG.exception("map pose for %s failed", robot_id)
            return None

    def _open(self, trip_id: str) -> _Live:
        live = self._live
        if live is None or live.view["trip_id"] != trip_id:
            if self._store.trip(trip_id) is None:
                raise TripError(404, "TRIP_UNKNOWN")
            raise TripError(409, "TRIP_NOT_RUNNING")
        if live.view["state"] not in OPEN:
            raise TripError(409, "TRIP_NOT_RUNNING", {"state": live.view["state"]})
        return live

    def _describe(self, live: _Live) -> None:
        index = live.view["segment_index"]
        segment = live.segments[index]
        live.view.update(current_edge=segment["edge_id"], drive_mode=live.arc(index).drive_mode,
                         next_place=live.ends_at_place(index),
                         next_action=STOP if live.view["hold"] else self._action(live, index))

    def _finish(self, live: _Live, state: str, reason: Optional[str], detail: Optional[dict] = None) -> None:
        live.view.update(state=state, reason=reason)
        live.view["detail"].update(detail or {})
        self._save(live)

    def _finish_row(self, trip: dict, state: str, reason: str) -> None:
        trip.update(state=state, reason=reason, updated_at=self._clock())
        self._store.put_trip(trip)

    def _save(self, live: _Live) -> None:
        live.view["updated_at"] = self._clock()
        self._store.put_trip(live.view)


def plan_body(plan) -> dict:
    """The JSON plan shape ``/trip`` returns and the store keeps (D-490 5, D-491 5)."""
    return {
        "map_version": plan.map_version,
        "segments": [{"edge_id": e, "forward": f, "s_from": a, "s_to": b} for e, f, a, b in plan.segments],
        "places": list(plan.places),
        "actions": [{"place_id": p, "action": a, "theta_deg": t} for p, a, t in plan.actions],
        "length_m": plan.length_m, "eta_s": plan.eta_s,
    }


def _pose_view(pose: Optional[MapPose]) -> Optional[dict]:
    if pose is None:
        return None
    return {"x": round(pose.x, 3), "y": round(pose.y, 3), "yaw": round(pose.yaw, 3), "state": pose.state,
            "source": pose.source, "dead_reckon_m": round(pose.dead_reckon_m, 3), "age_s": round(pose.age_s, 2)}
