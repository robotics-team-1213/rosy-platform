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

from core.bridge import battery_policy
from core.bridge.battery_policy import apply_voltage
from core_common.protocol.schemas import BatteryStatus
from core_common.protocol.wire_status import NavigationState
from core_features.command.arbitration import Mode, ModeMachine
from core_features.power.battery import BatteryLevel
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits
from core_features.state.manager import StateManager


class Recorder:
    """Every manager call, in order, as `("service.method", args)`."""

    def __init__(self):
        self.calls: list[tuple] = []

    def names(self) -> list[str]:
        return [call[0] for call in self.calls]


def build(recorder, *, percent=55.0, level=BatteryLevel.OK, action=None,
          home_raises=False, status="DISCHARGING", dock_state=None,
          docking_active=False, charge_return=None):
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
        battery_policy=SimpleNamespace(warning_percent=20.0, critical_percent=10.0), battery_return_suppressed=False,
        release_recovered_battery_stop=lambda: False, estop=False, estop_source="",
    )
    docking = SimpleNamespace(
        on_battery_level=lambda lv: log.append(("docking.on_battery_level", lv)),
        state=dock_state)

    def home(source):
        log.append(("nav.home", source))
        if home_raises:
            raise RuntimeError("no home waypoint")

    # `localization=None`: a robot without D-395 (the policy reads the field directly).
    # `charge_return`: a mutable [lease_live, navigating] pair, or None (no D-1029 lease).
    cr = charge_return or [False, False]
    return SimpleNamespace(battery=battery, state=state, power=power,
                           safety=safety, docking=docking, localization=None,
                           trip_lease=SimpleNamespace(charge_return_active=lambda: cr[0], critical_deferred=False, critical_inactive_since=None),
                           events=SimpleNamespace(publish=lambda t, **kw: log.append(("events." + t, kw["data"]["percent"]))),
                           nav=_Nav(home, cr, docking_active))


class _Nav:
    """``nav_state`` follows ``cr[1]`` live, as the manager's property does."""

    def __init__(self, home, cr, docking_active):
        self.home, self._cr = home, cr
        self.docking_active_provider = lambda: docking_active

    @property
    def nav_state(self):
        return NavigationState.NAVIGATING if self._cr[1] else NavigationState.ARRIVED


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

    apply_voltage(build(rec, action="RETURN_HOME", dock_state=DockState.DOCKING,
                        docking_active=True), 7.0)

    assert "nav.home" not in rec.names()
    assert "safety.trigger_estop" not in rec.names()


@pytest.mark.parametrize("dock_state", ["UNDOCKING", "UNDOCKED"])
def test_any_docking_hold_on_the_robot_skips_the_home_goal(dock_state):
    """N4: navigation refuses goals whenever docking holds the robot — an
    undock under way, or the DOCKING mode taken before the state moves. Only
    checking `state is DOCKING` sent those to nav.home, which refused, and the
    refusal escalated to e-stop."""
    from core_common.protocol.schemas import DockState
    rec = Recorder()

    apply_voltage(build(rec, action="RETURN_HOME", dock_state=DockState(dock_state),
                        docking_active=True), 7.0)

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


# --- D-395: the SAF-005 return-home obeys the LOCALIZED gate ----------------------


class _Loc:
    def __init__(self, ok: bool) -> None:
        import threading
        self.ok = ok
        self.gate = threading.RLock()

    def autonomy_allowed(self) -> bool:
        return self.ok


def test_return_home_is_not_dispatched_when_not_localized():
    """Not LOCALIZED means the home goal cannot be dispatched: the same escalation
    as any other undispatchable RETURN_HOME (e-stop), never a drive on a bad pose."""
    rec = Recorder()
    services = build(rec, action="RETURN_HOME")
    services.localization = _Loc(False)

    apply_voltage(services, 7.0)

    assert "nav.home" not in rec.names()
    assert rec.calls[-1] == ("safety.trigger_estop", "battery_policy")


def test_return_home_is_dispatched_when_localized():
    rec = Recorder()
    services = build(rec, action="RETURN_HOME")
    services.localization = _Loc(True)

    apply_voltage(services, 7.0)

    assert rec.calls[-1] == ("nav.home", "battery_policy")


