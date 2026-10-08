"""D-489 6·7·8 / D-490 2: one trip request -> one plan, or a ``PlanError``.

``via`` places are solved in the same layered A* as the goal (``planner.search``), so the
route is optimal over the whole trip and the arc that reaches a via carries on (no U-turn
there). Excluded arcs (robot kind, drive mode, blocked) are left out; on ``TRIP_NO_ROUTE``
one more search without the blocks, against the same goal, tells the console whether
unblocking would help.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

from fleet.routing.cost import STOP, RoutingConfig, classify, speed, transition_cost, turn_deg
from fleet.routing.graph import Arc, Graph
from fleet.routing.planner import Goal, search
from fleet.routing.snap import PlanError, heading_ok, snap_goal, snap_start

DRIVE_MODES = frozenset({"lane", "free"})


@dataclass(frozen=True)
class PlanRequest:
    map_version: int | None
    start_pose: tuple[float, float, float]
    #: A place id, or ``(x, y, yaw or None)``.
    goal: str | tuple[float, float, float | None]
    robot_kind: str | None = None
    drive_modes: frozenset[str] = DRIVE_MODES
    max_speed_mps: float | None = None
    via: tuple[str, ...] = ()
    arrive_yaw: float | None = None
    speed_cap: float | None = None
    blocked_edges: frozenset[str] = frozenset()
    extra_cost: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Plan:
    segments: tuple[tuple[str, bool, float, float], ...]  # (edge_id, forward, s_from, s_to)
    places: tuple[str, ...]
    actions: tuple[tuple[str | None, str, float], ...]  # (place_id, action, theta_deg)
    length_m: float
    eta_s: float
    map_version: int | None


#: A robot this close to its goal place (and facing the arrive yaw) is already there.
ARRIVED_M = 0.05


def prepare(graph: Graph, config: RoutingConfig) -> None:
    """Build every tangent and successor once; raises if the map cannot be planned on."""
    for arc in graph.arcs.values():
        if not (arc.length_m > 0.0 and math.isfinite(arc.start_tangent) and math.isfinite(arc.end_tangent)):
            raise ValueError(f"lane {arc.id} has no direction")
    graph.successors(config, lambda arc, nxt, kind: transition_cost(
        turn_deg(arc.end_tangent, nxt.start_tangent), kind, config))


def plan_trip(graph: Graph, request: PlanRequest, config: RoutingConfig) -> Plan:
    if request.map_version != graph.version:
        raise PlanError("TRIP_NO_ACTIVE_MAP", {"map_version": graph.version})
    if request.max_speed_mps is not None and not (math.isfinite(request.max_speed_mps)
                                                  and request.max_speed_mps > 0.0):
        raise ValueError("max_speed_mps must be a positive finite speed")
    if any(not math.isfinite(v) or v < 0.0 for v in request.extra_cost.values()):
        raise ValueError("extra_cost must be finite and nonnegative")
    for target in [*request.via, request.goal]:
        if isinstance(target, str) and target not in graph.places:
            raise PlanError("TRIP_UNKNOWN_PLACE", {"place": target})
    arrived = _arrived(graph, request, config)
    if arrived is not None:
        return arrived

    def allowed(arc: Arc, blocked=request.blocked_edges) -> bool:
        return ((arc.robot_kinds is None or request.robot_kind in arc.robot_kinds)
                and arc.drive_mode in request.drive_modes and arc.edge_id not in blocked)

    def arc_speed(arc: Arc) -> float:
        return speed(arc.speed_cap_mps, request.max_speed_mps, request.speed_cap)

    at = snap_start(graph, *request.start_pose, config)
    eta, segments, done = 0.0, [], 0
    legs = _legs(graph, request)
    for index, (via, target) in enumerate(legs):
        last = index == len(legs) - 1
        goal, loose = _goal(graph, target, request.arrive_yaw if last else None, config)
        kwargs = dict(speed=arc_speed, extra_cost=request.extra_cost, via=via)
        stats: dict = {}
        found = search(graph, at, goal, config, allowed=allowed, stats=stats, **kwargs)
        if found is None:
            layer = done + stats["layer"]
            if search(graph, at, goal, config, allowed=lambda arc: allowed(arc, frozenset()), **kwargs):
                raise PlanError("TRIP_NO_ROUTE", {"segment": layer, "unblock_would_help": True})
            if loose is not None and search(graph, at, loose, config, allowed=allowed, **kwargs):
                raise PlanError("TRIP_ARRIVE_YAW_UNREACHABLE", {"segment": layer})
            raise PlanError("TRIP_NO_ROUTE", {"segment": layer, "unblock_would_help": False})
        eta += found[0]
        for arc_id, s_from, s_to in found[1]:  # a leg ending part-way carries on along the same arc
            if segments and segments[-1][0] == arc_id and math.isclose(segments[-1][2], s_from, abs_tol=1e-9):
                segments[-1] = (arc_id, segments[-1][1], s_to)
            else:
                segments.append((arc_id, s_from, s_to))
        at, done = (segments[-1][0], segments[-1][2]), done + len(via) + 1
    return _assemble(graph, segments, eta, config)


def _mid_lane(graph: Graph, place: str) -> bool:
    """D-517 2: a place on no lane end (a D-513 start slot part-way along a lane)."""
    return not any(place in (arc.start_place, arc.end_place) for arc in graph.arcs.values())


def _legs(graph: Graph, request: PlanRequest) -> list[tuple[tuple[str, ...], object]]:
    """``(via, target)`` legs: a part-way place cannot be a via of the layered A*, so the trip
    is cut there and that place becomes a coordinate goal (D-489 6); lane-end vias stay in one leg."""
    legs, via = [], []
    for place in request.via:
        if _mid_lane(graph, place):
            legs.append((tuple(via), place))
            via = []
        else:
            via.append(place)
    return legs + [(tuple(via), request.goal)]


def _arrived(graph: Graph, request: PlanRequest, config: RoutingConfig) -> Plan | None:
    """D-489 부록: already standing on the goal place, facing its arrive yaw -> an empty plan."""
    if request.via or not isinstance(request.goal, str):
        return None
    x, y, yaw = request.start_pose
    if math.dist((x, y), graph.place_xy(request.goal)) > ARRIVED_M:
        return None
    want = request.arrive_yaw if request.arrive_yaw is not None else getattr(
        graph.places[request.goal], "yaw", None)
    if want is not None and not heading_ok(yaw, want, config):
        return None
    return Plan(segments=(), places=(request.goal,), actions=((request.goal, STOP, 0.0),),
                length_m=0.0, eta_s=0.0, map_version=graph.version)


def _goal(graph: Graph, target, arrive_yaw, config: RoutingConfig) -> tuple[Goal, Goal | None]:
    """The goal and, when an arrive yaw narrows a place goal, the same goal without it."""
    if isinstance(target, str):
        place = graph.places[target]
        yaw = arrive_yaw if arrive_yaw is not None else getattr(place, "yaw", None)
        if _mid_lane(graph, target):  # D-517 2: a part-way place is its coordinates and yaw
            point, on_arcs = snap_goal(graph, *graph.place_xy(target), yaw, config)
            if yaw is None:
                return Goal(point, on_arcs=on_arcs), None
            any_way, any_arcs = snap_goal(graph, *graph.place_xy(target), None, config)
            return Goal(point, on_arcs=on_arcs), Goal(any_way, on_arcs=any_arcs)
        loose = Goal(graph.place_xy(target), place=target)
        if yaw is None:
            return loose, None
        return Goal(loose.xy, place=target,
                    arrive_ok=lambda arc: heading_ok(yaw, arc.end_tangent, config)), loose
    x, y, yaw = target
    point, on_arcs = snap_goal(graph, x, y, yaw if yaw is not None else arrive_yaw, config)
    return Goal(point, on_arcs=on_arcs), None


def _assemble(graph: Graph, segments, eta: float, config: RoutingConfig) -> Plan:
    places: list[str] = []
    actions: list[tuple[str | None, str, float]] = []
    for index, (arc_id, s_from, s_to) in enumerate(segments):
        arc = graph.arcs[arc_id]
        if not math.isclose(s_to, arc.length_m, abs_tol=1e-9):
            continue
        places.append(arc.end_place)
        if index + 1 < len(segments):
            theta = turn_deg(arc.end_tangent, graph.arcs[segments[index + 1][0]].start_tangent)
            actions.append((arc.end_place, classify(theta, config), round(theta, 1)))
    final = graph.arcs[segments[-1][0]]
    end_place = final.end_place if math.isclose(segments[-1][2], final.length_m, abs_tol=1e-9) else None
    actions.append((end_place, STOP, 0.0))
    return Plan(
        segments=tuple((graph.arcs[a].edge_id, graph.arcs[a].forward, round(s0, 4), round(s1, 4))
                       for a, s0, s1 in segments),
        places=tuple(places), actions=tuple(actions),
        length_m=round(sum(s1 - s0 for _a, s0, s1 in segments), 4), eta_s=round(eta, 3),
        map_version=graph.version)
