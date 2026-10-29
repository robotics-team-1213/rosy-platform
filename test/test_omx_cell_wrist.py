"""cell_wrist: the wrist view's shift from a reference, through a per-arm J, corrects the pick before the descent;
anything the view cannot vouch for is refused (no descent)."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_auto_pick as auto  # noqa: E402
import cell_wrist as cw  # noqa: E402

HSV = ([35, 80, 60], [90, 255, 255])
J = [[0.5, 0.0], [0.0, -0.5]]  # 2 px per mm, v grows toward -y
BAND = {"yaw_lo": -180, "yaw_hi": 180, "J": J, "ref": {"u": 320, "v": 240, "area": 120 * 60, "axis_deg": 0.0}}


def frame(cx=320, cy=240, w=120, h=60, extra=None):
    img = np.full((480, 640, 3), 90, np.uint8)
    cv2.rectangle(img, (int(cx - w / 2), int(cy - h / 2)), (int(cx + w / 2) - 1, int(cy + h / 2) - 1), (40, 190, 50), -1)
    if extra:
        cv2.rectangle(img, *extra, (40, 190, 50), -1)
    return img


def test_the_container_is_measured_and_a_cut_or_second_blob_is_flagged():
    seen = cw.observe(frame(400, 200), *HSV)
    assert seen["found"] and abs(seen["cx"] - 400) < 1 and abs(seen["cy"] - 200) < 1 and seen["blobs"] == 1
    assert abs(seen["area"] - 7200) < 200 and seen["fill"] > 0.95
    assert min(seen["axis_deg"], 180 - seen["axis_deg"]) < 2  # the long side is horizontal
    assert cw.observe(frame(40, 240), *HSV)["cut"]
    far = cw.observe(frame(extra=((500, 400), (580, 460))), *HSV, near=(320, 240))
    assert far["blobs"] == 1 and abs(far["cx"] - 320) < 1  # a container elsewhere in the frame is not in the way
    beside = cw.observe(frame(extra=((382, 210), (440, 270))), *HSV, near=(320, 240))
    assert beside["blobs"] == 2  # one right beside it: the jaws may meet it
    assert not cw.observe(np.full((480, 640, 3), 90, np.uint8), *HSV)["found"]


def test_fit_recovers_j_from_offset_hovers_and_refuses_a_degenerate_set():
    A = np.array([[2.0, 0.3], [-0.2, -1.8]])
    xy = [(dx, dy) for dx in (-8, 0, 8) for dy in (-8, 0, 8)]
    rng = np.random.default_rng(0)
    uv = [A @ p + (320, 240) + rng.normal(0, 0.5, 2) for p in xy]
    fitted = cw.fit(xy, uv)
    assert np.allclose(fitted["J"], np.linalg.inv(A), atol=0.02) and fitted["rms_px"] < 1.5
    with pytest.raises(ValueError):
        cw.fit([(0, k) for k in range(9)], [(320, 240 + 2 * k) for k in range(9)])  # one line: no x information


def test_verdicts_pass_correct_and_refuse():
    centred = cw.observe(frame(), *HSV)
    assert cw.judge(centred, BAND)["verdict"] == "pass"
    off = cw.judge(cw.observe(frame(340, 220), *HSV), BAND)  # 20 px right, 20 px up -> 10 mm x, +10 mm y
    assert off["verdict"] == "correct" and off["dx_mm"] == pytest.approx(10, abs=0.6) and off["dy_mm"] == pytest.approx(10, abs=0.6)
    assert "over" in cw.judge(cw.observe(frame(400, 240), *HSV), BAND)["why"]  # 40 mm in one step
    assert "disagree" in cw.judge(cw.observe(frame(360, 240), *HSV), BAND, total_mm=15)["why"]
    assert cw.judge(cw.observe(frame(w=60, h=40), *HSV), BAND)["why"].startswith("area")
    assert cw.judge({"found": False}, BAND)["why"] == "container not seen"


class Cell:
    def __init__(self, frames, answers=None):
        self.frames, self.answers, self.sent = list(frames), answers or {}, []

    def frame(self, camera):
        assert camera == "wrist"
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]

    def act(self, command):
        self.sent.append(command)
        return {"ok": True, **self.answers.get(command, {})}


def test_align_corrects_once_then_passes_and_replans_from_the_corrected_pick():
    cell = Cell([frame(340, 220)] * 3 + [frame()] * 3)
    asked = []
    out = cw.align(cell, "wrist", BAND, HSV, lambda dx, dy: asked.append((dx, dy)) or "replan.json")
    assert out["verdict"] == "pass" and len(out["iterations"]) == 2
    assert asked[0][0] == pytest.approx(10, abs=0.6) and cell.sent == ["load replan.json", "goto above_pick"]


def test_a_refused_wrist_view_parks_without_the_descent():
    cell = __import__("test_omx_cell_auto_pick").Scripted()
    refuse = {"verdict": "refuse", "dx_mm": 0, "dy_mm": 0, "total_mm": 0}
    moved = auto.transfer_folded(cell, "lib.json", closed=46.6, wrist=lambda: refuse)
    assert moved["result"] == "misaligned" and "run descend_pick" not in cell.commands and cell.commands[-1] == "park"


def test_no_hook_without_the_flag_or_a_calibration_for_this_arm(tmp_path):
    target = {"pick": {"x": 0, "y": 0.2, "z": 0.02, "yaw_deg": -67.8}, "place": {}}
    config = {"params": None, "wrist": {"cal_path": str(tmp_path / "cal.json")}, "work_dir": str(tmp_path)}
    assert cw.hook(config, None, target, None) is None  # wrist.enabled defaults to 0
    (tmp_path / "cal.json").write_text('{"schema": "rosy.omx-wrist-cal.v1", "arms": {"A": {"bands": [%s]}}}' % str(BAND).replace("'", '"'))
    enabled = dict(config, params={"wrist.enabled": 1}, arm_id="S")
    assert cw.hook(enabled, None, target, None) is None  # arm A is calibrated, arm S is not
    assert cw.hook(dict(enabled, arm_id="A", wrist=dict(config["wrist"], hsv_min=HSV[0], hsv_max=HSV[1])), None, target, None) is not None


def test_calibration_hovers_nine_offsets_fits_j_and_saves_a_band_per_arm(tmp_path):
    import cell_wrist_cal as cal

    A = np.array([[2.0, 0.0], [0.0, -2.0]])  # what the camera does: 2 px per mm of box offset
    state = {"pick": None}

    class Hovering(Cell):
        def frame(self, camera):
            dx = (state["pick"]["x"] - 0.05) * 1000
            dy = (state["pick"]["y"] - 0.2) * 1000
            u, v = A @ (-dx, -dy) + (320, 240)  # the gripper moved +d sees the box at -d
            return frame(u, v)

    def write(pick):
        state["pick"] = pick
        return "lib.json"

    cell = Hovering([None])
    body = cal.calibrate(cell, "wrist", HSV, {"x": 0.05, "y": 0.2, "z": 0.06, "yaw_deg": -67.8}, write)
    assert body["n"] == 9 and np.allclose(body["J"], np.linalg.inv(A), atol=0.03)
    assert abs(body["ref"]["u"] - 320) < 1 and abs(body["ref"]["v"] - 240) < 1 and cell.sent[-1] == "park"
    path = tmp_path / "wrist-cal.json"
    cal.save(path, "S", -67.8, 45, body, "wrist")
    cal.save(path, "A", 20.0, 45, body, "arm_a_wrist")
    saved = __import__("json").loads(path.read_text())
    assert set(saved["arms"]) == {"S", "A"} and cw.band_for(saved, "S", -60) and cw.band_for(saved, "A", -60) is None


def test_finger_pads_give_the_scale_and_the_container_offset_along_the_closing_axis():
    img = np.full((480, 640, 3), 170, np.uint8)
    cv2.rectangle(img, (60, 380), (180, 479), (20, 20, 20), -1)   # left pad
    cv2.rectangle(img, (460, 380), (580, 479), (20, 20, 20), -1)  # right pad: inner gap 280 px = 46 mm
    cv2.rectangle(img, (390, 250), (450, 310), (40, 190, 50), -1)  # the container right of the midpoint (320), on grey
    cv2.rectangle(img, (200, 330), (300, 470), (40, 140, 230), -1)  # an orange board ...
    cv2.rectangle(img, (220, 360), (280, 440), (40, 190, 50), -1)  # ... with a nearer container on it: not the target
    out = cw.finger_offset_mm(img, HSV, 46.0)
    assert out["found"] and out["along_mm"] == pytest.approx((420 - 320) * 46 / 279, abs=1.0) and out["across_mm"] < 0
    assert not cw.finger_offset_mm(np.full((480, 640, 3), 170, np.uint8), HSV, 46.0)["found"]


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

    out = cw.finger_servo(Cam(), "wrist", HSV, 0.0, 46.0, replan, {"wrist.servo_iter": 8, "wrist.servo_total_mm": 80.0})
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

    out = cw.finger_servo(Cam(), "wrist", HSV, 0.0, 46.0, replan, {"wrist.servo_iter": 10, "wrist.servo_total_mm": 120.0})
    assert out["verdict"] == "pass" and abs(moved["dx"] - 20.0) < 3, (out, moved)


def test_reference_servo_probes_j_then_converges_and_broyden_learns_a_rotated_camera():
    # a camera whose image axes are rotated and scaled against the arm (the oblique wrist view): px = M @ (box - jaws)
    M = np.array([[4.0, -2.0], [1.5, 5.0]])
    box, jaws = np.array([12.0, -9.0]), np.zeros(2)

    def frame():
        u, v = np.array([320.0, 200.0]) + M @ (box - jaws)
        img = np.full((480, 640, 3), 170, np.uint8)
        cv2.rectangle(img, (int(u) - 35, int(v) - 35), (int(u) + 35, int(v) + 35), (40, 190, 50), -1)
        return img

    class Cam:
        def frame(self, camera):
            return frame()

        def act(self, command):
            return {"ok": True}

    def replan(dx, dy):
        jaws[:] = (dx, dy)
        return "lib.json"

    out = cw.ref_servo(Cam(), "wrist", HSV, {"u": 320.0, "v": 200.0}, replan, {"wrist.servo_iter": 12, "wrist.servo_gain": 0.7})
    assert out["verdict"] == "pass" and np.allclose(jaws, box, atol=2.0), (out, jaws)
    assert np.allclose(out["J"], -M, atol=0.6)  # moving the jaws +d moves the box -M d in the image


def test_broyden_update_matches_the_step_it_saw():
    J = cw.broyden(np.eye(2), [2.0, 0.0], [6.0, 1.0])
    assert np.allclose(J @ np.array([2.0, 0.0]), [6.0, 1.0])


def test_an_estimated_reference_is_the_fingertip_point_plus_the_height_shift():
    state = {"up": 0.0}

    def frame():
        img = np.full((480, 640, 3), 170, np.uint8)
        cv2.rectangle(img, (100, 400), (220, 479), (20, 20, 20), -1)
        cv2.rectangle(img, (420, 400), (540, 479), (20, 20, 20), -1)  # tips meet at x 320, top row 400
        v = 300 - 2.0 * state["up"]  # raising the hover moves the box up 2 px per mm
        cv2.rectangle(img, (300, int(v) - 35), (370, int(v) + 35), (40, 190, 50), -1)
        return img

    class Cam:
        def frame(self, camera):
            return frame()

    def hover_up(mm):
        state["up"] = mm
        return True

    ref = cw.estimate_reference(Cam(), "wrist", HSV, hover_up, {"wrist.tip_to_top_mm": 25.0})
    assert ref["tip"] == pytest.approx([320.0, 400.0], abs=1) and ref["per_mm"][1] == pytest.approx(-2.0, abs=0.2)
    assert ref["u"] == pytest.approx(320.0, abs=2) and ref["v"] == pytest.approx(400 - 50, abs=6) and state["up"] == 0.0
