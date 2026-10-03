import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core_common.protocol.omx_sim import OmxSimGripperGoal, OmxSimJog
from omx_adapter.command_owner import ArmCommandConfig, CommandDecision, JointStateSnapshot
from omx_adapter.pilot_sim_runtime import PilotSimRuntime
from omx_adapter.ros_goal_contract import RosGoalEvent

ROOT = Path(__file__).resolve().parents[6]


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


def test_urdf_limits_come_from_the_pinned_kinematics_record():
    import math
    from omx_adapter.pilot_sim_runtime import urdf_position_limits
    limits = urdf_position_limits()
    assert limits["joint1"] == (-2 * math.pi, 2 * math.pi)
    assert limits["gripper_joint_1"] == (-2 * math.pi, 2 * math.pi)
    assert {"joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"} <= set(limits)
    assert "end_effector_joint" not in limits


# --- D-411 C: gripper mode -------------------------------------------------------------

def grip(position, sequence=8, request_id="grip", duration_s=0.8):
    return OmxSimGripperGoal(instance_id="instance", seat_id="seat", request_id=request_id,
                             position=position, duration_s=duration_s, state_sequence=sequence,
                             expires_at_ms=9999999999999)


GRIPPER = {"gripper_open": 0.1, "gripper_closed": 0.0, "gripper_velocity": 0.5, "gripper_preload": 0.02}


def _gripper_runtime(arm=None, **changes):
    return PilotSimRuntime(arm or Arm(), **{**GRIPPER, **changes})


def _terminal(runtime, command_id, status=4, result_code=0, sequence=1):
    runtime.on_goal_event(RosGoalEvent(kind="TERMINAL_RESULT", command_id=command_id, phase_id=None,
                                       goal_id=str(uuid4()), observed_at_monotonic_s=time.monotonic(),
                                       sequence=sequence, status=status, result_code=result_code))
    runtime.arm.owner.state = "ready" if status == 4 and result_code == 0 else "hold"


def _readback(arm, sequence, **positions):
    arm.latest_joint_state = JointStateSnapshot(
        positions={"joint1": 0.0, "gripper_joint_1": 0.0, **positions}, sequence=sequence,
        received_at=time.monotonic(), calibration_revision="sim")


def test_gripper_mode_needs_every_gripper_parameter():
    for missing in GRIPPER:
        with pytest.raises(ValueError, match="together"):
            PilotSimRuntime(Arm(), **{key: value for key, value in GRIPPER.items() if key != missing})
    with pytest.raises(ValueError, match="preload"):
        _gripper_runtime(gripper_preload=0.2)
    with pytest.raises(ValueError, match="velocity"):
        _gripper_runtime(gripper_velocity=0.0)


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


def test_gripper_goal_outside_the_offered_range_is_rejected():
    runtime = _gripper_runtime(range_inset_rad=0.01)
    runtime.snapshot()
    assert runtime.submit_gripper(grip(0.095)) == {"command_id": "grip", "state": "REJECTED",
                                                   "reason": "gripper_limit"}
    assert runtime.submit_gripper(grip(-0.2, request_id="g2"))["reason"] == "gripper_limit"
    assert runtime.submit_gripper(grip(0.085, request_id="g3"))["state"] == "LOCAL_ACCEPTED"


def test_gripper_goal_faster_than_the_gripper_speed_is_rejected():
    arm = Arm()
    runtime = _gripper_runtime(arm, gripper_velocity=0.1)
    runtime.snapshot()
    # 0.095 rad in 0.2 s needs 0.475 rad/s; the bound is 0.1 x 0.2 s + 0.05 rad slack = 0.07 rad.
    assert runtime.submit_gripper(grip(0.095, duration_s=0.2))["reason"] == "gripper_velocity_limit"
    assert not arm.commands
    assert runtime.submit_gripper(grip(0.095, request_id="slow", duration_s=0.5))["state"] == "LOCAL_ACCEPTED"


