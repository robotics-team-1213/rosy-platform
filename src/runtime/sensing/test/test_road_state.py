"""D-384 road-state estimator: prediction, gates, association, degradation ladder.

ROS-free. Operating point 0.03-0.08 m/s at 8 fps (lane auto is refused below L1);
the tests drive at 0.05 m/s unless a case needs another speed.
"""

import json
import math

import numpy as np
import pytest

from control.sensing.perception.road_state import (
    COAST,
    SLOW,
    STOP,
    TRACK,
    BoundaryMeas,
    IrMeas,
    OffsetMeas,
    RoadStateEstimator,
    RoadStateParams,
    WallSeg,
    boundaries_from_keep,
    decision_point_from_keep,
    offset_from_shadow,
    wall_segments_from_scan,
)

W = 0.185
HALF = W / 2
X = 0.22
FPS = 8.0
DT = 1.0 / FPS
V = 0.05


def pair(d=0.0, phi=0.0, width=W):
    """Right and left boundary as seen from lateral offset d (left +) and heading error phi."""
    return [BoundaryMeas(y=-width / 2 - d - X * phi, psi=-phi, x=X),
            BoundaryMeas(y=width / 2 - d - X * phi, psi=-phi, x=X)]


class Clock:
    def __init__(self, est, v=V):
        self.est, self.v, self.t = est, v, 0.0

    def frame(self, meas=(), v=None, **kw):
        v = self.v if v is None else v
        self.t += DT
        self.est.predict(v * DT, 0.0, dt=DT, stamp=self.t)
        return self.est.update(list(meas), self.t, **kw)


def tracking(**params):
    est = RoadStateEstimator(RoadStateParams(**params))
    clock = Clock(est)
    for _ in range(8):
        clock.frame(pair())
    assert est.level == TRACK
    return est, clock


# ---------------------------------------------------------------- prediction

def test_predict_straight_moves_d_along_the_heading_error():
    est = RoadStateEstimator()
    est.x[:] = [0.01, 0.1, 0.0, W]
    est.predict(0.1, 0.0, dt=1.0)
    assert est.x[0] == pytest.approx(0.01 + 0.1 * math.sin(0.1))
    assert est.x[1] == pytest.approx(0.1)


def test_predict_on_an_arc_keeps_the_heading_error_when_turning_with_the_road():
    est = RoadStateEstimator()
    est.x[:] = [0.0, 0.0, 2.0, W]
    est.predict(0.1, 0.2, dt=1.0)   # dtheta = kappa * ds
    assert est.x[1] == pytest.approx(0.0)
    assert est.x[0] == pytest.approx(0.0)
    est.predict(0.1, 0.0, dt=1.0)   # not turning on a left bend: heading error goes right
    assert est.x[1] == pytest.approx(-0.2)


def test_process_noise_matches_odometry_error_and_has_a_time_floor():
    p = RoadStateParams()
    est = RoadStateEstimator(p)
    before = est.P.copy()
    est.predict(0.0, 0.0, dt=1.0)   # held still: the filter must not collapse
    grow = np.diag(est.P - before)
    assert grow[0] == pytest.approx(p.q_d_floor ** 2)
    assert grow[1] == pytest.approx(p.q_phi_floor ** 2)
    assert grow[2] > 0 and grow[3] > 0
    est = RoadStateEstimator(p)
    est.P[:] = 0.0                  # only Q remains
    est.predict(0.1, 0.05, dt=0.0)
    grow = np.diag(est.P)
    assert grow[0] == pytest.approx((0.08 * 0.1) ** 2)
    assert grow[1] == pytest.approx((0.03 * 0.05) ** 2 + (0.02 * 0.1) ** 2)


def test_map_curvature_pulls_kappa():
    est = RoadStateEstimator()
    est.set_map_curvature(3.0)
    for _ in range(40):
        est.predict(0.05, 0.0, dt=DT)
    assert est.x[2] == pytest.approx(3.0, abs=0.05)


# ---------------------------------------------------------------- update and gates

def test_update_pulls_toward_the_measurement():
    est, clock = tracking()
    clock.frame(pair(d=0.01))
    assert 0.0 < est.x[0] < 0.01


def test_image_wall_rejection_and_lidar_veto_off_by_default():
    est, clock = tracking()
    right, left = pair(d=0.0)
    clock.frame([BoundaryMeas(y=right.y, psi=right.psi, x=X, rejected="wall"), left])
    assert est.rejects["wall"] == 1
    assert est.last_frame["hypothesis"]["labels"] == "L"
    wall = WallSeg(0.1, right.y, 0.4, right.y)
    clock.frame([right, left, wall])       # LiDAR veto off: the wall segment is ignored
    assert est.rejects["wall"] == 1
    assert est.last_frame["hypothesis"]["labels"] == "RL"


