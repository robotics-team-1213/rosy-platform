"""A standing robot's pin stays on the lanes its body can touch (2026-11-27 live run: three robots in the charge
bays, 0.226 m apart, each pinned its neighbours' bay lanes and all three waited on one another)."""
import math
from types import SimpleNamespace as NS

import pytest

from core_common.robot_body import MARGIN_M, PINKY_PRO
from fleet.traffic.lane_traffic_helpers import units_under_pose
from rosy.world.state.projections.map_pose import MapPose
from test_lane_traffic import _ticks, _trip
from test_road_trip_table_peers import _restarted

BAY_GAP_M, WIDTH_M, U_MAX = 0.226, 0.20, 0.12 + 0.03
LENGTH = PINKY_PRO.front_x_m - PINKY_PRO.rear_x_m
FRESH = min(U_MAX, PINKY_PRO.rotation_radius_m + MARGIN_M)   # the body at any heading, plus the body margin


def _bay(x, width=WIDTH_M):  # a bay lane along +y at x
    return NS(forward=True, width_m=width, edge_id=f"bay@{x:.3f}",
              project=lambda px, py: (abs(px - x), py, math.pi / 2))


def _bays(width=WIDTH_M):
    arcs = {i: _bay(i * BAY_GAP_M, width) for i in range(3)}
    layout = NS(edge_units={arc.edge_id: ((f"lane:{arc.edge_id}", 0.0, 0.5),) for arc in arcs.values()})
    return layout, NS(arcs=arcs)


@pytest.mark.parametrize("width", [0.20, 0.224])
def test_a_fresh_pose_in_one_bay_pins_only_that_bay(width):
    layout, graph = _bays(width)
    pose = (BAY_GAP_M, 0.25, math.pi / 2)   # the middle bay
    assert set(units_under_pose(layout, graph, pose, LENGTH, U_MAX, 0.0, FRESH)) == {"lane:bay@0.226"}
    # the dead-reckoned bound reaches both neighbours: what deadlocked the three robots
    assert len(units_under_pose(layout, graph, pose, LENGTH, U_MAX)) == 3


def test_a_body_that_reaches_the_next_lane_still_pins_it():
    layout, graph = _bays()
    astride = (BAY_GAP_M / 2, 0.25, math.pi / 2)   # between two bays: its body touches both lanes
    assert set(units_under_pose(layout, graph, astride, LENGTH, U_MAX, 0.0, FRESH)) == {"lane:bay@0.000", "lane:bay@0.226"}


def test_the_reach_along_the_lane_is_not_narrowed():
    layout, graph = _bays()
    layout.edge_units["bay@0.000"] = (("near", 0.0, 0.25), ("far", 0.25, 0.5))
    pose = (0.0, 0.10, math.pi / 2)
    assert units_under_pose(layout, graph, pose, LENGTH, U_MAX, 0.0, FRESH) == \
        {unit: True for unit in units_under_pose(layout, graph, pose, LENGTH, U_MAX) if unit in ("near", "far")}
    assert "far" in units_under_pose(layout, graph, pose, LENGTH, U_MAX, 0.0, FRESH)   # 0.10 + length + u reaches 0.25


def test_a_skewed_body_whose_corner_reaches_the_next_lane_pins_it():
    layout, graph = _bays()
    edge = BAY_GAP_M - WIDTH_M / 2                      # the middle lane's near edge
    reach = PINKY_PRO.rotation_radius_m + MARGIN_M      # how far a body at any heading may stick out
    pose = (edge - reach + 0.001, 0.25, math.pi / 4)    # its corner is just inside that lane
    assert "lane:bay@0.226" in units_under_pose(layout, graph, pose, LENGTH, U_MAX, 0.0, FRESH)
    assert "lane:bay@0.226" not in units_under_pose(layout, graph, (edge - reach - 0.005, 0.25, 0.0), LENGTH, U_MAX, 0.0, FRESH)


def test_the_fresh_side_reach_stays_under_the_bay_gap_and_never_exceeds_u():
    assert 0.224 / 2 + FRESH < BAY_GAP_M and FRESH <= U_MAX


def _beside(east, gap):
    """A pose beside ``east``, ``gap`` m past the lane's edge."""
    x, y, tangent = east.point_at(east.length_m * 0.6)
    off = east.width_m / 2 + gap
    return x - math.sin(tangent) * off, y + math.cos(tangent) * off, tangent


def _idle(east, gap, age=0.1):
    return MapPose(*_beside(east, gap), "LOCALIZED", "sighting", 0.0, age, age)


def test_through_the_table_only_a_standing_robot_gets_the_body_reach():
    """Between the body reach (0.103 m) and u (0.12 m and more) beside the lane: a standing robot is not on it."""
    gap = PINKY_PRO.rotation_radius_m + MARGIN_M + 0.008
    runner, store, fleet, east = _restarted(lambda east: _idle(east, gap))
    _trip(runner, store, fleet, "b", "east:fwd", east.length_m * 0.1)
    _ticks(runner, fleet, n=1)
    assert runner.traffic.pinned() == ["a"]            # first sight: no earlier pose says it stands, so u
    _ticks(runner, fleet, n=2)
    assert runner.traffic.pinned() == []               # the same pose again: it stands, and its body is off the lane
    for step in range(3):                              # moved 2 cm each period (a jog, a dock): u again
        x, y, yaw = _beside(east, gap)
        fleet.p["a"].pose = MapPose(x + 0.02 * (step + 1) * math.cos(yaw), y + 0.02 * (step + 1) * math.sin(yaw), yaw,
                                    "LOCALIZED", "sighting", 0.0, 0.1, 0.1)
        _ticks(runner, fleet, n=1)
        assert runner.traffic.pinned() == ["a"]
