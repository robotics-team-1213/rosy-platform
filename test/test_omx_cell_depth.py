"""cell_depth: heights from a tilted depth view, put onto the colour view by the objects themselves."""
import sys
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_depth as cd  # noqa: E402

SCALE, SHIFT = 0.62, (106.0, 100.0)  # colour -> depth, as measured on the cell 2026-11-01


def scene(tilt_deg=10.0):
    """A table 620 mm away tilted about x, two 76 mm boxes and a plate 20 mm high; depth and colour views."""
    h, w = 480, 640
    ys, xs = np.mgrid[0:h, 0:w]
    rays = np.dstack([(xs - w / 2) / cd.FOCAL_PX, (ys - h / 2) / cd.FOCAL_PX, np.ones((h, w))])
    t = np.radians(tilt_deg)
    normal = np.array([0.0, -np.sin(t), -np.cos(t)])  # toward the camera
    colour = np.zeros((h, w, 3), np.uint8)
    boxes = [(300, 160, 330, 260), (350, 160, 380, 260)]  # colour pixels (x0, y0, x1, y1)
    lift = np.zeros((h, w))
    to_colour = lambda x, y: ((x - SHIFT[0]) / SCALE, (y - SHIFT[1]) / SCALE)  # noqa: E731
    cxs, cys = to_colour(xs, ys)
    for x0, y0, x1, y1 in boxes:
        colour[y0:y1, x0:x1] = (0, 128, 255)  # orange (BGR)
        lift[(cxs >= x0) & (cxs < x1) & (cys >= y0) & (cys < y1)] = 76.0
    plate = (np.hypot(cxs - 150, cys - 380) < 60) & (np.hypot(cxs - 150, cys - 380) > 25)
    lift[plate] = 20.0
    cv2.circle(colour, (150, 380), 60, (150, 150, 150), -1)  # the plate is seen in colour too (grey: not in the mask)
    cv2.circle(colour, (150, 380), 25, (0, 0, 0), -1)
    # depth along each ray to the plane n.p + 620 = lift (heights measured along the normal)
    depth = (lift - 620.0) / (rays @ normal)
    return depth.astype(np.uint16), colour


def test_the_table_is_found_through_the_tilt_and_heights_are_measured_from_it():
    depth, _ = scene()
    heights = cd.height_map(depth, cd.table_plane(depth))
    assert np.nanmedian(heights[400:470, 400:600]) == pytest.approx(0.0, abs=1.5)
    normal, _ = cd.table_plane(depth)
    assert np.degrees(np.arccos(abs(normal[2]))) == pytest.approx(10.0, abs=0.5)


def test_the_colour_view_is_put_onto_the_depth_view_by_the_objects():
    depth, colour = scene()
    heights = cd.height_map(depth, cd.table_plane(depth))
    mask = cv2.inRange(cv2.cvtColor(colour, cv2.COLOR_BGR2HSV), (5, 120, 120), (22, 255, 255))
    m, overlap = cd.align(mask, heights)
    assert overlap > 0.9
    assert cd.height_at(heights, m, (315, 210)) == pytest.approx(76.0, abs=3.0)
    assert cd.height_at(heights, m, (450, 300)) == pytest.approx(0.0, abs=3.0)
    assert cd.plate_top(heights, m, (150, 380)) == pytest.approx(20.0, abs=3.0)


def test_a_ring_with_no_plate_reads_none():
    depth, _ = scene()
    heights = cd.height_map(depth, cd.table_plane(depth))
    assert cd.plate_top(heights, np.float32([[SCALE, 0, SHIFT[0]], [0, SCALE, SHIFT[1]]]), (500, 120)) is None


def test_the_edges_put_the_colour_view_onto_the_depth_view_even_with_objects_in_one_row():
    depth, colour = scene()
    heights = cd.height_map(depth, cd.table_plane(depth))
    m, edge_px = cd.align_edges(colour, heights)
    assert edge_px < 2.0
    assert m[0, 0] == pytest.approx(SCALE, abs=0.02)
    assert (m[0, 2], m[1, 2]) == pytest.approx(SHIFT, abs=4.0)
    assert cd.height_at(heights, m, (315, 210)) == pytest.approx(76.0, abs=3.0)
