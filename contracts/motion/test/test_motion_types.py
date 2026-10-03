"""D-442(a): pure contract shape and immutability, never dispatch authority."""

from dataclasses import FrozenInstanceError, replace
import importlib
import math

import pytest


def motion():
    return importlib.import_module("rosy.contracts.motion")


def header(**changes):
    fields = dict(intent_id="intent-1", device_id="device-1", source="manual", priority_class="MANUAL",
                  issued_at=10.0, valid_for_s=0.5)
    fields.update(changes)
    return motion().MotionHeader(**fields)


@pytest.mark.parametrize("source,priority", [("manual", "MANUAL"), ("navigation", "NAVIGATION"),
                                           ("docking", "DOCKING"), ("swarm", "NAVIGATION"),
                                           pytest.param("navigation", "NAVIGATION", id="line-follow-current-slot"),
                                           pytest.param("navigation", "NAVIGATION", id="localization-current-slot")])
def test_base_producer_roundtrip_keeps_both_twist_values(source, priority):
    m = motion()
    intent = m.MotionIntent(m.MotionKind.BASE_TWIST, header(source=source, priority_class=priority),
                            m.BaseTwist(0.125, -0.375))
    assert (intent.payload.linear_mps, intent.payload.angular_radps) == (0.125, -0.375)
    assert intent.payload.frame == "base_link" and intent.phase == "servo"
    assert intent.header.source == source and intent.header.priority_class.value == priority


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -float("inf")])
def test_twist_rejects_nonphysical_numbers(value):
    m = motion()
    with pytest.raises(ValueError):
        m.BaseTwist(value, 0.0)
    with pytest.raises(ValueError):
        m.BaseTwist(0.0, value)


def test_guarded_twist_is_deeply_immutable_and_does_not_issue_authority():
    m = motion()
    token = object()
    guarded = m.GuardedMotion(m.BaseTwist(0.1, -0.2), "clip-v1", token)
    with pytest.raises(FrozenInstanceError):
        guarded.payload.linear_mps = 10.0
    assert replace(guarded) is not guarded
    assert guarded._token is token


@pytest.mark.parametrize("changes", [{"issued_at": True}, {"issued_at": math.inf},
                                      {"valid_for_s": 0.0}, {"valid_for_s": True},
                                      {"valid_for_s": math.nan}, {"state_sequence": True}])
def test_header_refuses_invalid_monotonic_validity_and_sequence(changes):
    m = motion()
    with pytest.raises(ValueError):
        header(**changes)


def test_validity_uses_caller_monotonic_time_with_closed_expiry_boundary():
    h = header()
    assert h.is_valid_at(10.0) and h.is_valid_at(10.499)
    assert not h.is_valid_at(9.9) and not h.is_valid_at(10.5)
    with pytest.raises(ValueError):
        h.is_valid_at(math.nan)


def test_limits_are_an_independent_immutable_snapshot():
    limits = {"linear_mps": 0.1}
    h = header(limits=limits)
    limits["linear_mps"] = 9.0
    assert h.limits["linear_mps"] == 0.1
    with pytest.raises(TypeError):
        h.limits["linear_mps"] = 0.2


def test_kind_and_exact_payload_must_agree():
    m = motion()
    with pytest.raises(ValueError):
        m.MotionIntent(m.MotionKind.ARM_GRIPPER, header(), m.BaseTwist(0.0, 0.0))


def test_arm_intent_requires_state_and_calibration_header():
    m = motion()
    gripper = m.ArmGripper("gripper", 0.1)
    with pytest.raises(ValueError):
        m.MotionIntent(m.MotionKind.ARM_GRIPPER, header(), gripper)
    intent = m.MotionIntent(m.MotionKind.ARM_GRIPPER, header(state_sequence=12, calibration_revision="cal-1"), gripper)
    assert intent.phase == "servo"


def test_tcp_pose_refuses_zero_quaternion():
    m = motion()
    with pytest.raises(ValueError):
        m.ArmTcpPose((0.1, 0.2, 0.3), (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, -1.0), "arm_base")


