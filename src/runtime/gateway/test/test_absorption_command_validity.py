"""The final CORE authority must not turn invalid worker output into motion."""
import math

import pytest

from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, Twist
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits


def manager(mode):
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    modes = ModeMachine()
    assert modes.transition(mode)[0]
    return CommandManager(SourceRegistry(), modes, safety), safety


@pytest.mark.parametrize('invalid', [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize('axis', ['linear', 'angular'])
def test_invalid_worker_velocity_stops_both_axes(invalid, axis):
    command, safety = manager(Mode.NAVIGATION)
    value = Twist(.05, .1)
    setattr(value, axis, invalid)
    command.set_nav_twist(value, now=10.)
    assert command.select_output(now=10.1) == Twist()


@pytest.mark.parametrize('invalid', [math.nan, math.inf, -math.inf])
def test_invalid_manual_request_revokes_previous_motion(invalid):
    command, safety = manager(Mode.MANUAL)
    assert command.teleop(.05, .1)[0]
    assert command.teleop(invalid, .1) == (False, 'VALIDATION_ERROR')
    assert command.select_output() == Twist()


@pytest.mark.parametrize('limit', [math.nan, math.inf, -.1])
def test_invalid_session_limit_is_rejected_without_replacing_prior_limit(limit):
    command, safety = manager(Mode.MANUAL)
    safety.set_session_speed(.03)
    with pytest.raises(ValueError):
        safety.set_session_speed(limit)
    assert safety.session_linear == .03


@pytest.mark.parametrize('invalid', [math.nan, math.inf, -.1])
def test_invalid_profile_limit_cannot_generate_motion(invalid):
    command, safety = manager(Mode.NAVIGATION)
    safety.limits.max_linear = invalid
    command.set_nav_twist(Twist(.05, .1), now=10.)
    assert command.select_output(now=10.1) == Twist()


def test_fresh_valid_worker_command_can_recover_after_invalid_input():
    command, safety = manager(Mode.NAVIGATION)
    command.set_nav_twist(Twist(.05, .1), now=10.)
    command.set_nav_twist(Twist(math.nan, .1), now=10.1)
    assert command.select_output(now=10.2) == Twist()
    command.set_nav_twist(Twist(.03, .05), now=10.3)
    assert command.select_output(now=10.4) == Twist(.03, .05)
