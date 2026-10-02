import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core_common.protocol.omx_sim import OmxSimGripperGoal, OmxSimJog
from omx_adapter.command_owner import ArmCommandConfig, CommandDecision, JointStateSnapshot
from omx_adapter.pilot_sim_runtime import PilotSimRuntime
from omx_adapter.ros_goal_contract import RosGoalEvent

ROOT = Path(__file__).resolve().parents[5]


class Arm:
    def __init__(self):
        config = ArmCommandConfig(
            enabled=True, workcell_id="sim", instance_id="instance", joint_names=("joint1", "gripper_joint_1"),
            position_limits={"joint1": (-1, 1), "gripper_joint_1": (-0.1, 0.1)},
            allowed_owners=("pilot_sim",), calibration_revision="sim",
        )
        self.owner = SimpleNamespace(config=config, state="ready", session_id="session")
        self.latest_joint_state = JointStateSnapshot(
            positions={"joint1": 0.0, "gripper_joint_1": 0.0}, sequence=8,
            received_at=time.monotonic(), calibration_revision="sim",
        )
        self.action_port = SimpleNamespace(server_is_ready=lambda: True)
        self.commands = []

    def submit(self, command):
        self.commands.append(command)
        self.owner.state = "active"
        return CommandDecision(True, "active", "submitted", command.command_id)

    def cancel(self, *, command_id, owner):
        self.owner.state = "hold"
        return CommandDecision(False, "hold", "cancel_requested", command_id, "call_returned")


def jog(sequence=8):
    return OmxSimJog(instance_id="instance", seat_id="seat", request_id="request", joint="joint1",
                     delta_rad=0.02, duration_s=0.4, state_sequence=sequence, expires_at_ms=9999999999999)


def event(kind, goal_id=None, sequence=1, **facts):
    return RosGoalEvent(kind=kind, command_id="request", phase_id=None, goal_id=goal_id,
                        observed_at_monotonic_s=time.monotonic(), sequence=sequence, **facts)


def test_local_acceptance_is_not_ros_acceptance_or_completion():
    arm = Arm()
    runtime = PilotSimRuntime(arm)
    assert runtime.snapshot()["ready"] is True
    arm.latest_joint_state = JointStateSnapshot(
        positions={"joint1": 0.0, "gripper_joint_1": 0.0}, sequence=9,
        received_at=time.monotonic(), calibration_revision="sim",
    )
    assert runtime.submit(jog())["state"] == "LOCAL_ACCEPTED"
    assert arm.commands[0].positions["joint1"] == 0.02
    assert arm.commands[0].source_state_sequence == 9
    assert runtime.snapshot()["ready"] is False
    goal_id = str(uuid4())
    runtime.on_goal_event(event("GOAL_ACCEPTED", goal_id))
    assert runtime.goal("request")["state"] == "ROS_ACCEPTED"
    runtime.on_goal_event(event("TERMINAL_RESULT", goal_id, 2, status=4, result_code=0))
    assert runtime.goal("request")["state"] == "SUCCEEDED"


def test_stale_state_and_cancel_fail_closed():
    arm = Arm()
    runtime = PilotSimRuntime(arm)
    assert runtime.submit(jog(sequence=7))["reason"] == "readback_not_recently_served"
    assert not arm.commands
    assert runtime.snapshot()["ready"] is True
    assert runtime.submit(jog())["state"] == "LOCAL_ACCEPTED"
    assert runtime.cancel("request")["state"] == "CANCEL_REQUESTED"
    assert runtime.submit(jog())["state"] == "REJECTED"
    assert runtime.goal("request")["state"] == "CANCEL_REQUESTED"


def test_immediate_ros_acceptance_is_retained_and_capture_sees_absolute_target():
    arm = Arm()
    captured = []
    runtime = PilotSimRuntime(arm)
    runtime.capture = SimpleNamespace(prepare=lambda command: captured.append(command),
                                     on_goal_event=lambda event: captured.append(event))
    original = arm.submit
    ros_id = str(uuid4())

    def dispatch(command):
        runtime.on_goal_event(event("GOAL_ACCEPTED", ros_id))
        return original(command)

    arm.submit = dispatch
    runtime.snapshot()
    assert runtime.submit(jog())["state"] == "ROS_ACCEPTED"
    assert runtime.goal("request")["ros_goal_id"] == ros_id
    assert captured[0].positions == {"joint1": 0.02, "gripper_joint_1": 0.0}
    assert captured[1].kind == "GOAL_ACCEPTED"


def test_recording_disk_failure_cannot_disable_cancel_or_seat_expiry():
    arm = Arm()
    runtime = PilotSimRuntime(arm)
    runtime.snapshot()
    runtime.submit(jog())

    def broken_recording(reason):
        raise OSError("disk unavailable")

    runtime.capture = SimpleNamespace(interrupt=broken_recording)
    assert runtime.cancel("request")["state"] == "CANCEL_REQUESTED"
    runtime.cancel_active()  # The seat watcher must survive this failure too.


