"""D-854 OMX action space: declaration, golden values against the lerobot 0.4.4 formula, round trip, clip counts."""
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts/learning/src"))
from rosy.contracts.learning.action_space import (
    MOTORS, NORM, RAD, ROS, ROS_JOINTS, calibration_sha256, convert, validate_calibration, validate_declaration,
    ros_declaration, validate_joint_map)

CAL = {m: {"id": i + 11, "homing_offset": 0, "range_min": 1024, "range_max": 3072, "drive_mode": 0}
       for i, m in enumerate(MOTORS)}
CAL["gripper"] = {"id": 16, "homing_offset": 0, "range_min": 2000, "range_max": 3000, "drive_mode": 0}


def rad(raw):
    return raw * 2 * math.pi / 4096 - math.pi


def test_golden_values_match_lerobot_normalize():
    # raw 2048 -> 0, raw 3072 -> +100, raw 1024 -> -100; gripper raw 2250 in 2000..3000 -> 25.
    values = [rad(2048), rad(3072), rad(1024), rad(1536), rad(3072), rad(2250)]
    out, clipped, version = convert(values, RAD, NORM, CAL)
    assert (clipped, version) == (0, 1)
    assert out == pytest.approx([0.0, 100.0, -100.0, -50.0, 100.0, 25.0])


def test_drive_mode_is_ignored_like_lerobot_dynamixel_bus():
    # lerobot 0.4.4 DynamixelMotorsBus.apply_drive_mode is False: omx_follower values never flip.
    flipped = {m: {**v, "drive_mode": 1} for m, v in CAL.items()}
    values = [rad(2048), rad(3072), rad(1024), rad(1536), rad(3072), rad(2250)]
    assert convert(values, RAD, NORM, flipped)[0] == convert(values, RAD, NORM, CAL)[0]
    norm = [-87.5, -10.0, 0.0, 33.3, 99.0, 12.5]
    assert convert(norm, NORM, RAD, flipped)[0] == convert(norm, NORM, RAD, CAL)[0]
    assert calibration_sha256(flipped) == calibration_sha256(CAL)


def test_round_trip_inside_range():
    norm = [-87.5, -10.0, 0.0, 33.3, 99.0, 12.5]
    back, clipped, _ = convert(convert(norm, NORM, RAD, CAL)[0], RAD, NORM, CAL)
    assert clipped == 0 and back == pytest.approx(norm, abs=1e-9)


def test_out_of_range_is_clipped_and_counted():
    out, clipped, _ = convert([rad(4000), 0.0, 0.0, 0.0, 0.0, rad(1000)], RAD, NORM, CAL)
    assert clipped == 2 and out[0] == pytest.approx(100.0) and out[5] == pytest.approx(0.0)
    _, clipped, _ = convert([150.0, 0, 0, 0, 0, -5.0], NORM, RAD, CAL)
    assert clipped == 2


def test_refuses_bad_input():
    with pytest.raises(ValueError):
        convert([0.0] * 5, RAD, NORM, CAL)
    with pytest.raises(ValueError):
        convert([0.0, 0, 0, 0, 0, float("nan")], RAD, NORM, CAL)
    with pytest.raises(ValueError):
        convert([0.0] * 6, RAD, "degrees", CAL)
    with pytest.raises(ValueError):
        validate_calibration({m: CAL[m] for m in MOTORS[:-1]})
    with pytest.raises(ValueError):
        validate_calibration({**CAL, "gripper": {**CAL["gripper"], "range_min": 3000}})
    with pytest.raises(ValueError):
        validate_calibration({**CAL, "gripper": None})


def test_calibration_digest_ignores_unread_fields():
    other = {m: {**v, "id": 99, "homing_offset": 7} for m, v in CAL.items()}
    assert calibration_sha256(other) == calibration_sha256(CAL)
    changed = {**CAL, "elbow_flex": {**CAL["elbow_flex"], "range_max": 3000}}
    assert calibration_sha256(changed) != calibration_sha256(CAL)


def test_declaration_is_exact():
    good = {"unit": NORM, "motor_order": list(MOTORS), "calibration_sha256": calibration_sha256(CAL)}
    assert validate_declaration(good) == good
    for bad in ({**good, "unit": "normalized_-100_100"}, {**good, "motor_order": list(reversed(MOTORS))},
                {**good, "calibration_sha256": "x"}, {k: v for k, v in good.items() if k != "unit"},
                {**good, "fps": 30}):
        with pytest.raises(ValueError):
            validate_declaration(bad)


RIG = "omx-cell-s-follower"