def test_lidar_veto_when_enabled_rejects_a_boundary_on_a_wall():
    est, clock = tracking(lidar_wall_veto=True)
    right, left = pair()
    clock.frame([right, left, WallSeg(0.1, right.y + 0.03, 0.4, right.y + 0.03)])
    assert est.rejects["wall"] == 1
    assert est.last_frame["hypothesis"]["labels"] == "L"
    # 20 degrees off the wall is not the wall
    tilt = math.radians(20)
    clock.frame([right, left, WallSeg(0.1, right.y, 0.1 + math.cos(tilt), right.y + math.sin(tilt))])
    assert est.rejects["wall"] == 1


def test_nis_outlier_is_rejected():
    est, clock = tracking()
    right, _ = pair()
    d0 = est.x[0]
    clock.frame([BoundaryMeas(y=right.y, psi=math.radians(40), x=X)])
    assert est.rejects["nis"] == 1
    assert est.x[0] == pytest.approx(d0, abs=1e-3)


def test_five_centimetre_jump_is_rejected_even_when_nis_passes():
    est, clock = tracking()
    est.P[0, 0] = 0.04 ** 2       # loose enough that NIS alone would accept 5 cm
    clock.frame([BoundaryMeas(y=-HALF - 0.05, psi=0.0, x=X)])
    assert est.rejects["jump"] == 1
    assert est.last_frame["hypothesis"]["labels"] == "N"


def test_bad_pair_width_is_rejected():
    est, clock = tracking()
    est.P[0, 0] = 0.02 ** 2        # each line alone passes NIS; only the pair width fails
    clock.frame([BoundaryMeas(y=-HALF - 0.025, psi=0.0, x=X),
                 BoundaryMeas(y=HALF + 0.025, psi=0.0, x=X)])
    assert est.rejects["width"] == 1
    assert est.last_frame["hypothesis"]["labels"] in ("RN", "NL")


def test_non_parallel_pair_is_rejected():
    est, clock = tracking()
    est.P[1, 1] = math.radians(15) ** 2
    clock.frame([BoundaryMeas(y=-HALF, psi=math.radians(7), x=X),
                 BoundaryMeas(y=HALF, psi=math.radians(-7), x=X)])
    assert est.rejects["width"] == 1


def test_far_boundaries_are_not_measurements():
    est, clock = tracking()
    clock.frame([BoundaryMeas(y=-HALF, psi=0.0, x=0.40)])
    assert est.last_frame["candidates"] == []


def test_learned_offset_gated_in_one_dimension():
    est, clock = tracking()
    clock.frame([OffsetMeas(d=0.2, sigma=0.01, stamp=clock.t)])
    assert est.rejects["nis"] == 1
    clock.frame([OffsetMeas(d=0.005, sigma=0.01, stamp=clock.t)])
    assert est.last_frame["accepted"]["learned"] == 1


def test_learned_offset_with_wall_in_view_is_not_used():
    est, clock = tracking()
    meas = offset_from_shadow({"visible": True, "error": 0.0, "confidence": 0.9, "stamp": clock.t,
                               "class_fractions": {"wall": 0.4}}, half_width_m=HALF)
    clock.frame([meas])
    assert est.rejects["wall"] == 1


def test_offset_from_shadow_sigma_and_sign():
    m = offset_from_shadow({"visible": True, "error": 0.2, "confidence": 0.1, "stamp": 3.0,
                            "class_fractions": {}}, half_width_m=HALF)
    # lane right of image centre (error > 0) -> the robot is left of the lane centre (d > 0)
    assert m.d == pytest.approx(0.2 * HALF)
    assert m.sigma == pytest.approx(0.03 / 0.2)
    assert m.stamp == 3.0
    assert m.confidence == pytest.approx(0.1)
    assert offset_from_shadow({"visible": False, "error": None, "confidence": 0.0,
                               "stamp": 1.0}, half_width_m=HALF) is None


def test_stale_learned_measurement_is_shifted_by_odometry_since_its_stamp():
    est = RoadStateEstimator()
    est.x[:] = [0.0, 0.1, 0.0, W]
    t = 0.0
    for _ in range(10):
        t += 0.1
        est.predict(0.005, 0.0, dt=0.1, stamp=t)
    meas = OffsetMeas(d=0.02, sigma=0.01, stamp=0.5)   # 5 steps = 0.025 m ago
    assert est.shifted_offset(meas) == pytest.approx(0.02 + 0.025 * math.sin(0.1), abs=1e-9)
    assert est.shifted_offset(OffsetMeas(d=0.02, sigma=0.01, stamp=t)) == pytest.approx(0.02)
    assert est.shifted_offset(OffsetMeas(d=0.02, sigma=0.01, stamp=-5.0)) is None   # older than history


def test_stale_learned_measurement_beyond_history_is_rejected():
    est, clock = tracking()
    clock.frame([OffsetMeas(d=0.0, sigma=0.01, stamp=clock.t - 60.0)])
    assert est.rejects["stale"] == 1


# ---------------------------------------------------------------- association

def test_single_boundary_is_tracked_as_right_on_fresh_acquisition():
    est = RoadStateEstimator()
    est.update([BoundaryMeas(y=-0.005, psi=0.0, x=X)], 0.1)
    assert est.last_frame["hypothesis"]["labels"] == "R"
    assert est.x[0] < 0.0


