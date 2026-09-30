"""D-384 R0 replay harness on a synthetic session (no MCAP, no device data)."""
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "perception"))

import road_replay as rr  # noqa: E402
from control.recording import SHADOW_TOPIC  # noqa: E402

PROFILE, GROUND = rr.lane_replay._nominal_ground()
X_OFFSET = float(PROFILE["x_offset_m"])
HALF = rr.HALF
FPS = 8.0
V = 0.05


def _floor_xy():
    rows, cols = np.mgrid[0:240, 0:320].astype(float)
    angle = GROUND.pitch_rad + np.arctan((rows - GROUND.principal_y) / GROUND.focal_px)
    with np.errstate(divide="ignore", invalid="ignore"):
        forward = np.where(angle > 0, GROUND.height_m / np.tan(angle), np.nan)
        denominator = (GROUND.focal_px * np.sin(GROUND.pitch_rad)
                       + (rows - GROUND.principal_y) * np.cos(GROUND.pitch_rad))
        right = GROUND.height_m * (cols - GROUND.principal_x) / denominator
    return forward + X_OFFSET, np.where(np.isfinite(forward), -right, np.nan)


FX, FY = _floor_xy()


def render(d=0.0, lines=True, yaw_deg=0.0):
    """Grey carpet with the two tape lines of a straight lane, robot at offset d (left +)
    and yawed yaw_deg CCW against the lane (the lines then run at -yaw_deg in base_link)."""
    rng = np.random.default_rng(7)
    image = 100 + rng.normal(0, 8, FX.shape)
    floor = np.isfinite(FX)
    slope = math.tan(math.radians(-yaw_deg))
    if lines:
        for y0 in (-HALF - d, HALF - d):
            image[floor & (np.abs(FY - (y0 + slope * FX)) <= 0.015 / math.cos(math.atan(slope)))] = 195.0
    image[~floor] = 60.0
    return np.dstack([np.clip(image, 0, 255).astype(np.uint8)] * 3)


LANE, BLANK = render(), render(lines=False)


def synthetic(n=96, blank=(), yaw_rate=0.0):
    """Straight drive at 0.05 m/s, 8 fps; frames in `blank` show no lines."""
    x = yaw = 0.0
    for i in range(n):
        t = 100.0 + i / FPS
        yield rr.Frame(t, BLANK if i in blank else LANE, (x, 0.0, yaw))
        x += V / FPS
        yaw += yaw_rate / FPS


def test_replay_reports_keep_and_road_metrics_and_gates():
    metrics, rows = rr.replay(synthetic())
    assert metrics["frames"] == 96 and len(rows) == 96
    for key in ("on_line_rate", "on_paint_rate", "none_rate", "jump_rate", "straight_mean_abs_err"):
        assert key in metrics["keep"] and key in metrics["road"]
    assert metrics["levels"]["TRACK"] > 0.9
    assert abs(rows[-1]["d"]) < 0.01
    assert set(metrics["gates"]) == {
        "on_line_le_keep", "on_paint_le_keep", "jump", "straight_mean_abs_err", "nis_mean_by_regime",
        "nis_above_9_21", "coast_survival", "wall_false_accept", "hypothesis_switches",
        "wrong_side_lock", "deterministic"}
    assert metrics["gates"]["jump"]["pass"] is True
    assert metrics["gates"]["straight_mean_abs_err"]["pass"] is True
    assert metrics["gates"]["wrong_side_lock"]["pass"] is True
    assert metrics["gates"]["wall_false_accept"]["pass"] is None      # no D-379 labels
    assert metrics["calibration_suspect_run"] is False
    json.dumps(metrics, allow_nan=False)


def test_replay_is_bit_deterministic():
    a, _ = rr.replay(synthetic(48), dropouts=())
    b, _ = rr.replay(synthetic(48), dropouts=())
    assert a["deterministic"] is True
    assert a["estimator_sha256"] == b["estimator_sha256"]
    assert a["keeper_sha256"] == b["keeper_sha256"]


def test_dropout_injection_coasts_and_reacquires():
    metrics, _ = rr.replay(synthetic(128))
    for key in ("0.05", "0.10"):
        s = metrics["coast_survival"][key]
        assert s["trials"] > 0, key
        assert s["rate"] >= 0.95, (key, s)
    assert metrics["gates"]["coast_survival"]["pass"] is True