def _real_services(percent=30.0, level=BatteryLevel.OK):
    """The real latch and mode machine with their real listener, so the release is judged on both."""
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    modes = ModeMachine()
    state = StateManager("rosy_01")

    def reflect_stop():
        state.set_estop(True, safety.estop_source)
        modes.transition(Mode.EMERGENCY)
    safety.estop_listeners.append(reflect_stop)
    battery = SimpleNamespace(percent=percent, level=level, on_voltage=lambda v: None, status=BatteryStatus)
    return SimpleNamespace(
        battery=battery, safety=safety, modes=modes, state=state, localization=None,
        power=SimpleNamespace(on_battery_alert=lambda lv: None),
        docking=SimpleNamespace(on_battery_level=lambda lv: None, state=None),
        trip_lease=SimpleNamespace(charge_return_active=lambda: False, critical_deferred=False, critical_inactive_since=None),
        nav=SimpleNamespace(home=lambda source: None, docking_active_provider=lambda: False))


@pytest.mark.parametrize("source", ["battery_policy", "battery_deep"])
def test_a_battery_stop_ends_when_the_pack_recovers_and_nothing_moves(source):
    services = _real_services()
    services.safety.trigger_estop(source)
    assert services.state.snapshot().safety.releases_when_charged is True

    apply_voltage(services, 7.6)

    assert services.safety.estop is False
    assert services.modes.mode is Mode.IDLE
    safety = services.state.snapshot().safety
    assert (safety.estop, safety.source, safety.releases_when_charged) == (False, "", False)


@pytest.mark.parametrize("source", ["api:operator", "control:policy_failed"])
def test_charging_never_releases_a_stop_a_person_or_policy_set(source):
    services = _real_services()
    services.safety.trigger_estop(source)

    apply_voltage(services, 8.3)

    assert services.safety.estop is True
    assert services.modes.mode is Mode.EMERGENCY
    assert services.state.snapshot().safety.releases_when_charged is False


def test_a_persons_stop_over_a_battery_stop_takes_it_over():
    services = _real_services()
    services.safety.trigger_estop("battery_policy")

    assert services.safety.trigger_estop("api:operator") is False  # still not a new latch
    assert services.state.snapshot().safety.source == "api:operator"
    apply_voltage(services, 8.3)

    assert services.safety.estop is True
    assert services.modes.mode is Mode.EMERGENCY


def test_a_battery_source_does_not_replace_a_persons_stop():
    services = _real_services()
    services.safety.trigger_estop("api:operator")
    assert services.safety.trigger_estop("battery_policy") is False
    assert services.safety.estop_source == "api:operator"


@pytest.mark.parametrize("percent,level", [
    (30.0, BatteryLevel.WARNING),   # debounce not finished: the level still lags
    (15.0, BatteryLevel.OK),        # level lags upward: this reading is under warning
    (9.0, BatteryLevel.CRITICAL),
])
def test_a_battery_stop_stays_until_the_recovery_is_settled(percent, level):
    services = _real_services(percent, level)
    services.safety.trigger_estop("battery_policy")

    apply_voltage(services, 7.4)

    assert services.safety.estop is True
    assert services.modes.mode is Mode.EMERGENCY


def test_a_stop_arriving_during_the_release_keeps_emergency():
    services = _real_services()
    services.safety.trigger_estop("battery_policy")
    release = services.modes.release_emergency

    def stopped_meanwhile():
        result = release()
        services.safety.trigger_estop("api:operator")
        return result
    services.modes.release_emergency = stopped_meanwhile

    apply_voltage(services, 7.6)

    assert services.safety.estop is True
    assert services.modes.mode is Mode.EMERGENCY
    assert services.state.snapshot().safety.source == "api:operator"


def test_a_sensor_stuck_high_does_not_end_a_battery_stop():
    services = _real_services()
    services.safety.trigger_estop("battery_policy")

    apply_voltage(services, 16.0)

    assert services.safety.estop is True
    assert services.modes.mode is Mode.EMERGENCY


# --- D-1029: a Fleet charge return defers the 10% action, never the 5% DEEP stop ---

@pytest.mark.parametrize("action", ["RETURN_HOME", "STOP"])
def test_critical_action_is_deferred_during_a_charge_return(action):
    rec = Recorder()
    svc = build(rec, level=BatteryLevel.CRITICAL, percent=9.0, action=action, charge_return=[True, True])

    apply_voltage(svc, 7.3)

    assert ("events.battery.critical_deferred", 9.0) in rec.calls
    assert "safety.trigger_estop" not in rec.names() and "nav.home" not in rec.names()
    assert svc.trip_lease.critical_deferred