def test_trajectory_preserves_optional_fields_and_copies_mutable_maps():
    m = motion()
    positions = {"joint-1": 0.1}
    trajectory = m.ArmJointTrajectory("cell-1", "session-1", positions, 0.5)
    positions["joint-1"] = 9.0
    assert trajectory.positions["joint-1"] == 0.1
    assert trajectory.joint_names is None and trajectory.trajectory_points is None
    assert trajectory.phase_id is None and trajectory.expected_start_state_positions is None


@pytest.mark.parametrize("points", [
    ((0.2, (0.1,)), (0.1, (0.1,))),
    ((0.5, (0.1, 0.2)),),
    ((0.5, (0.9,)),),
    ((0.4, (0.1,)),),
])
def test_trajectory_refuses_time_dimension_final_position_or_duration_mismatch(points):
    m = motion()
    typed = tuple(m.TrajectoryPoint(time, positions) for time, positions in points)
    with pytest.raises(ValueError):
        m.ArmJointTrajectory("cell-1", "session-1", {"joint-1": 0.1}, 0.5,
                             joint_names=("joint-1",), trajectory_points=typed)


def test_port_protocol_has_only_minimal_operations():
    m = motion()
    operations = {name for name in vars(m.DeviceControlPort) if not name.startswith("_")}
    assert operations == {"capabilities", "submit", "cancel", "state", "estop_status"}
    assert {kind.value for kind in m.MotionKind} == {"base.twist", "base.pose_goal", "base.path_follow",
                                                    "arm.joint_trajectory", "arm.tcp_pose", "arm.gripper"}


@pytest.mark.parametrize("name,args", [
    ("PortDecision", (1, "ready", "accepted")), ("PortDecision", (True, "unknown", "accepted")),
    ("PortState", ("unknown",)), ("PortState", ("ready", None, True)),
    ("EstopStatus", ("unknown",)), ("EstopStatus", (False, 1)),
])
def test_port_readback_types_refuse_ambiguous_scalar_or_state(name, args):
    m = motion()
    with pytest.raises(ValueError):
        getattr(m, name)(*args)


def test_policy_shape_requires_envelope_but_never_grants_execution():
    m = motion()
    with pytest.raises(ValueError):
        m.MotionIntent(m.MotionKind.BASE_TWIST, header(source="learned_policy", priority_class="POLICY"),
                       m.BaseTwist(0.0, 0.0))
    shape = m.MotionIntent(m.MotionKind.BASE_TWIST,
                           header(source="learned_policy", priority_class="POLICY", envelope_ref="envelope-1"),
                           m.BaseTwist(0.0, 0.0))
    assert shape.header.envelope_ref == "envelope-1"


def test_attempt_device_and_arm_workcell_identity_must_agree():
    m = motion()
    from rosy.contracts.skill import AttemptIdentity
    attempt = AttemptIdentity("mission-1", "step-1", "action-1", "attempt-1", "cell-1", "device-1",
                              "a" * 64, 1, 1)
    with pytest.raises(ValueError):
        header(attempt=attempt, device_id="another-device")
    h = header(attempt=attempt, state_sequence=12, calibration_revision="cal-1")
    with pytest.raises(ValueError):
        m.MotionIntent(m.MotionKind.ARM_JOINT_TRAJECTORY, h,
                       m.ArmJointTrajectory("another-cell", "session-1", {"joint-1": 0.1}, 0.5))


def test_all_goal_payload_kinds_are_goal_shaped_and_immutable():
    m = motion()
    cases = [(m.MotionKind.BASE_POSE_GOAL, m.BasePoseGoal(1.0, 2.0, 0.3, 0.1, 0.1)),
             (m.MotionKind.BASE_PATH_FOLLOW, m.BasePathFollow("path-1", "forward")),
             (m.MotionKind.ARM_TCP_POSE, m.ArmTcpPose([0.1, 0.2, 0.3], [0.0, 0.0, 0.0, 1.0],
                                                    [0.0, 0.0, -1.0], "arm_base"))]
    for kind, payload in cases:
        intent = m.MotionIntent(kind, header(state_sequence=12, calibration_revision="cal-1"), payload)
        assert intent.phase == "goal"
        with pytest.raises(FrozenInstanceError):
            payload.frame = "other"
    assert cases[-1][1].position_m == (0.1, 0.2, 0.3)


@pytest.mark.parametrize("source,priority", [("pilot_sim", "MANUAL"), ("rule_based", "SKILL"),
                                           ("moveit", "SKILL"), ("leader_teleop", "MANUAL"),
                                           ("learned_policy", "POLICY")])
