"""D-494 5 / D-495 3: what a stored plan asks of a robot at each place, and whether it can.

Pure like the rest of ``fleet.routing``: the trip loop (``server/trip_runner.py``) calls these
with the active graph and the robot's capability fields.
"""

from __future__ import annotations

import math
from typing import Optional

from fleet.routing.cost import LEFT, RIGHT, STOP, UTURN, RoutingConfig, classify, turn_deg
from fleet.routing.graph import Graph
from fleet.routing.snap import PlanError
from fleet.routing.trip import PlanRequest, plan_trip

#: D-495 1: CORE turns at most this much at a junction.
MAX_TURN_DEG = 150.0
#: D-495 1: CORE's default straight run after a junction turn; Fleet sends it with every turn.
ADVANCE_M = 0.10
#: D-507 4 (lap SIM 3): the incoming lane's end heading from its last two chords of this length,
#: the last one plus half their difference (a circle's tangent; a straight lane's chord). The
#: 5 cm lead tangent catches paint noise at a mouth (260919 SW 72.6 deg, this 62.7, the robot
#: 59-60); on the ring this equals the circle's tangent within 0.1 deg.
INCOMING_HEADING_M = 0.10


def plan_body(plan) -> dict:
    """The JSON plan shape ``/trip`` returns and the store keeps (D-490 5, D-494 5)."""
    return {
        "map_version": plan.map_version,
        "segments": [{"edge_id": e, "forward": f, "s_from": a, "s_to": b} for e, f, a, b in plan.segments],
        "places": list(plan.places),
        "actions": [{"place_id": p, "action": a, "theta_deg": t} for p, a, t in plan.actions],
        "length_m": plan.length_m, "eta_s": plan.eta_s,
    }


def arc_id(segment: dict) -> str:
    return f"{segment['edge_id']}:{'fwd' if segment['forward'] else 'rev'}"


def theta(graph: Graph, segments: list, index: int) -> float:
    """Signed turn at the end of segment ``index`` into the next one (+ is left)."""
    return turn_deg(graph.arcs[arc_id(segments[index])].end_tangent,
                    graph.arcs[arc_id(segments[index + 1])].start_tangent)


def advance_m(graph: Graph, segments: list, index: int) -> float:
    """The ``advance_m`` sent with a turn at the end of segment ``index``: never past the outgoing lane."""
    return min(ADVANCE_M, graph.arcs[arc_id(segments[index + 1])].length_m)


def turn_target(graph: Graph, segments: list, index: int) -> float:
    """D-507 4 (lap SIM 3): the ``turn_deg`` sent with a left/right at the end of segment ``index``:
    from the incoming lane's end heading (``INCOMING_HEADING_M``) to the outgoing lane's map
    tangent. CORE adds it to the heading it entered the junction with, so the turn ends on the
    outgoing tangent (lap SIM 2: the 72.6 deg lead tangent and the former 6 deg over-turn left SW
    12-20 deg outward of the ring).
    """
    lane, step = graph.arcs[arc_id(segments[index])], INCOMING_HEADING_M
    if lane.length_m < 2 * step:  # review: two chords need 0.20 m of lane
        return theta(graph, segments, index)
    x0, y0, _ = lane.point_at(lane.length_m - 2 * step)
    x1, y1, _ = lane.point_at(lane.length_m - step)
    x2, y2, _ = lane.point_at(lane.length_m)
    last = math.degrees(math.atan2(y2 - y1, x2 - x1))
    heading = last + turn_deg(math.atan2(y1 - y0, x1 - x0), math.atan2(y2 - y1, x2 - x1)) / 2
    return turn_deg(math.radians(heading), graph.arcs[arc_id(segments[index + 1])].start_tangent)


#: D-520 1: CORE takes ``exit_segment`` with 0.5 <= |curvature| <= 5.0 1/m and length in (0, 1.0] m.
ARC_CURVATURE_1PM = (0.5, 5.0)
ARC_MAX_LENGTH_M = 1.0
#: A circle through fewer points proves nothing (any three fit one); 260919 ring lanes have 38-47.
ARC_MIN_POINTS = 6


