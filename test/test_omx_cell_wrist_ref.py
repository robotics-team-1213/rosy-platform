"""cell_wrist_ref: the reference-pixel servo probes J, converges, Broyden learns a rotated camera; the estimated
reference is the fingertip point plus the height shift."""
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
