"""cell_fingers: the open pads are the ruler for the container's offset; the servo learns the image->arm sign."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_fingers as cf  # noqa: E402

HSV = ([35, 80, 60], [90, 255, 255])


def frame(cx=320, cy=240, w=120, h=60, extra=None):
    img = np.full((480, 640, 3), 90, np.uint8)
    cv2.rectangle(img, (int(cx - w / 2), int(cy - h / 2)), (int(cx + w / 2) - 1, int(cy + h / 2) - 1), (40, 190, 50), -1)
    if extra:
        cv2.rectangle(img, *extra, (40, 190, 50), -1)
    return img




def test_finger_pads_give_the_scale_and_the_container_offset_along_the_closing_axis():
    img = np.full((480, 640, 3), 170, np.uint8)
    cv2.rectangle(img, (60, 380), (180, 479), (20, 20, 20), -1)   # left pad
    cv2.rectangle(img, (460, 380), (580, 479), (20, 20, 20), -1)  # right pad: inner gap 280 px = 46 mm
    cv2.rectangle(img, (390, 250), (450, 310), (40, 190, 50), -1)  # the container right of the midpoint (320), on grey
    cv2.rectangle(img, (200, 330), (300, 470), (40, 140, 230), -1)  # an orange board ...
    cv2.rectangle(img, (220, 360), (280, 440), (40, 190, 50), -1)  # ... with a nearer container on it: not the target
    out = cf.finger_offset_mm(img, HSV, 46.0)
    assert out["found"] and out["along_mm"] == pytest.approx((420 - 320) * 46 / 279, abs=1.0) and out["across_mm"] < 0
    assert not cf.finger_offset_mm(np.full((480, 640, 3), 170, np.uint8), HSV, 46.0)["found"]


def test_finger_servo_moves_part_way_learns_the_across_sign_and_converges():
    true = {"x": 20.0, "y": -12.0}  # the container's arm-frame offset from the jaws, mm
    moved = {"dx": 0.0, "dy": 0.0}

    def frame_now():
        img = np.full((480, 640, 3), 170, np.uint8)
        cv2.rectangle(img, (60, 380), (180, 479), (20, 20, 20), -1)
        cv2.rectangle(img, (460, 380), (580, 479), (20, 20, 20), -1)
        ex, ey = true["x"] - moved["dx"], true["y"] - moved["dy"]  # closing axis = arm x; across = -arm y here
        u, v = 320 + ex * 279 / 46, 280 + ey * 279 / 46
        cv2.rectangle(img, (int(u) - 35, int(v) - 35), (int(u) + 35, int(v) + 35), (40, 190, 50), -1)
        return img

    class Cam:
        def frame(self, camera):
            return frame_now()

        def act(self, command):
            return {"ok": True}

    def replan(dx, dy):
        moved.update(dx=dx, dy=dy)
        return "lib.json"

    out = cf.finger_servo(Cam(), "wrist", HSV, 0.0, 46.0, replan, {"wrist.servo_iter": 8, "wrist.servo_total_mm": 80.0})
    assert out["verdict"] == "pass", out
    assert abs(moved["dx"] - 20.0) < 3 and moved["dy"] == 0  # along the closing axis only (across uncalibrated)


def test_a_reversed_camera_axis_is_learned_after_one_step_that_made_it_worse():
    true = {"x": 20.0}
    moved = {"dx": 0.0}

    def frame_now():
        img = np.full((480, 640, 3), 170, np.uint8)
        cv2.rectangle(img, (60, 380), (180, 479), (20, 20, 20), -1)
        cv2.rectangle(img, (460, 380), (580, 479), (20, 20, 20), -1)
        u = 320 - (true["x"] - moved["dx"]) * 279 / 46  # this camera shows +x to the LEFT
        cv2.rectangle(img, (int(u) - 35, 245), (int(u) + 35, 315), (40, 190, 50), -1)
        return img

    class Cam:
        def frame(self, camera):
            return frame_now()

        def act(self, command):
            return {"ok": True}

    def replan(dx, dy):
        moved.update(dx=dx)
        return "lib.json"

    out = cf.finger_servo(Cam(), "wrist", HSV, 0.0, 46.0, replan, {"wrist.servo_iter": 10, "wrist.servo_total_mm": 120.0})
    assert out["verdict"] == "pass" and abs(moved["dx"] - 20.0) < 3, (out, moved)