def test_a_real_gap_in_the_lines_degrades_and_recovers():
    _, rows = rr.replay(synthetic(96, blank=range(40, 50)), dropouts=())
    levels = [r["level"] for r in rows]
    assert "COAST" in levels[40:50]
    assert levels[-1] == "TRACK"
    assert rows[45]["road"] is not None          # the road estimate keeps a target while coasting
    assert rows[45]["keep"] is None               # the keeper holds


def test_wall_false_accept_uses_d379_masks(tmp_path):
    frames = list(synthetic(24))
    (tmp_path / "masks").mkdir()
    with open(tmp_path / "labels.jsonl", "w", encoding="utf-8") as fh:
        for i, f in enumerate(frames):
            fh.write(json.dumps({"index": i, "t": f.t}) + "\n")
            cv2.imwrite(str(tmp_path / "masks" / f"{i:06d}.png"), np.full((240, 320), 2, np.uint8))
    metrics, _ = rr.replay(iter(frames), labels=rr.load_labels(tmp_path), dropouts=())
    wall = metrics["wall_false_accept"]
    assert wall["labelled_frames"] == 24 and wall["accepted"] > 0
    assert wall["rate"] == 1.0 and metrics["gates"]["wall_false_accept"]["pass"] is False


def test_learned_and_ir_side_data_reach_the_estimator():
    frames = []
    for f in synthetic(24):
        f.shadow = {"visible": True, "error": 0.0, "confidence": 0.9, "stamp": f.t, "class_fractions": {}}
        f.ir = {"source": "IR_LINE", "visible": False, "error": None, "stamp": f.t}
        frames.append(f)
    metrics, rows = rr.replay(iter(frames), dropouts=())
    assert metrics["levels"]["TRACK"] > 0.8
    assert rows[-1]["accepted"] >= 3      # a pair plus the learned offset


