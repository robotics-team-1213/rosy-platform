from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from omx_adapter.command_owner import (
    ArmCommandConfig,
    ArmCommandOwner,
    JointStateSnapshot,
    TrajectoryCommand,
)
from omx_adapter.manipulation_plan import JointTrajectoryPoint

SESSION = "session-01"


class FakeHandle:
    def __init__(self):
        self.cancel_calls = 0
        self.cancel_error = None
        self.finished = False
        self.success = False

    def cancel(self):
        self.cancel_calls += 1
        if self.cancel_error:
            raise self.cancel_error

    def done(self):
        return self.finished

    def succeeded(self):
        return self.success


class FakeActionClient:
    def __init__(self):
        self.commands = []
        self.handles = []
        self.error = None

    def send_goal(self, command):
        if self.error:
            raise self.error
        handle = FakeHandle()
        self.commands.append(command)
        self.handles.append(handle)
        return handle


def make_config(**changes):
    config = ArmCommandConfig(
        enabled=True,
        workcell_id="omx_01",
        instance_id="omx_01_control",
        joint_names=("joint_1", "joint_2"),
        position_limits={"joint_1": (-1.0, 1.0), "joint_2": (-0.5, 0.5)},
        allowed_owners=("leader_teleop", "moveit", "rule_based"),
        calibration_revision="cal-7",
        max_joint_state_age_s=0.5,
        max_goal_duration_s=2.0,
        action_timeout_s=3.0,
    )
    return replace(config, **changes)


def make_state(*, sequence=10, received_at=100.0, calibration_revision="cal-7", positions=None):
    return JointStateSnapshot(
        positions=positions or {"joint_1": 0.1, "joint_2": -0.1},
        sequence=sequence,
        received_at=received_at,
        calibration_revision=calibration_revision,
    )


def make_command(*, command_id="cmd-1", owner="moveit", sequence=10, **changes):
    values = dict(
        workcell_id="omx_01",
        instance_id="omx_01_control",
        command_id=command_id,
        session_id=SESSION,
        owner=owner,
        positions={"joint_1": 0.3, "joint_2": 0.2},
        duration_s=1.0,
        source_state_sequence=sequence,
        calibration_revision="cal-7",
    )
    values.update(changes)
    return TrajectoryCommand(**values)


def owner_at(clock, config=None, client=None):
    action = client or FakeActionClient()
    owner = ArmCommandOwner(
        config or make_config(), action, monotonic=lambda: clock[0], session_id=SESSION
    )
    return owner, action


def test_disabled_owner_never_submits_an_action():
    clock = [100.0]
    owner, action = owner_at(clock, make_config(enabled=False))
    owner.observe_joint_state(make_state())

    result = owner.submit(make_command())

    assert not result.accepted
    assert result.reason == "disabled"
    assert owner.state == "disabled"
    assert action.commands == []


@pytest.mark.parametrize(
    "changes",
    [
        {"joint_names": ("joint_1", "joint_1")},
        {"position_limits": {"joint_1": (-1.0, 1.0)}},
        {"allowed_owners": ("any_client",)},
        {"action_timeout_s": 1.0},
    ],
)
def test_enabled_policy_rejects_incomplete_or_ambiguous_limits(changes):
    with pytest.raises(ValueError):
        replace(make_config(), **changes)


def test_enabled_owner_requires_fresh_feedback_and_allows_one_active_writer():
    clock = [100.0]
    owner, action = owner_at(clock)
    assert owner.observe_joint_state(make_state())

    accepted = owner.submit(make_command())
    competing = owner.submit(make_command(command_id="cmd-2", owner="rule_based"))

    assert accepted.accepted and accepted.state == "active"
    assert not competing.accepted and competing.reason == "busy"
    assert len(action.commands) == 1


def test_concurrent_command_sources_cannot_both_acquire_the_writer():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state())
    barrier = Barrier(2)

    def submit(command):
        barrier.wait()
        return owner.submit(command)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, [
            make_command(command_id="cmd-a", owner="moveit"),
            make_command(command_id="cmd-b", owner="rule_based"),
        ]))

    assert sum(result.accepted for result in results) == 1
    assert len(action.commands) == 1
    assert owner.state == "active"


def test_wrong_owner_cannot_cancel_the_active_command():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state())
    owner.submit(make_command())

    result = owner.cancel(command_id="cmd-1", owner="leader_teleop")

    assert not result.accepted and result.reason == "active_command_mismatch"
    assert owner.state == "active"
    assert action.handles[0].cancel_calls == 0


