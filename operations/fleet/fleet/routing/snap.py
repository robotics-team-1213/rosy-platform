"""D-489 5·6: put a robot pose or a coordinate target onto a lane."""

from __future__ import annotations

import math
from typing import Callable

from fleet.routing.cost import RoutingConfig, wrap
from fleet.routing.graph import Arc, Graph


class PlanError(Exception):
    """``code`` is the D-490 4 API code; ``detail`` goes into the response."""

    def __init__(self, code: str, detail: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail or {}


def heading_ok(yaw: float, tangent: float, config: RoutingConfig) -> bool:
    return abs(math.degrees(wrap(yaw - tangent))) <= config.heading_tol_deg


def snap_start(graph: Graph, x: float, y: float, yaw: float, config: RoutingConfig,
               allowed: Callable[[Arc], bool] | None = None) -> tuple[str, float]:
    """Closest arc within half its lane width whose direction matches ``yaw``: ``(arc id, s)``.

    An ``allowed`` arc wins over a closer excluded one (blocked, wrong kind or mode): at a place
    every arc out of it is as close, and a closed one must not become the plan's first arc
    (2026-10-09 signal SIM: a lap from SE began on blocked ``ring_e``). A robot standing part-way
    along an excluded arc still starts on it.
    """
    best: tuple[bool, float, str, float] | None = None
    near = False
    for arc in graph.arcs.values():
        dist, s_m, tangent = arc.project(x, y)
        if dist > arc.width_m / 2:
            continue
        near = True
        key = (allowed is not None and not allowed(arc), dist, arc.id)
        if heading_ok(yaw, tangent, config) and (best is None or key < best[:3]):
            best = (*key, s_m)
    if best is None:
        raise PlanError("TRIP_HEADING_CONFLICT" if near else "TRIP_START_OFF_MAP")
    return best[2], best[3]


def snap_goal(graph: Graph, x: float, y: float, yaw: float | None,
              config: RoutingConfig) -> tuple[tuple[float, float], dict[str, float]]:
    """Nearest lane point within ``snap_width_factor`` × width: ``(point, {arc id: s})``.

    With ``yaw`` the arcs that would arrive facing it are kept first, then the nearest of
    those wins (a parallel lane the other way is not the target). Both arcs of a two-way
    edge end there when no yaw is given.
    """
    near = []
    for arc in graph.arcs.values():
        dist, s_m, tangent = arc.project(x, y)
        if dist <= config.snap_width_factor * arc.width_m:
            near.append((dist, arc.edge_id, arc, s_m, tangent))
    if not near:
        raise PlanError("TRIP_OFF_MAP")
    if yaw is not None:
        near = [item for item in near if heading_ok(yaw, item[4], config)]
        if not near:
            raise PlanError("TRIP_ARRIVE_YAW_UNREACHABLE")
    _dist, edge_id, arc, s_m, _t = min(near, key=lambda item: (item[0], item[1], item[2].id))
    point = arc.point_at(s_m)[:2]
    return point, {item[2].id: item[3] for item in near if item[1] == edge_id}
