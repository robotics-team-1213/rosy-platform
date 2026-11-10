"""cell_place_fit: a held box goes where its whole footprint fits the destination and nothing is there yet."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_place_fit as pf  # noqa: E402

PX = lambda p: (100 + p[0] * 1000, 100 + p[1] * 1000)  # noqa: E731  1 px per mm, origin at pixel (100, 100)
C3 = {"length_mm": 90, "width_mm": 30}


def config(polygon, yaw=0.0):
    return {"sites": {"dest": {"yaw_deg": yaw, "surface_px": polygon}}, "params": None}


def test_a_long_box_at_a_surface_edge_moves_inward_along_it():
    # 2026-10-29: a 3-cell placed at the belt's near edge landed half off it. The belt runs along x.
    belt = [[40, 100], [260, 100], [260, 160], [40, 160]]
    fits, why = pf.options(config(belt), "dest", (0.0, 0.0), 0.0, C3, PX)
    assert why is None
    (x, y), yaw = fits[0]
    assert yaw == 0.0 and y >= 0.020 and abs(x) < 1e-9  # moved 20 mm inward (15 + 5 margin), not along


def test_a_box_longer_than_the_tray_is_refused_and_a_turned_one_is_tried():
    tray = [[70, 70], [130, 70], [130, 130], [70, 130]]  # 60 x 60 mm
    fits, why = pf.options(config(tray), "dest", (0.0, 0.0), 0.0, C3, PX)
    assert fits == [] and "does not fit" in why
    narrow = [[84, 40], [116, 40], [116, 160], [84, 160]]  # 32 x 120 mm, along y: only the yaw turned 90 fits a 2-cell
    fits, why = pf.options(config(narrow), "dest", (0.0, 0.0), 0.0, {"length_mm": 60, "width_mm": 20}, PX)
    assert why is None and fits[0][1] in (90.0, -90.0)


def test_a_box_lies_along_a_long_belt_even_where_a_diagonal_would_fit():
    # 2026-10-30 dry run: site yaw -14.4 with the jaws across the box put a 2-cell diagonally on the belt
    belt = [[-50, 35], [250, 35], [250, 165], [-50, 165]]  # 300 x 130 mm along x: the diagonal fits too
    fits, why = pf.options(config(belt, yaw=-14.4), "dest", (0.0, 0.0), 90.0, {"length_mm": 60, "width_mm": 30}, PX)
    assert why is None
    assert abs((fits[0][1] + 90.0 + 90) % 180 - 90) <= 2.5  # the box's long axis along x
    assert -92.5 <= fits[0][1] <= -87.5 and fits[0][0] == (0.0, 0.0)  # nearest the site's yaw, not +90


def test_a_tray_is_not_a_long_surface():
    assert pf.along_yaw([[70, 70], [130, 70], [130, 130], [70, 130]], (0.0, 0.0), 0.0, 0.0, PX) is None


def test_an_occupied_tray_is_refused():
    tray = [[60, 60], [140, 60], [140, 140], [60, 140]]
    occupied = np.zeros((100, 100), np.uint8)
    occupied[:, :] = 1  # a box covers the whole tray (roi from pixel (50, 50))
    fits, why = pf.options(config(tray), "dest", (0.0, 0.0), 0.0, {"length_mm": 30, "width_mm": 30}, PX, occupied, (50, 50, 150, 150))
    assert fits == [] and "already there" in why


def test_no_surface_polygon_keeps_the_configured_point():
    fits, why = pf.options({"sites": {"dest": {"yaw_deg": -14.4}}, "params": None}, "dest", (0.12, 0.08), 0.0, C3, PX)
    assert (fits, why) == ([((0.12, 0.08), -14.4)], None)


def test_with_tiers_expands_three_tiers_and_upper_tiers_require_support():
    tray = [[60, 60], [140, 60], [140, 140], [60, 140]]
    cfg, cal = pf.with_tiers({"sites": {"dest": {"yaw_deg": 0.0, "surface_z": -0.01, "surface_px": tray}}, "params": None},
                             {"sites": {"dest": {"homography": "H"}}}, [{"top_height_mm": 32.4}])
    assert [cfg["sites"][f"dest-l{k}"]["surface_z"] for k in (0, 1, 2)] == pytest.approx([-0.01, 0.0224, 0.0548])
    assert [cfg["sites"][f"dest-l{k}"]["tier"] for k in (0, 1, 2)] == [1, 2, 3]
    assert all(cal["sites"][f"dest-l{k}"] == {"homography": "H"} for k in (0, 1, 2))
    empty, occupied = np.zeros((100, 100), np.uint8), np.ones((100, 100), np.uint8)
    roi, box = (50, 50, 150, 150), {"length_mm": 30, "width_mm": 30}
    # 1단 (dest-l0): accepted when empty, refused when occupied
    assert pf.options(cfg, "dest-l0", (0.0, 0.0), 0.0, box, PX, empty, roi)[1] is None
    assert "already there" in pf.options(cfg, "dest-l0", (0.0, 0.0), 0.0, box, PX, occupied, roi)[1]
    # 2단 (dest-l1) and 3단 (dest-l2): refused when empty, accepted when the lower tier supports it
    for upper in ("dest-l1", "dest-l2"):
        assert "nothing under it" in pf.options(cfg, upper, (0.0, 0.0), 0.0, box, PX, empty, roi)[1]
        fits, why = pf.options(cfg, upper, (0.0, 0.0), 0.0, box, PX, occupied, roi)
        assert why is None and fits[0] == ((0.0, 0.0), 0.0)
    # Real cell (pallet yaw_deg=0.0, 1단 30x90 container standing along y at x in [-15, 15], y in [-45, 45]):
    # a 2단 3-cell must align with the 1단 container (yaw 90/-90), not sit crosswise (yaw 0) overhanging empty air
    wide_tray = [[40, 40], [160, 40], [160, 160], [40, 160]]
    cfg_wide, _ = pf.with_tiers({"sites": {"dest": {"yaw_deg": 0.0, "surface_z": -0.01, "surface_px": wide_tray}}, "params": None})
    bar_along_y = np.zeros((160, 160), np.uint8)
    bar_along_y[55:145, 85:115] = 1  # 30 mm wide in x (cols 85..115), 90 mm long in y (rows 55..145) around (100, 100)
    fits_bar, why_bar = pf.options(cfg_wide, "dest-l1", (0.0, 0.0), 0.0, C3, PX, bar_along_y, (0, 0, 160, 160))
    assert why_bar is None and fits_bar[0][1] in (90.0, -90.0)
