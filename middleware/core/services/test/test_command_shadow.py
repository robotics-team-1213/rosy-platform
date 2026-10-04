"""D-400: shadow never changes cmd_vel; events leave only via announce_pending."""

import time
from types import SimpleNamespace

import pytest

from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, Twist
from core_features.safety import manager as safety_module
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits


class Events:
    def __init__(self):
        self.published = []

    def publish(self, type_, severity="info", source="", data=None):
        self.published.append((type_, severity, data or {}))


class Policy:
    revision = "rev-1"

    def __init__(self, mode):
        self.mode = mode

    def evaluate(self, linear, angular, now, allow_bounded_sweep=False):
        if self.mode == "raise":
            raise RuntimeError("boom")
        reason = "pickup" if self.mode == "stop" else "allow"
        snapshot = SimpleNamespace(calibration_revision="rev-1", observed_at=now - 0.05, expires_at=now + 0.3)
        return snapshot, SimpleNamespace(reason=reason, linear=0.0, angular=0.0)


def _rig(policy=None, events=None, mode=Mode.NAVIGATION):
    safety = SafetyManager(SpeedLimits(), BatteryPolicy(), events=events)
    safety._policy_clock = lambda: 1.0
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, safety, events=events)
    if policy is not None:
        safety.bind_shadow_control_policy(policy)
    modes.transition(mode)
    return command, safety, modes


def _drive(command):
    outputs = []
    for i, twist in enumerate([Twist(0.1, 0.0), Twist(0.2, 0.3), None, Twist(0.05, -0.2)]):
        now = 10.0 + 0.02 * i
        command.set_nav_twist(twist, now=now)
        outputs.append(command.select_output(now=now))
    return outputs


@pytest.mark.parametrize("mode", ["allow", "stop", "raise"])
def test_shadow_output_equals_off_output_and_never_latches(mode):
    off_command, _, _ = _rig()
    shadow_command, safety, modes = _rig(Policy(mode))

    assert _drive(shadow_command) == _drive(off_command)
    assert safety.estop is False
    assert modes.mode is Mode.NAVIGATION


def test_shadow_events_leave_only_through_announce_pending():
    events = Events()
    command, _, _ = _rig(Policy("stop"), events=events)

    command.set_nav_twist(Twist(0.1, 0.0), now=10.0)
    command.select_output(now=10.0)
    assert [e for e in events.published if e[0] == "safety.shadow_verdict"] == []

    command.announce_pending()
    shadow = [e for e in events.published if e[0] == "safety.shadow_verdict"]
    assert shadow == [("safety.shadow_verdict", "info",
                       {"verdict": "stop", "reason": "pickup", "source": "navigation", "t": 10.0,
                        "commanded": [0.1, 0.0], "output": [0.1, 0.0], "limited": [0.0, 0.0],
                        "suppressed": 0})]


def test_policy_off_is_announced_once_per_navigation_entry():
    events = Events()
    command, _, modes = _rig(events=events)

    for i in range(3):
        command.set_nav_twist(Twist(0.1, 0.0), now=10.0 + i * 0.02)
        command.select_output(now=10.0 + i * 0.02)
        command.announce_pending()
    modes.transition(Mode.IDLE)
    command.select_output(now=11.0)
    modes.transition(Mode.NAVIGATION)
    command.set_nav_twist(Twist(0.1, 0.0), now=11.1)
    command.select_output(now=11.1)
    command.announce_pending()

    offs = [e for e in events.published if e[0] == "safety.policy_off"]
    assert offs == [("safety.policy_off", "warning", {"source": "navigation"})] * 2


def test_policy_off_rearms_after_a_manual_detour():
    events = Events()
    command, _, modes = _rig(events=events)

    command.set_nav_twist(Twist(0.1, 0.0), now=10.0)
    command.select_output(now=10.0)
    command.announce_pending()
    modes.transition(Mode.MANUAL)
    command.select_output(now=10.5)
    command.announce_pending()
    modes.transition(Mode.NAVIGATION)
    command.set_nav_twist(Twist(0.1, 0.0), now=11.0)
    command.select_output(now=11.0)
    command.announce_pending()

    assert sum(1 for e in events.published if e[0] == "safety.policy_off") == 2


def test_zero_commands_are_not_judged():
    command, safety, _ = _rig(Policy("stop"))

    command.set_nav_twist(Twist(0.0, 0.0), now=10.0)
    command.select_output(now=10.0)

    assert sum(safety.shadow.snapshot()["counts"].values()) == 0


def test_shadow_and_enforce_mode_do_not_announce_policy_off():
    events = Events()
    command, _, _ = _rig(Policy("allow"), events=events)

    command.set_nav_twist(Twist(0.1, 0.0), now=10.0)
    command.select_output(now=10.0)
    command.announce_pending()

    assert [e for e in events.published if e[0] == "safety.policy_off"] == []


def test_no_events_bus_is_harmless():
    command, safety, _ = _rig(Policy("stop"), events=None)

    command.set_nav_twist(Twist(0.1, 0.0), now=10.0)
    command.select_output(now=10.0)
    command.announce_pending()

    assert sum(safety.shadow.snapshot()["counts"].values()) == 1


