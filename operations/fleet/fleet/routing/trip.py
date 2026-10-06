"""D-485 6·7·8 / D-486 2: one trip request -> one plan, or a ``PlanError``.

Legs through ``via`` places are solved in order; a leg starts on the arc the previous leg
ended on, so a via place is never a U-turn. Excluded arcs (robot kind, drive mode,
blocked) are left out; on ``TRIP_NO_ROUTE`` one more search without the blocks tells the
console whether unblocking would help.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

from fleet.routing.cost import STOP, RoutingConfig, classify, speed, turn_deg
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


def plan_trip(graph: Graph, request: PlanRequest, config: RoutingConfig) -> Plan:
    if request.map_version != graph.version:
        raise PlanError("TRIP_NO_ACTIVE_MAP", {"map_version": graph.version})
    targets = [*request.via, request.goal]
    for target in targets:
        if isinstance(target, str) and target not in graph.places:
            raise PlanError("TRIP_UNKNOWN_PLACE", {"place": target})

    def allowed(arc: Arc, blocked=request.blocked_edges) -> bool:
        return ((arc.robot_kinds is None or request.robot_kind in arc.robot_kinds)
                and arc.drive_mode in request.drive_modes and arc.edge_id not in blocked)

    def arc_speed(arc: Arc) -> float:
        return speed(arc.speed_cap_mps, request.max_speed_mps, request.speed_cap)

    at = snap_start(graph, *request.start_pose, config)
    segments: list[tuple[str, float, float]] = []
    eta = 0.0
    for index, target in enumerate(targets):
        last = index == len(targets) - 1
        goal, loose = _goal(graph, target, request.arrive_yaw if last else None, last, config)
        kwargs = dict(speed=arc_speed, extra_cost=request.extra_cost)
        found = search(graph, at, goal, config, allowed=allowed, **kwargs)
        if found is None:
            if loose is not None and search(graph, at, loose, config, allowed=allowed, **kwargs):
                raise PlanError("TRIP_ARRIVE_YAW_UNREACHABLE", {"segment": index})
            unblocked = search(graph, at, loose or goal, config,
                               allowed=lambda arc: allowed(arc, frozenset()), **kwargs)
            raise PlanError("TRIP_NO_ROUTE", {"segment": index, "unblock_would_help": unblocked is not None})
        cost, leg = found
        eta += cost
        for item in leg:  # a later leg starts with the zero-length end of the previous arc
            if item[2] > item[1] or not segments:
                segments.append(item)
        at = (segments[-1][0], segments[-1][2])
    return _assemble(graph, segments, eta, config)


def _goal(graph: Graph, target, arrive_yaw, last: bool, config: RoutingConfig) -> tuple[Goal, Goal | None]:
    """The leg goal and, when an arrive yaw narrows it, the same goal without it."""
    if isinstance(target, str):
        place = graph.places[target]
        yaw = arrive_yaw if arrive_yaw is not None else (getattr(place, "yaw", None) if last else None)
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
