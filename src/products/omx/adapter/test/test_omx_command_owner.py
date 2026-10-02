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


def make_state(*, sequence=10, received_at=100.0, calibration_revision="cal-7"):
    return JointStateSnapshot(
        positions={"joint_1": 0.1, "joint_2": -0.1},
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


# A1 (C3b): the caller reads a joint state, journals, then submits; joint states keep
# arriving at ~100 Hz in between. A command with a start_state_window is checked against the
# owner's own latest state under its lock and bound to that sequence (no exact-race).
WINDOW = {"joint_1": (0.1, 0.02), "joint_2": (-0.1, 0.02)}


def test_window_command_binds_to_a_newer_state_that_arrived_before_submit():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state(sequence=10))
    command = make_command(sequence=10, start_state_window=WINDOW)
    clock[0] = 100.01
    owner.observe_joint_state(make_state(sequence=11, received_at=100.01))

    result = owner.submit(command)

    assert result.accepted and result.reason == "submitted"
    assert action.commands[0].source_state_sequence == 11
    assert action.commands[0].command_id == command.command_id


def test_single_goal_home_command_with_window_survives_the_same_race():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state(sequence=10))
    home = make_command(command_id="home", sequence=10, owner="rule_based",
                        start_state_window={"joint_1": (0.1, 0.05), "joint_2": (-0.1, 0.05)})
    for seq in (11, 12, 13):
        owner.observe_joint_state(make_state(sequence=seq, received_at=100.0))
    assert owner.submit(home).accepted
    assert action.commands[0].source_state_sequence == 13


def test_window_command_still_rejects_a_stale_latest_state():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state(sequence=10))
    clock[0] = 100.6  # max_joint_state_age_s 0.5
    result = owner.submit(make_command(sequence=10, start_state_window=WINDOW))
    assert not result.accepted and result.reason == "joint_state_stale"
    assert owner.state == "hold" and action.commands == []


def test_window_command_rejects_a_latest_state_outside_the_window():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state(sequence=10))
    moved = JointStateSnapshot(positions={"joint_1": 0.15, "joint_2": -0.1}, sequence=11,
                               received_at=100.0, calibration_revision="cal-7")
    owner.observe_joint_state(moved)
    result = owner.submit(make_command(sequence=10, start_state_window=WINDOW))
    assert not result.accepted and result.reason == "start_state_deviation"
    assert action.commands == [] and owner.state == "ready"


def test_window_command_rejects_a_sequence_the_owner_never_observed():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state(sequence=10))
    owner.observe_joint_state(make_state(sequence=11))
    result = owner.submit(make_command(sequence=12, start_state_window=WINDOW))
    assert not result.accepted and result.reason == "joint_state_sequence_mismatch"
    assert action.commands == []


def test_partial_window_checks_only_the_listed_joints():
    # After grasp the runner leaves the gripper out (object width, D-402 §3d).
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(JointStateSnapshot(positions={"joint_1": 0.1, "joint_2": 0.4}, sequence=10,
                                                 received_at=100.0, calibration_revision="cal-7"))
    result = owner.submit(make_command(sequence=10, start_state_window={"joint_1": (0.1, 0.02)}))
    assert result.accepted


def test_window_window_values_are_validated_on_the_command():
    with pytest.raises(ValueError, match="start_state_window"):
        make_command(start_state_window={"joint_1": (0.1, -0.01), "joint_2": (0.0, 0.01)})
    with pytest.raises(ValueError, match="start_state_window"):
        make_command(start_state_window={"joint_9": (0.1, 0.01)})
    with pytest.raises(ValueError, match="start_state_window"):
        make_command(start_state_window={})


def test_window_command_never_rebinds_to_a_sequence_already_used():
    clock = [100.0]
    owner, action = owner_at(clock)
    owner.observe_joint_state(make_state(sequence=10))
    assert owner.submit(make_command(command_id="a", sequence=10, start_state_window=WINDOW)).accepted
    action.handles[0].finished = action.handles[0].success = True
    assert owner.poll().reason == "completed"
    result = owner.submit(make_command(command_id="b", sequence=10, start_state_window=WINDOW))
    assert not result.accepted and result.reason == "joint_state_not_advanced"


