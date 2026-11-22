"""A site-map place of kind "stop" is the stop line: the body front halts on it, never past it.

The trip goal is therefore the line point moved back along the arrival heading by the registered body's
front (robot body registry, nominal body as the fallback) plus STOP_MARGIN_M. Other place kinds are untouched.
"""

from __future__ import annotations

from fleet.routing.cost import RoutingConfig
from fleet.routing.graph import Arc, Graph
from fleet.routing.snap import heading_ok

STOP_MARGIN_M = 0.01
#: Used when the caller names no registered body; routing stays stdlib-only (test_routing), so the registry
#: lookup is ``fleet.stop_front.body_front_m`` and a test pins this to the nominal body.
FALLBACK_FRONT_M = 0.04205


def stop_goals(graph: Graph, place_id: str, yaw: float | None, config: RoutingConfig,
               front_m: float) -> list[tuple[Arc, float, tuple[float, float]]]:
    """``(arc, s, xy)`` for each lane arriving at a stop place (facing ``yaw`` when given); empty for any
    other kind. Heading is the arc's last non-zero segment (``end_tangent``), or ``yaw`` when the trip has one.
    shortcut: the offset runs along the arc, so a final lane shorter than the offset has no goal (the line is used)."""
    place = graph.places[place_id]
    # A commissioned precision stop (D-1051) names its measured reference pose: the robot centre goes there.
    if getattr(place, "kind", None) != "stop" or getattr(place, "precision_stop", None) is not None:
        return []
    off = front_m + STOP_MARGIN_M
    return [(arc, arc.length_m - off, arc.point_at(arc.length_m - off)[:2]) for arc in graph.arcs.values()
            if arc.end_place == place_id and arc.length_m > off
            and (yaw is None or heading_ok(yaw, arc.end_tangent, config))]
