"""D-442 U3: cross-owner preemption latches HOLD; recovery never sends motion."""

import pytest

from test_omx_command_owner import make_command, make_config, make_state, owner_at


def test_arbiter_preempts_a_different_owner_without_admitting_manual_motion():
    owner, action = owner_at([100.0])
    owner.observe_joint_state(make_state())
    assert owner.submit(make_command(owner="rule_based")).accepted
    decision = owner.preempt("manual_priority")
    assert decision.state == "hold"
    assert decision.command_id == "cmd-1"
    assert decision.reason == "preempt:manual_priority"
    assert decision.cancel_outcome == "call_returned"
    assert action.handles[0].cancel_calls == 1
    for source in ("leader_teleop", "moveit", "rule_based"):
        assert not owner.submit(make_command(command_id=f"blocked-{source}", owner=source)).accepted
    assert len(action.commands) == 1


def test_preempt_cancel_failure_preserves_hold_and_never_retries_the_goal():
    owner, action = owner_at([100.0])
    owner.observe_joint_state(make_state())
    owner.submit(make_command())
    action.handles[0].cancel_error = RuntimeError("transport unavailable")
    decision = owner.preempt("manual_priority")
    assert decision.state == "hold" and decision.cancel_outcome == "call_failed"
    assert not owner.submit(make_command(command_id="next")).accepted
    assert len(action.commands) == 1


def test_repeated_preemption_does_not_cancel_again_or_refresh_hold_sequence():
    owner, action = owner_at([100.0])
    owner.observe_joint_state(make_state())
    owner.submit(make_command())
    owner.preempt("manual_priority")
    owner.observe_joint_state(make_state(sequence=11))
    assert owner.preempt("repeated").state == "hold"
    assert action.handles[0].cancel_calls == 1
    assert owner.recover(operator_confirmed=True, observed_sequence=11).accepted
    assert len(action.commands) == 1


def test_recovery_requires_confirmation_and_fresh_post_preempt_readback():
    owner, action = owner_at([100.0])
    owner.observe_joint_state(make_state())
    owner.submit(make_command())
    owner.preempt("manual_priority")
    assert not owner.recover(operator_confirmed=True, observed_sequence=10).accepted
    owner.observe_joint_state(make_state(sequence=11))
    assert not owner.recover(operator_confirmed=False, observed_sequence=11).accepted
    assert owner.recover(operator_confirmed=True, observed_sequence=11).accepted
    assert owner.state == "ready"
    assert len(action.commands) == 1


@pytest.mark.parametrize("reason", ["", None, 1])
def test_invalid_preempt_reason_leaves_active_goal_untouched(reason):
    owner, action = owner_at([100.0])
    owner.observe_joint_state(make_state())
    owner.submit(make_command())
    with pytest.raises(ValueError):
        owner.preempt(reason)
    assert owner.state == "active" and action.handles[0].cancel_calls == 0


def test_disabled_owner_stays_disabled_on_preempt():
    owner, action = owner_at([100.0], make_config(enabled=False))
    decision = owner.preempt("manual_priority")
    assert decision.state == "disabled" and not decision.accepted
    assert action.commands == []