def test_existing_omx_command_every_field_roundtrips_without_backend_import_in_contract(source, priority):
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "middleware/apps/device/omx/adapter"))
    from omx_adapter.command_owner import TrajectoryCommand
    from omx_adapter.manipulation_plan import JointTrajectoryPoint
    m = motion()
    original = TrajectoryCommand("cell-1", "device-1", "intent-1", "session-1", source,
                                 {"joint-1": 0.2}, 0.5, 12, "cal-1", joint_names=("joint-1",),
                                 trajectory_points=(JointTrajectoryPoint(0.5, (0.2,), (0.1,), (0.05,)),),
                                 phase_id="phase-1", expected_start_state_positions={"joint-1": 0.0},
                                 start_state_tolerances={"joint-1": 0.1})
    h = header(source=original.owner, priority_class=priority,
               envelope_ref="representation-only" if priority == "POLICY" else None,
               intent_id=original.command_id, device_id=original.instance_id,
               state_sequence=original.source_state_sequence, calibration_revision=original.calibration_revision)
    body = m.ArmJointTrajectory(original.workcell_id, original.session_id, original.positions, original.duration_s,
                               original.joint_names,
                               tuple(m.TrajectoryPoint(p.time_from_start_s, p.positions, p.velocities, p.accelerations)
                                     for p in original.trajectory_points),
                               original.phase_id, original.expected_start_state_positions, original.start_state_tolerances)
    intent = m.MotionIntent(m.MotionKind.ARM_JOINT_TRAJECTORY, h, body)
    rebuilt = TrajectoryCommand(body.workcell_id, h.device_id, h.intent_id, body.session_id, h.source,
                                body.positions, body.duration_s, h.state_sequence, h.calibration_revision,
                                joint_names=body.joint_names,
                                trajectory_points=tuple(JointTrajectoryPoint(p.time_from_start_s, p.positions,
                                                                            p.velocities, p.accelerations)
                                                        for p in body.trajectory_points),
                                phase_id=body.phase_id, expected_start_state_positions=body.expected_start_state_positions,
                                start_state_tolerances=body.start_state_tolerances)
    assert intent.phase == "servo" and rebuilt == original


@pytest.mark.parametrize("difference", [5e-10, -5e-10])
def test_existing_trajectory_final_time_tolerance_is_preserved(difference):
    m = motion()
    point = m.TrajectoryPoint(0.5 + difference, (0.1,))
    body = m.ArmJointTrajectory("cell-1", "session-1", {"joint-1": 0.1}, 0.5,
                               joint_names=("joint-1",), trajectory_points=(point,))
    assert body.duration_s == 0.5 and body.trajectory_points[0].time_from_start_s == 0.5 + difference


def test_port_capabilities_keep_readonly_limits_and_explicit_transport_modes():
    m = motion()
    limits = {"linear_mps": 0.2}
    caps = m.PortCapabilities((m.MotionKind.BASE_TWIST,), frames=["base_link"], limits=limits,
                              supports_stream=True, supports_goals=False)
    limits["linear_mps"] = 2.0
    assert caps.frames == ("base_link",) and caps.limits["linear_mps"] == 0.2
    assert caps.supports_stream is True and caps.supports_goals is False
    with pytest.raises(TypeError):
        caps.limits["linear_mps"] = 1.0


@pytest.mark.parametrize("kwargs", [{"kinds": ("base.pose_goal",)},
                                    {"kinds": ("base.twist", "base.twist")},
                                    {"kinds": ("base.twist",), "supports_stream": 1},
                                    {"kinds": ("base.twist",), "supports_goals": "yes"},
                                    {"kinds": ("base.twist",), "limits": {"PWM": 1.0}}])
def test_port_capabilities_refuse_goal_intents_ambiguity_and_raw_limits(kwargs):
    m = motion()
    with pytest.raises(ValueError):
        m.PortCapabilities(**kwargs)


@pytest.mark.parametrize("priority", ["FLEET", "IDLE"])
def test_reserved_and_idle_priorities_are_representable_without_authorizing_a_producer(priority):
    h = header(source="representation-only", priority_class=priority)
    assert h.priority_class.value == priority
