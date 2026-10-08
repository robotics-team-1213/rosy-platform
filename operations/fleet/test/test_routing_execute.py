"""D-494 5 / D-495 3: the pure executability rules of a stored plan (``fleet.routing.execute``)."""

from __future__ import annotations

from pathlib import Path

import math

import pytest

from fleet.routing.cost import RoutingConfig
from fleet.routing.execute import (ADVANCE_M, advance_m, ends_at_place, lane_action, plan_body, theta,
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
def test_ring_turn_aims_at_the_advance_chord(into, out):
    """D-507 4 (2026-10-08, SIM round 3): SW and NE on 260919 turn right onto the ring (r ~ 0.25 m).

    The ring bends left, so the chord to ``ADVANCE_M`` along it lies left of the lead tangent by
    about (ADVANCE_M - TANGENT_M)/(2r), and the straight advance from the place ends on the lane.
    """
    graph = build_graph(from_lane_graph(LANE_GRAPH), version=1)
    trip = [{"edge_id": into, "forward": False}, {"edge_id": out, "forward": True}]
    tangent, chord = theta(graph, trip, 0), turn_target(graph, trip, 0)
    assert lane_action(graph, trip, 0, CONFIG) == "right"
    assert chord - tangent == pytest.approx(math.degrees((ADVANCE_M - TANGENT_M) / (2 * 0.25)), abs=0.5)
    arc = graph.arcs[f"{out}:fwd"]
    px, py = arc.polyline[0]
    entry = graph.arcs[f"{into}:rev"].end_tangent

    def off_lane(turn):
        heading = entry + math.radians(turn)
        return arc.project(px + ADVANCE_M * math.cos(heading), py + ADVANCE_M * math.sin(heading))[0]

    assert off_lane(chord) < 0.002 < 0.005 < off_lane(tangent)


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


def test_the_sent_chord_angle_is_what_the_limit_checks():
    """Tangent 95 deg is within a 100 deg limit; the chord the robot is sent (about 112) is not."""
    graph, trip = _bent((95, 0.05), (130, 0.5))
    assert theta(graph, trip, 0) == pytest.approx(95.0, abs=0.1)
    assert _refused(graph, trip, max_turn_deg=100.0) == {"edge_id": "ab", "reason": "LANE_TURN_TOO_SHARP",
                                                         "turn_deg": round(turn_target(graph, trip, 0), 1)}
    assert turn_target(graph, trip, 0) > 100.0 and _refused(graph, trip, max_turn_deg=120.0) is None


def test_a_chord_of_the_other_sign_is_refused():
    """A left by the tangent (+25) whose lane hooks right: the chord is negative, CORE would refuse it."""
    graph, trip = _bent((25, 0.05), (-60, 0.5))
    assert lane_action(graph, trip, 0, CONFIG) == "left" and turn_target(graph, trip, 0) < 0
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
