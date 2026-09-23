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
