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


def render(d=0.0, lines=True):
    """Grey carpet with the two tape lines of a straight lane, robot at offset d (left +)."""
    rng = np.random.default_rng(7)
    image = 100 + rng.normal(0, 8, FX.shape)
    floor = np.isfinite(FX)
    if lines:
        for y0 in (-HALF - d, HALF - d):
            image[floor & (np.abs(FY - y0) <= 0.015)] = 195.0
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
        "on_line_le_keep", "on_paint_le_keep", "jump", "straight_mean_abs_err", "nis_mean",
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