def exit_segment(graph: Graph, segments: list, index: int, *, fit_tol_m: float,
                 outer_line_offset_m: float) -> Optional[dict]:
    """D-520 1: the ``exit_segment`` for the place at the end of segment ``index``, or None.

    Only when the next segment is a whole ``lane`` arc to its place whose polyline lies within
    ``fit_tol_m`` of one circle (Kasa fit) of curvature and length in CORE's range. The sign is
    REP-103: + when the circle's centre is left of the lane (counter-clockwise).
    """
    if index + 1 >= len(segments):
        return None
    nxt, arc = segments[index + 1], graph.arcs[arc_id(segments[index + 1])]
    points = arc.polyline
    if (arc.drive_mode != "lane" or nxt["s_from"] > 1e-3 or ends_at_place(graph, nxt) is None
            or not 0 < arc.length_m <= ARC_MAX_LENGTH_M or len(points) < ARC_MIN_POINTS):
        return None
    n = len(points)
    mx, my = sum(p[0] for p in points) / n, sum(p[1] for p in points) / n
    u, v = [p[0] - mx for p in points], [p[1] - my for p in points]
    suu, svv, suv = sum(a * a for a in u), sum(b * b for b in v), sum(a * b for a, b in zip(u, v))
    det = suu * svv - suv * suv
    if det <= 1e-9 * (suu + svv) ** 2:  # collinear: a straight lane
        return None
    ru = sum(a * (a * a + b * b) for a, b in zip(u, v)) / 2
    rv = sum(b * (a * a + b * b) for a, b in zip(u, v)) / 2
    uc, vc = (ru * svv - rv * suv) / det, (rv * suu - ru * suv) / det
    radius, cx, cy = math.sqrt(uc * uc + vc * vc + (suu + svv) / n), uc + mx, vc + my
    if max(abs(math.dist(p, (cx, cy)) - radius) for p in points) > fit_tol_m:
        return None
    (px, py), heading = points[0], arc.start_tangent
    left = math.cos(heading) * (cy - py) - math.sin(heading) * (cx - px) > 0
    curvature = (1.0 if left else -1.0) / radius
    if not ARC_CURVATURE_1PM[0] <= abs(curvature) <= ARC_CURVATURE_1PM[1]:
        return None
    return {"curvature_1pm": round(curvature, 4), "length_m": round(arc.length_m, 4),
            "outer_line_offset_m": outer_line_offset_m, "end_place_id": arc.end_place}


def ends_at_place(graph: Graph, segment: dict) -> Optional[str]:
    arc = graph.arcs[arc_id(segment)]
    return arc.end_place if math.isclose(segment["s_to"], arc.length_m, abs_tol=1e-3) else None


def lane_action(graph: Graph, segments: list, index: int, config: RoutingConfig) -> str:
    """The junction action at the end of lane segment ``index``.

    ``stop`` at the last place and where the trip leaves the lane (D-494 4 has no hand-over).
    """
    if index + 1 >= len(segments) or graph.arcs[arc_id(segments[index + 1])].drive_mode != "lane":
        return STOP
    return classify(theta(graph, segments, index), config)


