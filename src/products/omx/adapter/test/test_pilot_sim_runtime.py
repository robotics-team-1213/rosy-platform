import time
from types import SimpleNamespace
from uuid import uuid4

from core_common.protocol.omx_sim import OmxSimJog
from omx_adapter.command_owner import ArmCommandConfig, CommandDecision, JointStateSnapshot
from omx_adapter.pilot_sim_runtime import PilotSimRuntime
from omx_adapter.ros_goal_contract import RosGoalEvent


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