def verdict(**change):
    """Shape of joint_map_check.py output (schema 2), as recorded in omx-joint-map-check-2026-10-24."""
    joints = [dict(motor_id=11 + i, joint=name, homing_offset_raw=0, drive_mode=0, operating_mode=4,
                   reasons=[], holds=True) for i, name in enumerate(ROS_JOINTS)]
    doc = dict(schema="rosy.omx-joint-map-check/3", hypothesis="ros_joint_rad == dynamixel_rad_v1",
               arm=RIG, calibration_sha256=calibration_sha256(CAL), probes=2,
               probe_files=[dict(file="probe-1.json", sha256="a" * 64)], holds=True, joints=joints)
    doc.update(change)
    return doc


def test_ros_joint_rad_needs_a_bound_verdict():
    norm = [-87.5, -10.0, 0.0, 33.3, 99.0, 12.5]
    with pytest.raises(ValueError):
        convert(norm, NORM, ROS, CAL)
    ros, clipped, version = convert(norm, NORM, ROS, CAL, joint_map=verdict(), rig_revision=RIG)
    assert (clipped, version) == (0, 1) and ros == convert(norm, NORM, RAD, CAL)[0]
    assert convert(ros, ROS, NORM, CAL, joint_map=verdict(), rig_revision=RIG)[0] == pytest.approx(norm)
    assert convert(ros, ROS, RAD, CAL, joint_map=verdict(), rig_revision=RIG)[0] == ros
    assert len(validate_joint_map(verdict(), CAL, RIG)) == 64


@pytest.mark.parametrize("bad", [
    verdict(holds=False), verdict(probes=1), verdict(schema="rosy.omx-joint-map-check/1"),
    verdict(joints=verdict()["joints"][:5]),
    verdict(joints=[dict(j, holds=False) if j["motor_id"] == 16 else j for j in verdict()["joints"]]),
    verdict(joints=list(reversed(verdict()["joints"]))),
    verdict(calibration_sha256=None),  # a verdict made before it named its calibration
    verdict(schema="rosy.omx-joint-map-check/2"),
    verdict(joints=[dict(j, drive_mode=None) for j in verdict()["joints"]]),
    verdict(joints=["not a joint"] * 6),
])
def test_failing_or_malformed_verdicts_are_refused(bad):
    with pytest.raises(ValueError):
        convert([0.0] * 6, NORM, ROS, CAL, joint_map=bad, rig_revision=RIG)


def test_a_verdict_for_another_rig_cannot_open_conversion():
    # Full-range calibrations are identical across arms, so the rig revision is what tells them apart.
    for rig in ("arm_a", None, " "):
        with pytest.raises(ValueError):
            convert([0.0] * 6, NORM, ROS, CAL, joint_map=verdict(), rig_revision=rig)


def test_another_arm_with_clean_registers_cannot_use_the_verdict():
    # arm_a/arm_b calibrations on the same PC also have homing 0 and drive 0; only their ranges differ.
    other_arm = {**CAL, "elbow_flex": {**CAL["elbow_flex"], "range_min": 1000}}
    with pytest.raises(ValueError):
        convert([0.0] * 6, NORM, ROS, other_arm, joint_map=verdict(), rig_revision=RIG)


def test_calibration_from_another_register_state_cannot_use_the_verdict():
    # The older pinky_follower calibration on the same PC carries wrist_roll homing 957.
    other = {**CAL, "wrist_roll": {**CAL["wrist_roll"], "homing_offset": 957}}
    with pytest.raises(ValueError):
        convert([0.0] * 6, NORM, ROS, other, joint_map=verdict(), rig_revision=RIG)
    flipped = {**CAL, "gripper": {**CAL["gripper"], "drive_mode": 1}}
    with pytest.raises(ValueError):
        validate_joint_map(verdict(), flipped, RIG)


def test_ros_declarations_separate_sim_data_from_converted_data():
    sim = {"unit": ROS, "motor_order": list(ROS_JOINTS), "calibration_sha256": None, "joint_map_revision": None}
    assert validate_declaration(sim) == sim
    converted = ros_declaration(CAL, verdict(), RIG)
    assert validate_declaration(converted) == converted and converted["calibration_sha256"] == calibration_sha256(CAL)
    for bad in ({**sim, "motor_order": list(MOTORS)}, {**converted, "joint_map_revision": None},
                {**sim, "calibration_sha256": calibration_sha256(CAL)},
                {k: v for k, v in sim.items() if k != "joint_map_revision"},
                {"unit": NORM, "motor_order": list(MOTORS), "calibration_sha256": None}):
        with pytest.raises(ValueError):
            validate_declaration(bad)