def test_single_boundary_is_left_when_right_fails_the_gate():
    est, clock = tracking()
    clock.frame([BoundaryMeas(y=HALF, psi=0.0, x=X)])
    assert est.last_frame["hypothesis"]["labels"] == "L"
    assert est.x[0] == pytest.approx(0.0, abs=0.005)


THREE_LINES = [BoundaryMeas(y=-HALF - W, psi=0.0, x=X),
               BoundaryMeas(y=-HALF, psi=0.0, x=X),
               BoundaryMeas(y=HALF, psi=0.0, x=X)]


def test_ambiguity_on_fresh_acquisition_takes_the_rightmost_lane():
    est = RoadStateEstimator()
    est.P[0, 0] = 1.0
    est.update(THREE_LINES, 0.1)
    frame = est.last_frame
    assert frame["tie"] and frame["tie_rule"] == "right"
    assert frame["hypothesis"]["labels"] == "RLN"
    assert est.x[0] == pytest.approx(W, abs=0.01)


def test_route_hint_overrides_the_right_rule_at_a_decision_point():
    est = RoadStateEstimator(route_hint="left")
    est.P[0, 0] = 1.0
    est.update(THREE_LINES, 0.1, decision_point=True)
    assert est.last_frame["tie_rule"] == "route"
    assert est.last_frame["hypothesis"]["labels"] == "NRL"
    assert est.x[0] == pytest.approx(0.0, abs=0.01)


def test_route_hint_is_ignored_away_from_a_decision_point():
    est = RoadStateEstimator(route_hint="left")
    est.P[0, 0] = 1.0
    est.update(THREE_LINES, 0.1)
    assert est.last_frame["tie_rule"] == "right"
    assert est.last_frame["hypothesis"]["labels"] == "RLN"


def test_route_hint_never_breaks_a_tie_on_an_established_track_without_a_decision_point():
    est, clock = tracking()
    est.route_hint = "right"
    split = [BoundaryMeas(y=-HALF + 0.0125, psi=0.0, x=X), BoundaryMeas(y=-HALF - 0.0125, psi=0.0, x=X)]
    clock.frame(split)
    assert est.last_frame["tie_rule"] == "ambiguous"
    clock.frame(split, decision_point=True)
    assert est.last_frame["tie_rule"] == "route"
    assert est.last_frame["hypothesis"]["labels"] == "RN"      # the rightmost candidate as R


IR_ON = {"ir_geometry_measured": True}


def test_ir_is_off_until_its_geometry_is_measured():
    est, clock = tracking()
    clock.frame(pair() + [IrMeas(y=-HALF)])
    assert est.last_frame["accepted"]["ir"] == 0
    est, clock = tracking(**IR_ON)
    clock.frame(pair() + [IrMeas(y=-HALF)])
    assert est.last_frame["accepted"]["ir"] == 1


def test_right_rule_must_agree_with_ir_or_hold():
    est = RoadStateEstimator(RoadStateParams(**IR_ON))
    est.P[0, 0] = 1.0
    est.update(THREE_LINES + [IrMeas(y=HALF)], 0.1)    # IR sees a line where the rightmost lane has none
    assert est.level == STOP
    assert est.stop_reason == "ambiguous"
    assert est.x[0] == pytest.approx(0.0)
    est = RoadStateEstimator(RoadStateParams(**IR_ON))
    est.P[0, 0] = 1.0
    est.update(THREE_LINES + [IrMeas(y=-HALF)], 0.1)  # the rightmost lane's left line under IR
    assert est.last_frame["hypothesis"]["labels"] == "RLN"


def test_an_established_track_is_never_switched_by_the_right_rule():
    est, clock = tracking()
    for _ in range(3):
        clock.frame(THREE_LINES)
    assert est.x[0] == pytest.approx(0.0, abs=0.01)
    assert est.last_frame["hypothesis"]["labels"] == "NRL"


def test_a_tie_on_an_established_track_uses_no_boundary():
    est, clock = tracking()
    d0 = est.x[0]
    clock.frame([BoundaryMeas(y=-HALF + 0.0125, psi=0.0, x=X), BoundaryMeas(y=-HALF - 0.0125, psi=0.0, x=X)])
    frame = est.last_frame
    assert frame["tie"] and frame["tie_rule"] == "ambiguous"
    assert frame["hypothesis"]["labels"] is None
    assert est.rejects["ambiguous"] == 1
    assert est.x[0] == pytest.approx(d0, abs=1e-3)
    assert est.level == TRACK          # the ladder, not an immediate stop


def test_compatible_labellings_are_not_a_tie():
    est, clock = tracking()
    right, left = pair()
    clock.frame([right, BoundaryMeas(y=left.y + 0.03, psi=0.0, x=X)])   # a mediocre left line
    assert est.last_frame["tie_rule"] is None