def _command(command, mode, linear, angular, now):
    if mode is Mode.MANUAL:
        command.teleop(linear, angular)
    elif mode is Mode.DOCKING:
        command.set_docking_twist(Twist(linear, angular), now=now)
    else:
        command.set_nav_twist(Twist(linear, angular), now=now)


@pytest.mark.parametrize("policy_kind", ["allow", "stop", "raise"])
@pytest.mark.parametrize("mode", [Mode.MANUAL, Mode.NAVIGATION, Mode.DOCKING])
def test_non_interference_across_modes_clipping_lapse_and_estop(mode, policy_kind):
    off, off_safety, off_modes = _rig(mode=mode)
    shadow, shadow_safety, shadow_modes = _rig(Policy(policy_kind), mode=mode)
    t0 = time.monotonic()
    # (command or None, clock offset, estop action)
    steps = [((0.1, 0.0), 0.0, None), ((1.0, 0.3), 0.02, None), (None, 1.0, None),
             ((0.1, 0.0), 1.02, "raise"), (None, 1.04, "release"), ((0.1, 0.1), 1.06, None)]
    for command, offset, estop in steps:
        outputs = []
        for rig, safety in ((off, off_safety), (shadow, shadow_safety)):
            if estop == "raise":
                safety.trigger_estop("test")
            elif estop == "release":
                safety.release("test")
            if command is not None:
                _command(rig, mode, *command, t0 + offset)
            outputs.append(rig.select_output(now=t0 + offset))
            rig.announce_pending()
        assert outputs[0] == outputs[1]
        assert off_safety.estop == shadow_safety.estop
        assert off_modes.mode is shadow_modes.mode
        assert off_safety.policy_reason == shadow_safety.policy_reason


def test_bus_that_raises_does_not_escape_or_skip_later_publishes():
    class Flaky(Events):
        def publish(self, type_, severity="info", source="", data=None):
            if type_ == "safety.policy_off":
                raise RuntimeError("sink down")
            super().publish(type_, severity, source, data)

    events = Flaky()
    command, safety, _ = _rig(events=events)
    command.set_nav_twist(Twist(0.1, 0.0), now=10.0)
    command.select_output(now=10.0)
    command.announce_pending()
    assert command.announce_errors == 1

    shadow_events = Flaky()
    command, _, _ = _rig(Policy("stop"), events=shadow_events)
    command._pending_unguarded = "navigation"
    command.set_nav_twist(Twist(0.1, 0.0), now=10.0)
    command.select_output(now=10.0)
    command.announce_pending()
    assert command.announce_errors == 1
    assert [e[0] for e in shadow_events.published] == ["safety.shadow_verdict"]


def test_failing_shadow_record_leaves_output_unchanged(monkeypatch):
    off, _, _ = _rig()
    command, safety, _ = _rig(Policy("stop"))

    def boom(_verdict):
        raise RuntimeError("recorder bug")

    monkeypatch.setattr(safety.shadow, "record", boom)
    assert _drive(command) == _drive(off)
    command.announce_pending()
    assert safety.shadow_record_errors >= 1


def test_policy_off_not_emitted_while_output_is_zero():
    events = Events()
    command, _, _ = _rig(events=events)
    command.set_nav_twist(Twist(0.0, 0.0), now=10.0)
    command.select_output(now=10.0)
    command.announce_pending()
    assert [e for e in events.published if e[0] == "safety.policy_off"] == []


def test_policy_off_is_emitted_for_docking():
    events = Events()
    command, _, _ = _rig(events=events, mode=Mode.DOCKING)
    command.set_docking_twist(Twist(0.05, 0.0), now=10.0)
    command.select_output(now=10.0)
    command.announce_pending()
    assert events.published == [("safety.policy_off", "warning", {"source": "docking"})]


def test_shadow_is_judged_only_in_announce_pending():
    command, safety, _ = _rig(Policy("allow"))
    command.set_nav_twist(Twist(0.1, 0.0), now=10.0)
    command.select_output(now=10.0)
    assert sum(safety.shadow.snapshot()["counts"].values()) == 0
    command.announce_pending()
    assert sum(safety.shadow.snapshot()["counts"].values()) == 1


def test_enforce_binding_reports_enforce_and_never_warns_policy_off():
    events = Events()
    safety = SafetyManager(SpeedLimits(), BatteryPolicy(), events=events)
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, safety, events=events)
    safety._policy_clock = lambda: 1.0

    def evaluator(request):
        return safety_module.SafetyDecision(
            request.command_id, request.source, "rev", request.now - 0.05, request.now + 0.3,
            1.0, 1.0, "limit", "allow")

    safety.bind_policy(evaluator, "rev")
    assert safety.policy_mode == "enforce"
    modes.transition(Mode.NAVIGATION)
    command.set_nav_twist(Twist(0.1, 0.0), now=10.0)
    command.select_output(now=10.0)
    command.announce_pending()
    assert [e for e in events.published if e[0] == "safety.policy_off"] == []
