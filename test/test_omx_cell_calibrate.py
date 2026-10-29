"""cell_calibrate: a clear pivot point is found next to a target; a moved camera makes every later step stale."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_calibrate as cc  # noqa: E402

ROI = (0, 0, 400, 400)


def to_px(p):  # 1 px per mm, arm (0, 0.2) at pixel (200, 200)
    return (200 + p[0] * 1000, 200 + (p[1] - 0.2) * 1000)


def test_the_nearest_clear_point_avoids_the_box_and_stays_on_the_surface():
    mask = np.zeros((400, 400), np.uint8)
    mask[185:216, 185:216] = 255  # a 30 mm box at the target
    inside = np.ones((400, 400), np.uint8)
    inside[:, 260:] = 0  # the surface ends 60 mm to the +x side (a board beyond)
    p = cc.clear_point((0.0, 0.2), mask, ROI, inside, to_px, radius_px=30, reach_m=1.0)
    assert p is not None
    x, y = to_px(p)
    assert not mask[int(y) - 30:int(y) + 30, int(x) - 30:int(x) + 30].any() and x + 30 < 260
    assert cc.clear_point((0.0, 0.2), np.full((400, 400), 255, np.uint8), ROI, inside, to_px) is None  # nothing clear


def test_a_moved_camera_makes_the_map_regions_and_every_bias_stale():
    moved = cc.stale({"camera_moved": True, "targets": ["floor:-0.03,0.17"], "missing_bias": [], "missing_surface": []})
    assert moved == ["remap", "regions", "pivot-near floor:-0.03,0.17"]
    still = cc.stale({"camera_moved": False, "targets": [], "missing_bias": ["pinky:0.04,0.22"], "missing_surface": ["belt"]})
    assert still == ["pivot-near pinky:0.04,0.22", "surface belt"]
    assert cc.stale({"camera_moved": False, "missing_bias": [], "missing_surface": []}) == []
