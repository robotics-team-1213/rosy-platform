"""D-563 3 ceiling poses: odometry fusion, clock offset, calibration reading (no rosy_vision)."""
import json
import math

import numpy as np
import pytest

import ceiling_pose as cp  # noqa: E402
from geometry import PoseSeries  # noqa: E402


def _odom():
    """Robot clock 100..115: still until 102, then 0.1 m/s along odom x."""
    t = np.arange(100.0, 115.01, 0.05)
    return PoseSeries(t, 0.1 * np.clip(t - 102.0, 0, None), np.zeros_like(t), np.zeros_like(t))


def _detections(offset=5.0):
    """Map: start (1, 2) facing +y; one detection a second in the site clock (robot - offset)."""
    rows = [{"t": rt - offset, "x": 1.0, "y": 2.0 + 0.1 * max(rt - 102.0, 0.0), "yaw": math.pi / 2,
             "reproj_err": 0.001} for rt in np.arange(100.0, 111.0)]
    rows.append({"t": 103.5 - offset, "x": 9.0, "y": 9.0, "yaw": 0.0, "reproj_err": 0.02})  # bad fit: ignored
    return rows


def test_fuse_carries_detections_by_odometry_and_flags_gaps_and_disagreement():
    dets = _detections()
    dets[7]["y"] += 0.2  # robot 107: off by 20 cm
    rows = cp.fuse(dets, _odom(), [103.5, 106.5, 113.0, 120.0], clock_offset_s=5.0)
    ok = rows[0]
    assert ok["usable"] and ok["x"] == pytest.approx(1.0, abs=1e-6)
    assert ok["y"] == pytest.approx(2.15, abs=1e-6) and ok["yaw"] == pytest.approx(math.pi / 2)
    assert ok["anchor_dt"] == pytest.approx(0.5) and ok["sigma_m"] == pytest.approx(0.02 + 0.05 * 0.05)
    assert [r["reason"] for r in rows[1:]] == ["disagree", "no_detection", "no_detection"]
    assert cp.fuse(dets, _odom(), [99.5], clock_offset_s=0.0)[0]["reason"] == "no_odom"


def test_clock_offset_from_yaw_rate_correlation():
    rng = np.random.default_rng(0)
    t = np.arange(100.0, 160.0, 0.05)
    yaw = np.cumsum(np.where((t % 10) < 3, 0.5, 0.0) * 0.05)  # turns of 3 s every 10 s
    odom = PoseSeries(t, np.zeros_like(t), np.zeros_like(t), yaw)
    site = np.arange(96.0, 155.0, 0.33)  # site clock = robot - 3.2
    dets = [{"t": s, "x": 0.0, "y": 0.0, "yaw": float(np.interp(s + 3.2, t, yaw) + 1.0 + rng.normal(0, 0.02)),
             "reproj_err": 0.001} for s in site]
    assert cp.estimate_clock_offset(dets, odom) == pytest.approx(3.2, abs=0.15)
    assert cp.estimate_clock_offset([], odom) is None
    still = PoseSeries(t, np.zeros_like(t), np.zeros_like(t), np.zeros_like(t))
    assert cp.estimate_clock_offset(dets, still) is None


def test_read_calibration_takes_a_saved_listing(tmp_path):
    record = {"source_id": "ceiling_north", "map_id": "map_v2_fleet"}
    (tmp_path / "calibrations.json").write_text(json.dumps({"calibrations": [dict(record, source_id="x"), record]}))
    assert cp.read_calibration(tmp_path)[1]["record"] == record
    (tmp_path / "calibration.json").write_text(json.dumps({"record": None, "frame_lens": {"kind": "wide"}}))
    assert cp.read_calibration(tmp_path)[1]["frame_lens"] == {"kind": "wide"}
