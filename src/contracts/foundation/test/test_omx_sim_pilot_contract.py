"""OMX Pilot simulation wire values stay bounded and explicitly simulation-only."""

import pytest
from pydantic import ValidationError

from core_common.protocol.omx_sim import OmxSimGoal, OmxSimJog, OmxSimTarget


def test_target_cannot_advertise_physical_arm_or_missing_joints():
    target = OmxSimTarget(instance_id="omx_01", joints=("joint1",), gripper="gripper_joint_1")
    assert target.kind == "omx_sim" and target.simulation is True
    with pytest.raises(ValidationError):
        OmxSimTarget(instance_id="omx_01", joints=(), gripper="gripper_joint_1")
    with pytest.raises(ValidationError):
        OmxSimTarget(instance_id="omx_01", joints=("joint1",),
                     gripper="gripper_joint_1", simulation=False)


def test_jog_rejects_unbounded_or_malformed_requests():
    valid = dict(instance_id="omx_01", seat_id="seat-1", request_id="request-1",
                 joint="joint1", delta_rad=0.02, duration_s=0.4,
                 state_sequence=8, expires_at_ms=100_000)
    assert OmxSimJog(**valid).delta_rad == 0.02
    for changed in ({"delta_rad": 0.2}, {"delta_rad": float("nan")},
                    {"duration_s": 2}, {"state_sequence": -1},
                    {"expires_at_ms": 0}, {"joint": ""}):
        with pytest.raises(ValidationError):
            OmxSimJog(**{**valid, **changed})


def test_goal_status_separates_local_ros_cancel_and_terminal_results():
    base = dict(command_id="request-1", state="LOCAL_ACCEPTED")
    assert OmxSimGoal(**base).ros_goal_id is None
    assert OmxSimGoal(command_id="request-1", state="ROS_ACCEPTED",
                      ros_goal_id="8b62da7d-f78b-4907-a808-fc0752450020").state == "ROS_ACCEPTED"
    with pytest.raises(ValidationError):
        OmxSimGoal(command_id="request-1", state="SUCCEEDED", ros_goal_id=None)
    with pytest.raises(ValidationError):
        OmxSimGoal(command_id="request-1", state="LOCAL_ACCEPTED",
                   ros_goal_id="8b62da7d-f78b-4907-a808-fc0752450020")


def test_jog_and_descriptor_share_one_step_bound():
    from core_common.protocol.controls import BOUNDED_JOG_MAX_STEP_RAD, JointJogControl
    valid = dict(instance_id="omx_01", seat_id="seat-1", request_id="request-1",
                 joint="joint1", duration_s=0.4, state_sequence=8, expires_at_ms=100_000)
    assert OmxSimJog(**valid, delta_rad=-BOUNDED_JOG_MAX_STEP_RAD).delta_rad == -BOUNDED_JOG_MAX_STEP_RAD
    with pytest.raises(ValidationError):
        OmxSimJog(**valid, delta_rad=BOUNDED_JOG_MAX_STEP_RAD + 1e-6)
    joints = [{"name": "joint1", "lower": -1.0, "upper": 1.0}]
    assert JointJogControl(id="arm", label="팔", joints=joints, max_step_rad=BOUNDED_JOG_MAX_STEP_RAD,
                           duration_s=0.4).max_step_rad == BOUNDED_JOG_MAX_STEP_RAD
    with pytest.raises(ValidationError):
        JointJogControl(id="arm", label="팔", joints=joints, max_step_rad=BOUNDED_JOG_MAX_STEP_RAD + 1e-6,
                        duration_s=0.4)


def test_target_may_carry_a_controls_descriptor():
    from core_common.protocol.controls import ControlsDescriptor
    descriptor = ControlsDescriptor(items=())
    target = OmxSimTarget(instance_id="omx_01", joints=("joint1",), gripper="gripper_joint_1",
                          controls=descriptor)
    assert target.model_dump(by_alias=True)["controls"] == {"schema": "rosy.controls/1", "items": ()}


def _gripper(**changes):
    from core_common.protocol.omx_sim import OmxSimGripperGoal
    body = {"instance_id": "omx_01", "seat_id": "s", "request_id": "r", "position": 0.5,
            "duration_s": 0.8, "state_sequence": 3, "expires_at_ms": 10**13}
    return OmxSimGripperGoal(**{**body, **changes})


def test_gripper_goal_is_absolute_and_duration_bounded():
    assert _gripper().position == 0.5
    assert _gripper(duration_s=0.2).duration_s == 0.2 and _gripper(duration_s=2.0).duration_s == 2.0
    for bad in ({"duration_s": 0.1}, {"duration_s": 2.5}, {"position": float("nan")},
                {"position": float("inf")}, {"joint": "x"}, {"state_sequence": -1}, {"seat_id": ""}):
        with pytest.raises(ValidationError):
            _gripper(**bad)
