"""Offline 12-scenario closed loop: same scoring as the Gazebo harness."""

import math

import lane_sim
import numpy as np
import pytest
from control.sensing.perception.lane import LaneObservation
from control.sensing.perception.lane_boundaries import LaneBoundaryTracker
from lane_scenarios import (
    LOST_AFTER_S,
    SCENARIOS,
    OdomError,
    believed_start,
    run_scenario,
)
from lane_sim import CAM_X


def centre_tracker():
    return LaneBoundaryTracker(camera_x_offset_m=CAM_X)


def test_twelve_scenarios_match_the_harness_definition():
    assert len(SCENARIOS) == 12
    assert sorted({s["node"] for s in SCENARIOS}) == ["NE", "NW", "SE", "SW"]


def test_runner_returns_track_and_score_keys():
    result = run_scenario(SCENARIOS[5], centre_tracker(), steps=120)
    for key in ("track", "pass", "branch_ok", "reached_end", "max_centre_dev_m",
                "wrong_way", "ring_ccw_ok", "tiers"):
        assert key in result


def test_centre_mode_reproduces_the_gazebo_baseline_shape():
    """Gazebo run 2026-09-23 (baseline.md): 0/12; 10 never start (no pair to
    seed on a bend); 05 and 11 drive the ring clockwise. The offline loop is
    the same renderer, so it must show the same two failure modes."""
    stuck, moved = [], []
    for scenario in SCENARIOS:
        result = run_scenario(scenario, centre_tracker(), steps=150)
        travelled = sum(math.dist(result["track"][i], result["track"][i + 1])
                        for i in range(len(result["track"]) - 1))
        (moved if travelled > 0.05 else stuck).append(scenario["node"] + ":" + scenario["into"])
        assert not result["pass"]
    assert len(stuck) >= 8, f"expected most starts to fail closed, stuck={stuck}"
    assert moved, "at least one scenario moved in the Gazebo baseline"


# --- odometry error and CORE lease (the drift-grid instrument) -------------


class _Recorder:
    """Stub follower: records what it is given, answers a fixed observation."""

    def __init__(self, observation=None):
        self.observation = observation
        self.poses, self.frames = [], []
        self.state = "-"

    def update(self, now_s, pose, bgr, ground, **kwargs):
        self.poses.append(pose)
        self.frames.append(bgr)
        return self.observation


STRAIGHT = LaneObservation(error=0.0, confidence=1.0)


def test_without_odom_error_the_follower_gets_the_true_pose():
    recorder = _Recorder(STRAIGHT)
    result = run_scenario(SCENARIOS[5], recorder, steps=5)
    assert recorder.poses[0] == tuple(SCENARIOS[5]["start"])
    assert recorder.poses[-1] == pytest.approx(result["last_true_pose"])
    assert result["last_odom_pose"] == pytest.approx(result["last_true_pose"])


def test_a_start_offset_moves_odometry_but_not_the_camera():
    recorder = _Recorder(None)
    start = tuple(SCENARIOS[5]["start"])
    run_scenario(SCENARIOS[5], recorder, steps=2,
                 odom_error=OdomError(start_offset_lateral_m=0.02,
                                      start_offset_yaw_rad=math.radians(2.0)))
    x, y, yaw = start
    expected = (x - 0.02 * math.sin(yaw), y + 0.02 * math.cos(yaw), yaw + math.radians(2.0))
    assert recorder.poses[0] == pytest.approx(expected)
    assert believed_start(SCENARIOS[5], OdomError(0.0, 0.0, 0.02, math.radians(2.0)))         == pytest.approx(expected)
    assert np.array_equal(recorder.frames[0], lane_sim.stl_world().render(start))


def test_scale_and_yaw_bias_corrupt_only_the_odometry():
    """Straight at cruise: the truth goes straight, odometry reads (1+s) of
    the travel and turns at the bias rate."""
    recorder = _Recorder(STRAIGHT)
    steps = 6
    result = run_scenario(SCENARIOS[5], recorder, steps=steps,
                          odom_error=OdomError(scale=0.05, yaw_rate_bias=0.02))
    start = tuple(SCENARIOS[5]["start"])
    true_travel = math.dist(result["track"][-1], start[:2])
    assert true_travel == pytest.approx(steps * 0.08 * lane_sim.DT)
    assert result["final_pose"][2] == pytest.approx(start[2])
    odom_travel = math.dist(recorder.poses[-1][:2], start[:2])
    assert odom_travel == pytest.approx(1.05 * (steps - 1) * 0.08 * lane_sim.DT, rel=1e-3)
    assert recorder.poses[-1][2] - start[2] == pytest.approx((steps - 1) * lane_sim.DT * 0.02)


def test_yaw_bias_does_not_accumulate_while_standing_still():
    recorder = _Recorder(None)
    run_scenario(SCENARIOS[5], recorder, steps=5, odom_error=OdomError(yaw_rate_bias=0.02))
    assert recorder.poses[-1] == pytest.approx(recorder.poses[0])


@pytest.mark.parametrize("observation", [None, LaneObservation(error=0.0, confidence=0.34)])
def test_cores_lease_ends_the_run_as_lost(observation):
    """CORE line_follow: invalid evidence (none, or under min_confidence)
    for longer than lost_after_s latches LOST."""
    recorder = _Recorder(observation)
    result = run_scenario(SCENARIOS[5], recorder, steps=200)
    assert result["reason"] == "lost"
    assert not result["pass"]
    # First invalid frame at t=0; LOST on the first tick past 3.0 s.
    assert len(recorder.poses) == round(LOST_AFTER_S / lane_sim.DT) + 2
    assert result["stall_s"] == pytest.approx(result["max_stall_s"])
    assert result["max_stall_s"] > LOST_AFTER_S


def test_a_short_stall_is_counted_but_not_lost():
    class Blink(_Recorder):
        def update(self, now_s, pose, bgr, ground, **kwargs):
            super().update(now_s, pose, bgr, ground, **kwargs)
            return None if 5 <= len(self.poses) <= 14 else STRAIGHT

    result = run_scenario(SCENARIOS[5], Blink(), steps=30)
    assert result["reason"] is None
    assert result["stall_s"] == pytest.approx(10 * lane_sim.DT)
    assert result["max_stall_s"] == pytest.approx(10 * lane_sim.DT)
