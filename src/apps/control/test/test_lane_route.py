"""Route model shared by both junction prototypes."""

import math

import numpy as np
import pytest
import yaml

from control.sensing.lane_route import LaneRoute
from lane_scenarios import GRAPH, SCENARIOS


def test_route_of_one_transition_has_two_segments():
    scenario = SCENARIOS[5]
    route = LaneRoute(GRAPH, [scenario["into"], scenario["out"]])
    assert route.segments == [scenario["into"], scenario["out"]]
    assert route.length_m > 0.5


def test_progress_follows_the_pose_along_the_route():
    scenario = SCENARIOS[5]
    route = LaneRoute(GRAPH, [scenario["into"], scenario["out"]])
    start = route.locate(scenario["start"][:2])
    assert start.segment_index == 0
    assert start.lateral_m == pytest.approx(0.0, abs=0.005)
    assert start.distance_to_node_m == pytest.approx(0.35, abs=0.02)


def test_exit_tangent_is_the_heading_of_the_next_segment_at_the_node():
    scenario = SCENARIOS[5]
    route = LaneRoute(GRAPH, [scenario["into"], scenario["out"]])
    points = np.array(GRAPH["segments"][scenario["out"].split(":")[0]]["points"])
    if scenario["out"].endswith(":r"):
        points = points[::-1]
    expected = math.atan2(*(points[3] - points[0])[::-1])
    assert abs(math.atan2(math.sin(route.exit_heading(0) - expected),
                          math.cos(route.exit_heading(0) - expected))) < math.radians(10)


def test_target_point_ahead_returns_a_route_point_at_the_lookahead():
    scenario = SCENARIOS[5]
    route = LaneRoute(GRAPH, [scenario["into"], scenario["out"]])
    point = route.point_ahead(scenario["start"][:2], 0.15)
    assert math.dist(point, scenario["start"][:2]) == pytest.approx(0.15, abs=0.02)


def test_off_route_pose_reports_its_lateral_error():
    scenario = SCENARIOS[5]
    route = LaneRoute(GRAPH, [scenario["into"], scenario["out"]])
    x, y, yaw = scenario["start"]
    shifted = (x - 0.03 * math.sin(yaw), y + 0.03 * math.cos(yaw))
    assert abs(route.locate(shifted).lateral_m) == pytest.approx(0.03, abs=0.005)


def test_route_rejects_a_disconnected_pair():
    with pytest.raises(ValueError, match="not connected"):
        LaneRoute(GRAPH, ["west:f", "east:f"])


def test_route_rejects_a_ring_arc_driven_backwards():
    with pytest.raises(ValueError, match="one-way"):
        LaneRoute(GRAPH, ["ring_n:r", "west:r"])


def test_route_rejects_a_u_turn_back_along_the_same_road():
    with pytest.raises(ValueError, match="U-turn"):
        LaneRoute(GRAPH, ["west:f", "west:r"])


def _tour():
    from control.sensing.lane_coverage import coverage_route
    start = tuple(GRAPH["parking"]["points"][0])
    return coverage_route(GRAPH, start), start


def test_a_tour_starting_mid_segment_fixes_on_its_first_pass():
    keys, start = _tour()
    assert keys[0] == keys[-1]      # the same segment, driven twice
    route = LaneRoute(GRAPH, keys)
    fix = route.locate(start)
    assert fix.segment_index == 0
    assert fix.lateral_m == pytest.approx(0.0, abs=0.002)


def test_a_long_tour_is_tracked_pass_by_pass_without_jumping():
    """Walk the whole tour, 5 mm off its centreline, from the start on the
    first west:f pass to the start again on the last: every fix stays on the
    pass the walk is on (monotonic s, the right segment index), including
    the ring arcs and segments the tour drives twice."""
    keys, start = _tour()
    route = LaneRoute(GRAPH, keys)
    first = route.locate(start)
    s0 = route._seg_start_s[0] + first.s_m
    last_seg = LaneRoute(GRAPH, keys[-1:])
    s_end = route._seg_start_s[-1] + last_seg.locate(start).s_m
    arc, points = route._arc, route._points
    prev = None
    for s in np.arange(s0, s_end, 0.01):
        i = min(int(np.searchsorted(arc, s, side="right")) - 1, len(points) - 2)
        a, b = points[i], points[i + 1]
        d = (b - a) / max(np.linalg.norm(b - a), 1e-12)
        p = a + d * (s - arc[i]) + 0.005 * np.array([-d[1], d[0]])
        fix = route.locate(p)
        got = route._seg_start_s[fix.segment_index] + fix.s_m
        assert got == pytest.approx(s, abs=0.02), (s, got, fix.segment_index)
        if prev is not None:
            assert got >= prev - 0.005
        prev = got
    assert fix.segment_index == len(keys) - 1