def test_at_most_three_hypotheses_are_kept():
    est, clock = tracking()
    clock.frame(THREE_LINES + [BoundaryMeas(y=HALF + W, psi=0.0, x=X)])
    assert 1 <= len(est.last_frame["hypotheses"]) <= 3


# ---------------------------------------------------------------- degradation ladder

def test_ladder_by_distance_and_clock_at_operating_speed():
    est, clock = tracking()
    levels = []
    for _ in range(40):          # 5 s at 0.05 m/s without a line
        clock.frame([])
        levels.append(est.level)
    assert levels[0] == TRACK and levels[1] == COAST
    first_slow = levels.index(SLOW)
    first_stop = levels.index(STOP)
    # COAST until 1.08 * s_lost reaches 0.10 m (1.85 s at 0.05 m/s)
    assert first_slow == pytest.approx(0.10 / 1.08 / (V * DT), abs=1.5)
    # CORE latches LOST after 3.0 s: SLOW ends at 2.5 s, before the 0.25 m budget
    assert (first_stop + 1) * DT == pytest.approx(2.5, abs=DT + 1e-9)
    assert est.stop_reason == "lost_time"


def test_ladder_distance_budget_ends_slow_at_higher_speed():
    est, clock = tracking()
    for _ in range(30):
        clock.frame([], v=0.15)
        if est.level == STOP:
            break
    assert est.stop_reason == "lost_distance"


def test_held_robot_still_times_out():
    est, clock = tracking()
    for _ in range(int(2.4 / DT)):
        clock.frame([], v=0.0)
    assert est.level == COAST
    for _ in range(3):
        clock.frame([], v=0.0)
    assert est.level == STOP and est.stop_reason == "lost_time"


def test_ladder_by_covariance():
    est, clock = tracking()
    clock.frame([])
    est.P[0, 0] = 0.04 ** 2
    clock.frame([])
    assert est.level == SLOW
    est.P[0, 0] = 0.06 ** 2
    clock.frame([])
    assert est.level == STOP and est.stop_reason == "covariance"


def test_three_wall_only_frames_stop():
    est, clock = tracking()
    wall = [BoundaryMeas(y=-HALF, psi=0.0, x=X, rejected="wall")]
    clock.frame(wall)
    clock.frame(wall)
    assert est.level != STOP
    clock.frame(wall)
    assert est.level == STOP and est.stop_reason == "wall_only"


def test_reacquisition_needs_three_consistent_frames_over_one_centimetre():
    est = RoadStateEstimator()
    assert est.level == STOP
    held = Clock(est, v=0.0)
    for _ in range(5):
        held.frame(pair())
    assert est.level == STOP             # consistent but not moving
    est = RoadStateEstimator()
    clock = Clock(est)
    clock.frame(pair())
    clock.frame(pair())
    assert est.level == STOP
    clock.frame(pair())
    assert est.level == TRACK


def test_reacquisition_resets_on_an_inconsistent_frame():
    est = RoadStateEstimator()
    clock = Clock(est)
    clock.frame(pair())
    clock.frame(pair())
    right, _ = pair()
    clock.frame([right])                 # one side, no IR: not consistent
    clock.frame(pair())
    assert est.level == STOP
    clock.frame(pair())
    clock.frame(pair())
    assert est.level == TRACK


def test_one_side_with_matching_ir_is_consistent():
    est = RoadStateEstimator(RoadStateParams(**IR_ON))
    clock = Clock(est)
    right, _ = pair()
    for _ in range(3):
        clock.frame([right, IrMeas(y=right.y)])   # IR places the same right line
    assert est.level == TRACK
    assert est.snapshot()["reacq_reason"] == "side+ir"


def test_pair_reacquisition_is_logged():
    est = RoadStateEstimator()
    clock = Clock(est)
    for _ in range(3):
        clock.frame(pair())
    snap = est.snapshot()
    assert snap["reacq_reason"] == "pair"
    assert snap["reacq_counts"] == {"pair": 1, "side+ir": 0, "side+learned": 0}


def _side_learned(est, d=0.0, confidence=0.9, frames=3):
    clock = Clock(est)
    right, _ = pair()
    for _ in range(frames):
        clock.frame([right, OffsetMeas(d=d, sigma=0.03 / confidence, stamp=clock.t + DT, confidence=confidence)])
    return est


def test_one_side_with_agreeing_learned_reacquires_in_shadow_without_calibrated_ir():
    est = _side_learned(RoadStateEstimator())
    assert est.level == TRACK
    snap = est.snapshot()
    assert snap["reacq_reason"] == "side+learned"
    assert snap["reacq_counts"]["side+learned"] == 1


def test_side_plus_learned_needs_three_agreeing_frames():
    assert _side_learned(RoadStateEstimator(), frames=2).level == STOP


@pytest.mark.parametrize("kw,params", [
    ({"d": 0.08}, {}),                           # learned 0.08 m off the side's d: beyond 2 sigma
    ({"confidence": 0.3}, {}),                   # below the learned re-acquisition confidence
    ({}, {"ir_calibrated": True}),               # calibrated IR removes the path
    ({}, {"mode": "control"}),                   # never in a control mode
])
def test_side_plus_learned_is_refused(kw, params):
    est = _side_learned(RoadStateEstimator(RoadStateParams(**params)), **kw)
    assert est.level == STOP
    assert est.snapshot()["reacq_counts"]["side+learned"] == 0