def test_gripper_speed_check_tolerates_small_readback_drift_but_not_more():
    """The client sizes a goal at max_velocity from one readback; the readback drifts before dispatch."""
    from omx_adapter.pilot_sim_gripper import GRIPPER_TOLERANCE_RAD
    arm = Arm()
    arm.owner.config = ArmCommandConfig(
        enabled=True, workcell_id="sim", instance_id="instance", joint_names=("joint1", "gripper_joint_1"),
        position_limits={"joint1": (-1, 1), "gripper_joint_1": (-0.1, 1.1)},
        allowed_owners=("pilot_sim",), calibration_revision="sim")
    runtime = PilotSimRuntime(arm, gripper_open=1.0, gripper_closed=0.0, gripper_velocity=0.5, gripper_preload=0.05)
    _readback(arm, 8, gripper_joint_1=-0.003)     # sized from 0.000: 0.5 rad in 1.0 s at exactly 0.5 rad/s
    runtime.snapshot()
    assert runtime.submit_gripper(grip(0.5, duration_s=1.0))["state"] == "LOCAL_ACCEPTED"
    _terminal(runtime, "grip")
    _readback(arm, 9, gripper_joint_1=0.5 - 0.5 - GRIPPER_TOLERANCE_RAD - 0.01)   # drifted beyond the slack
    runtime.snapshot()
    assert runtime.submit_gripper(grip(0.5, sequence=9, request_id="far", duration_s=1.0))["reason"] == (
        "gripper_velocity_limit")


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
    assert legacy.gripper_joint_for_goals is None and runtime.gripper_joint_for_goals == "gripper_joint_1"


def test_jog_no_longer_admits_the_gripper_joint():
    runtime = _gripper_runtime()
    runtime.snapshot()
    gripper_jog = OmxSimJog(instance_id="instance", seat_id="seat", request_id="j", joint="gripper_joint_1",
                            delta_rad=0.02, duration_s=0.4, state_sequence=8, expires_at_ms=9999999999999)
    assert runtime.submit(gripper_jog)["reason"] == "joint_not_admitted"


def test_snapshot_reports_gripper_state():
    snap = _gripper_runtime().snapshot()
    assert snap["gripper"] == {"joint": "gripper_joint_1", "position": 0.0, "state": "closed",
                               "open": 0.1, "closed": 0.0, "hold_target": None}
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
                                             "state": "unknown", "open": 0.1, "closed": 0.0,
                                             "hold_target": None}


def test_the_watchdog_samples_gripper_motion_between_state_polls():
    arm = Arm()
    runtime = _gripper_runtime(arm)
    _readback(arm, 8, gripper_joint_1=0.06)
    runtime.on_watchdog()
    _readback(arm, 9, gripper_joint_1=0.03)
    runtime.on_watchdog()
    assert [sample[2] for sample in runtime._gripper_samples] == [0.06, 0.03]
    assert runtime.snapshot()["gripper"]["state"] == "moving"


def _hold_an_object(arm, runtime, stall=0.07):
    _readback(arm, 8, gripper_joint_1=0.1)
    runtime.snapshot()
    runtime.submit_gripper(grip(0.0, duration_s=1.0))
    _readback(arm, 9, gripper_joint_1=stall)      # fingers stopped on an object, then SUCCEEDED
    _terminal(runtime, "grip")
    runtime._gripper_samples.clear()
    _readback(arm, 10, gripper_joint_1=stall)


def test_finished_close_that_stops_short_is_holding_and_arm_jogs_squeeze_by_the_preload():
    arm = Arm()
    runtime = _gripper_runtime(arm)
    _hold_an_object(arm, runtime)
    assert runtime.snapshot()["gripper"]["state"] == "holding"
    assert runtime.submit(jog(sequence=10))["state"] == "LOCAL_ACCEPTED"
    # stall 0.07 - preload 0.02 toward closed: bounded, never the full 0.07 error to closed.
    assert arm.commands[-1].positions == {"joint1": 0.02, "gripper_joint_1": pytest.approx(0.05)}


