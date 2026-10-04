from dataclasses import replace

import pytest

from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, Twist
from core_features.safety.manager import SafetyManager, SpeedLimits, BatteryPolicy, SafetyDecision


def decision(request, **changes):
    value = SafetyDecision(request.command_id, request.source, request.calibration_revision,
                           request.now, request.now + .1, .04, .06, 'limit')
    return replace(value, **changes)


def setup_safety(provider=None):
    safety = SafetyManager(SpeedLimits(), BatteryPolicy(), policy_required=True)
    if provider is not None:
        safety.bind_policy(provider, 'calibration-1')
    modes = ModeMachine()
    modes.transition(Mode.NAVIGATION)
    command = CommandManager(SourceRegistry(), modes, safety)
    command.set_nav_twist(Twist(.1, .2), now=10.)
    return command, safety, modes


def test_selected_command_is_limited_by_matching_current_policy():
    command, safety, modes = setup_safety(decision)
    assert command.select_output(now=10.01) == Twist(.04, .06)
    assert not safety.estop


@pytest.mark.parametrize('changes', [
    {'command_id': -1}, {'command_id': True}, {'source': 'manual'}, {'calibration_revision': 'old'},
    {'expires_at': 9.}, {'observed_at': 11.}, {'linear_limit': float('nan')},
    {'angular_limit': -.1}, {'disposition': 'unknown'}, {'disposition': 'stop'},
])
def test_invalid_or_stop_decision_latches_stop_and_discards_candidate(changes):
    command, safety, modes = setup_safety(lambda request: decision(request, **changes))
    assert command.select_output(now=10.01) == Twist()
    assert safety.estop
    assert modes.mode is Mode.EMERGENCY
    modes.release_emergency()
    safety.release('maintainer')
    modes.transition(Mode.NAVIGATION)
    safety.bind_policy(decision, 'calibration-1')
    assert command.select_output(now=10.02) == Twist()


def test_required_missing_policy_cannot_authorize_motion():
    command, safety, modes = setup_safety()
    assert command.select_output(now=10.01) == Twist()
    assert safety.estop


def test_policy_cannot_increase_profile_clipped_velocity():
    command, safety, modes = setup_safety(lambda request: decision(request, linear_limit=10., angular_limit=10.))
    assert command.select_output(now=10.01) == Twist(.1, .2)


def test_policy_exception_stops_output():
    def broken(request):
        raise RuntimeError('unavailable')
    command, safety, modes = setup_safety(broken)
    assert command.select_output(now=10.01) == Twist()
    assert safety.estop


def test_policy_over_budget_cannot_authorize_delayed_output():
    command, safety, modes = setup_safety(decision)
    ticks = iter([1., 1.02])
    safety._policy_clock = lambda: next(ticks)
    assert command.select_output(now=10.01) == Twist()
    assert safety.estop


def test_new_input_during_evaluation_discards_old_result():
    first = True
    def superseded(request):
        nonlocal first
        if first:
            first = False
            command.set_nav_twist(Twist(.02, .03), now=10.02)
        return decision(request)
    command, safety, modes = setup_safety(superseded)
    assert command.select_output(now=10.01) == Twist()
    assert not safety.estop
    assert command.select_output(now=10.03) == Twist(.02, .03)


def test_manual_path_uses_same_policy_and_zero_limit_allows_replanning():
    command, safety, modes = setup_safety(lambda request: decision(request, linear_limit=0., angular_limit=0.))
    modes.transition(Mode.MANUAL)
    command.teleop(.05, .1)
    assert command.select_output() == Twist()
    assert not safety.estop


def test_estop_during_evaluation_cannot_leak_prior_candidate():
    command, safety, modes = setup_safety()
    def stop(request):
        safety.trigger_estop('external')
        return decision(request)
    safety.bind_policy(stop, 'calibration-1')
    command.set_nav_twist(Twist(.1, .2), now=10.)
    assert command.select_output(now=10.01) == Twist()
    assert safety.estop


def test_e_stop_does_not_buffer_navigation_commands_for_release():
    command, safety, modes = setup_safety(decision)
    safety.trigger_estop('external')
    command.set_nav_twist(Twist(.1, .2), now=10.02)
    safety.release('maintainer')
    assert command.select_output(now=10.03) == Twist()


def test_estop_alone_discards_candidate_even_without_intervening_output_tick():
    command, safety, modes = setup_safety(decision)
    safety.trigger_estop('external')
    safety.release('maintainer')
    assert command.select_output(now=10.03) == Twist()