def test_learned_alone_never_reacquires():
    est = RoadStateEstimator()
    clock = Clock(est)
    for _ in range(5):
        clock.frame([OffsetMeas(d=0.0, sigma=0.03, stamp=clock.t, confidence=1.0)])
    assert est.level == STOP


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="mode"):
        RoadStateEstimator(RoadStateParams(mode="auto"))


def test_reacquisition_timeout_reports():
    est = RoadStateEstimator()
    clock = Clock(est)
    for _ in range(int(2.4 / DT)):
        clock.frame([])
    assert est.snapshot()["reacquire"]["timed_out"] is True
    est = RoadStateEstimator()
    clock = Clock(est)
    clock.frame([])
    assert est.snapshot()["reacquire"]["timed_out"] is False


# ---------------------------------------------------------------- calibration and output

def test_calibration_suspect_after_two_seconds_of_width_mismatch():
    est, clock = tracking()
    wide = W * 1.15
    for _ in range(int(1.8 / DT)):
        est.x[3] = wide
        clock.frame(pair(width=wide))
    assert est.snapshot()["calibration_suspect"] is False
    for _ in range(4):
        est.x[3] = wide
        clock.frame(pair(width=wide))
    assert est.snapshot()["calibration_suspect"] is True


def test_width_prior_is_tight():
    est = RoadStateEstimator()
    assert math.sqrt(est.P[3, 3]) == pytest.approx(0.005)


def test_snapshot_is_json_and_carries_no_command():
    est, clock = tracking()
    clock.frame(pair(), profile="nominal-v1")
    snap = est.snapshot()
    json.dumps(snap, allow_nan=False)
    for key in ("d", "phi", "kappa", "w", "p_diag", "level", "hypothesis", "rejects", "s_lost_m",
                "core_suggestion", "candidates", "hypotheses", "profile"):
        assert key in snap, key
    assert set(snap["rejects"]) >= {"wall", "nis", "jump", "width"}
    assert snap["profile"] == "nominal-v1"
    text = json.dumps(snap)
    for word in ("cmd", "linear", "angular", "speed", "velocity", "steer", "error"):
        assert f'"{word}' not in text, word


@pytest.mark.parametrize("level,visible,confidence", [
    (TRACK, True, 0.9), (COAST, True, 0.8), (SLOW, True, 0.6), (STOP, False, 0.0)])
def test_core_suggestion_by_level(level, visible, confidence):
    est, clock = tracking()
    frames = {TRACK: 0, COAST: 2, SLOW: 17, STOP: 30}[level]
    for _ in range(frames):
        clock.frame([])
    assert est.level == level
    assert est.snapshot()["core_suggestion"] == {"visible": visible, "confidence": confidence}


def test_slow_confidence_is_the_lane_memory_confidence():
    from control.sensing.perception.lane_bev import MEMORY_CONFIDENCE
    assert RoadStateParams().slow_confidence == MEMORY_CONFIDENCE


def test_replay_is_deterministic():
    def run():
        est, clock = tracking()
        for k in range(20):
            clock.frame(pair(d=0.002 * (k % 5)) + THREE_LINES[:1])
        return json.dumps(est.snapshot(), sort_keys=True)
    assert run() == run()


# ---------------------------------------------------------------- adapters

def test_boundaries_from_keep_debug_bundle():
    last = {"strategy": "both", "transverse": [{"heading_deg": 88.0, "ends_m": [[0.3, -0.1], [0.3, 0.1]]}],
            "boundaries": [
                {"side": "right", "y_at_side_x_m": -0.09, "heading_deg": 2.0,
                 "ends_m": [[0.12, -0.09], [0.35, -0.08]]},
                {"side": "left", "y_at_side_x_m": 0.10, "heading_deg": -1.0,
                 "ends_m": [[0.40, 0.10], [0.55, 0.10]]},      # starts beyond the near field
            ]}
    out = boundaries_from_keep(last)
    assert len(out) == 2
    near = out[0]
    assert near.y == pytest.approx(-0.09) and near.psi == pytest.approx(math.radians(2.0))
    assert near.x == pytest.approx(X) and near.side_hint == "right" and near.rejected is None
    assert out[1].x > 0.33                                 # the estimator drops it


def test_boundaries_from_keep_prefers_candidates_with_reasons():
    accepted = {"side": "right", "y_at_side_x_m": -0.09, "heading_deg": 0.0, "length_m": 0.2,
                "ends_m": [[0.1, -0.09], [0.3, -0.09]], "ends_px": [], "tracked": True, "pursuit_m": [0.25, 0.0],
                "rejected": False, "reason": None}
    transverse = dict(accepted, heading_deg=88.0, rejected=True, reason="transverse")
    last = {"boundaries": [accepted], "candidates": [accepted, transverse]}
    out = boundaries_from_keep(last)
    assert len(out) == 2                      # accepted lines are not counted twice
    assert out[0].rejected is None and out[1].rejected == "transverse"


