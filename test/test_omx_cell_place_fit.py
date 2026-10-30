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


def test_an_occupied_tray_is_refused():
    tray = [[60, 60], [140, 60], [140, 140], [60, 140]]
    occupied = np.zeros((100, 100), np.uint8)
    occupied[:, :] = 1  # a box covers the whole tray (roi from pixel (50, 50))
    fits, why = pf.options(config(tray), "dest", (0.0, 0.0), 0.0, {"length_mm": 30, "width_mm": 30}, PX, occupied, (50, 50, 150, 150))
    assert fits == [] and "already there" in why


def test_no_surface_polygon_keeps_the_configured_point():
    fits, why = pf.options({"sites": {"dest": {"yaw_deg": -14.4}}, "params": None}, "dest", (0.12, 0.08), 0.0, C3, PX)
    assert (fits, why) == ([((0.12, 0.08), -14.4)], None)
