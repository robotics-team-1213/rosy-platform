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


def test_white_pads_and_yellow_structural_vs_baseplate_filtering():
    import cell_finger_container as cfc

    # 1. Slanted/narrow v2.1 white jaws should use inner edges rather than saturating at [0.36*w, 0.72*w]
    img_slanted = np.full((480, 640, 3), 130, np.uint8)
    cv2.fillPoly(img_slanted, [np.array([[220, 479], [355, 360], [362, 479]])], (235, 225, 215))
    cv2.fillPoly(img_slanted, [np.array([[470, 479], [404, 360], [398, 479]])], (235, 225, 215))
    pads = cf.finger_pads(img_slanted, color="white")
    assert pads is not None and 330.0 <= 0.5 * (pads[0][0] + pads[1][0]) <= 420.0 and pads[2] < 120.0

    # 2. structural_container_between_fingers accepts yellow container on neutral grey floor
    img_yel_ctr = np.full((480, 640, 3), (140, 140, 140), np.uint8)
    img_yel_ctr[30:350, 210:420] = (30, 195, 215)
    sc_ok = cfc.structural_container_between_fingers(img_yel_ctr)
    assert sc_ok is not None and sc_ok["is_container_shape"] is True

    # 3. structural_container_between_fingers rejects yellow housing surrounded by dark bracket/housing
    img_housing = np.full((480, 640, 3), (18, 18, 18), np.uint8)
    img_housing[30:350, 140:500] = (30, 195, 215)
    img_housing[30:350, 0:140] = (18, 18, 18)
    img_housing[30:350, 500:640] = (18, 18, 18)
    sc_bad = cfc.structural_container_between_fingers(img_housing)
    if sc_bad is not None:
        assert sc_bad["is_container_shape"] is False
    assert cfc.top_face_between_fingers(img_housing, np.array([250.0, 400.0]), np.array([390.0, 400.0])) is None

    # 4. on_surface_blob rejects oversized (>45000 px) yellow baseplate and supports multi-range wrapped HSV
    img_big = np.full((480, 640, 3), (160, 160, 160), np.uint8)
    img_big[100:460, 80:400] = (20, 200, 220)  # 360*320 = 115200 px > 45000 px
    assert cfc.on_surface_blob(img_big, ([10, 80, 80], [35, 255, 255])) is None
    img_pink = np.full((480, 640, 3), (160, 160, 160), np.uint8)
    img_pink[140:260, 260:380] = (140, 40, 230)  # wrapped pink/magenta hue near H=165..179
    multi_hsv = [([0, 90, 90], [25, 255, 255]), ([155, 70, 90], [180, 255, 255])]
    assert cfc.on_surface_blob(img_pink, multi_hsv) is not None


def test_finger_hook_uses_live_fk_yaw_and_respects_target_offset(tmp_path, monkeypatch):
    import cell_pivot

    seen_closing = []
    monkeypatch.setattr(cf, "finger_servo", lambda _c, _cam, _hsv, closing, *_a, **_kw: seen_closing.append(closing) or {"verdict": "refuse", "why": "stop", "dx_mm": 0.0, "dy_mm": 0.0, "total_mm": 0.0, "iterations": []})
    monkeypatch.setattr(cell_pivot, "joints_tcp", lambda state, **_kw: (0.12, 0.05, 0.10, 45.0))
    cell = type("C", (), {"act": lambda self, cmd: {"ok": True, "state": [0.0, 0.0, 0.0, 0.0, 0.0, 56.0]}})()
    target = {"pick": {"x": 0.12, "y": 0.05, "z": 0.02, "yaw_deg": -135.0}, "place": {"x": 0.15, "y": 0.0, "z": 0.02, "yaw_deg": 0.0}, "offset": 0.0}
    cfg = {"params": {"wrist.finger_servo": 1}, "wrist": {"hsv_min": HSV[0], "hsv_max": HSV[1]}, "work_dir": str(tmp_path), "arm_id": "arm_b"}
    fn = cf.finger_hook(cfg, cell, target, lambda _c, p, _pl, path: path, 44.0)
    fn()
    assert seen_closing == [45.0]  # live FK yaw 45 + target offset 0, not planned -135 + 90