# LaneKeeper.last shape from feat/lane-keep-candidates (7218c6b5, test_candidates_list_every_line_
# with_its_reject_reason: a centred lane with a stop line at 0.25 m), plus one extrapolation reject.
KEEP_CANDIDATES_7218C6B5 = {
    "strategy": "both", "reason": None, "blobs": 0,
    "transverse": [{"heading_deg": 89.6, "length_m": 0.21, "ends_m": [[0.25, -0.105], [0.251, 0.105]],
                    "ends_px": [[228.4, 150.2], [91.6, 150.3]]}],
    "boundaries": [
        {"heading_deg": 0.3, "length_m": 0.31, "ends_m": [[0.12, -0.093], [0.43, -0.091]],
         "ends_px": [[291.2, 222.0], [205.1, 121.4]], "side": "right", "y_at_side_x_m": -0.092,
         "tracked": False, "pursuit_m": [0.25, -0.001]},
        {"heading_deg": -0.2, "length_m": 0.3, "ends_m": [[0.12, 0.093], [0.42, 0.092]],
         "ends_px": [[28.9, 222.0], [115.2, 122.5]], "side": "left", "y_at_side_x_m": 0.093,
         "tracked": False, "pursuit_m": [0.25, 0.0]}],
    "candidates": [
        {"heading_deg": 89.6, "length_m": 0.21, "ends_m": [[0.25, -0.105], [0.251, 0.105]],
         "ends_px": [[228.4, 150.2], [91.6, 150.3]], "rejected": True, "reason": "transverse"},
        {"heading_deg": 12.0, "length_m": 0.05, "ends_m": [[0.52, 0.2], [0.57, 0.21]],
         "ends_px": [[40.0, 110.0], [52.0, 106.0]], "side": "left", "y_at_side_x_m": 0.14,
         "rejected": True, "reason": "extrapolation"},
        {"heading_deg": 0.3, "length_m": 0.31, "ends_m": [[0.12, -0.093], [0.43, -0.091]],
         "ends_px": [[291.2, 222.0], [205.1, 121.4]], "side": "right", "y_at_side_x_m": -0.092,
         "tracked": False, "pursuit_m": [0.25, -0.001], "rejected": False, "reason": None},
        {"heading_deg": -0.2, "length_m": 0.3, "ends_m": [[0.12, 0.093], [0.42, 0.092]],
         "ends_px": [[28.9, 222.0], [115.2, 122.5]], "side": "left", "y_at_side_x_m": 0.093,
         "tracked": False, "pursuit_m": [0.25, 0.0], "rejected": False, "reason": None}],
}


def test_boundaries_from_the_lane_owner_candidates_shape():
    out = boundaries_from_keep(KEEP_CANDIDATES_7218C6B5)
    # transverse lines carry no side fields: a decision-point cue, not a boundary
    assert [(b.side_hint, b.rejected) for b in out] == [
        ("left", "extrapolation"), ("right", None), ("left", None)]
    assert out[0].x > 0.33                       # far extrapolation reject: outside the near field
    assert decision_point_from_keep(KEEP_CANDIDATES_7218C6B5) is True
    fallback = {k: v for k, v in KEEP_CANDIDATES_7218C6B5.items() if k != "candidates"}
    assert [(b.side_hint, b.rejected) for b in boundaries_from_keep(fallback)] == [
        ("right", None), ("left", None)]


def test_owner_candidates_drive_the_estimator():
    est = RoadStateEstimator()
    clock = Clock(est)
    for _ in range(3):
        clock.frame(boundaries_from_keep(KEEP_CANDIDATES_7218C6B5))
    assert est.level == TRACK
    assert est.last_frame["hypothesis"]["labels"] == "RL"


def test_keeper_rejected_candidates_are_not_measurements():
    est, clock = tracking()
    right, left = pair()
    clock.frame([right, left, BoundaryMeas(y=0.0, psi=0.0, x=X, rejected="junction")])
    assert est.rejects["keeper"] == 1
    assert est.last_frame["hypothesis"]["labels"] == "RL"


@pytest.mark.parametrize("last,expected", [
    ({"strategy": "both", "transverse": [], "reason": None}, False),
    ({"strategy": "both", "transverse": [{"heading_deg": 88.0}]}, True),
    ({"strategy": "corner_left", "transverse": []}, True),
    ({"strategy": "none", "transverse": [], "reason": "junction_fork"}, True),
])
def test_decision_point_from_keep(last, expected):
    assert decision_point_from_keep(last) is expected


def test_wall_segments_from_scan_straight_wall():
    # a wall 0.15 m to the right, scan frame rotated 180 deg from the nose
    yaws = np.radians(np.arange(-80.0, -30.0, 1.0))
    ranges = 0.15 / np.abs(np.sin(yaws))
    angles = yaws + math.pi
    inc = math.radians(1.0)
    segs = wall_segments_from_scan(ranges, float(angles[0]), inc, yaw_offset_rad=math.pi, max_range_m=0.6)
    assert segs
    for s in segs:
        assert s.y0 == pytest.approx(-0.15, abs=1e-6) and s.y1 == pytest.approx(-0.15, abs=1e-6)


