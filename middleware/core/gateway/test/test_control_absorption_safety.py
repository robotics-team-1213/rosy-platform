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
    ticks = iter([1., 1.03])
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


# D-400 4: in enforce a sensor gap younger than stale_hold_s is HOLD, not a latch.

def setup_hold(provider=None, hold=2., clock=None):
    command, safety, modes = setup_safety()
    clock = [100.] if clock is None else clock
    safety._policy_clock = lambda: clock[0]
    if provider is None:
        safety._policy_hold_s = hold   # no evaluator yet: the state before the adapter has bound
    else:
        safety.bind_policy(provider, 'calibration-1', hold)
    return command, safety, modes, clock


def ask(command, now, twist=Twist(.1, .2)):
    command.set_nav_twist(twist, now=now)
    return command.select_output(now=now + .01)


def late(clock, delay):
    def provider(request):
        clock[0] += delay[0]
        return decision(request)
    return provider


def test_late_answer_holds_without_latch_and_a_valid_answer_resumes():
    delay, clock = [.03], [100.]
    command, safety, modes, _ = setup_hold(late(clock, delay), clock=clock)
    assert ask(command, 10.) == Twist()
    assert not safety.estop and modes.mode is Mode.NAVIGATION
    assert safety.policy_hold and safety.policy_reason == 'policy_invalid'
    assert (safety.policy_holds, safety.policy_hold_reason) == (1, 'policy_invalid')
    delay[0] = 0.
    assert ask(command, 10.1) == Twist(.04, .06)
    assert not safety.policy_hold and not safety.estop and safety.policy_reason == ''


def test_late_answers_past_the_hold_latch_as_before():
    delay, clock = [.03], [100.]
    command, safety, modes, _ = setup_hold(late(clock, delay), clock=clock)
    assert ask(command, 10.) == Twist() and not safety.estop
    clock[0] = 101.9
    assert ask(command, 11.9) == Twist() and not safety.estop
    clock[0] = 102.
    assert ask(command, 12.) == Twist()
    assert safety.estop and safety.estop_source == 'control:policy_invalid'
    assert modes.mode is Mode.EMERGENCY and not safety.policy_hold


def test_unbound_evaluator_holds_then_latches():
    command, safety, modes, clock = setup_hold()
    assert ask(command, 10.) == Twist()
    assert not safety.estop and modes.mode is Mode.NAVIGATION
    assert safety.policy_hold and safety.policy_reason == 'policy_unavailable'
    clock[0] = 102.
    assert ask(command, 12.) == Twist()
    assert safety.estop and safety.estop_source == 'control:policy_unavailable'
    assert modes.mode is Mode.EMERGENCY


def test_zero_command_does_not_end_a_gap_and_a_valid_answer_does():
    delay, clock = [.03], [100.]
    command, safety, modes, _ = setup_hold(late(clock, delay), clock=clock)
    assert ask(command, 10.) == Twist() and not safety.estop
    delay[0], clock[0] = 0., 101.
    assert ask(command, 11.) == Twist(.04, .06)          # ends the first gap
    delay[0], clock[0] = .03, 103.
    assert ask(command, 13.) == Twist() and not safety.estop
    assert safety.policy_holds == 2
    assert ask(command, 13.1, Twist()) == Twist()        # a zero command never asks the policy
    clock[0] = 105.5
    assert ask(command, 15.5) == Twist()
    assert safety.estop and safety.estop_source == 'control:policy_invalid'


def test_backward_policy_clock_is_not_held():
    delay, clock = [.03], [100.]
    command, safety, modes, _ = setup_hold(late(clock, delay), clock=clock)
    assert ask(command, 10.) == Twist() and not safety.estop
    clock[0] = 99.
    assert ask(command, 10.1) == Twist()
    assert safety.estop


def boom(request):
    raise RuntimeError('unavailable')


@pytest.mark.parametrize('provider, source', [
    (lambda request: decision(request, disposition='stop', reason='pickup'), 'control:pickup'),
    (lambda request: decision(request, command_id=-1), 'control:policy_invalid'),
    (lambda request: decision(request, source='manual'), 'control:policy_invalid'),
    (lambda request: decision(request, calibration_revision='old'), 'control:policy_invalid'),
    (lambda request: decision(request, linear_limit=float('nan')), 'control:policy_invalid'),
    (lambda request: decision(request, expires_at=request.now + 1.), 'control:policy_invalid'),
    (lambda request: decision(request, disposition='unknown'), 'control:policy_invalid'),
    (lambda request: None, 'control:policy_invalid'),
    (boom, 'control:policy_failed'),
])
def test_stop_malformed_and_broken_policy_latch_at_once_even_with_a_hold(provider, source):
    command, safety, modes, clock = setup_hold(provider)
    assert ask(command, 10.) == Twist()
    assert safety.estop and safety.estop_source == source
    assert modes.mode is Mode.EMERGENCY and not safety.policy_hold and safety.policy_holds == 0


def test_late_stop_latches_at_once_even_with_a_hold():
    clock = [100.]
    def provider(request):
        clock[0] += .03
        return decision(request, disposition='stop', reason='pickup')
    command, safety, modes, _ = setup_hold(provider, clock=clock)
    assert ask(command, 10.) == Twist()
    assert safety.estop and safety.estop_source == 'control:policy_invalid'
    assert modes.mode is Mode.EMERGENCY and safety.policy_holds == 0


@pytest.mark.parametrize('hold', [-1., 5.1, float('nan'), True, '2'])
def test_stale_hold_must_be_within_the_adr_range(hold):
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    with pytest.raises(ValueError, match='stale_hold_s'):
        safety.bind_policy(decision, 'calibration-1', hold)
