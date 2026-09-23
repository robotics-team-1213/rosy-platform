"""The SAF-005 chain: what one battery reading sets in motion.

Nine effects across five services, and the *order* is the policy — publish state
before acting on it, stop the motors before the shutdown grace period, offer the
dock before falling back. This lived inline in `ros_bridge.py`, which host pytest
cannot import, so none of it had an assertion: not the NaN guard, not the DEEP
e-stop, not the escalation when a return-home cannot be dispatched.

The call log is the point. Asserting each effect separately would pass on a
reordered chain, and a reordered chain is how a robot ends up shutting down
before it stops moving.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.bridge.battery_policy import apply_voltage
from core_features.power.battery import BatteryLevel


class Recorder:
    """Every manager call, in order, as `("service.method", args)`."""

    def __init__(self):
        self.calls: list[tuple] = []

    def names(self) -> list[str]:
        return [call[0] for call in self.calls]


def build(recorder, *, percent=55.0, level=BatteryLevel.OK, action=None,
          home_raises=False, status="DISCHARGING", dock_state=None):
    log = recorder.calls

    battery = SimpleNamespace(
        percent=percent, level=level,
        on_voltage=lambda v: log.append(("battery.on_voltage", v)),
        status=lambda: status,
    )
    state = SimpleNamespace(
        set_battery=lambda p, v: log.append(("state.set_battery", p, v)),
        set_battery_status=lambda s: log.append(("state.set_battery_status", s)),
    )
    power = SimpleNamespace(
        on_battery_alert=lambda lv: log.append(("power.on_battery_alert", lv)))
    safety = SimpleNamespace(
        trigger_estop=lambda reason: log.append(("safety.trigger_estop", reason)),
        on_battery_percent=lambda p: (log.append(("safety.on_battery_percent", p)) or action),
    )
    docking = SimpleNamespace(
        on_battery_level=lambda lv: log.append(("docking.on_battery_level", lv)),
        state=dock_state)

    def home(source):
        log.append(("nav.home", source))
        if home_raises:
            raise RuntimeError("no home waypoint")

    return SimpleNamespace(battery=battery, state=state, power=power,
                           safety=safety, docking=docking,
                           nav=SimpleNamespace(home=home))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_sample_never_reaches_the_filter(bad):
    """A NaN from a disconnected ADC would poison every later reading."""
    rec = Recorder()

    apply_voltage(build(rec), bad)

    assert rec.calls == []


def test_the_raw_sample_goes_through_the_filter_not_around_it():
    """One voltage sag as the motors start used to fire the critical policy.
    The filter is the fix — the chain must feed it and read back from it."""
    rec = Recorder()

    apply_voltage(build(rec), 7.4)

    assert rec.calls[0] == ("battery.on_voltage", 7.4)


def test_no_percent_yet_means_early_not_low():
    """`percent is None` is an unconverged curve, not an empty battery."""
    rec = Recorder()

    apply_voltage(build(rec, percent=None), 7.4)

    assert rec.names() == ["battery.on_voltage"]


def test_the_ordinary_chain_runs_in_the_documented_order():
    rec = Recorder()

    apply_voltage(build(rec), 7.4)

    assert rec.names() == [
        "battery.on_voltage",
        "state.set_battery",
        "state.set_battery_status",
        "power.on_battery_alert",
        "docking.on_battery_level",
        "safety.on_battery_percent",
    ]


def test_state_is_published_before_anything_acts_on_the_reading():
    """The dashboard must show the number the robot is about to act on."""
    rec = Recorder()

    apply_voltage(build(rec, level=BatteryLevel.DEEP, action="STOP"), 6.2)

    names = rec.names()
    assert names.index("state.set_battery") < names.index("safety.trigger_estop")


def test_deep_stops_the_robot_before_the_dock_offer_or_the_saf005_action():
    """Motors are the largest draw. Dropping the load lets the voltage recover
    toward its resting curve, which makes the shutdown decision better informed."""
    rec = Recorder()

    apply_voltage(build(rec, level=BatteryLevel.DEEP, action="STOP"), 6.2)

    names = rec.names()
    assert ("safety.trigger_estop", "battery_deep") in rec.calls
    assert names.index("safety.trigger_estop") < names.index("docking.on_battery_level")
    assert names.index("safety.trigger_estop") < names.index("safety.on_battery_percent")


def test_a_non_deep_level_does_not_estop():
    rec = Recorder()

    apply_voltage(build(rec, level=BatteryLevel.CRITICAL), 6.8)

    assert "safety.trigger_estop" not in rec.names()


def test_the_dock_is_offered_before_the_saf005_fallback():
    """DNC-006. No dock or no support and this does nothing — the fallback stands."""
    rec = Recorder()

    apply_voltage(build(rec, level=BatteryLevel.WARNING), 7.0)

    names = rec.names()
    assert names.index("docking.on_battery_level") < names.index("safety.on_battery_percent")
    assert ("docking.on_battery_level", BatteryLevel.WARNING) in rec.calls


def test_return_home_dispatches_a_goal():
    rec = Recorder()

    apply_voltage(build(rec, action="RETURN_HOME"), 7.0)

    assert ("nav.home", "battery_policy") in rec.calls
    assert "safety.trigger_estop" not in rec.names()


def test_a_dock_run_is_the_return_home_so_nav2_is_left_to_it():
    """The dock offer came first (DNC-006). A Nav2 home goal would preempt the
    staging goal — and navigation refuses goals while docking, which would
    escalate to e-stop and kill the very return that is under way."""
    from core_common.protocol.schemas import DockState
    rec = Recorder()

    apply_voltage(build(rec, action="RETURN_HOME", dock_state=DockState.DOCKING), 7.0)

    assert "nav.home" not in rec.names()
    assert "safety.trigger_estop" not in rec.names()


def test_a_return_home_that_cannot_be_dispatched_escalates_to_estop():
    """Refusing to move is safe. Believing you are driving home when you are not
    is not — so a failed dispatch must not leave the robot rolling."""
    rec = Recorder()

    apply_voltage(build(rec, action="RETURN_HOME", home_raises=True), 7.0)

    assert rec.calls[-1] == ("safety.trigger_estop", "battery_policy")


def test_stop_estops_without_trying_to_drive():
    rec = Recorder()

    apply_voltage(build(rec, action="STOP"), 6.5)

    assert "nav.home" not in rec.names()
    assert rec.calls[-1] == ("safety.trigger_estop", "battery_policy")


def test_no_action_leaves_the_robot_alone():
    rec = Recorder()

    apply_voltage(build(rec, action=None), 7.4)

    assert "safety.trigger_estop" not in rec.names()
    assert "nav.home" not in rec.names()


def test_the_filtered_percent_is_what_the_policy_sees_not_the_raw_volts():
    rec = Recorder()

    apply_voltage(build(rec, percent=18.5), 7.1)

    assert ("state.set_battery", 18.5, 7.1) in rec.calls
    assert ("safety.on_battery_percent", 18.5) in rec.calls