def test_the_squeeze_is_fixed_at_the_stall_and_does_not_ratchet():
    arm = Arm()
    runtime = _gripper_runtime(arm)
    _hold_an_object(arm, runtime)
    for sequence, request_id in ((10, "a"), (12, "b")):
        _readback(arm, sequence, gripper_joint_1=0.06)   # fingers compressed a little by the squeeze
        runtime.snapshot()
        runtime.submit(OmxSimJog(instance_id="instance", seat_id="seat", request_id=request_id, joint="joint1",
                                 delta_rad=0.02, duration_s=0.4, state_sequence=sequence,
                                 expires_at_ms=9999999999999))
        _terminal(runtime, request_id, sequence=2)
    assert [command.positions["gripper_joint_1"] for command in arm.commands[1:]] == [
        pytest.approx(0.05), pytest.approx(0.05)]


def test_squeeze_never_passes_closed_and_a_full_close_keeps_its_target():
    arm = Arm()
    runtime = _gripper_runtime(arm, gripper_preload=0.09)
    _hold_an_object(arm, runtime)
    runtime.submit(jog(sequence=10))
    assert arm.commands[-1].positions["gripper_joint_1"] == 0.0
    arm = Arm()
    runtime = _gripper_runtime(arm)
    _hold_an_object(arm, runtime, stall=0.01)      # closed on nothing
    assert runtime.snapshot()["gripper"]["state"] == "closed"
    runtime.submit(jog(sequence=10))
    assert arm.commands[-1].positions["gripper_joint_1"] == 0.0


def test_a_failed_close_is_hold_evidence_never_holding():
    arm = Arm()
    runtime = _gripper_runtime(arm)
    _readback(arm, 8, gripper_joint_1=0.1)
    runtime.snapshot()
    runtime.submit_gripper(grip(0.0, duration_s=1.0))
    _readback(arm, 9, gripper_joint_1=0.07)
    _terminal(runtime, "grip", status=6, result_code=-5)    # ABORTED, GOAL_TOLERANCE_VIOLATED
    assert runtime.goal("grip") == {"command_id": "grip", "state": "UNKNOWN_HOLD",
                                    "reason": "terminal_status_6_result_-5"}
    assert runtime.snapshot()["gripper"]["state"] == "unknown"


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
    assert (grip_control.open, grip_control.closed, grip_control.max_velocity) == (0.1, 0.0, 0.5)
    assert grip_control.presets.half == pytest.approx(0.05)


def test_offered_ranges_are_admission_inset_by_the_start_state_tolerance():
    from core_common.protocol.controls import ControlsDescriptor
    runtime = PilotSimRuntime(Arm(), range_inset_rad=0.02)
    (jog_control,) = ControlsDescriptor.model_validate(runtime.controls()).items
    assert [(j.name, j.lower, j.upper) for j in jog_control.joints] == [
        ("joint1", -0.98, 0.98), ("gripper_joint_1", pytest.approx(-0.08), pytest.approx(0.08))]
    with pytest.raises(ValueError, match="inset"):
        PilotSimRuntime(Arm(), range_inset_rad=0.1)


def test_a_jog_past_the_offered_bound_is_refused_but_inward_jogs_are_not():
    arm = Arm()
    runtime = PilotSimRuntime(arm, range_inset_rad=0.02)
    _readback(arm, 8, joint1=0.97)
    runtime.snapshot()
    assert runtime.submit(jog())["reason"] == "joint_limit"          # 0.99 > offered 0.98
    _readback(arm, 9, joint1=0.99)                                    # an overshoot read back
    runtime.snapshot()
    inward = OmxSimJog(instance_id="instance", seat_id="seat", request_id="in", joint="joint1",
                       delta_rad=-0.02, duration_s=0.4, state_sequence=9, expires_at_ms=9999999999999)
    assert runtime.submit(inward)["state"] == "LOCAL_ACCEPTED"