# ---------------------------------------------------------------- shadow node (static; rclpy is not on the host)

NODE = __import__("pathlib").Path(__file__).resolve().parents[1] / "control" / "road_state_node.py"


def test_node_publishes_only_the_road_state_and_never_a_command():
    import ast
    text = NODE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    publishers = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "create_publisher"]
    assert [ast.unparse(n.args[1]) for n in publishers] == ["TOPIC"]
    assert "cmd_vel" not in text and "Twist" not in text
    assert "DurabilityPolicy.TRANSIENT_LOCAL" in text and "ReliabilityPolicy.RELIABLE" in text
    subs = {ast.unparse(n.args[1]).strip("'") for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "create_subscription"}
    assert subs == {"odom", "line/keep_debug", "line/observation", "perception/learned/shadow", "scan"}


def test_node_documents_that_r1_needs_keep_mode():
    import ast
    doc = ast.get_docstring(ast.parse(NODE.read_text(encoding="utf-8")))
    assert "camera_lane_mode" in doc and "keep" in doc


def test_node_is_an_installed_entry_point():
    setup = (NODE.parents[1] / "setup.py").read_text(encoding="utf-8")
    assert "'road_state_node = control.road_state_node:main'" in setup


def test_heading_is_predicted_at_the_chord_midpoint_of_the_seen_line():
    """A straight fit through an arc runs parallel to the tangent at the arc's midpoint,
    not at SIDE_X_M: psi = -phi + kappa * x_psi."""
    est, clock = tracking()
    est.x[:] = [0.0, 0.0, 2.0, W]
    est.P[:] = np.diag([1e-6, 1e-6, 1e-6, 1e-8])
    y_r = -HALF + 2.0 * X * X / 2
    chord = BoundaryMeas(y=y_r, psi=2.0 * 0.40, x=X, x_psi=0.40)
    est.update([chord], clock.t)
    assert est.last_frame["candidates"][0]["nis"]["R"] < 0.5
    assert boundaries_from_keep({"boundaries": [
        {"side": "right", "y_at_side_x_m": -0.09, "heading_deg": 0.0, "ends_m": [[0.10, -0.09], [0.50, -0.09]]}
    ]})[0].x_psi == pytest.approx(0.30)


def test_a_line_without_seen_extent_predicts_heading_at_its_x():
    assert BoundaryMeas(y=0.0, psi=0.0).x_psi is None


def test_a_lost_track_restarts_from_the_prior():
    """Replay 2026-10-01: while STOP the odometry kept turning phi (|phi| up to 290 deg in the
    roundabout), so no later line could pass the gate. Without an acquisition under way the
    lane state starts again from the prior."""
    est, clock = tracking()
    for _ in range(int(5.0 / DT)):          # STOP at 2.5 s, then more than 2 s lost
        clock.frame([], v=0.0)
    assert est.level == STOP
    est.x[:3] = [0.05, 5.0, 3.0]
    clock.frame([])
    assert list(est.x[:3]) == [0.0, 0.0, 0.0]
    assert est.P[1, 1] >= RoadStateParams().sigma_phi0_rad ** 2
    assert est.P[0, 1] == 0.0


def test_heading_error_is_wrapped():
    est = RoadStateEstimator()
    est.predict(0.0, 7.0, dt=1.0)
    assert -math.pi < est.x[1] <= math.pi
    assert est.x[1] == pytest.approx(7.0 - 2 * math.pi)


def test_a_yawed_robot_on_a_straight_lane_reads_mostly_as_heading_not_curvature():
    """psi = -phi + kappa x cannot split phi from kappa in one frame; the curvature prior
    decides. A robot yawed 10 deg on a straight lane must come out as phi ~ 10 deg."""
    est = RoadStateEstimator()
    clock = Clock(est)
    for _ in range(3):
        clock.frame(pair(phi=math.radians(10)))
    assert math.degrees(est.x[1]) == pytest.approx(10.0, abs=1.5)


def _R(est, b):
    return est._boundary_eval(b, "R", 1.0, True).R


def test_heading_noise_grows_for_short_lines_and_lateral_noise_with_range():
    est = RoadStateEstimator()
    short, long_ = BoundaryMeas(y=-HALF, psi=0.0, length_m=0.05), BoundaryMeas(y=-HALF, psi=0.0, length_m=0.40)
    assert _R(est, short)[1, 1] > _R(est, long_)[1, 1]
    near, far = BoundaryMeas(y=-HALF, psi=0.0, x_psi=0.22), BoundaryMeas(y=-HALF, psi=0.0, x_psi=0.40)
    assert _R(est, far)[0, 0] > _R(est, near)[0, 0]
    p = RoadStateParams()
    # no length or range known: the fitted floors plus the jitter at the reference
    plain = _R(est, BoundaryMeas(y=-HALF, psi=0.0))
    assert plain[0, 0] == pytest.approx(p.sigma_y_m ** 2 + p.jitter_y_m ** 2)
    assert plain[1, 1] == pytest.approx(p.sigma_psi_rad ** 2 + (p.jitter_psi_rad_m / p.jitter_ref_length_m) ** 2)