def test_no_charge_return_lease_keeps_today_s_action():
    rec = Recorder()
    apply_voltage(build(rec, percent=9.0, action="STOP"), 7.3)
    assert ("safety.trigger_estop", "battery_policy") in rec.calls
    rec = Recorder()
    apply_voltage(build(rec, percent=9.0, action="RETURN_HOME"), 7.3)
    assert ("nav.home", "battery_policy") in rec.calls


def test_a_lease_without_a_navigation_goal_does_not_defer():
    rec = Recorder()
    apply_voltage(build(rec, percent=9.0, action="STOP", charge_return=[True, False]), 7.3)
    assert ("safety.trigger_estop", "battery_policy") in rec.calls


def _deferred(rec, cr):
    svc = build(rec, level=BatteryLevel.CRITICAL, percent=9.0, action="STOP", charge_return=cr)
    apply_voltage(svc, 7.3)
    rec.calls.clear()
    svc.safety.on_battery_percent = lambda p: None   # the crossing was reported once
    return svc


@pytest.mark.parametrize("ended", [[False, True], [True, False]], ids=["lease_ended", "goal_ended"])
def test_the_deferred_action_latches_when_the_return_ends_while_still_critical(ended, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(battery_policy.time, "monotonic", lambda: clock[0])
    rec = Recorder()
    cr = [True, True]
    svc = _deferred(rec, cr)

    apply_voltage(svc, 7.3)
    assert "safety.trigger_estop" not in rec.names() and svc.trip_lease.critical_deferred

    cr[:] = ended
    apply_voltage(svc, 7.3)                      # the first reading after the end only starts the clock
    assert "safety.trigger_estop" not in rec.names()
    clock[0] += battery_policy.INACTIVE_LATCH_S
    apply_voltage(svc, 7.3)
    assert ("safety.trigger_estop", "battery_policy") in rec.calls
    assert not svc.trip_lease.critical_deferred


def test_a_reading_between_two_legs_does_not_end_the_return(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(battery_policy.time, "monotonic", lambda: clock[0])
    rec = Recorder()
    cr = [True, True]
    svc = _deferred(rec, cr)

    cr[1] = False
    apply_voltage(svc, 7.3)
    clock[0] += 1.0
    cr[1] = True                                  # the next leg started
    apply_voltage(svc, 7.3)
    clock[0] += battery_policy.INACTIVE_LATCH_S
    apply_voltage(svc, 7.3)

    assert "safety.trigger_estop" not in rec.names() and svc.trip_lease.critical_deferred


def test_a_person_stop_during_the_return_keeps_the_deferral_until_it_is_released(monkeypatch):
    # Review 2026-11-14: a person's e-stop must not swallow the deferral, or the release leaves 10..5 % unlatched.
    clock = [100.0]
    monkeypatch.setattr(battery_policy.time, "monotonic", lambda: clock[0])
    rec = Recorder()
    cr = [True, True]
    svc = _deferred(rec, cr)
    svc.safety.estop = True                       # a person's stop; nav goes idle under it
    cr[1] = False

    apply_voltage(svc, 7.3)
    clock[0] += battery_policy.INACTIVE_LATCH_S
    apply_voltage(svc, 7.3)
    assert "safety.trigger_estop" not in rec.names() and svc.trip_lease.critical_deferred

    svc.safety.estop = False                      # released while still critical
    apply_voltage(svc, 7.3)
    assert ("safety.trigger_estop", "battery_policy") in rec.calls


def test_recovery_above_critical_clears_the_deferral():
    rec = Recorder()
    cr = [True, True]
    svc = _deferred(rec, cr)
    svc.battery.percent = 15.0

    apply_voltage(svc, 7.4)
    cr[:] = [False, False]
    apply_voltage(svc, 7.4)

    assert not svc.trip_lease.critical_deferred
    assert "safety.trigger_estop" not in rec.names()


def test_deep_still_stops_immediately_during_a_charge_return():
    rec = Recorder()
    apply_voltage(build(rec, level=BatteryLevel.DEEP, percent=4.0, action="STOP", charge_return=[True, True]), 7.0)
    assert ("safety.trigger_estop", "battery_deep") in rec.calls
