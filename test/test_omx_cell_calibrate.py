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
    config["params"]["pivot.clear_above_m"] = 0.05  # (the default would raise the view to 0.08 by itself)
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


def test_a_region_carried_from_another_site_does_not_skip_the_pivot(tmp_path, monkeypatch):
    """2026-10-30: the Pinky tray's region was the floor's bias copied over; the pivot was skipped and the pick came
    down on the box top."""
    import cell_pivot

    seen = []
    monkeypatch.setattr(cell_pivot, "pivot_calibrate", lambda cell, config, point, *a: seen.append(point) or {"result": "stopped"})
    config = {"params": {"pivot.over_target": 1}, "pivot": {}, "coarse": {"z_view": 0.08},
              "sites": {"pinky": {"yaw_deg": -67.8, "surface_z": 0.0467}}}
    region = {"site": "pinky", "point_m": [0.05, 0.2], "bias_mm": [4.2, -2.5], "measured": "2026-10-29",
              "source": "carried from the floor pivot on the same remapped top camera map"}
    args = ({}, tmp_path / "cal.json", "pinky", (0.0694, 0.2137), [{"raw_m": [0.0694, 0.2137]}], tmp_path)
    _, problem = cc.self_calibrate(object(), config, *args, {"regions": [region]}, None, None)
    assert seen == [(0.0694, 0.2137)] and problem == "pivot: stopped"
    fitted = {k: v for k, v in region.items() if k != "source"}  # the same region measured there: no pivot
    seen.clear()
    assert cc.self_calibrate(object(), config, *args, {"regions": [fitted]}, None, None)[1] is None and seen == []


def test_the_auto_pivot_point_judges_clutter_against_the_sites_measured_surface(monkeypatch):
    pytest.importorskip("cv2")
    import cell_objects
    import cell_observe
    seen = {}

    def foreground(img, roi, **kw):
        seen.update(kw)
        return np.zeros((roi[3] - roi[1], roi[2] - roi[0]), np.uint8)

    monkeypatch.setattr(cell_objects, "foreground", foreground)
    monkeypatch.setattr(cell_observe, "predicted_pixel", lambda c, k, s, p: to_px(p))
    cell = type("Cell", (), {"frame": lambda self, name: np.zeros((480, 640, 3), np.uint8)})()
    site = {"surface_lab": [74, 135, 88], "surface_px": [[0, 0], [399, 0], [399, 399], [0, 399]], "auto_roi": [100, 100, 300, 300]}
    assert cc.auto_pivot_point(cell, {"sites": {"pallet": site}}, {}, "pallet", (0.0, 0.2)) is not None
    assert seen["surface_lab"] == [74, 135, 88] and seen["surface_px"] == site["surface_px"]


def test_a_pivot_near_a_packed_column_goes_over_it_only_when_the_jaws_clear_both_layers():
    """2026-11-01: no 72 px empty patch beside the packed pallet columns (65-71 mm tall), so pivot-near marks the jaws
    right over the target, which needs the view height raised above the default 80 mm."""
    config = {"params": {"pivot.over_target": 1, "pivot.over_top_mm": 71.0}, "pivot": {"z_view": 0.08},
              "coarse": {"z_view": 0.118}, "sites": {"pallet": {"surface_z": -0.01}}}
    assert not cc.over_target(config, "pallet")  # 90 mm above the pallet, 19 mm over the top: below 30
    config["pivot"]["z_view"] = 0.10
    assert cc.over_target(config, "pallet")
    config["params"]["pivot.over_target"] = 0
    assert not cc.over_target(config, "pallet")


def test_a_pivot_over_a_packed_column_keeps_its_yaws_inside_the_arc_that_marked():
    """2026-11-02: over the packed pallet only base -40..+40 marked, so 4 marks need the narrower 20 degree set."""
    config = {"params": {"pivot.over_target": 1, "pivot.over_top_mm": 71.0}, "pivot": {"z_view": 0.10},
              "coarse": {"z_view": 0.118}, "sites": {"pallet": {"surface_z": -0.01, "yaw_deg": 90}}}
    over = cc.pivot_near_yaws(config, "pallet")
    assert over == [30, 50, 70, 90, 110, 130, 150] and sum(50 <= y <= 130 for y in over) >= 4
    config["params"]["pivot.over_target"] = 0
    assert cc.pivot_near_yaws(config, "pallet") == [10, 50, 90, 130, 170, 210]


def test_a_jaw_mark_split_into_pieces_over_a_box_top_counts_once_merged_and_noise_does_not():
    """2026-11-02: over a packed column the gripper body hid the fingers; the open-closed change came as 72, 165 and
    260 px pieces a few px apart, each under min_blob 300, and the pivot marked nothing."""
    pytest.importorskip("cv2")
    import cell_pivot

    closed = np.zeros((200, 200, 3), np.uint8)
    opened = closed.copy()
    opened[100:104, 80:104] = 255  # three pieces of one finger's change, 2-3 px apart
    opened[106:114, 75:99] = 255
    opened[116:131, 80:96] = 255
    assert cell_pivot.jaw_blobs(closed, opened, {"pivot.merge_px": 0}) == []
    merged = cell_pivot.jaw_blobs(closed, opened, {"pivot.merge_px": 3})
    assert len(merged) == 1 and merged[0][2] >= 300
    noise = closed.copy()
    for x in range(10, 190, 20):  # scattered 4x4 specks, 16 px apart: not one mark at any merge
        noise[50:54, x:x + 4] = 255
    assert cell_pivot.jaw_blobs(closed, noise, {"pivot.merge_px": 3}) == []