def test_invalid_joint_feedback_latches_hold_and_its_sequence_cannot_be_replayed():
    clock = [100.0]
    owner, _ = owner_at(clock)
    assert owner.observe_joint_state(make_state(sequence=10))
    invalid = JointStateSnapshot(
        positions={"joint_1": 0.1},
        sequence=11,
        received_at=100.1,
        calibration_revision="cal-7",
    )
    assert not owner.observe_joint_state(invalid)
    assert not owner.observe_joint_state(make_state(sequence=11, received_at=100.2))
    assert owner.state == "hold"

    clock[0] = 100.3
    assert owner.observe_joint_state(make_state(sequence=12, received_at=100.3))
    recovered = owner.recover(operator_confirmed=True, observed_sequence=12)
    assert recovered.accepted and recovered.state == "ready"


def test_joint_feedback_outside_configured_position_bounds_latches_hold():
    clock = [100.0]
    owner, _ = owner_at(clock)
    out_of_range = JointStateSnapshot(
        positions={"joint_1": 1.1, "joint_2": 0.0},
        sequence=1,
        received_at=100.0,
        calibration_revision="cal-7",
    )

    assert not owner.observe_joint_state(out_of_range)
    assert owner.state == "hold"


def test_future_dated_joint_feedback_is_rejected_and_latches_hold():
    clock = [100.0]
    owner, _ = owner_at(clock)

    accepted = owner.observe_joint_state(make_state(received_at=100.1))

    assert not accepted
    assert owner.state == "hold"


def test_duplicate_command_id_is_idempotent_but_cannot_change_payload():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state())
    first = owner.submit(make_command())

    duplicate = owner.submit(make_command())
    reused = owner.submit(make_command(positions={"joint_1": 0.4, "joint_2": 0.2}))

    assert first.accepted and duplicate.accepted
    assert duplicate.reason == "duplicate_ignored"
    assert not reused.accepted and reused.reason == "command_id_reused"
    assert len(action.commands) == 1


def test_newer_joint_state_inside_explicit_start_tolerance_can_close_dispatch_race():
    clock = [100.01]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state(sequence=10))
    command = make_command(
        expected_start_state_positions={"joint_1": 0.1, "joint_2": -0.1},
        start_state_tolerances={"joint_1": 0.01, "joint_2": 0.01},
    )
    owner.observe_joint_state(make_state(
        sequence=11, received_at=100.01,
        positions={"joint_1": 0.105, "joint_2": -0.095},
    ))

    result = owner.submit(command)

    assert result.accepted
    assert result.reason == "submitted"
    assert owner._last_command_state_sequence == 11
    assert action.commands == [command]


def test_newer_joint_state_outside_start_tolerance_is_rejected():
    clock = [100.01]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state(sequence=10))
    owner.observe_joint_state(make_state(
        sequence=11, received_at=100.01,
        positions={"joint_1": 0.12, "joint_2": -0.1},
    ))
    command = make_command(
        expected_start_state_positions={"joint_1": 0.1, "joint_2": -0.1},
        start_state_tolerances={"joint_1": 0.01, "joint_2": 0.01},
    )

    result = owner.submit(command)

    assert not result.accepted
    assert result.reason == "start_state_outside_tolerance"
    assert action.commands == []


def test_advanced_state_without_explicit_start_tolerance_stays_fail_closed():
    clock = [100.01]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state(sequence=10))
    owner.observe_joint_state(make_state(sequence=11, received_at=100.01))

    result = owner.submit(make_command())

    assert not result.accepted
    assert result.reason == "joint_state_sequence_mismatch"
    assert action.commands == []


@pytest.mark.parametrize(
    ("config_changes", "state_changes", "command_changes", "reason"),
    [
        ({}, {"received_at": 99.0}, {}, "joint_state_stale"),
        ({}, {}, {"source_state_sequence": 9}, "joint_state_sequence_mismatch"),
        ({}, {}, {"calibration_revision": "cal-old"}, "calibration_mismatch"),
        ({}, {}, {"positions": {"joint_1": 1.1, "joint_2": 0.0}}, "joint_limit"),
        ({}, {}, {"owner": "learned_policy"}, "owner_not_allowed"),
        ({}, {}, {"duration_s": 2.1}, "duration_limit"),
        ({}, {}, {"workcell_id": "omx_02"}, "workcell_mismatch"),
        ({}, {}, {"session_id": "session-old"}, "session_mismatch"),
    ],
)
def test_invalid_or_stale_commands_are_rejected_without_submission(
    config_changes, state_changes, command_changes, reason
):
    clock = [100.0]
    owner, action = owner_at(clock, make_config(**config_changes))
    owner.observe_joint_state(make_state(**state_changes))

    result = owner.submit(make_command(**command_changes))

    assert not result.accepted
    assert result.reason == reason
    assert action.commands == []


