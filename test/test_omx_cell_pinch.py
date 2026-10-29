"""cell_pinch: lowered to grasp height, the gap between each finger pad and the box (scaled by the known jaw opening)
says whether the jaws close on the box; a box half under a finger is shifted into the middle, the image->arm sign is
learned, a turned camera and a box of the wrong size are refused."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_pinch  # noqa: E402

HSV = ([40, 80, 40], [90, 255, 255])
GAP_MM = 48.0  # pads' inner edges 240 px apart -> 0.2 mm/px


def frame(box_offset_px, box_w_px=100):
    img = np.full((480, 640, 3), 150, np.uint8)
    x0 = 320 - box_w_px // 2 + int(box_offset_px)
    cv2.rectangle(img, (x0, 300), (x0 + box_w_px - 1, 440), (0, 180, 0), -1)
    for x in (150, 440):  # the pads in front of the box
        cv2.rectangle(img, (x, 360), (x + 49, 440), (20, 20, 20), -1)
    return img


def test_centred_box_is_between_with_its_width():
    seen = cell_pinch.measure(frame(0), HSV, GAP_MM, 20.0)
    assert seen["between"] and seen["sized"]
    assert seen["width_mm"] == pytest.approx(20, abs=1) and seen["gap_left_mm"] == pytest.approx(14, abs=1)


class Arm:
    """The box's image offset follows the arm's move along the closing axis (mirrored when sign = -1)."""

    def __init__(self, offset_px, sign=1, width_px=100):
        self.o0, self.sign, self.dx, self.width_px = offset_px, sign, 0.0, width_px

    def frame(self, camera):
        return frame(self.o0 - self.sign * self.dx / 0.2, self.width_px)

    def redescend(self, dx, dy):
        self.dx = dx
        return True


def test_a_box_half_under_a_finger_is_shifted_into_the_middle():
    arm = Arm(-110)  # box spans 160..260: the left pad (150..199) covers part of it
    assert not cell_pinch.measure(arm.frame("wrist"), HSV, GAP_MM, 20.0)["between"]
    out = cell_pinch.check(arm, "wrist", HSV, 0.0, GAP_MM, 20.0, arm.redescend)
    assert out["verdict"] == "pass" and out["dx_mm"] < -10


def test_a_reversed_camera_direction_is_learned_and_still_passes():
    arm, sign = Arm(-110, sign=-1), {"along": 1.0}
    out = cell_pinch.check(arm, "wrist", HSV, 0.0, GAP_MM, 20.0, arm.redescend, sign=sign)
    assert out["verdict"] == "pass" and sign["along"] == -1.0


def test_a_turned_camera_and_a_wrong_sized_box_are_refused():
    arm = Arm(0)
    moved = cell_pinch.check(arm, "wrist", HSV, 0.0, GAP_MM, 20.0, arm.redescend, mount=[[60, 200], [580, 200]])
    assert moved["verdict"] == "refuse" and "camera moved" in moved["why"]
    long_box = Arm(0, width_px=200)  # 40 mm across where a 20 mm box was planned
    assert cell_pinch.check(long_box, "wrist", HSV, 0.0, GAP_MM, 20.0, long_box.redescend)["why"].startswith("box width")
