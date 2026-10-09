"""D-563 3 ceiling poses: synthetic ArUco frames through a known calibration, odometry fusion."""
import json
import math

import cv2
import numpy as np
import pytest

pytest.importorskip("pydantic")  # rosy_vision.project -> core_common.protocol
import ceiling_pose as cp  # noqa: E402
from geometry import PoseSeries  # noqa: E402

PX_PER_M = 2000.0  # map (x, y) -> image (640 + k x, 480 - k y)
RECORD = {"source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-test",
          "map_to_image": [PX_PER_M, 0, 640, 0, -PX_PER_M, 480, 0, 0, 1],
          "image": {"width": 1280, "height": 960},
          "track_bounds_m": {"min_x": -0.3, "min_y": -0.2, "max_x": 0.3, "max_y": 0.2}, "lens": None}


def _ceiling(tmp_path, frames):
    """frames: [(u, v, quarter_turns_cw)]: a 60 px (30 mm) marker 41 with its top-left at (u, v)."""
    from rosy_vision.detect import generate_marker_image
    (tmp_path / "frames").mkdir()
    rows = []
    for seq, (u, v, turns) in enumerate(frames):
        image = np.full((960, 1280), 128, np.uint8)
        image[v - 15:v + 75, u - 15:u + 75] = 255
        image[v:v + 60, u:u + 60] = np.rot90(generate_marker_image(41, 60), -turns)
        name = f"frames/{seq:08d}.jpg"
        cv2.imwrite(str(tmp_path / name), image)
        rows.append({"seq": seq, "captured_at": 100.0 + seq, "file": name, "width": 1280, "height": 960})
    (tmp_path / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / "calibration.json").write_text(json.dumps({"record": RECORD, "frame_lens": None}))
    return tmp_path


def test_detect_maps_marker_centre_and_heading(tmp_path):
    rec = _ceiling(tmp_path, [(700, 300, 0), (500, 600, 1), (1000, 700, 2)])
    poses, frames = cp.detect(rec, 41)
    assert frames == 3 and len(poses) == 3
    first, second = poses[0], poses[1]
    assert first["x"] == pytest.approx((730 - 640 - 0.5) / PX_PER_M, abs=1e-3)
    assert first["y"] == pytest.approx((480 - 330 + 0.5) / PX_PER_M, abs=1e-3)
    assert first["yaw"] == pytest.approx(math.pi / 2, abs=0.05)  # marker top edge = map +y
    assert second["yaw"] == pytest.approx(0.0, abs=0.05)         # turned a quarter clockwise
    assert poses[2]["yaw"] == pytest.approx(-math.pi / 2, abs=0.05)  # upside down
    assert first["reproj_err"] < 0.002 and first["src"] == "aruco" and first["t"] == 100.0
    assert cp.detect(rec, 42)[0] == []


def test_marker_pose_parallax_pulls_toward_the_nadir():
    quad = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    scale = np.diag([0.04, 0.04, 1.0])  # 1 px = 4 cm: a 4 cm quad at x, y 0.02
    flat = cp.marker_pose(quad, scale, None, size_m=0.04)
    pulled = cp.marker_pose(quad, scale, (0.0, 0.0, 2.0), height_m=1.0, size_m=0.02)
    assert flat[:2] == pytest.approx((0.02, 0.02)) and flat[3] == pytest.approx(0.0, abs=1e-9)
    assert pulled[:2] == pytest.approx((0.01, 0.01)) and pulled[3] == pytest.approx(0.0, abs=1e-9)


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


def test_clock_offset_from_motion_onset():
    assert cp.estimate_clock_offset(_detections(5.0), _odom()) == pytest.approx(5.0, abs=1.0)
    assert cp.estimate_clock_offset([], _odom()) is None
