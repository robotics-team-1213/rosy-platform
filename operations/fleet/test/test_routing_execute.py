"""D-494 5 / D-495 3: the pure executability rules of a stored plan (``fleet.routing.execute``)."""

from __future__ import annotations

from pathlib import Path

import math

import pytest

from fleet.routing.cost import RoutingConfig
from fleet.routing.execute import (ADVANCE_M, advance_m, ends_at_place, exit_segment, lane_action, plan_body, theta,
                                   turn_target, unsupported)
from fleet.routing import execute
from fleet.routing.graph import TANGENT_M, build_graph
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


def test_straight_outgoing_lane_turns_to_the_tangent():
    for graph in (_graph((1, 1)), _graph((1, -1)), _graph((2, 0.5))):
        assert turn_target(graph, LEFT_TRIP, 0) == pytest.approx(theta(graph, LEFT_TRIP, 0), abs=1e-9)


@pytest.mark.parametrize(("into", "out"), [("west", "ring_s"), ("east", "ring_n")])
def test_ring_entry_turns_6_deg_past_the_tangent(into, out):
    """D-507 4 (2026-10-08, SIM 4c): SW and NE on 260919 turn right onto the ring, which bends left.

    The chord (5.7 deg less turn) was worst in SIM; tangent - 6 deg (more turn) held SW and reacquired NE.
    """
    graph = build_graph(from_lane_graph(LANE_GRAPH), version=1)
    trip = [{"edge_id": into, "forward": False}, {"edge_id": out, "forward": True}]
    tangent = theta(graph, trip, 0)
    assert lane_action(graph, trip, 0, CONFIG) == "right" and tangent < 0
    assert execute.TURN_OVERTURN_DEG == 6.0
    assert turn_target(graph, trip, 0) == pytest.approx(tangent - 6.0, abs=1e-9)


def _bent(*legs):
    """A(0,0) -> B(1,0) -> C, the outgoing lane leaving B in ``(heading_deg, length_m)`` legs."""
    line = [[1.0, 0.0]]
    for heading, length in legs:
        x, y = line[-1]
        line.append([x + length * math.cos(math.radians(heading)), y + length * math.sin(math.radians(heading))])
    site = SiteMap.model_validate({
        "places": [{"id": p, "name": p, "x": x, "y": y, "kind": "junction"}
                   for p, (x, y) in (("A", (0, 0)), ("B", (1, 0)), ("C", line[-1]))],
        "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [1, 0]], "width_m": 0.2,
                   "speed_cap_mps": 0.2, "drive_mode": "lane"},
                  {"id": "bc", "from": "B", "to": "C", "polyline": line, "width_m": 0.2,
                   "speed_cap_mps": 0.2, "drive_mode": "lane"}]})
    graph = build_graph(site, version=1)
    return graph, [LEFT_TRIP[0], {**LEFT_TRIP[1], "s_to": graph.arcs["bc:fwd"].length_m}]


def test_a_lane_bending_with_the_turn_gets_the_tangent():
    """SIM 4c measured only lanes bending back against the turn; one bending further the same way is not over-turned."""
    graph, trip = _bent((90, 0.05), (130, 0.5))
    assert turn_target(graph, trip, 0) == pytest.approx(theta(graph, trip, 0), abs=1e-9)


def test_the_sent_over_turn_is_what_the_limit_checks():
    """Tangent 95 deg is within a 100 deg limit; the 101 deg the robot is sent is not."""
    graph, trip = _bent((95, 0.05), (60, 0.5))
    assert theta(graph, trip, 0) == pytest.approx(95.0, abs=0.1)
    assert turn_target(graph, trip, 0) == pytest.approx(theta(graph, trip, 0) + 6.0, abs=1e-9)
    assert _refused(graph, trip, max_turn_deg=100.0) == {"edge_id": "ab", "reason": "LANE_TURN_TOO_SHARP",
                                                         "turn_deg": round(turn_target(graph, trip, 0), 1)}
    assert _refused(graph, trip, max_turn_deg=120.0) is None


def test_a_right_onto_a_lane_bending_back_turns_further_right():
    graph, trip = _bent((-60, 0.05), (-20, 0.5))
    assert lane_action(graph, trip, 0, CONFIG) == "right"
    assert turn_target(graph, trip, 0) == pytest.approx(theta(graph, trip, 0) - 6.0, abs=1e-9)


def test_a_sent_angle_of_the_other_sign_is_refused(monkeypatch):
    """CORE refuses a sent angle whose sign is not the action's (or 0); the check reads the sent value."""
    graph, trip = _bent((25, 0.05), (-60, 0.5))
    assert lane_action(graph, trip, 0, CONFIG) == "left" and _refused(graph, trip) is None
    monkeypatch.setattr(execute, "turn_target", lambda *_: -5.0)
    assert _refused(graph, trip) == {"edge_id": "ab", "reason": "LANE_TURN_TOO_SHARP", "turn_deg": -5.0}
    monkeypatch.setattr(execute, "turn_target", lambda *_: 0.0)
    assert _refused(graph, trip)["reason"] == "LANE_TURN_TOO_SHARP"


