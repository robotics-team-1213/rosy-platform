"""D-785: SUCCEEDED is completed only when the measured joints reached the commanded final positions."""
import pytest

from omx_adapter.command_owner import JointStateSnapshot
from test_omx_command_owner import make_command, make_config, make_state, owner_at

CHECKED = {"max_final_state_errors": {"joint_1": 0.02, "joint_2": None}}


def _finish(owner, action, clock, final_positions):
    owner.observe_joint_state(make_state(sequence=10))
    assert owner.submit(make_command(sequence=10)).accepted  # targets joint_1 0.3, joint_2 0.2
    clock[0] = 100.5
    owner.observe_joint_state(JointStateSnapshot(positions=final_positions, sequence=11, received_at=100.5,
                                                 calibration_revision="cal-7"))
    action.handles[0].finished = action.handles[0].success = True
    return owner.poll()


def test_unset_policy_keeps_trusting_succeeded():
    clock = [100.0]
    owner, action = owner_at(clock)
    decision = _finish(owner, action, clock, {"joint_1": 0.1, "joint_2": -0.1})
    assert decision.accepted and decision.reason == "completed"


def test_succeeded_without_motion_holds_goal_not_reached():
    clock = [100.0]
    owner, action = owner_at(clock, make_config(**CHECKED))
    decision = _finish(owner, action, clock, {"joint_1": 0.1, "joint_2": -0.1})
    assert not decision.accepted and decision.reason == "goal_not_reached"
    assert owner.state == "hold"


def test_reached_checked_joint_completes_and_unchecked_joint_may_stall():
    clock = [100.0]
    owner, action = owner_at(clock, make_config(**CHECKED))
    decision = _finish(owner, action, clock, {"joint_1": 0.29, "joint_2": -0.1})
    assert decision.accepted and decision.reason == "completed" and owner.state == "ready"


@pytest.mark.parametrize("errors, message", [
    ({"joint_1": 0.02}, "exactly match"),
    ({"joint_1": 0.0, "joint_2": None}, "positive"),
    ({"joint_1": float("nan"), "joint_2": None}, "positive"),
    ({"joint_1": True, "joint_2": None}, "positive"),
    ({"joint_1": None, "joint_2": None}, "at least one"),
])
def test_policy_is_validated(errors, message):
    with pytest.raises(ValueError, match=message):
        make_config(max_final_state_errors=errors)


@pytest.mark.parametrize("errors", [5, "x", {"joint_1": -0.1, "joint_2": None},
                                    {"joint_1": 0.02, "joint_2": None, "joint_9": 0.1}])
def test_malformed_policy_is_a_value_error(errors):
    with pytest.raises(ValueError):
        make_config(max_final_state_errors=errors)


def test_integer_error_is_accepted_and_disabled_config_ignores_the_policy():
    assert make_config(max_final_state_errors={"joint_1": 1, "joint_2": None}).max_final_state_errors["joint_1"] == 1.0
    make_config(enabled=False, max_final_state_errors=5)


def test_failed_action_still_holds_action_failed_with_the_policy_set():
    clock = [100.0]
    owner, action = owner_at(clock, make_config(**CHECKED))
    owner.observe_joint_state(make_state(sequence=10))
    assert owner.submit(make_command(sequence=10)).accepted
    action.handles[0].finished, action.handles[0].success = True, False
    assert owner.poll().reason == "action_failed"


def test_goal_not_reached_hold_is_recoverable_by_the_operator_path():
    clock = [100.0]
    owner, action = owner_at(clock, make_config(**CHECKED))
    _finish(owner, action, clock, {"joint_1": 0.1, "joint_2": -0.1})
    state = owner.recovery_state()
    assert state["state"] == "hold" and state["reason"] == "goal_not_reached"