def test_measurement_noise_constants_are_the_124745z_fit():
    p = RoadStateParams()
    assert p.sigma_y_m == pytest.approx(0.007)
    assert math.degrees(p.sigma_psi_rad) == pytest.approx(1.73)
    assert p.jitter_y_m == pytest.approx(0.0006) and p.jitter_y_per_m == pytest.approx(0.008)
    assert math.degrees(p.jitter_psi_rad_m) == pytest.approx(0.1)


def test_boundaries_carry_the_seen_length():
    out = boundaries_from_keep({"boundaries": [{"side": "right", "y_at_side_x_m": -0.09, "heading_deg": 0.0,
                                                "length_m": 0.12, "ends_m": [[0.1, -0.09], [0.22, -0.09]]}]})
    assert out[0].length_m == pytest.approx(0.12)


def test_a_held_robot_does_not_refit_the_same_view_as_new_evidence():
    """Replay 2026-10-01: at zero motion the keeper returns the same lines each frame; their
    errors are one error, not many. Fitting a slightly non-parallel pair 40 times drove kappa
    and then phi away (a +10 deg yaw read as -1.7 deg). Only a moved view is new evidence."""
    est, clock = tracking()
    view = [BoundaryMeas(y=-HALF, psi=math.radians(-1.5), x=X, x_psi=0.34, length_m=0.2),
            BoundaryMeas(y=HALF, psi=math.radians(1.5), x=X, x_psi=0.29, length_m=0.29)]
    clock.frame(view, v=0.0)
    after_first = est.x.copy()
    for _ in range(40):
        clock.frame(view, v=0.0)
    assert est.x == pytest.approx(after_first, abs=1e-9)
    assert est.last_frame["deduplicated"] is True
    assert est.level == TRACK                 # the view still holds the track
    clock.frame(view, v=0.08)                # moved 1 cm: new evidence again
    assert est.last_frame["deduplicated"] is False


def test_associated_candidates_carry_their_innovation():
    est, clock = tracking()
    clock.frame(pair(d=0.01))
    for c in est.last_frame["candidates"]:
        assert set(c["nu"]) == {"y", "psi_deg"}
        assert c["nu"]["y"] == pytest.approx(-0.01, abs=0.004)


def test_a_steep_crossing_candidate_is_a_decision_point_never_a_boundary():
    """Lane owner (fix/lane-keep-steep-crossing): a steep diagonal whose paint crosses the
    path ahead is kept out of `transverse` (that list drives the device's junction HOLD) but
    is a decision point for the road state, and never a side boundary."""
    crossing = {"heading_deg": 60.2, "length_m": 0.236, "ends_m": [[0.328, -0.109], [0.446, 0.096]],
                "ends_px": [], "side": "right", "y_at_side_x_m": -0.297, "rejected": True, "reason": "steep_crossing"}
    last = {"strategy": "right_only", "reason": None, "transverse": [], "candidates": [crossing]}
    assert decision_point_from_keep(last) is True
    assert decision_point_from_keep(dict(last, candidates=[dict(crossing, reason="steep_far")])) is False
    est, clock = tracking()
    clock.frame(boundaries_from_keep(last) + pair())
    assert est.rejects["keeper"] == 1
    assert est.last_frame["hypothesis"]["labels"] == "RL"


def test_a_fresh_stop_keeps_the_coasted_state_as_its_acquisition_prior():
    """Trace 2026-10-01 (124745Z): a 0.10 m line dropout at 0.03-0.05 m/s outlasts the 2.5 s
    COAST/SLOW clock, so the ladder stops; wiping d/phi/kappa right then threw away a coast
    that was still good (every 0.10 m dropout trial failed on the zeroed prior). A recent stop
    keeps the coasted mean with the covariance widened to the acquisition prior; only a stop
    older than reacq_timeout_s or longer than slow_s_m of travel restarts from zero."""
    est, clock = tracking()
    est.x[:2] = [0.02, math.radians(3)]
    for _ in range(int(2.7 / DT)):
        clock.frame([], v=0.04)
    assert est.level == STOP
    coasted = est.x[:3].copy()
    assert coasted[0] > 0.02 and coasted[1] == pytest.approx(math.radians(3), abs=1e-3)
    clock.frame([], v=0.04)
    assert est.x[0] == pytest.approx(coasted[0] + 0.04 * DT * math.sin(coasted[1]), abs=1e-6)
    assert est.P[0, 0] >= RoadStateParams().sigma_d0_m ** 2
    for _ in range(int(2.2 / DT)):
        clock.frame([], v=0.04)
    assert list(est.x[:3]) == [0.0, 0.0, 0.0]
