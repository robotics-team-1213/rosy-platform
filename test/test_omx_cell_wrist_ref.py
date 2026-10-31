"""cell_wrist_ref: the reference-pixel servo probes J, converges, Broyden learns a rotated camera; the estimated
reference is the fingertip point plus the height shift."""
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_wrist_ref as cr  # noqa: E402

HSV = ([35, 80, 60], [90, 255, 255])
J = [[0.5, 0.0], [0.0, -0.5]]  # 2 px per mm, v grows toward -y


def frame(cx=320, cy=240, w=120, h=60, extra=None):
    img = np.full((480, 640, 3), 90, np.uint8)
    cv2.rectangle(img, (int(cx - w / 2), int(cy - h / 2)), (int(cx + w / 2) - 1, int(cy + h / 2) - 1), (40, 190, 50), -1)
    if extra:
        cv2.rectangle(img, *extra, (40, 190, 50), -1)
    return img




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

    out = cr.ref_servo(Cam(), "wrist", HSV, {"u": 320.0, "v": 200.0}, replan, {"wrist.servo_iter": 12, "wrist.servo_gain": 0.7})
    assert out["verdict"] == "pass" and np.allclose(jaws, box, atol=2.0), (out, jaws)
    assert np.allclose(out["J"], -M, atol=0.6)  # moving the jaws +d moves the box -M d in the image


def test_broyden_update_matches_the_step_it_saw():
    J = cr.broyden(np.eye(2), [2.0, 0.0], [6.0, 1.0])
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

    ref = cr.estimate_reference(Cam(), "wrist", HSV, hover_up, {"wrist.tip_to_top_mm": 25.0})
    assert ref["tip"] == pytest.approx([320.0, 400.0], abs=1) and ref["per_mm"][1] == pytest.approx(-2.0, abs=0.2)
    assert ref["u"] == pytest.approx(320.0, abs=2) and ref["v"] == pytest.approx(400 - 50, abs=6) and state["up"] == 0.0


def test_the_hover_height_comes_from_the_shrink_on_a_known_rise_and_a_lower_top_shows_as_an_offset():
    area = lambda d: (140 * 150 / d) ** 2  # noqa: E731  a square's image side is inverse to its distance
    assert cr.scale_height(area(150), area(165), 15) == pytest.approx(150, abs=0.5)
    assert cr.scale_height(area(150), area(150.5), 15) is None  # too small a shrink to measure
    ref = {"area": area(150), "scale_mm": 150.0, "footprint_mm2": 900}
    assert cr.top_offset_mm(ref, area(155), 900) == pytest.approx(5, abs=0.2)
    assert cr.top_offset_mm(ref, 2 * area(150), 1800) == pytest.approx(0, abs=0.2)  # a two-cell container, same height
    assert cr.top_offset_mm(ref, area(150), None) is None and cr.top_offset_mm({"area": 1.0}, 1.0) is None


def test_a_saved_reference_gets_its_height_scale_from_one_rise_probe_and_the_pick_records_the_top_offset(tmp_path):
    state = {"dz": 0.0}

    def frame():
        side = 21000 / (155 + state["dz"])  # the top is 5 mm lower than at the reference (140 px at 150)
        img = np.full((480, 640, 3), 170, np.uint8)
        cv2.rectangle(img, (int(320 - side / 2), int(240 - side / 2)), (int(320 + side / 2) - 1, int(240 + side / 2) - 1), (40, 190, 50), -1)
        return img

    class Cam:
        def frame(self, camera):
            return frame()

        def act(self, command):
            return {"ok": True}

    def write_library(config, pick, place, path):
        state["dz"] = (pick["z"] - 0.05) * 1000
        return "lib.json"

    path = cr.ref_path(tmp_path, "arm_s")
    path.write_text('{"u": 320.0, "v": 240.0, "area": 19600, "footprint_mm2": 900, "J": [[2, 0], [0, 2]]}')
    config = {"params": {"wrist.ref_servo": 1}, "wrist": {"hsv_min": HSV[0], "hsv_max": HSV[1]}, "work_dir": str(tmp_path)}
    target = {"pick": {"x": 0.1, "y": 0.2, "z": 0.05, "yaw_deg": 0.0}, "place": {}, "entry": {"length_mm": 30, "width_mm": 30}}
    out = cr.ref_hook(config, Cam(), target, write_library, "any")()
    assert out["verdict"] == "pass" and out["top_offset_mm"] == pytest.approx(5, abs=2) and state["dz"] == 0.0
    assert json.loads(path.read_text())["scale_mm"] == pytest.approx(155, abs=10)
