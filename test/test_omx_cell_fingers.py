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


def test_per_arm_finger_color_distinguishes_arm_s_black_pads_and_arm_a_arm_b_white_pads():
    # 1. arm_s (black fingers) on a bright surface with white markings: color="dark" or params={"wrist.finger_color": 1}
    img_s = np.full((480, 640, 3), 170, np.uint8)
    cv2.rectangle(img_s, (10, 360), (90, 479), (245, 245, 245), -1)   # white floor reflection left
    cv2.rectangle(img_s, (550, 360), (630, 479), (245, 245, 245), -1) # white floor reflection right
    cv2.rectangle(img_s, (120, 380), (200, 479), (20, 20, 20), -1)    # arm_s left black finger
    cv2.rectangle(img_s, (440, 380), (520, 479), (20, 20, 20), -1)    # arm_s right black finger (inner gap 240 px)
    cv2.rectangle(img_s, (290, 250), (350, 310), (40, 190, 50), -1)   # centred green container
    assert cf.resolve_finger_color({"wrist.finger_color": 1}) == "dark"
    assert cf.resolve_finger_color(wrist_spec={"finger_color": "black"}) == "dark"
    out_s = cf.finger_offset_mm(img_s, HSV, 48.0, params={"wrist.finger_color": 1})
    assert out_s["found"] and out_s["finger_color"] == "dark" and abs(out_s["along_mm"]) < 1.0

    # 2. arm_a / arm_b (white v2.1 fingers) over a dark slot shadow: color="white" or params={"wrist.finger_color": 2}
    img_ab = np.full((480, 640, 3), 150, np.uint8)
    cv2.rectangle(img_ab, (80, 330), (190, 420), (15, 15, 15), -1)    # dark background shadow left (not touching bottom)
    cv2.rectangle(img_ab, (450, 330), (560, 420), (15, 15, 15), -1)   # dark background shadow right
    cv2.rectangle(img_ab, (140, 380), (210, 479), (235, 235, 235), -1)  # arm_b left white finger
    cv2.rectangle(img_ab, (430, 380), (500, 479), (235, 235, 235), -1)  # arm_b right white finger
    cv2.rectangle(img_ab, (290, 250), (350, 310), (40, 190, 50), -1)    # centred green container
    assert cf.resolve_finger_color({"wrist.finger_color": 2}) == "white"
    assert cf.resolve_finger_color(wrist_spec={"finger_color": "white"}) == "white"
    # Even in auto mode, mid-frame dark shadows that don't reach bottom are ignored in favour of bottom-anchored white fingers
    out_auto = cf.finger_offset_mm(img_ab, HSV, 48.0)
    assert out_auto["found"] and abs(out_auto["along_mm"]) < 2.0
    out_w = cf.finger_offset_mm(img_ab, HSV, 48.0, params={"wrist.finger_color": 2})
    assert out_w["found"] and out_w["finger_color"] == "white" and abs(out_w["along_mm"]) < 2.0


def test_per_arm_auto_calibration_profile_persistence_and_infer_holding(tmp_path):
    import cell_arm_cal as ac

    prof_s = ac.load(tmp_path, "arm_s")
    prof_b = ac.load(tmp_path, "arm_b")
    assert prof_s["finger_color"] == "dark" and prof_b["finger_color"] == "white"

    updated = ac.record_grasp_measurement(
        tmp_path,
        arm_id="arm_b",
        gripper_pos=54.26,
        gripper_current_ma=119.0,
        width_mm=30.0,
        skew_mm=-0.8,
        mm_per_px=0.08,
        finger_color="white",
    )
    assert updated["samples"] == 1
    assert updated["held_30mm"] == pytest.approx(54.26, abs=0.05)
    assert 70 <= updated["hold_current_ma"] <= 90
    assert updated["grip_open_30mm"] >= 58.0
    assert (tmp_path / "arm-cal-arm_b.json").exists()

    cfg = {
        "arm_id": "arm_b",
        "work_dir": str(tmp_path),
        "params": {},
        "plan": {"hold_current_ma": 140, "grip_open": 56.2, "grip_release": 56.1},
        "wrist": {},
    }
    ac.apply_to_config(cfg)
    assert cfg["params"]["wrist.finger_color"] == 2
    assert cfg["params"]["gripper.held_30mm"] == pytest.approx(54.26, abs=0.05)
    assert cfg["plan"]["hold_current_ma"] == updated["hold_current_ma"]
    assert cfg["plan"]["grip_open"] == updated["grip_open_30mm"]

    status = {"holding": False, "gripper_current_ma": 119, "state": [0.0, 0.0, 0.0, 0.0, 0.0, 54.26]}
    assert ac.infer_holding(status, closed=48.8) is True
    assert ac.infer_holding({"holding": False, "gripper_current_ma": 15, "state": [0, 0, 0, 0, 0, 49.1]}, closed=48.8) is False

