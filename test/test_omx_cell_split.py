"""cell_split: boxes that only touch are separated by their neck; one box, or boxes sharing a full side, are not."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_split  # noqa: E402


def box(mask, centre, size, angle):
    cv2.fillPoly(mask, [np.round(cv2.boxPoints((centre, size, angle))).astype(np.int32)], 1)


def test_two_boxes_touching_at_a_corner_become_two_pieces():
    mask = np.zeros((240, 320), np.uint8)
    box(mask, (100, 100), (60, 60), 0)  # a 1-cell, 2 px/mm
    box(mask, (170, 165), (120, 60), 45)  # a 2-cell leaning on its corner
    assert cv2.connectedComponents(mask)[0] == 2  # one blob
    pieces = cell_split.split_touching(mask)
    assert len(pieces) == 2
    areas = sorted(int(p.sum()) for p in pieces)
    assert areas[0] == pytest.approx(3600, rel=0.15) and areas[1] == pytest.approx(7200, rel=0.15)


def test_one_box_or_a_full_shared_side_is_not_split():
    one = np.zeros((240, 320), np.uint8)
    box(one, (160, 120), (120, 60), 30)  # a single 2-cell: one long ridge, one marker
    assert cell_split.split_touching(one) == []
    pair = np.zeros((240, 320), np.uint8)
    box(pair, (160, 90), (120, 60), 0)
    box(pair, (160, 150), (120, 60), 0)  # side by side along the whole length: one wide box (cell_objects strips)
    assert cell_split.split_touching(pair) == []
