"""D-485 5·6: put a robot pose or a coordinate target onto a lane."""

from __future__ import annotations

import math

from fleet.routing.cost import RoutingConfig, wrap
from fleet.routing.graph import Graph


class PlanError(Exception):
    """``code`` is the D-486 4 API code; ``detail`` goes into the response."""

    def __init__(self, code: str, detail: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail or {}


def heading_ok(yaw: float, tangent: float, config: RoutingConfig) -> bool:
    return abs(math.degrees(wrap(yaw - tangent))) <= config.heading_tol_deg


def snap_start(graph: Graph, x: float, y: float, yaw: float, config: RoutingConfig) -> tuple[str, float]:
    """Closest arc within its lane width whose direction matches ``yaw``: ``(arc id, s)``."""
    best: tuple[float, str, float] | None = None
    near = False
    for arc in graph.arcs.values():
        dist, s_m, tangent = arc.project(x, y)
        if dist > arc.width_m:
            continue
        near = True
        if heading_ok(yaw, tangent, config) and (best is None or dist < best[0]):
            best = (dist, arc.id, s_m)
    if best is None:
        raise PlanError("TRIP_HEADING_CONFLICT" if near else "TRIP_START_OFF_MAP")
    return best[1], best[2]


def snap_goal(graph: Graph, x: float, y: float, yaw: float | None,
              config: RoutingConfig) -> tuple[tuple[float, float], dict[str, float]]:
    """Nearest lane point within ``snap_width_factor`` × width: ``(point, {arc id: s})``.

    Both arcs of a two-way edge end there. ``yaw`` keeps only the arcs that arrive facing it.
    """
    best: tuple[float, str] | None = None
    for arc in graph.arcs.values():
        dist, _s, _t = arc.project(x, y)
        if dist <= config.snap_width_factor * arc.width_m and (best is None or (dist, arc.edge_id) < best):
            best = (dist, arc.edge_id)
    if best is None:
        raise PlanError("TRIP_OFF_MAP")
    goals: dict[str, float] = {}
    point = None
    for arc in graph.arcs.values():
        if arc.edge_id != best[1]:
            continue
        _dist, s_m, tangent = arc.project(x, y)
        px, py, _ = arc.point_at(s_m)
        point = point or (px, py)
        if yaw is None or heading_ok(yaw, tangent, config):
            goals[arc.id] = s_m
    if not goals:
        raise PlanError("TRIP_ARRIVE_YAW_UNREACHABLE")
    return point, goals