def unsupported(graph: Graph, segments: list, *, kind: Optional[str], modes, junction_turn: bool,
                config: RoutingConfig, max_turn_deg: float = MAX_TURN_DEG, repeat: bool = False) -> Optional[dict]:
    """None when the robot can drive every segment; otherwise ``TRIP_MODE_UNSUPPORTED`` detail.

    Any lane segment needs ``junction_turn`` (CORE's junction gate runs only with live keep-mode
    evidence, D-495): without it the robot neither stops at a junction nor takes a branch.
    A ``repeat`` trip (D-517 2) never stops at its lap end, so that end may be part-way along
    a lane; it still needs a place in the lap, where a hold stops it.
    """
    if repeat and any(graph.arcs[arc_id(s)].drive_mode == "lane" for s in segments if arc_id(s) in graph.arcs)             and not any(ends_at_place(graph, s) for s in segments if arc_id(s) in graph.arcs):
        return {"edge_id": segments[-1]["edge_id"], "reason": "LANE_END_NOT_A_PLACE"}
    for i, segment in enumerate(segments):
        arc = graph.arcs.get(arc_id(segment))
        if arc is None:
            return {"edge_id": segment["edge_id"], "reason": "UNKNOWN_EDGE"}
        if arc.drive_mode not in modes or (arc.robot_kinds is not None and kind not in arc.robot_kinds):
            return {"edge_id": segment["edge_id"], "drive_mode": arc.drive_mode}
        if arc.drive_mode != "lane":
            continue
        if not junction_turn:
            return {"edge_id": segment["edge_id"], "reason": "JUNCTION_TURN_UNSUPPORTED"}
        if i + 1 == len(segments) and not repeat and ends_at_place(graph, segment) is None:
            return {"edge_id": segment["edge_id"], "reason": "LANE_END_NOT_A_PLACE"}
        if lane_action(graph, segments, i, config) == STOP:
            continue  # the last place, or a hand-over
        action = classify(theta(graph, segments, i), config)
        if action == UTURN:
            return {"edge_id": segment["edge_id"], "reason": "LANE_UTURN"}
        if action not in (LEFT, RIGHT):
            continue
        # D-495 1 / D-507 4: CORE refuses a sent angle over the limit or of the other sign (or 0)
        sent = round(turn_target(graph, segments, i), 1)
        if abs(sent) > max_turn_deg or (sent > 0) != (action == LEFT) or sent == 0:
            return {"edge_id": segment["edge_id"], "reason": "LANE_TURN_TOO_SHARP", "turn_deg": sent}
    return None


def plan_again(active, start_pose, request: dict, caps: dict, blocked: frozenset, passed: set,
               config: RoutingConfig, max_turn_deg: float = MAX_TURN_DEG) -> tuple[Optional[dict], Optional[dict]]:
    """``(plan body, None)`` from ``start_pose`` on the active map, or ``(None, hold)`` saying why not."""
    to = request["to"]
    goal = to if isinstance(to, str) else (to["x"], to["y"], to.get("yaw"))
    try:
        if active is None:
            raise PlanError("TRIP_NO_ACTIVE_MAP")
        plan = plan_trip(active[2], PlanRequest(
            map_version=active[0], start_pose=tuple(start_pose), goal=goal, robot_kind=caps.get("kind"),
            drive_modes=frozenset(caps.get("modes") or ("lane", "free")), max_speed_mps=caps.get("max_speed"),
            via=tuple(v for v in request.get("via", ()) if v not in passed), arrive_yaw=request.get("arrive_yaw"),
            speed_cap=request.get("speed_cap"), blocked_edges=blocked), config)
    except PlanError as exc:
        return None, {"reason": "replan", "plan": None, "code": exc.code, "detail": exc.detail}
    body = plan_body(plan)
    refused = unsupported(active[2], body["segments"], kind=caps.get("kind"), modes=frozenset(caps.get("modes") or ()),
                          junction_turn=bool(caps.get("junction_turn")), config=config, max_turn_deg=max_turn_deg,
                          repeat=bool(request.get("repeat")))
    if refused is not None:
        return None, {"reason": "replan", "plan": None, "code": "TRIP_MODE_UNSUPPORTED", "detail": refused}
    return body, None


def route_key(segments: list) -> list:
    """What makes two routes the same (D-489 9): the edges driven and where each ends. A zero-length
    segment drives nothing (a plan from a place may start at the very end of the lane into it)."""
    return [(s["edge_id"], s["forward"], s["s_to"]) for s in segments if s["s_to"] - s["s_from"] > 1e-6]


def replan_hold(active, start_pose, remaining: list, request: dict, caps: dict, blocked: frozenset,
                passed: set, map_version, config: RoutingConfig, max_turn_deg: float = MAX_TURN_DEG) -> Optional[dict]:
    """D-489 9: plan again from ``start_pose`` (just before the next place) on the active map.

    None when the route is unchanged (same map version); otherwise the hold to show the
    operator: a new plan to confirm, or ``plan: None`` with the reason it cannot go on.
    """
    body, failed = plan_again(active, start_pose, request, caps, blocked, passed, config, max_turn_deg)
    if failed is not None:
        return failed
    if route_key(remaining) == route_key(body["segments"]) and body["map_version"] == map_version:
        return None
    return {"reason": "replan", "map_version": body["map_version"],
            "plan": {k: body[k] for k in ("segments", "places", "actions")},
            "length_m": body["length_m"], "eta_s": body["eta_s"]}