# A3 (C3b): with use_sim_time the owner's deadlines run on sim time (the trajectory's own
# clock). A wall clock stays as an outer bound, wall_clock_bound_factor x the sim limits,
# so a frozen or crawling simulation still HOLDs.
def sim_owner(sim, wall, factor=4.0):
    owner = ArmCommandOwner(make_config(wall_clock_bound_factor=factor), FakeActionClient(),
                            monotonic=lambda: sim[0], wall_monotonic=lambda: wall[0],
                            session_id=SESSION)
    return owner, owner._action_port


def test_slow_simulation_is_timed_on_sim_time_not_wall_time():
    sim, wall = [100.0], [5000.0]
    owner, action = sim_owner(sim, wall)
    owner.observe_joint_state(make_state(sequence=10, received_at=100.0))
    assert owner.submit(make_command(sequence=10)).accepted
    seq = 10
    while sim[0] < 102.9:  # RTF 0.3: 2.9 s of sim time is ~9.7 s of wall time
        sim[0] = round(sim[0] + 0.03, 6)
        wall[0] += 0.1
        seq += 1
        owner.observe_joint_state(make_state(sequence=seq, received_at=sim[0]))
        assert owner.poll().reason == "active"
    assert wall[0] - 5000.0 > 3.0  # past action_timeout_s in wall time, still active
    sim[0] = 103.0
    owner.observe_joint_state(make_state(sequence=seq + 1, received_at=103.0))
    assert owner.poll().reason == "action_timeout"


def test_frozen_simulation_holds_on_the_wall_clock_bound():
    sim, wall = [100.0], [5000.0]
    owner, action = sim_owner(sim, wall)
    owner.observe_joint_state(make_state(sequence=10, received_at=100.0))
    assert owner.submit(make_command(sequence=10)).accepted
    wall[0] += 1.9  # sim frozen: no new joint state, sim age stays 0
    assert owner.poll().reason == "active"
    wall[0] += 0.2  # > max_joint_state_age_s 0.5 x factor 4
    decision = owner.poll()
    assert decision.reason == "joint_state_stale_wall_clock" and owner.state == "hold"
    assert action.handles[0].cancel_calls == 1


def test_crawling_simulation_holds_on_the_wall_action_bound():
    sim, wall = [100.0], [5000.0]
    owner, _ = sim_owner(sim, wall)
    owner.observe_joint_state(make_state(sequence=10, received_at=100.0))
    assert owner.submit(make_command(sequence=10)).accepted
    seq = 10
    while wall[0] < 5000.0 + 11.9:  # RTF 0.05: joint states fresh, sim barely moves
        wall[0] += 0.1
        sim[0] += 0.005
        seq += 1
        owner.observe_joint_state(make_state(sequence=seq, received_at=sim[0]))
        assert owner.poll().reason == "active"
    wall[0] += 0.2  # action_timeout_s 3.0 x factor 4 = 12 s wall
    owner.observe_joint_state(make_state(sequence=seq + 1, received_at=sim[0]))
    assert owner.poll().reason == "action_wall_timeout" and owner.state == "hold"


def test_submit_rejects_a_state_that_is_fresh_in_sim_time_but_old_in_wall_time():
    sim, wall = [100.0], [5000.0]
    owner, action = sim_owner(sim, wall)
    owner.observe_joint_state(make_state(sequence=10, received_at=100.0))
    wall[0] += 2.5
    result = owner.submit(make_command(sequence=10))
    assert result.reason == "joint_state_stale_wall_clock" and action.commands == []


@pytest.mark.parametrize("factor", [0.5, 0.0, float("nan"), True])
def test_wall_clock_bound_factor_must_be_at_least_one(factor):
    with pytest.raises(ValueError, match="wall_clock_bound_factor"):
        make_config(wall_clock_bound_factor=factor)


def test_sim_clock_owner_requires_a_wall_clock_bound():
    with pytest.raises(ValueError, match="wall"):
        ArmCommandOwner(make_config(), FakeActionClient(), monotonic=lambda: 0.0,
                        wall_monotonic=lambda: 0.0, session_id=SESSION)