def test_advance_never_runs_past_a_short_outgoing_lane(monkeypatch):
    """The schema keeps lanes >= 0.1 m (= ADVANCE_M today); a longer advance (CORE allows 0.30) is clamped."""
    graph, trip = _bent((90, 0.15))
    assert advance_m(graph, trip, 0) == ADVANCE_M
    monkeypatch.setattr(execute, "ADVANCE_M", 0.30)
    assert advance_m(graph, trip, 0) == pytest.approx(0.15)
    assert turn_target(graph, trip, 0) == pytest.approx(90.0)


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


# ---- D-520 1: exit_segment ------------------------------------------------------------------

ARC_ARGS = {"fit_tol_m": 0.005, "outer_line_offset_m": 0.095}


@pytest.mark.parametrize(("into", "out", "end", "length"), [
    ("west", "ring_s", "SE", 0.3739), ("ring_s", "ring_e", "NE", 0.4595),
    ("ring_e", "ring_n", "NW", 0.3722), ("ring_n", "ring_w", "SW", 0.3739)])
def test_260919_ring_lanes_are_exit_segments(into, out, end, length):
    """The ring is one-way counter-clockwise, radius 0.2514 m: + 3.98 1/m (ADR Context 1)."""
    graph = build_graph(from_lane_graph(LANE_GRAPH), version=1)
    first = {"edge_id": into, "forward": into != "west", "s_from": 0.0, "s_to": 0.0}
    nxt = {"edge_id": out, "forward": True, "s_from": 0.0, "s_to": graph.arcs[f"{out}:fwd"].length_m}
    found = exit_segment(graph, [first, nxt], 0, **ARC_ARGS)
    assert found["curvature_1pm"] == pytest.approx(1 / 0.2514, abs=0.01)
    assert found["length_m"] == pytest.approx(length, abs=0.0006)
    assert (found["outer_line_offset_m"], found["end_place_id"]) == (0.095, end)


def _circle_map(clockwise: bool, degrees=90, radius=0.25, step=10):
    """A -> B straight, then a circular lane B -> C turning left (or right) of radius ``radius``."""
    sign = -1 if clockwise else 1
    arc = [[1 + radius * math.sin(t), sign * (radius - radius * math.cos(t))]
           for t in (math.radians(d) for d in range(0, degrees + 1, step))]
    site = SiteMap.model_validate({
        "places": [{"id": "A", "name": "A", "x": 0, "y": 0}, {"id": "B", "name": "B", "x": 1, "y": 0},
                   {"id": "C", "name": "C", "x": arc[-1][0], "y": arc[-1][1]}],
        "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [1, 0]], "width_m": 0.2,
                   "speed_cap_mps": 0.2},
                  {"id": "bc", "from": "B", "to": "C", "polyline": arc, "width_m": 0.2, "speed_cap_mps": 0.2}]})
    graph = build_graph(site, version=1)
    return graph, [LEFT_TRIP[0], {**LEFT_TRIP[1], "s_to": graph.arcs["bc:fwd"].length_m}]


def test_curvature_sign_is_left_positive():
    for clockwise, sign in ((False, 1), (True, -1)):
        graph, trip = _circle_map(clockwise)
        assert exit_segment(graph, trip, 0, **ARC_ARGS)["curvature_1pm"] == pytest.approx(sign * 4.0, abs=0.01)


def test_straight_and_bent_lanes_get_no_exit_segment():
    graph = build_graph(from_lane_graph(LANE_GRAPH), version=1)
    spoke = [{"edge_id": "ring_w", "forward": True, "s_from": 0.0, "s_to": 0.374},
             {"edge_id": "west", "forward": True, "s_from": 0.0, "s_to": graph.arcs["west:fwd"].length_m}]
    assert exit_segment(graph, spoke, 0, **ARC_ARGS) is None              # long and not one circle
    assert exit_segment(_graph((1, 1)), LEFT_TRIP, 0, **ARC_ARGS) is None   # a straight lane
    graph, trip = _bent((90, 0.05), (90, 0.1), (60, 0.1), (60, 0.1), (30, 0.1), (30, 0.1))
    assert exit_segment(graph, trip, 0, **ARC_ARGS) is None               # a polygon bend, not a circle
    graph, trip = _circle_map(False)
    assert exit_segment(graph, trip, 1, **ARC_ARGS) is None               # no next segment
    assert exit_segment(graph, [trip[0], {**trip[1], "s_to": 0.2}], 0, **ARC_ARGS) is None  # ends mid-lane
    graph, trip = _circle_map(False, radius=2.5, degrees=20, step=4)      # 0.4 1/m: under CORE's range
    assert exit_segment(graph, trip, 0, **ARC_ARGS) is None
    graph, trip = _circle_map(False, radius=0.5, degrees=180, step=15)    # 1.57 m: over 1.0 m
    assert exit_segment(graph, trip, 0, **ARC_ARGS) is None