def test_timeout_requests_cancel_and_latches_hold_until_explicit_fresh_recovery():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state())
    assert owner.submit(make_command()).accepted

    clock[0] = 102.9
    assert owner.observe_joint_state(make_state(sequence=11, received_at=102.9))
    clock[0] = 103.0
    timeout = owner.poll()
    blocked = owner.submit(make_command(command_id="cmd-2"))
    no_confirmation = owner.recover(operator_confirmed=False, observed_sequence=11)
    no_new_readback = owner.recover(operator_confirmed=True, observed_sequence=11)

    assert not timeout.accepted and timeout.reason == "action_timeout"
    assert timeout.state == "hold"
    assert timeout.cancel_outcome == "call_returned"
    assert action.handles[0].cancel_calls == 1
    assert not blocked.accepted and blocked.reason == "hold_latched"
    assert not no_confirmation.accepted and no_confirmation.reason == "operator_confirmation_required"
    assert not no_new_readback.accepted and no_new_readback.reason == "fresh_readback_required"

    clock[0] = 103.1
    assert owner.observe_joint_state(make_state(sequence=12, received_at=103.1))
    recovered = owner.recover(operator_confirmed=True, observed_sequence=12)
    assert recovered.accepted and recovered.state == "ready"
    assert owner.submit(make_command(command_id="cmd-2", sequence=12)).accepted
    assert len(action.commands) == 2


def test_cancel_latches_hold_and_does_not_claim_physical_standstill():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state())
    owner.submit(make_command())

    cancelled = owner.cancel(command_id="cmd-1", owner="moveit")

    assert not cancelled.accepted
    assert cancelled.state == "hold"
    assert cancelled.reason == "cancel_requested"
    assert cancelled.cancel_outcome == "call_returned"
    assert action.handles[0].cancel_calls == 1


def test_cancel_dispatch_failure_is_reported_while_hold_remains_latched():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state())
    owner.submit(make_command())
    action.handles[0].cancel_error = RuntimeError("transport unavailable")

    cancelled = owner.cancel(command_id="cmd-1", owner="moveit")

    assert not cancelled.accepted
    assert cancelled.state == "hold"
    assert cancelled.reason == "cancel_call_failed"
    assert cancelled.cancel_outcome == "call_failed"
    assert action.handles[0].cancel_calls == 1


def test_action_submission_failure_latches_hold_and_never_replays():
    clock = [100.0]
    action = FakeActionClient()
    action.error = RuntimeError("transport unavailable")
    owner, _ = owner_at(clock, client=action)
    owner.observe_joint_state(make_state())

    failed = owner.submit(make_command())
    retried = owner.submit(make_command(command_id="cmd-2"))

    assert not failed.accepted and failed.state == "hold"
    assert failed.reason == "action_submission_failed"
    assert not retried.accepted and retried.reason == "hold_latched"
    assert action.commands == []


def test_new_runtime_session_rejects_command_from_previous_instance_start():
    clock = [100.0]
    action = FakeActionClient()
    owner = ArmCommandOwner(make_config(), action, monotonic=lambda: clock[0])
    owner.observe_joint_state(make_state())

    result = owner.submit(make_command(session_id=SESSION))

    assert not result.accepted and result.reason == "session_mismatch"
    assert owner.state == "ready"
    assert action.commands == []


def test_freshness_loss_during_action_requests_cancel_and_latches_hold():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state())
    owner.submit(make_command())
    clock[0] = 100.51

    result = owner.poll()

    assert not result.accepted and result.reason == "joint_state_stale"
    assert result.state == "hold"
    assert action.handles[0].cancel_calls == 1


def test_failed_action_result_latches_hold_and_requires_new_readback():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state())
    owner.submit(make_command())
    action.handles[0].finished = True
    action.handles[0].success = False

    result = owner.poll()
    retry = owner.submit(make_command(command_id="cmd-2"))

    assert not result.accepted and result.reason == "action_failed"
    assert result.state == "hold"
    assert not retry.accepted and retry.reason == "hold_latched"