def test_an_overshoot_past_the_offered_upper_bound_does_not_latch_hold():
    from omx_adapter.command_owner import ArmCommandOwner
    arm = Arm()
    runtime = PilotSimRuntime(arm, range_inset_rad=0.02)
    owner = ArmCommandOwner(arm.owner.config, SimpleNamespace())
    upper = runtime.offered_range("joint1")[1]
    overshoot = JointStateSnapshot(positions={"joint1": upper + 0.015, "gripper_joint_1": 0.0}, sequence=1,
                                   received_at=time.monotonic(), calibration_revision="sim")
    assert owner.observe_joint_state(overshoot) is True and owner.state != "hold"
    beyond = JointStateSnapshot(positions={"joint1": upper + 0.025, "gripper_joint_1": 0.0}, sequence=2,
                                received_at=time.monotonic(), calibration_revision="sim")
    assert owner.observe_joint_state(beyond) is False and owner.state == "hold"   # admission edge is HOLD


def test_sim_admission_is_the_cell_profile_within_the_urdf():
    from omx_adapter.pilot_sim_runtime import sim_admission_limits, urdf_position_limits, urdf_velocity_limits
    from omx_adapter.pose_plan import CellPlanningProfile
    cell = CellPlanningProfile.load(ROOT / "deploy/robot/omx/sim/cell_profile.yaml")
    limits = sim_admission_limits(cell.position_limits, urdf_position_limits())
    assert set(limits) == set(cell.joint_names) and cell.gripper_joint in limits
    assert limits == dict(cell.position_limits)   # the profile is inside URDF +/-2pi
    lower, upper = limits[cell.gripper_joint]
    inset = cell.start_state_tolerance_rad
    assert lower + inset < cell.gripper_closed < cell.gripper_open < upper - inset
    assert urdf_velocity_limits()[cell.gripper_joint] == 4.8 and cell.velocity_limits[cell.gripper_joint] == 0.5
    assert 0 < cell.gripper_preload_rad < abs(cell.gripper_open - cell.gripper_closed)
    assert sim_admission_limits({"j": (-1.0, 9.0)}, {"j": (-2.0, 2.0)}) == {"j": (-1.0, 2.0)}
    with pytest.raises(ValueError, match="outside"):
        sim_admission_limits({"j": (3.0, 4.0)}, {"j": (-2.0, 2.0)})
    with pytest.raises(ValueError, match="no URDF range"):
        sim_admission_limits({"j": (-1.0, 1.0)}, {})


def test_server_builds_admission_from_the_cell_profile_and_two_second_goals():
    source = (ROOT / "middleware/apps/device/omx/adapter/omx_adapter/pilot_sim_server.py").read_text(encoding="utf-8")
    assert "CellPlanningProfile.load(cell_path)" in source
    assert "position_limits=sim_admission_limits(cell.position_limits, urdf_limits)" in source
    assert "max_goal_duration_s=GRIPPER_GOAL_MAX_DURATION_S" in source
    assert "range_inset_rad=cell.start_state_tolerance_rad" in source
    assert ("min(cell.velocity_limits[cell.gripper_joint], urdf_velocity_limits()[cell.gripper_joint])"
            in source)
    assert "gripper_velocity=gripper_velocity, gripper_preload=cell.gripper_preload_rad" in source
    assert "(-3.0, 3.0)" not in source and "(-0.5, 0.5)" not in source


