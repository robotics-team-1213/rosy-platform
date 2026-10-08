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
        angle = theta(graph, segments, i)
        action = classify(angle, config)
        if action == UTURN:
            return {"edge_id": segment["edge_id"], "reason": "LANE_UTURN"}
        if action in (LEFT, RIGHT) and abs(angle) > max_turn_deg:
            return {"edge_id": segment["edge_id"], "reason": "LANE_TURN_TOO_SHARP", "turn_deg": round(angle, 1)}
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
    """What makes two routes the same (D-489 9): the edges driven and where each ends."""
    return [(s["edge_id"], s["forward"], s["s_to"]) for s in segments]


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
