"""Prototype B: pursue the planned route from the localised pose."""

import copy
import math

import cv2
import lane_sim
import numpy as np
import pytest
from control.sensing.route_map import RouteMapFollower
from lane_scenarios import (
    GRAPH,
    SCENARIOS,
    WORLD,
    junction_score,
    run_scenario,
    summary,
)
from lane_sim import CAM_X

#: Design §7: B's end position, estimate against truth, at the end condition.
END_POSITION_MAX_ERROR_M = 0.020


def follower(scenario):
    return RouteMapFollower(GRAPH, [scenario["into"], scenario["out"]],
                            start_pose=scenario["start"], camera_x_offset_m=CAM_X, seed=7)


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


def test_a_lost_localiser_stops_rather_than_guessing():
    """Fail-closed: paint erased after the node, so the match collapses."""
    scenario = SCENARIOS[5]
    blank = _world_without_paint_after_the_node(scenario)
    result = run_scenario(scenario, follower(scenario), steps=260, world=blank)
    assert not result["pass"]
    assert result["tiers"][-1] == "STOP"


def test_camera_lane_disagreement_stops_the_follower():
    """If the localised pose says the lane centre is here but the camera's
    own centre line says otherwise by more than half a half-width, stop."""
    scenario = SCENARIOS[5]
    f = follower(scenario)
    f.force_pose_offset(0.08)     # test hook: bias the estimate laterally
    result = run_scenario(scenario, f, steps=120)
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