def test_completed_action_clears_active_writer_but_requires_new_command_id():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state())
    owner.submit(make_command())
    action.handles[0].finished = True
    action.handles[0].success = True

    completed = owner.poll()
    replay = owner.submit(make_command())
    second_without_readback = owner.submit(make_command(command_id="cmd-2"))

    assert completed.accepted and completed.state == "ready"
    assert not replay.accepted and replay.reason == "command_id_reused"
    assert not second_without_readback.accepted
    assert second_without_readback.reason == "joint_state_not_advanced"
    assert len(action.commands) == 1


def _bounded_trajectory(*, middle_position=0.2, middle_velocity=0.2, middle_acceleration=0.2):
    return (
        JointTrajectoryPoint(
            time_from_start_s=0.4,
            positions=(middle_position, 0.1),
            velocities=(middle_velocity, 0.1),
            accelerations=(middle_acceleration, 0.1),
        ),
        JointTrajectoryPoint(
            time_from_start_s=1.0,
            positions=(0.3, 0.2),
            velocities=(0.2, 0.1),
            accelerations=(0.1, 0.1),
        ),
    )


def _trajectory_config(clock, action):
    config = replace(
        make_config(),
        max_goal_duration_s=2.0,
        velocity_limits={"joint_1": 1.0, "joint_2": 1.0},
        acceleration_limits={"joint_1": 2.0, "joint_2": 2.0},
    )
    return ArmCommandOwner(config, action, monotonic=lambda: clock[0], session_id=SESSION)


def _multi_point_command(owner, *, command_id="path-1", points=None):
    points = points or _bounded_trajectory()
    final = points[-1]
    return TrajectoryCommand(
        workcell_id="omx_01", instance_id="omx_01_control",
        command_id=command_id, session_id=owner.session_id, owner="moveit",
        joint_names=("joint_1", "joint_2"),
        positions=dict(zip(("joint_1", "joint_2"), final.positions)),
        trajectory_points=points, duration_s=final.time_from_start_s,
        source_state_sequence=10, calibration_revision="cal-7",
    )


def test_owner_preserves_every_validated_timed_trajectory_waypoint():
    clock = [100.0]
    action = FakeActionClient()
    owner = _trajectory_config(clock, action)
    owner.observe_joint_state(make_state())
    points = _bounded_trajectory()

    result = owner.submit(_multi_point_command(owner, points=points))

    assert result.accepted and result.reason == "submitted"
    sent = action.commands[0]
    assert sent.joint_names == ("joint_1", "joint_2")
    assert sent.trajectory_points == points
    assert tuple(point.time_from_start_s for point in sent.trajectory_points) == (0.4, 1.0)


@pytest.mark.parametrize("points, reason", [
    (_bounded_trajectory(middle_position=1.1), "joint_limit"),
    (_bounded_trajectory(middle_velocity=1.1), "velocity_limit"),
    (_bounded_trajectory(middle_acceleration=2.1), "acceleration_limit"),
])
def test_owner_rejects_any_waypoint_or_derivative_outside_configured_limits(points, reason):
    clock = [100.0]
    action = FakeActionClient()
    owner = _trajectory_config(clock, action)
    owner.observe_joint_state(make_state())

    result = owner.submit(_multi_point_command(owner, points=points))

    assert not result.accepted and result.reason == reason
    assert action.commands == []


def test_command_identity_includes_all_trajectory_points_and_rejects_reuse():
    clock = [100.0]
    action = FakeActionClient()
    owner = _trajectory_config(clock, action)
    owner.observe_joint_state(make_state())
    owner.submit(_multi_point_command(owner))
    changed = _bounded_trajectory(middle_position=0.25)

    result = owner.submit(_multi_point_command(owner, points=changed))

    assert not result.accepted and result.reason == "command_id_reused"
    assert len(action.commands) == 1


def test_multi_point_command_requires_explicit_velocity_and_acceleration_limits():
    clock = [100.0]
    action = FakeActionClient()
    config = replace(make_config(), max_goal_duration_s=2.0)
    owner = ArmCommandOwner(config, action, monotonic=lambda: clock[0], session_id=SESSION)
    owner.observe_joint_state(make_state())

    result = owner.submit(_multi_point_command(owner))

    assert not result.accepted and result.reason == "trajectory_rate_limits_missing"
    assert action.commands == []
