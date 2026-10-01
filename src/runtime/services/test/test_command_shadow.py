"""D-400: shadow never changes cmd_vel; events leave only via announce_pending."""

from types import SimpleNamespace

import pytest

from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, Twist
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


def _rig(policy=None, events=None):
    safety = SafetyManager(SpeedLimits(), BatteryPolicy(), events=events)
    safety._policy_clock = lambda: 1.0
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, safety, events=events)
    if policy is not None:
        safety.bind_shadow_control_policy(policy)
    modes.transition(Mode.NAVIGATION)
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