def test_controls_announce_a_bounded_joint_jog_with_limits():
    from core_common.protocol.controls import ControlsDescriptor
    descriptor = ControlsDescriptor.model_validate(PilotSimRuntime(Arm()).controls())
    (jog,) = descriptor.items
    assert jog.kind == "joint_jog" and jog.max_step_rad == 0.05 and jog.duration_s == 0.4
    assert [(j.name, j.lower, j.upper) for j in jog.joints] == [("joint1", -1, 1), ("gripper_joint_1", -0.1, 0.1)]


def test_controls_step_bound_is_the_shared_jog_bound():
    from core_common.protocol.controls import BOUNDED_JOG_MAX_STEP_RAD
    from omx_adapter import pilot_sim_runtime
    assert pilot_sim_runtime.JOG_MAX_STEP_RAD is BOUNDED_JOG_MAX_STEP_RAD


def test_published_limits_are_urdf_range_within_sim_admission():
    from core_common.protocol.controls import ControlsDescriptor
    runtime = PilotSimRuntime(Arm(), urdf_limits={"joint1": (-0.5, 2.0), "gripper_joint_1": (-6.28, 6.28)})
    (jog,) = ControlsDescriptor.model_validate(runtime.controls()).items
    assert [(j.name, j.lower, j.upper) for j in jog.joints] == [("joint1", -0.5, 1), ("gripper_joint_1", -0.1, 0.1)]


def test_urdf_limits_come_from_the_pinned_kinematics_record():
    import math
    from omx_adapter.pilot_sim_runtime import urdf_position_limits
    limits = urdf_position_limits()
    assert limits["joint1"] == (-2 * math.pi, 2 * math.pi)
    assert limits["gripper_joint_1"] == (-2 * math.pi, 2 * math.pi)
    assert {"joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"} <= set(limits)
    assert "end_effector_joint" not in limits


# --- D-411 C: gripper mode -------------------------------------------------------------

def grip(position, sequence=8, request_id="grip"):
    return OmxSimGripperGoal(instance_id="instance", seat_id="seat", request_id=request_id,
                             position=position, duration_s=0.8, state_sequence=sequence,
                             expires_at_ms=9999999999999)


def _gripper_runtime(arm=None):
    return PilotSimRuntime(arm or Arm(), gripper_open=0.1, gripper_closed=0.0)


def _finish(runtime, command_id):
    runtime.on_goal_event(RosGoalEvent(kind="TERMINAL_RESULT", command_id=command_id, phase_id=None,
                                       goal_id=str(uuid4()), observed_at_monotonic_s=time.monotonic(),
                                       sequence=1, status=4, result_code=0))
    runtime.arm.owner.state = "ready"


def _readback(arm, sequence, **positions):
    arm.latest_joint_state = JointStateSnapshot(
        positions={"joint1": 0.0, "gripper_joint_1": 0.0, **positions}, sequence=sequence,
        received_at=time.monotonic(), calibration_revision="sim")


def test_gripper_goal_sets_only_the_gripper_absolutely():
    arm = Arm()
    runtime = _gripper_runtime(arm)
    runtime.snapshot()
    assert runtime.submit_gripper(grip(0.05))["state"] == "LOCAL_ACCEPTED"
    assert arm.commands[0].positions == {"joint1": 0.0, "gripper_joint_1": 0.05}
    assert arm.commands[0].duration_s == 0.8
    snap = runtime.snapshot()
    assert snap["ready"] is False and snap["owner_state"] == "active"
    assert snap["gripper"]["state"] == "moving"


def test_gripper_goal_outside_limits_is_rejected():
    runtime = _gripper_runtime()
    runtime.snapshot()
    assert runtime.submit_gripper(grip(0.2)) == {"command_id": "grip", "state": "REJECTED",
                                                 "reason": "gripper_limit"}
    assert runtime.submit_gripper(grip(-0.2, request_id="g2"))["reason"] == "gripper_limit"


def test_gripper_goal_obeys_the_single_active_goal_rule():
    runtime = _gripper_runtime()
    runtime.snapshot()
    runtime.submit(jog())
    assert runtime.submit_gripper(grip(0.05))["reason"] == "goal_active"


def test_gripper_goal_needs_freshly_served_readback_and_gripper_mode():
    runtime = _gripper_runtime()
    assert runtime.submit_gripper(grip(0.05, sequence=7))["reason"] == "readback_not_recently_served"
    legacy = PilotSimRuntime(Arm())
    legacy.snapshot()
    assert legacy.submit_gripper(grip(0.05))["reason"] == "gripper_not_configured"


def test_jog_no_longer_admits_the_gripper_joint():
    runtime = _gripper_runtime()
    runtime.snapshot()
    gripper_jog = OmxSimJog(instance_id="instance", seat_id="seat", request_id="j", joint="gripper_joint_1",
                            delta_rad=0.02, duration_s=0.4, state_sequence=8, expires_at_ms=9999999999999)
    assert runtime.submit(gripper_jog)["reason"] == "joint_not_admitted"


