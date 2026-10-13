"""D-628: mode-bound candidates and curvature after the line body judgement."""

import math
from types import SimpleNamespace

import pytest

from core.bridge.traffic_gate import apply_line_candidate
from core.drive.line_follow import bind_motion_envelope
from core_events.events.bus import EventBus
from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, Twist
from core_features.line_follow import LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation
from core_features.safety.manager import BatteryPolicy, PersonAdvisory, SafetyDecision, SafetyManager, SpeedLimits
from core_features.traffic_policy import TrafficPolicyManager


def _command(mode=Mode.NAVIGATION):
    modes = ModeMachine()
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    command = CommandManager(SourceRegistry(), modes, safety)
    assert modes.transition(mode)[0]
    return command, modes, safety


@pytest.mark.parametrize("linear,angular,max_l,max_a,expected", [
    (.08, .4, .02, .8, (.02, .1)),
    (.08, .4, .1, .1, (.02, .1)),
    (-.08, -.4, .02, .8, (-.02, -.1)),
    (0., .4, .02, .1, (0., .1)),
    (.08, .4, 0., .8, (0., 0.)),
])
def test_static_line_caps_preserve_the_candidate_curve(linear, angular, max_l, max_a, expected):
    command, _, safety = _command()
    safety.limits.max_linear = max_l
    safety.limits.max_angular = max_a
    assert command.clip_line_candidate(linear, angular) == pytest.approx(expected)


@pytest.mark.parametrize("mode,setter", [(Mode.NAVIGATION, "set_nav_twist"),
                                        (Mode.DOCKING, "set_docking_twist")])
def test_mode_round_trip_requires_a_new_candidate(mode, setter):
    command, modes, _ = _command(mode)
    getattr(command, setter)(Twist(.05, .1), now=10.)
    assert command.select_output(now=10.01) == Twist(.05, .1)
    assert modes.transition(Mode.IDLE)[0]
    assert modes.transition(mode)[0]
    assert command.select_output(now=10.02) == Twist()


@pytest.mark.parametrize("mode,setter", [(Mode.NAVIGATION, "set_nav_twist"),
                                        (Mode.DOCKING, "set_docking_twist")])
def test_manual_period_does_not_queue_autonomous_motion(mode, setter):
    command, modes, _ = _command(Mode.MANUAL)
    getattr(command, setter)(Twist(.05, .1), now=10.)
    assert modes.transition(Mode.IDLE)[0]
    assert modes.transition(mode)[0]
    assert command.select_output(now=10.02) == Twist()


def test_mode_change_during_input_validation_cannot_commit_old_candidate(monkeypatch):
    import core_features.command.manager as module

    command, modes, _ = _command()
    finite = module.finite_velocity

    def interrupted(linear, angular):
        assert modes.transition(Mode.IDLE)[0]
        assert modes.transition(Mode.NAVIGATION)[0]
        return finite(linear, angular)

    monkeypatch.setattr(module, "finite_velocity", interrupted)
    command.set_nav_twist(Twist(.05, .1), now=10.)
    assert command.select_output(now=10.02) == Twist()


def _line_rig():
    command, modes, safety = _command()
    events = EventBus("rosy_01")
    line = LineFollowManager(events, config=LineFollowConfig(cruise_speed=.1), clock=lambda: 10.)
    traffic = TrafficPolicyManager(events)
    bind_motion_envelope(line, safety=safety, traffic_policy=traffic)
    line.set_mode(LineFollowMode.CAMERA_LINE)
    line.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=10., visible=True,
                                 error=.5, confidence=1.), received_at=10., source_now=10.)
    decision = line.tick(10.)
    assert decision.linear > 0 and decision.angular != 0
    assert apply_line_candidate(line, traffic, command, decision, 10.)
    return command, modes, safety


@pytest.mark.parametrize("cap", [.025, 0.])
def test_session_cap_after_line_submission_preserves_curve_or_stops(cap):
    command, _, safety = _line_rig()
    before = command.select_output(now=10.)
    safety.set_session_speed(cap)
    after = command.select_output(now=10.)
    if cap == 0:
        assert after == Twist()
    else:
        assert 0 < after.linear <= cap
        assert after.angular / after.linear == pytest.approx(before.angular / before.linear)


def test_person_cap_after_line_submission_preserves_curve(monkeypatch):
    monkeypatch.setattr("core_features.safety.manager.time.monotonic", lambda: 10.)
    command, _, safety = _line_rig()
    before = command.select_output(now=10.)
    safety.person_linear_cap = .02
    safety.set_person_advisory(PersonAdvisory(True, 1., 10.))
    after = command.select_output(now=10.)
    assert after.linear <= .02
    assert after.angular / after.linear == pytest.approx(before.angular / before.linear)


def test_policy_cap_after_line_submission_preserves_curve():
    command, _, safety = _line_rig()
    before = command.select_output(now=10.)
    safety._policy_clock = lambda: 10.
    safety.bind_policy(lambda r: SafetyDecision(r.command_id, r.source, r.calibration_revision,
                                               10., 10.2, .02, .8, "limit"), "rev")
    command.set_nav_twist(before, now=10., preserve_curvature=True)
    after = command.select_output(now=10.)
    assert 0 < after.linear <= .02
    assert after.angular / after.linear == pytest.approx(before.angular / before.linear)


@pytest.mark.parametrize("linear,angular", [(-.1, -.4), (.1, -.4), (0., -.4), (0., 0.), (math.nan, .2)])
def test_flagged_line_candidate_handles_reverse_pivot_zero_and_invalid(linear, angular):
    command, _, safety = _command()
    command.set_nav_twist(Twist(linear, angular), now=10., preserve_curvature=True)
    safety.set_session_speed(.02)
    out = command.select_output(now=10.)
    if not math.isfinite(linear) or (linear, angular) == (0., 0.):
        assert out == Twist()
    elif linear == 0:
        assert out == Twist(0., angular)
    else:
        assert (out.linear, out.angular) == pytest.approx((linear * .2, angular * .2))


def test_other_navigation_and_manual_keep_independent_clip_semantics():
    command, modes, safety = _command()
    safety.set_session_speed(.02)
    command.set_nav_twist(Twist(.1, .4), now=10.)
    assert command.select_output(now=10.) == Twist(.02, .4)
    assert modes.transition(Mode.MANUAL)[0]
    assert command.teleop(.1, .4)[0]
    assert command.select_output() == Twist(.02, .4)


def test_line_rejects_actuation_that_changes_the_checked_curve(monkeypatch):
    command, _, safety = _line_rig()
    safety._policy_clock = lambda: 10.
    safety.bind_policy(lambda r: SafetyDecision(r.command_id, r.source, r.calibration_revision,
                                               10., 10.2, .01, .1, "limit"), "rev")
    command.set_nav_twist(Twist(.04, .2), now=10., preserve_curvature=True)
    safety._actuation_required = True
    safety._actuation = SimpleNamespace(revision="rev", expires_at=10.2,
                                        scan_received_at=10., scan_source_at=10.,
                                        prepare=lambda *args: SimpleNamespace(
                                            motor_linear=.01, linear=.01, angular=.08))
    monkeypatch.setattr(safety, "_simulation_actuation_enabled", lambda: True)
    assert command.select_output(now=10.) == Twist()