def test_a_holding_close_is_reissued_once_at_stall_plus_preload():
    """Gazebo 2026-10-03: after SUCCEEDED the JTC keeps the close's own last point (full stall error);
    the first arm jog then relaxed the grip (0.359 -> 0.377 rad). One hold goal makes them equal."""
    arm = Arm()
    runtime = _gripper_runtime(arm)
    _hold_an_object(arm, runtime)
    assert runtime.snapshot()["gripper"]["hold_target"] == pytest.approx(0.05)
    runtime.on_watchdog()
    hold = arm.commands[-1]
    assert hold.command_id == "hold-grip" and hold.positions == {"joint1": 0.0, "gripper_joint_1": pytest.approx(0.05)}
    assert hold.duration_s == 0.2                       # 0.02 rad at 0.5 rad/s -> the 0.2 s minimum
    assert runtime.snapshot()["owner_state"] == "active"
    assert runtime.snapshot()["gripper"]["state"] == "holding"   # still the close goal's grasp
    _terminal(runtime, "hold-grip")
    runtime.on_watchdog()
    assert len(arm.commands) == 2                       # once, not on every watchdog tick


def test_no_hold_goal_after_a_close_on_nothing_or_an_open():
    arm = Arm()
    runtime = _gripper_runtime(arm)
    _hold_an_object(arm, runtime, stall=0.01)
    runtime.on_watchdog()
    assert [command.command_id for command in arm.commands] == ["grip"]
    arm = Arm()
    runtime = _gripper_runtime(arm)
    runtime.snapshot()
    runtime.submit_gripper(grip(0.08))
    _readback(arm, 9, gripper_joint_1=0.08)
    _terminal(runtime, "grip")
    runtime.on_watchdog()
    assert [command.command_id for command in arm.commands] == ["grip"]


def test_the_hold_waits_for_the_owner_and_a_fresh_readback():
    arm = Arm()
    runtime = _gripper_runtime(arm)
    _hold_an_object(arm, runtime)
    arm.owner.state = "active"
    runtime.on_watchdog()
    arm.owner.state = "ready"
    arm.latest_joint_state = JointStateSnapshot(positions={"joint1": 0.0, "gripper_joint_1": 0.07}, sequence=11,
                                                received_at=time.monotonic() - 5, calibration_revision="sim")
    runtime.on_watchdog()
    assert len(arm.commands) == 1
    _readback(arm, 12, gripper_joint_1=0.07)
    runtime.on_watchdog()
    assert arm.commands[-1].command_id == "hold-grip"


def test_without_a_terminal_readback_the_first_fresh_one_is_the_stall():
    arm = Arm()
    runtime = _gripper_runtime(arm)
    _readback(arm, 8, gripper_joint_1=0.1)
    runtime.snapshot()
    runtime.submit_gripper(grip(0.0, duration_s=1.0))
    arm.latest_joint_state = None                        # nothing at the terminal callback
    _terminal(runtime, "grip")
    assert runtime._gripper_stall is None
    _readback(arm, 9, gripper_joint_1=0.07)
    runtime.on_watchdog()                                # samples the stall, then issues the hold
    assert runtime._gripper_stall == 0.07
    assert arm.commands[-1].positions["gripper_joint_1"] == pytest.approx(0.05)


def test_failed_terminal_reason_format_is_status_and_result_code():
    """Pinned: probe_pilot_sim_http.terminal_facts parses exactly this format."""
    runtime = _gripper_runtime()
    runtime.snapshot()
    runtime.submit_gripper(grip(0.05))
    _terminal(runtime, "grip", status=4, result_code=-5)
    assert runtime.goal("grip")["reason"] == "terminal_status_4_result_-5"
    runtime = PilotSimRuntime(Arm())
    runtime.snapshot()
    runtime.submit(jog())
    runtime.on_goal_event(RosGoalEvent(kind="TERMINAL_RESULT", command_id="request", phase_id=None,
                                       goal_id=str(uuid4()), observed_at_monotonic_s=time.monotonic(),
                                       sequence=1, status=6))
    assert runtime.goal("request")["reason"] == "terminal_status_6_result_None"