def test_snapshot_reports_gripper_state():
    snap = _gripper_runtime().snapshot()
    assert snap["gripper"] == {"joint": "gripper_joint_1", "position": 0.0, "state": "closed",
                               "open": 0.1, "closed": 0.0}
    assert "gripper" not in PilotSimRuntime(Arm()).snapshot()


def test_snapshot_gripper_is_unknown_on_stale_readback_or_hold():
    arm = Arm()
    runtime = _gripper_runtime(arm)
    arm.owner.state = "hold"
    assert runtime.snapshot()["gripper"]["state"] == "unknown"
    arm.owner.state = "ready"
    arm.latest_joint_state = JointStateSnapshot(
        positions={"joint1": 0.0, "gripper_joint_1": 0.0}, sequence=9,
        received_at=time.monotonic() - 5, calibration_revision="sim")
    assert runtime.snapshot()["gripper"] == {"joint": "gripper_joint_1", "position": None,
                                             "state": "unknown", "open": 0.1, "closed": 0.0}


def test_finished_close_that_stops_short_is_holding_and_arm_jogs_keep_squeezing():
    arm = Arm()
    runtime = _gripper_runtime(arm)
    _readback(arm, 8, gripper_joint_1=0.1)
    runtime.snapshot()
    runtime.submit_gripper(grip(0.0))
    _finish(runtime, "grip")
    _readback(arm, 9, gripper_joint_1=0.07)   # fingers stopped on an object
    assert runtime.snapshot()["gripper"]["state"] == "moving"   # readback changed within the window
    runtime._gripper_samples.clear()
    _readback(arm, 10, gripper_joint_1=0.07)
    assert runtime.snapshot()["gripper"]["state"] == "holding"
    assert runtime.submit(jog(sequence=10))["state"] == "LOCAL_ACCEPTED"
    assert arm.commands[-1].positions == {"joint1": 0.02, "gripper_joint_1": 0.0}


def test_arm_jog_uses_readback_when_no_gripper_goal_finished():
    arm = Arm()
    runtime = _gripper_runtime(arm)
    _readback(arm, 8, gripper_joint_1=0.06)
    runtime.snapshot()
    runtime.submit(jog())
    assert arm.commands[-1].positions["gripper_joint_1"] == 0.06


def test_gripper_goal_receipts_follow_the_shared_goal_contract():
    from core_common.protocol.omx_sim import OmxSimGoal
    runtime = _gripper_runtime()
    runtime.snapshot()
    runtime.submit_gripper(grip(0.05))
    OmxSimGoal.model_validate(runtime.goal("grip"))
    OmxSimGoal.model_validate(runtime.cancel("grip"))


def test_controls_move_the_gripper_out_of_joint_jog():
    from core_common.protocol.controls import ControlsDescriptor
    descriptor = ControlsDescriptor.model_validate(_gripper_runtime().controls())
    jog_control, grip_control = descriptor.items
    assert [j.name for j in jog_control.joints] == ["joint1"]
    assert grip_control.kind == "gripper" and grip_control.joint == "gripper_joint_1"
    assert (grip_control.open, grip_control.closed) == (0.1, 0.0)
    assert grip_control.presets.half == pytest.approx(0.05)


def test_sim_admission_is_the_cell_profile_within_the_urdf():
    from omx_adapter.pilot_sim_runtime import sim_admission_limits, urdf_position_limits
    from omx_adapter.pose_plan import CellPlanningProfile
    cell = CellPlanningProfile.load(ROOT / "deploy/robot/omx/sim/cell_profile.yaml")
    limits = sim_admission_limits(cell.position_limits, urdf_position_limits())
    assert set(limits) == set(cell.joint_names) and cell.gripper_joint in limits
    assert limits == dict(cell.position_limits)   # the profile is inside URDF +/-2pi
    lower, upper = limits[cell.gripper_joint]
    assert lower < cell.gripper_closed < cell.gripper_open < upper
    assert sim_admission_limits({"j": (-1.0, 9.0)}, {"j": (-2.0, 2.0)}) == {"j": (-1.0, 2.0)}
    with pytest.raises(ValueError):
        sim_admission_limits({"j": (3.0, 4.0)}, {"j": (-2.0, 2.0)})


def test_server_builds_admission_from_the_cell_profile_and_two_second_goals():
    source = (ROOT / "src/products/omx/adapter/omx_adapter/pilot_sim_server.py").read_text(encoding="utf-8")
    assert "CellPlanningProfile.load(cell_path)" in source
    assert "position_limits=sim_admission_limits(cell.position_limits, urdf_limits)" in source
    assert "max_goal_duration_s=GRIPPER_GOAL_MAX_DURATION_S" in source
    assert "gripper_open=cell.gripper_open, gripper_closed=cell.gripper_closed" in source
    assert "(-3.0, 3.0)" not in source and "(-0.5, 0.5)" not in source
