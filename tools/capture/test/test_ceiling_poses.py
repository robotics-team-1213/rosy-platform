"""D-563 3 ceiling poses tool: synthetic ArUco frames through a known calibration."""
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

pytest.importorskip("pydantic")  # rosy_vision.project -> core_common.protocol
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ceiling_poses as cp  # noqa: E402
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


def test_detect_reads_a_saved_calibration_listing(tmp_path):
    rec = _ceiling(tmp_path, [(700, 300, 0)])
    (rec / "calibration.json").unlink()
    (rec / "calibrations.json").write_text(json.dumps({"calibrations": [dict(RECORD, source_id="other"), RECORD]}))
    assert len(cp.detect(rec, 41)[0]) == 1
