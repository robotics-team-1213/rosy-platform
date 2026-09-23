"""Prototype B: pursue the planned route from the localised pose."""

import copy
import math

import cv2
import lane_sim
import numpy as np
import pytest
from control.sensing.lane_bev import MEMORY_CONFIDENCE
from control.sensing.route_map import (
    CONFIDENCE_MIN,
    MAX_SPREAD_M,
    MIN_MATCH,
    RouteMapFollower,
    confidence_for,
)
from lane_scenarios import (
    GRAPH,
    SCENARIOS,
    WORLD,
    OdomError,
    junction_score,
    run_scenario,
    summary,
)
from lane_sim import CAM_X

#: Design §7: B's end position, estimate against truth, at the end condition.
END_POSITION_MAX_ERROR_M = 0.020


#: Camera/route cross-check coverage (compared frames / frames) on each
#: clean scenario. Measured 0.57 (05) to 0.94 (08); the frames not compared
#: are those where the camera tracker holds no fresh lock (MEMORY through
#: a mouth, the first frames before a seed). The review found 4-26 %.
MIN_COVERAGE = 0.5


def follower(scenario, cls=RouteMapFollower):
    return cls(GRAPH, [scenario["into"], scenario["out"]],
               start_pose=scenario["start"], camera_x_offset_m=CAM_X, seed=7)


class _BiasedFollower(RouteMapFollower):
    """Test double: every estimate is shifted `offset_m` to its left
    (negative: right) before it steers and is cross-checked."""

    offset_m = 0.0

    def _steer_pose(self, estimate):
        x, y, yaw = estimate.pose
        return (x - self.offset_m * math.sin(yaw), y + self.offset_m * math.cos(yaw), yaw)


def _world_without_paint_after_the_node(scenario):
    """WORLD with every painted pixel within 0.25 m of `out`'s centreline
    past its first 0.10 m erased: the robot reaches the node on real paint
    and then looks at bare floor."""
    world = copy.copy(WORLD)
    world.paint = WORLD.paint.copy()
    out = junction_score.directed_points(GRAPH, scenario["out"])
    after = out[junction_score._arc_length(out) >= 0.10]
    mask = np.zeros_like(world.paint)
    pts = np.rint(world.px(after) * 16).astype(np.int32)
    cv2.polylines(mask, [pts], False, 255, 500, shift=4)
    world.paint[mask > 0] = 0
    return world


@pytest.mark.parametrize("index", range(12))
def test_every_junction_transition_is_driven(index):
    scenario = SCENARIOS[index]
    f = follower(scenario)
    result = run_scenario(scenario, f, steps=260)
    result["scenario"] = scenario
    assert result["reached_end"], summary([result])
    assert result["branch_ok"], summary([result])
    assert not result["wrong_way"], summary([result])
    assert result["ring_ccw_ok"], summary([result])
    assert result["max_centre_dev_m"] <= 0.040, summary([result])
    # The last update saw the pose before the last command: track[-2].
    error = math.dist(f.last["estimate"].pose[:2], result["track"][-2])
    assert error <= END_POSITION_MAX_ERROR_M, (error, summary([result]))
    assert f.last["coverage"] >= MIN_COVERAGE, f.last["coverage"]


@pytest.mark.parametrize("bias", [0.02, -0.02])
@pytest.mark.parametrize("index", [2, 3, 8, 9])
def test_a_heading_bias_is_driven_without_stalls(index, bias):
    """Closed loop, odometry 5 % long with a 0.02 rad/s yaw bias while
    moving: before the per-metre yaw noise B passed these only through
    15-34 s MATCH stalls (LOST under CORE's 3 s lease: 6/12). Now no LOST
    and no stall, and the end estimate within design §7's 20 mm."""
    scenario = SCENARIOS[index]
    f = follower(scenario)
    result = run_scenario(scenario, f, steps=260, odom_error=OdomError(0.05, bias))
    result["scenario"] = scenario
    assert result["pass"], summary([result])
    assert result["reason"] is None
    assert result["max_stall_s"] <= 0.4, result["max_stall_s"]
    error = math.dist(f.last["estimate"].pose[:2], result["last_true_pose"][:2])
    assert error <= END_POSITION_MAX_ERROR_M, error


def test_a_lost_localiser_stops_rather_than_guessing():
    """Fail-closed: paint erased after the node, so the match collapses."""
    scenario = SCENARIOS[5]
    blank = _world_without_paint_after_the_node(scenario)
    result = run_scenario(scenario, follower(scenario), steps=260, world=blank)
    assert not result["pass"]
    assert result["tiers"][-1] == "STOP"


@pytest.mark.parametrize("offset_m", [0.05, -0.05])
@pytest.mark.parametrize("index", [0, 5, 7])
def test_a_50mm_pose_bias_stops_the_follower(index, offset_m):
    """HIGH-2: if the localised pose places the camera's own lane 50 mm off
    every centreline, stop (either side; 00 and 07 start on bends)."""
    scenario = SCENARIOS[index]
    f = follower(scenario, _BiasedFollower)
    f.offset_m = offset_m
    result = run_scenario(scenario, f, steps=120)
    assert not result["pass"]
    assert result["tiers"][-1] == "STOP"
    assert f.last["reason"] == "DISAGREE"


def test_without_odometry_or_ground_there_is_no_output():
    scenario = SCENARIOS[5]
    f = follower(scenario)
    frame = WORLD.render(scenario["start"])
    assert f.update(0.0, None, frame, lane_sim.GROUND, **lane_sim.KW) is None
    assert f.state == "STOP"
    f = follower(scenario)
    assert f.update(0.0, scenario["start"], frame, None, **lane_sim.KW) is None
    assert f.state == "STOP"


def test_confidence_stays_inside_cores_band():
    """Confidence is CORE's speed scale: never above 1.0 and, when there is
    an output at all, above CORE's 0.35 minimum."""
    scenario = SCENARIOS[0]
    f = follower(scenario)
    pose = tuple(scenario["start"])
    for k in range(20):
        obs = f.update(k * lane_sim.DT, pose, WORLD.render(pose), lane_sim.GROUND, **lane_sim.KW)
        if obs is not None:
            assert 0.35 < obs.confidence <= 1.0


def test_a_weak_match_slows_core_below_memory_speed():
    """MEDIUM (review): confidence was floored at MEMORY_CONFIDENCE, so a
    barely-accepted estimate drove as fast as remembered paint. A match
    just above MIN_MATCH must now read below MEMORY_CONFIDENCE."""
    assert confidence_for(MIN_MATCH + 0.01, 0.0) < MEMORY_CONFIDENCE


def test_confidence_maps_quality_linearly_onto_its_band():
    assert confidence_for(MIN_MATCH, 0.0) == pytest.approx(CONFIDENCE_MIN)
    assert confidence_for(0.9, 0.0) == pytest.approx(1.0)
    assert confidence_for(0.9, MAX_SPREAD_M) == pytest.approx(CONFIDENCE_MIN)
    matches = np.linspace(MIN_MATCH, 0.9, 20)
    values = [confidence_for(m, 0.004) for m in matches]
    assert all(b >= a for a, b in zip(values, values[1:]))
    assert 0.35 < CONFIDENCE_MIN < MEMORY_CONFIDENCE
