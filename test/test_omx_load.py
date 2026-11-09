"""omx_load: the torque a real-arm plan asks of each joint against the session's caps, with the measured margin."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools/sim"))
import omx_load as load  # noqa: E402


def test_derivatives_of_a_ramp_after_smoothing():
    q = np.outer(np.arange(60) / 30.0, np.ones(5))  # 1 rad/s at 30 fps
    qd, qdd = load.derivatives(q, 30, load.SMOOTH_S)
    assert qd[10:-10] == pytest.approx(np.ones((40, 5)), abs=1e-9)
    assert qdd[10:-10] == pytest.approx(np.zeros((40, 5)), abs=1e-6)


def test_caps_read_from_a_session_json_like_a_caps_file(tmp_path):
    session = tmp_path / "session.json"
    session.write_text(json.dumps({"caps": {"11": {"pwm_limit": 300}, "12": {"pwm_limit": 600, "p_gain": 1600}}}))
    assert load.load_caps(session) == {"11": {"pwm": 300}, "12": {"pwm": 600, "p": 1600}}


class Fixed:
    """An arm whose joints always need the same torque."""

    def __init__(self, tau):
        self.tau = np.array(tau, float)

    def torque(self, q, qd, qdd, payload_kg=0.0):
        return self.tau


def test_a_joint_is_flagged_on_its_margin_not_its_bare_share():
    cap = np.ones(5)
    frames = [[0] * 6] * 4
    out = load.review(Fixed([.15, .1, .1, .55, .1]), frames, 15, cap)
    assert out["worst"]["joint1"] == 0.15 and out["worst_with_margin"]["joint1"] == pytest.approx(0.63)  # 0.15 x 4.2
    assert {f["joint"] for f in out["flags"]} == {"joint1", "joint4"} and not out["ok"]  # joint4: 0.55 x 1.0
    assert load.review(Fixed([.1] * 5), frames, 15, cap)["ok"]


def test_the_arm_chain_carries_its_own_weight_and_a_payload():
    pytest.importorskip("mujoco")
    arm = load.Arm("arm_b")
    reach = load.norm_to_rad([0, -10, 10, 0, 0])
    bare = arm.torque(reach, np.zeros(5), np.zeros(5))
    held = arm.torque(reach, np.zeros(5), np.zeros(5), payload_kg=0.016)
    assert np.all(np.isfinite(bare)) and abs(bare[1]) > 0.01  # the shoulder holds the arm up
    assert abs(held[1]) > abs(bare[1])  # and a held container on top


def test_the_wrist_holder_closes_on_the_upper_arm_as_the_wrist_flexes_past_58():
    pytest.importorskip("mujoco")
    arm = load.Arm("arm_a")
    gap = [arm.clearance_mm(load.norm_to_rad([42.52, -9.4, -0.81, w, 73.09])) for w in (50, 58, 61.42, 64, 70, 76)]
    assert all(b <= a + 1e-6 for a, b in zip(gap, gap[1:])) and gap[0] > load.CLEAR_MM  # vertices: monotonic, no hull jumps
    assert gap[-1] < load.CLEAR_MM  # far enough over, the holder comes within the bound
    out = load.review(arm, [[42.52, -9.4, -0.81, 76, 73.09, 0]] * 3, 15, np.ones(5) * 9)
    assert not out["ok"] and out["flags"][-1]["joint"] == "holder-link4"


def test_surface_distance_is_to_the_triangle_not_its_corners():
    verts = np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]], float)  # one 100 mm triangle: vertices far from its middle
    faces = np.array([[0, 1, 2]])
    assert load.surface_mm(np.array([[0.02, 0.02, 0.005]]), verts, faces) == pytest.approx(5.0)  # straight above the face
    assert load.surface_mm(np.array([[-0.003, -0.004, 0.0]]), verts, faces) == pytest.approx(5.0)  # off the corner
    assert load.surface_mm(np.array([[0.06, 0.06, 0.0]]), verts, faces) == pytest.approx(0.02 / np.sqrt(2) * 1000, rel=1e-6)  # past the long edge
