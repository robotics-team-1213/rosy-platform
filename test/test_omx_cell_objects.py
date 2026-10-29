"""Catalogue-driven objects in the top view (cell_objects): synthetic scenes drawn in arm millimetres, seen
through a parallax-carrying camera, so the measured sizes, splits and vetoes are checked against known truth."""
import json
import math
from pathlib import Path
import sys

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import cell_calibration as cal
    import cell_objects as co
finally:
    sys.path.remove(str(OMX))

CATALOG = co.load_catalog(OMX / "object-catalog.example.json")
CAMERA = {"height_m": 0.5, "center_px": [320, 240]}
RECORD = {"homography": [[5e-4, 0, -0.16], [0, 5e-4, -0.12], [0, 0, 1]], "z_view": 0.0}  # 2 px/mm at z_view
ROI = (60, 60, 580, 420)
TOP = 0.030  # container top above the surface


def scene(rects, colour=(60, 160, 60), surface=(200, 200, 200), patches=()):
    """rects: (cx_mm, cy_mm, length_mm, width_mm, angle_deg) with their tops at TOP; patches: flat (rect, bgr)."""
    img = np.full((480, 640, 3), surface, np.uint8)

    def draw(r, bgr, z):
        cx, cy, length, width, ang = r
        pts = cv2.boxPoints(((cx, cy), (length, width), ang))
        px = [cal.parallax((320 + 2 * x, 240 + 2 * y), 0.0, z, CAMERA) for x, y in pts]
        cv2.fillPoly(img, [np.round(px).astype(np.int32)], bgr)

    for r, bgr in patches:
        draw(r, bgr, 0.0)
    for r in rects:
        draw(r, colour, TOP)
    return img


def seen(img):
    return co.detect(img, ROI, RECORD, CAMERA, CATALOG)


def angle_gap(a, b):
    return abs((a - b + 90) % 180 - 90)


@pytest.mark.parametrize("cells", [1, 2, 3])
@pytest.mark.parametrize("angle", [0, 30, -40])
def test_single_object_measured(cells, angle):
    (o,) = seen(scene([(20, -10, 30 * cells, 30, angle)]))
    assert o["matched"] and o["object"] == f"container-{cells}"
    assert o["centre_mm"] == pytest.approx([20, -10], abs=1.5)
    assert o["length_mm"] == pytest.approx(30 * cells, abs=2) and o["width_mm"] == pytest.approx(30, abs=2)
    if cells > 1:
        assert angle_gap(o["long_axis_deg"], angle) < 3


def test_touching_pair_is_split():
    # a 2-cell and a 3-cell container side by side, as seen on the real camera on 2026-10-28
    found = seen(scene([(-30, 0, 60, 30, 0), (-15, 31, 90, 30, 0)]))
    assert sorted(o["object"] for o in found) == ["container-2", "container-3"]
    assert all(o["split_from"] == 2 and o["matched"] for o in found)


def test_three_side_by_side_rotated():
    u = math.radians(25)
    rects = [(40 + k * 30 * -math.sin(u), 20 + k * 30 * math.cos(u), 90, 30, 25) for k in (-1, 0, 1)]
    found = seen(scene(rects))
    assert [o["object"] for o in found] == ["container-3"] * 3
    assert all(o["split_from"] == 3 for o in found)


def test_non_catalogue_blob_is_never_a_target():
    found = seen(scene([(0, 0, 45, 45, 10), (80, 60, 52, 52, 0)]))  # no side faces drawn here, so the edge piece is shrunk
    assert found and not any(o["matched"] or o["grasp"] for o in found)


def test_a_container_read_short_still_matches_its_cell_count_but_never_a_neighbour():
    # the real top camera read the isolated 60 x 30 container as 47 x 34 mm after the top-face cut (2026-10-28)
    assert co.match({"length_mm": 47.0, "width_mm": 34.0}, CATALOG)["id"] == "container-2"
    assert co.match({"length_mm": 98.0, "width_mm": 32.0}, CATALOG)["id"] == "container-3"
    assert co.match({"length_mm": 45.0, "width_mm": 30.0}, CATALOG) is None  # half way between 1 and 2 cells
    assert co.match({"length_mm": 47.0, "width_mm": 34.0}, CATALOG, strict=True) is None  # a split piece stays strict
    assert co.match({"length_mm": 60.0, "width_mm": 40.0}, CATALOG) is None  # the width stays strict


def test_small_fragment_is_unmatched():
    (o,) = seen(scene([(0, 0, 22, 13, 0)]))
    assert not o["matched"]


def test_black_object_on_light_surface():
    (o,) = seen(scene([(10, 10, 60, 30, 15)], colour=(15, 15, 15)))
    assert o["matched"] and o["object"] == "container-2"


def test_shadow_is_not_an_object():
    assert seen(scene([], patches=[((0, 0, 70, 40, 20), (150, 150, 150))])) == []


def test_a_1_cell_and_a_2_cell_touching_at_a_corner_are_found_as_two_targets():
    """2026-10-29 floor: corner to corner they made one unmatched blob that no push could part."""
    img = scene([(-60, 0, 30, 30, 0), (-25.5, 32.5, 60, 30, 45)])
    alone = co.detect(img, ROI, RECORD, CAMERA, CATALOG, params={"objects.split_touching": 0})
    assert len(alone) == 1 and not alone[0]["matched"]
    found = sorted(seen(img), key=lambda o: o["object"] or "")
    assert [o["object"] for o in found] == ["container-1", "container-2"]
    assert all(o["matched"] and o.get("split_from") == "touching" and o["hull_px"] for o in found)
    assert found[0]["centre_mm"] == pytest.approx([-60, 0], abs=3) and found[1]["centre_mm"] == pytest.approx([-25.5, 32.5], abs=3)


def test_a_split_piece_that_matches_is_a_target_while_its_unmatched_neighbour_stays_an_obstacle():
    img = scene([(-60, 0, 30, 30, 0), (-22, 37, 75, 44, 45)])  # the neighbour reads too wide for any catalogue entry
    found = sorted(seen(img), key=lambda o: o["matched"], reverse=True)
    assert len(found) == 2 and found[0]["object"] == "container-1" and found[0]["matched"]
    assert not found[1]["matched"] and found[1]["hull_px"]  # side_clear sees it


def test_a_box_shadow_on_the_yellow_board_is_dropped_but_a_black_plate_stays():
    """2026-10-29: the dark-yellow shadow beside a box on the board read as a fragment and closed the finger gap."""
    yellow, shade, black = (60, 190, 230), (30, 100, 125), (25, 25, 25)
    img = scene([(0, 0, 60, 30, 20)], surface=yellow,
                patches=[((10, 22, 60, 16, 20), shade), ((-90, -70, 90, 70, 0), black)])
    found = seen(img)
    assert [o["object"] for o in found if o["matched"]] == ["container-2"], [(o["object"], o["centre_mm"], o["length_mm"], o["width_mm"]) for o in found]
    assert not any(not o["matched"] and abs(o["centre_mm"][1] - 22) < 8 for o in found)  # no shadow fragment
    mask = co.foreground(img, ROI)
    bx, by = 320 + 2 * -90 - ROI[0], 240 + 2 * -70 - ROI[1]
    assert mask[by, bx] > 0  # the black plate is still foreground: an obstacle for the fingers
