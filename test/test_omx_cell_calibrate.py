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


def test_over_target_pivots_right_above_the_box_only_when_the_jaws_clear_its_top(tmp_path, monkeypatch):
    import cell_pivot

    seen = []
    monkeypatch.setattr(cell_pivot, "pivot_calibrate", lambda cell, config, point, *a: seen.append(point) or {"result": "stopped"})
    monkeypatch.setattr(cc, "auto_pivot_point", lambda *a: None)  # no clear floor point in this scene
    config = {"params": {"pivot.over_target": 1}, "pivot": {"z_view": 0.08}, "coarse": {"z_view": 0.118},
              "sites": {"floor": {"yaw_deg": 0.0, "surface_z": 0.006}}}
    far = {"regions": [{"site": "floor", "point_m": [0.0, 0.25], "bias_mm": [16.9, 0.0]}]}  # 50 mm away: not near enough
    _, problem = cc.self_calibrate(object(), config, {}, tmp_path / "cal.json", "floor", (0.0, 0.2), [{"raw_m": [0.0, 0.2]}],
                                   tmp_path, far, None, None)
    assert seen == [(0.0, 0.2)] and problem == "pivot: stopped"  # right over the target, even with the box there
    config["pivot"]["z_view"] = 0.06  # jaws 24 mm over a 30 mm box top on a 6 mm floor: below the 30 mm clearance
    seen.clear()
    cc.self_calibrate(object(), config, {}, tmp_path / "cal.json", "floor", (0.0, 0.2), [{"raw_m": [0.0, 0.2]}],
                      tmp_path, far, None, None)
    assert (0.0, 0.2) not in seen


def test_the_pivot_view_height_follows_each_sites_surface():
    """2026-10-29: an absolute 0.08 m view (tuned on the floor) swung the jaws 3 mm over a box on the Pinky tray."""
    import cell_pivot

    config = {"params": None, "pivot": {"z_view": 0.08}, "coarse": {"z_view": 0.118},
              "sites": {"floor": {"surface_z": 0.006}, "pinky": {"surface_z": 0.0467}, "odd": {}}}
    assert cell_pivot.pivot_z_view(config, "floor") == 0.08
    assert cell_pivot.pivot_z_view(config, "pinky") == pytest.approx(0.1207)
    assert cell_pivot.pivot_z_view(config, "odd") == 0.08  # no surface known: as configured
