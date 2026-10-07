"""D-491 5 / D-492 3: the pure executability rules of a stored plan (``fleet.routing.execute``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.routing.cost import RoutingConfig
from fleet.routing.execute import ends_at_place, lane_action, plan_body, theta, unsupported
from fleet.routing.graph import build_graph
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.site_map import SiteMap, from_lane_graph

ROOT = Path(__file__).resolve().parents[3]
LANE_GRAPH = ROOT / "middleware" / "perception" / "map" / "map_v2_fleet" / "lane_graph.yaml"
CONFIG = RoutingConfig()


def _graph(turn_to=(1, 1), mode="lane", last_mode=None):
    """A(0,0) -> B(1,0) -> C(turn_to)."""
    site = SiteMap.model_validate({
        "places": [{"id": "A", "name": "A", "x": 0, "y": 0, "kind": "junction"},
                   {"id": "B", "name": "B", "x": 1, "y": 0, "kind": "junction"},
                   {"id": "C", "name": "C", "x": turn_to[0], "y": turn_to[1], "kind": "junction"}],
        "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [1, 0]], "width_m": 0.2,
                   "speed_cap_mps": 0.2, "drive_mode": mode},
                  {"id": "bc", "from": "B", "to": "C", "polyline": [[1, 0], list(turn_to)], "width_m": 0.2,
                   "speed_cap_mps": 0.2, "drive_mode": last_mode or mode}]})
    return build_graph(site, version=1)


def _segments(*parts):
    return [{"edge_id": e, "forward": True, "s_from": a, "s_to": b} for e, a, b in parts]


LEFT_TRIP = _segments(("ab", 0.0, 1.0), ("bc", 0.0, 1.0))


def _refused(graph, segments=LEFT_TRIP, modes=("lane",), junction_turn=True, **kw):
    return unsupported(graph, segments, kind="pinky_pro", modes=frozenset(modes), junction_turn=junction_turn,
                       config=CONFIG, **kw)


def test_theta_sign_and_lane_actions():
    left, right = _graph((1, 1)), _graph((1, -1))
    assert theta(left, LEFT_TRIP, 0) == pytest.approx(90.0) and theta(right, LEFT_TRIP, 0) == pytest.approx(-90.0)
    assert lane_action(left, LEFT_TRIP, 0, CONFIG) == "left" and lane_action(right, LEFT_TRIP, 0, CONFIG) == "right"
    assert lane_action(left, LEFT_TRIP, 1, CONFIG) == "stop"  # the last place
    handover = _graph((1, 1), last_mode="free")
    assert lane_action(handover, LEFT_TRIP, 0, CONFIG) == "stop"  # leaving the lane
    assert ends_at_place(left, LEFT_TRIP[1]) == "C"
    assert ends_at_place(left, _segments(("bc", 0.0, 0.5))[0]) is None


def test_ring_junctions_are_straight():
    graph = build_graph(from_lane_graph(LANE_GRAPH), version=1)
    ring = _segments(("ring_s", 0.1, 0.374), ("ring_e", 0.0, 0.46), ("ring_n", 0.0, 0.372))
    ring = [{**s, "s_to": graph.arcs[f"{s['edge_id']}:fwd"].length_m} for s in ring]
    assert [lane_action(graph, ring, i, CONFIG) for i in range(3)] == ["straight", "straight", "stop"]


@pytest.mark.parametrize(("graph", "segments", "kwargs", "reason"), [
    (_graph(), _segments(("zz", 0.0, 1.0)), {}, "UNKNOWN_EDGE"),
    (_graph(), LEFT_TRIP, {"junction_turn": False}, "JUNCTION_TURN_UNSUPPORTED"),
    (_graph(), _segments(("bc", 0.0, 1.0)), {"junction_turn": False}, "JUNCTION_TURN_UNSUPPORTED"),
    (_graph(), _segments(("ab", 0.0, 1.0), ("bc", 0.0, 0.5)), {}, "LANE_END_NOT_A_PLACE"),
    (_graph((0.2, 0.05)), LEFT_TRIP, {}, "LANE_UTURN"),
    (_graph(), LEFT_TRIP, {"max_turn_deg": 80.0}, "LANE_TURN_TOO_SHARP"),
])
def test_unsupported_reasons(graph, segments, kwargs, reason):
    if reason == "LANE_UTURN":
        segments = [segments[0], {**segments[1], "s_to": graph.arcs["bc:fwd"].length_m}]
    assert _refused(graph, segments, **kwargs)["reason"] == reason


def test_drive_mode_and_kind_limits():
    assert _refused(_graph(), modes=("free",)) == {"edge_id": "ab", "drive_mode": "lane"}
    assert _refused(_graph(), junction_turn=True) is None
    assert _refused(_graph(mode="free"), modes=("free",), junction_turn=False) is None


def test_plan_body_is_the_stored_shape():
    graph = build_graph(from_lane_graph(LANE_GRAPH), version=1)
    x, y, yaw = graph.arcs["ring_s:fwd"].point_at(0.1)
    plan = plan_trip(graph, PlanRequest(map_version=1, start_pose=(x, y, yaw), goal="NW"), CONFIG)
    body = plan_body(plan)
    assert set(body) == {"map_version", "segments", "places", "actions", "length_m", "eta_s"}
    assert [s["edge_id"] for s in body["segments"]] == ["ring_s", "ring_e", "ring_n"]
    assert body["actions"][-1] == {"place_id": "NW", "action": "stop", "theta_deg": 0.0}