def test_video_with_sidecar_is_the_second_input_class(tmp_path):
    video = tmp_path / "s.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (320, 240))
    rows = []
    for i in range(6):
        writer.write(LANE)
        rows.append({"index": i, "t": 5.0 + i / FPS,
                     "side": {"odom": {"x": i * V / FPS, "y": 0.0, "yaw": 0.0},
                              SHADOW_TOPIC: {"visible": False},
                              "line/observation": {"source": "CAMERA_LINE", "visible": True}}})
    writer.release()
    (tmp_path / "s.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    frames = list(rr.session_frames(video))
    assert len(frames) == 6
    assert frames[3].odom == pytest.approx((3 * V / FPS, 0.0, 0.0))
    assert frames[3].ir is None                  # a CAMERA_LINE sample is not IR


def test_frame_only_video_is_refused(tmp_path):
    video = tmp_path / "bare.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (320, 240))
    writer.write(LANE)
    writer.release()
    with pytest.raises(SystemExit, match="odometry"):
        list(rr.session_frames(video))


def test_session_folder_without_mcap_is_refused(tmp_path):
    (tmp_path / "bag").mkdir()
    with pytest.raises(SystemExit, match="mcap"):
        list(rr.session_frames(tmp_path))


def test_odometry_is_interpolated_by_stamp():
    series = ([0.0, 1.0], [(0.0, 0.0, math.pi - 0.1), (1.0, 0.0, -math.pi + 0.1)])
    x, _, yaw = rr._interp(series, 0.5)
    assert x == pytest.approx(0.5)
    assert abs(math.atan2(math.sin(yaw), math.cos(yaw))) == pytest.approx(math.pi, abs=1e-9)


def test_out_inside_the_repo_is_refused():
    with pytest.raises(SystemExit, match="outside the public repo"):
        rr.main([str(ROOT / "nothing"), "--out", str(ROOT / "tmp-road-replay")])


def test_pitch_override_builds_the_ground_without_touching_the_profile():
    _, ground = rr.ground_for(11.8)
    assert ground.pitch_rad == pytest.approx(math.radians(11.8))
    profile, nominal = rr.ground_for(None)
    assert nominal.pitch_rad == pytest.approx(float(profile["pitch_rad"]))


def test_report_carries_heading_pairs_reacquisition_and_setup():
    metrics, _ = rr.replay(synthetic(48), dropouts=(), pitch_deg=8.0, lidar_forward_deg=181.0)
    assert metrics["keeper"]["pairs_rate"] > 0.9
    assert abs(metrics["keeper"]["median_heading_deg"]) < 2.0
    assert metrics["keeper"]["median_abs_heading_deg"] < 2.0
    assert metrics["reacq_counts"]["pair"] >= 1
    assert set(metrics["reacq_counts"]) == {"pair", "side+ir", "side+learned"}
    assert metrics["setup"] == {"pitch_deg": 8.0, "height_m": None, "roll_deg": 0.0,
                                "lidar_forward_deg": 181.0, "lidar_wall_veto": False,
                                "ir_geometry_measured": False, "mode": "shadow"}


def test_heading_sign_convention_matches_the_keeper():
    """Robot yawed +10 deg CCW against a straight lane: the keeper reads the lines at
    -10 deg (heading_deg = atan2(dir_y, dir_x), base_link) and the estimator's
    psi = -phi + kappa x is the same quantity, so phi converges to +10 deg."""
    img = render(yaw_deg=10.0)
    # held still: a static image with forward odometry would say the robot runs along the lane
    frames = [rr.Frame(100.0 + i / FPS, img, (0.0, 0.0, 0.0)) for i in range(6)]
    metrics, rows = rr.replay(iter(frames), dropouts=())
    assert metrics["keeper"]["median_heading_deg"] == pytest.approx(-10.0, abs=1.5)
    assert rows[-1]["hypothesis"] == "RL"
    # Same sign: phi comes out positive. One frame cannot split phi from kappa (psi =
    # -phi + kappa x_psi); the curvature prior takes part of the 10 deg, so only the sign
    # and the magnitude range are asserted here.
    assert 4.0 < math.degrees(rows[-1]["phi"]) <= 10.5


def test_nis_is_reported_by_motion_state():
    frames = list(synthetic(24)) + [rr.Frame(103.0 + i / FPS, LANE, (0.15, 0.0, 0.0)) for i in range(8)]
    metrics, rows = rr.replay(iter(frames), dropouts=())
    by = metrics["nis"]["by_state"]
    assert set(by) == {"straight", "curve", "turning", "stationary"}
    assert by["straight"]["n"] > 0          # held (stationary) views are not re-applied samples
    assert rows[-1]["motion"] == "stationary" and rows[10]["motion"] == "straight"
    sides = metrics["keeper"]["straight_heading_deg"]
    assert sides["left"]["n"] > 0 and abs(sides["left"]["median"]) < 2.0 and abs(sides["right"]["median"]) < 2.0


def test_report_records_every_estimator_parameter():
    params = rr.RoadStateParams(lane_width_m=2 * HALF, sigma_kappa0=0.5)
    metrics, _ = rr.replay(synthetic(8), dropouts=(), params=params)
    assert metrics["params"]["sigma_kappa0"] == 0.5
    assert set(metrics["params"]) == set(rr.dataclasses.asdict(params))
    json.dumps(metrics, allow_nan=False)


def test_curve_residuals_section_and_flag():
    # moving on a 0.2 rad/s arc while the camera sees a straight lane: curve frames exist
    metrics, rows = rr.replay(synthetic(48, yaw_rate=0.2), dropouts=())
    curve = metrics["curve_residuals"]
    assert curve["frames"] > 0 and any(r["motion"] == "curve" for r in rows)
    assert {"nis_mean", "nis_p95", "above_9_21", "straight_nis_mean", "blow_up", "validated_on_curves"} <= set(curve)
    assert curve["validated_on_curves"] is False
    straight, _ = rr.replay(synthetic(24), dropouts=())
    assert straight["curve_residuals"]["frames"] == 0 and straight["curve_residuals"]["blow_up"] is None


def _project_rolled(x, y, roll_deg, pitch=GROUND.pitch_rad, h=GROUND.height_m):
    """camera_extrinsic.CameraPose.project (feat/camera-extrinsic-autocalib), floor point z=0."""
    dx, dz = x - X_OFFSET, -h
    s, c = math.sin(pitch), math.cos(pitch)
    depth, up = dx * c - dz * s, dx * s + dz * c
    px, py = -GROUND.focal_px * y / depth, -GROUND.focal_px * up / depth
    sr, cr = math.sin(math.radians(roll_deg)), math.cos(math.radians(roll_deg))
    return GROUND.principal_x + cr * px - sr * py, GROUND.principal_y + sr * px + cr * py


def test_derotation_undoes_camera_roll_with_the_calibration_sign():
    # a floor point seen by a camera rolled -1.5 deg lands, after derotation, where a
    # roll-free camera sees it
    point = (0.30, 0.08)
    rolled = _project_rolled(*point, -1.5)
    ideal = _project_rolled(*point, 0.0)
    img = np.zeros((240, 320, 3), np.uint8)
    cv2.circle(img, (int(round(rolled[0])), int(round(rolled[1]))), 2, (255, 255, 255), -1)
    out = rr.derotate(img, -1.5, GROUND.principal_x, GROUND.principal_y)
    ys, xs = np.nonzero(out[..., 0] > 100)
    assert xs.mean() == pytest.approx(ideal[0], abs=1.0) and ys.mean() == pytest.approx(ideal[1], abs=1.0)
    assert rr.derotate(img, 0.0, 160.0, 120.0) is img


def test_height_override_builds_the_ground_through_the_profile():
    _, ground = rr.ground_for(11.2, height_m=0.0575)
    assert ground.height_m == pytest.approx(0.0575)
    assert ground.pitch_rad == pytest.approx(math.radians(11.2))
    metrics, _ = rr.replay(synthetic(8), dropouts=(), pitch_deg=11.2, height_m=0.0575, roll_deg=-1.5)
    assert metrics["setup"]["height_m"] == 0.0575 and metrics["setup"]["roll_deg"] == -1.5


def test_report_carries_the_parallel_pair_width():
    metrics, _ = rr.replay(synthetic(8), dropouts=())
    width = metrics["keeper"]["pair_width_m"]
    assert width["n"] == 8 and width["median"] == pytest.approx(2 * HALF, abs=0.01)
    assert width["ratio_to_map"] == pytest.approx(width["median"] / (2 * HALF), abs=1e-3)


def test_nis_consistency_uses_associated_measurements_only():
    """Clutter candidates (another lane's line, gated out) are not the filter's innovations;
    their NIS is reported separately."""
    metrics, rows = rr.replay(synthetic(24), dropouts=())
    tracked = sum(1 for r in rows if r["level"] != "STOP")
    assert metrics["nis"]["n"] == 2 * tracked            # a pair per frame
    assert metrics["nis"]["basis"] == "associated"
    assert metrics["nis_candidates"]["n"] >= metrics["nis"]["n"]


def test_wrong_side_reference_is_the_keepers_nearest_pair_not_the_extremes():
    """124745Z frame 754: a steep far line (64 deg, y -0.42 at SIDE_X_M) labelled right
    pulled (min + max) / 2 to -0.18 while the lane pair's midpoint was -0.03."""
    boundaries = [{"side": "left", "y_at_side_x_m": 0.061}, {"side": "right", "y_at_side_x_m": -0.117},
                  {"side": "right", "y_at_side_x_m": -0.422}]
    assert rr._keeper_pair_mid(boundaries) == pytest.approx(-0.028)
    assert rr._keeper_pair_mid([{"side": "left", "y_at_side_x_m": 0.06}]) is None


def test_nis_tail_is_the_pre_gate_best_association_with_a_gated_out_rate():
    metrics, rows = rr.replay(synthetic(24), dropouts=())
    tail = metrics["nis"]["tail"]
    assert tail["basis"] == "pre_gate_best_association_keeper_side"
    assert tail["n"] == 2 * sum(1 for r in rows if r["level"] != "STOP")   # best R and best L per frame
    assert tail["above_9_21"] == 0.0 and tail["gated_out_rate"] == 0.0
    assert metrics["gates"]["nis_above_9_21"]["value"] == tail["above_9_21"]


def test_nis_mean_gate_is_two_sided_per_regime():
    by = {"straight": {"n": 10, "mean": 1.2}, "curve": {"n": 5, "mean": 4.5}, "turning": {"n": 0, "mean": None},
          "stationary": {"n": 3, "mean": 0.1}}
    gate = rr._nis_mean_gate(by)
    assert gate["value"] == {"straight": 1.2, "curve": 4.5, "turning": None}
    assert gate["pass"] is False                                   # curve above 4.0
    by["curve"]["mean"] = 0.6
    assert rr._nis_mean_gate(by)["pass"] is True                 # stationary is not a regime
    by["straight"]["mean"] = 0.4
    assert rr._nis_mean_gate(by)["pass"] is False                # below 0.5
    assert rr._nis_mean_gate({k: {"n": 0, "mean": None} for k in by})["pass"] is None


def test_extrinsic_residual_logs_the_per_side_bias_on_straights():
    metrics, _ = rr.replay(synthetic(24), dropouts=())
    res = metrics["extrinsic_residual"]
    for side in ("left", "right"):
        assert res[side]["n"] > 0
        assert abs(res[side]["median_nu_y_m"]) < 0.01 and abs(res[side]["median_nu_psi_deg"]) < 2.0
    assert "not absorbed into R" in res["note"]


def test_held_view_frames_are_not_nis_samples():
    frames = list(synthetic(24)) + [rr.Frame(103.0 + i / FPS, LANE, (0.15, 0.0, 0.0)) for i in range(8)]
    metrics, _ = rr.replay(iter(frames), dropouts=())
    assert metrics["nis"]["by_state"]["stationary"]["n"] <= 2      # only the first held view is applied


def test_tail_counts_a_side_only_among_the_keepers_own_lines_for_that_side():
    cands = [{"side_hint": "right", "nis": {"R": 1.0, "L": 400.0}, "gate": {"R": None, "L": "nis"}},
             {"side_hint": "right", "nis": {"R": 30.0, "L": 900.0}, "gate": {"R": "nis", "L": "nis"}}]
    samples, missing = rr._tail_samples(cands)
    assert samples == [("R", 1.0, False)]      # the left side has no keeper line: no phantom sample
    assert missing == 1
    samples, missing = rr._tail_samples(cands + [{"side_hint": "left", "nis": {"R": 300.0, "L": 12.0},
                                                   "gate": {"R": "nis", "L": "nis"}}])
    assert samples == [("R", 1.0, False), ("L", 12.0, True)] and missing == 0


def test_report_carries_the_side_missing_rate():
    metrics, _ = rr.replay(synthetic(16), dropouts=())
    assert metrics["nis"]["tail"]["basis"] == "pre_gate_best_association_keeper_side"
    assert metrics["nis"]["tail"]["side_missing_rate"] == 0.0


def test_tail_only_on_applied_update_frames_and_coast_reported_apart():
    frames = list(synthetic(96, blank=range(40, 50)))
    metrics, rows = rr.replay(iter(frames), dropouts=())
    tail = metrics["nis"]["tail"]
    applied = sum(1 for r in rows if r["applied_update"] and r["level"] not in ("STOP", "COAST"))
    assert tail["frames"] == applied and applied < len(rows)
    coast = metrics["coast"]
    assert coast["episodes"] >= 1 and coast["rate"] == metrics["levels"]["COAST"]
    assert coast["max_s"] >= coast["mean_s"] > 0.0


def test_unassociated_keeper_lines_are_their_own_metric():
    rows = [{"level": "TRACK", "candidates": [
        {"side_hint": "right", "y": -0.30, "nis": {"R": 99.0, "L": 400.0}, "label": "N"},
        {"side_hint": "right", "y": -0.09, "nis": {"R": 1.0, "L": 400.0}, "label": "R"},
        {"side_hint": "left", "y": 0.10, "nis": {"R": 300.0, "L": 30.0}, "label": None},
        {"side_hint": "right", "y": -0.2, "rejected": "steep_crossing", "nis": None, "label": None}]},
        {"level": "STOP", "candidates": [{"side_hint": "left", "y": 0.5, "nis": {"R": 1, "L": 1}, "label": "N"}]}]
    out = rr._unassociated(rows)
    assert out["count"] == 2 and out["abs_y_m"]["median"] == pytest.approx(0.2)
