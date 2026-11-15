"""The shadow check's real-side parsing: the pipeline's health output and the joint unit (no MuJoCo, no arm)."""
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/sim"))
import omx_two_arm_shadow as shadow  # noqa: E402

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def bus(arm, role, base):
    return dict(arm=arm, role=role, motors={j: dict(id=11 + k, position=base + k) for k, j in enumerate(JOINTS)})


def test_health_joints_takes_the_followers_five_body_joints():
    out = "\n".join(["not json", json.dumps(dict(stage="receipt", path="x")),
                     json.dumps(dict(stage="health", buses=[bus("arm_a", "follower", 0.), bus("arm_a", "leader", 50.), bus("arm_b", "follower", 10.)]))])
    assert shadow.health_joints(out) == {"arm_a": [0., 1., 2., 3., 4.], "arm_b": [10., 11., 12., 13., 14.]}


def test_health_joints_refuses_output_without_the_stage():
    try:
        shadow.health_joints('{"stage": "receipt"}')
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_norm_to_rad_centre_and_ends():
    assert abs(shadow.norm_to_rad(0.)) < 1e-3  # tick ~2048 is 0 rad
    assert abs(shadow.norm_to_rad(-100.) + math.pi) < 1e-9
    assert abs(shadow.norm_to_rad(100.) - (4095 * 2 * math.pi / 4096 - math.pi)) < 1e-9
