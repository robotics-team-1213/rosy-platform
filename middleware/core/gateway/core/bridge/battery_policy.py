"""What one battery reading sets in motion (SAF-005, DNC-006). ROS-free.

Nine effects across five services, in an order that is itself the policy. This
lived inline in `ros_bridge.py`, which host pytest cannot import — so the whole
low-battery path, up to and including e-stop, had no assertion on it.

Nothing here touches ROS. It reads a float and calls managers, which is why it
could move unchanged.

**The order, and why each step is where it is:**

1. Reject a non-finite sample. A NaN from a disconnected ADC must not enter the
   filter, where it would poison every later reading.
2. Feed the raw sample to `BatteryMonitor` and act only on what it returns.
   A single sample used to reach the threshold check directly, and one voltage
   sag as the motors started would fire the critical policy. The filter is the
   fix; bypassing it re-introduces the bug.
3. Wait for a percent. `None` means the curve has not converged yet — early is
   not the same as low.
4-6. Publish state and wake the power policy before anything acts on the
   reading, so an operator looking at the dashboard sees the same number the
   robot is about to act on.
7. DEEP stops the robot *before* the shutdown grace period. Motors are the
   largest draw, so dropping the load lets the voltage recover toward its
   resting curve — which makes the shutdown decision itself better informed.
8. Offer the dock at the warning level (DNC-006). No dock, or no support, and
   this does nothing and the SAF-005 fallback below still stands.
9. D-1029: a Fleet charge return in progress defers the 10% action (the DEEP e-stop above never waits);
   it latches as soon as the return ends while the pack is still critical.
10. Then the SAF-005 action. A `RETURN_HOME` that cannot be dispatched escalates
   to e-stop: refusing to move is safe, believing you are driving home when you
   are not is not. A dock run under way *is* the return home: a Nav2 home goal
   would preempt it, and navigation refuses goals whenever docking holds the
   robot (docking, undocking, or the DOCKING mode) — the refusal would escalate
   to e-stop. So it asks navigation's own gate and leaves docking alone.
"""

from __future__ import annotations

import contextlib
import math
import time

from core_features.command.arbitration import Mode
from core_common.protocol.wire_status import NavigationState
from core_features.power.battery import BatteryLevel

#: D-1029: how long the return must be over before the deferred 10 % action latches.
INACTIVE_LATCH_S = 2.0
_NAV_IDLE = {NavigationState.IDLE, NavigationState.ARRIVED, NavigationState.CANCELED, NavigationState.FAILED}


#: A reading above this is a broken sensor, not a charged pack: a stuck ADC must not end a stop.
#: shortcut: fixed for the 2S pack (8.4 V full, 8.78 V read on the charger), so another pack just keeps
#: the administrator release; derive it from the battery curve when one ships.
MAX_PLAUSIBLE_PACK_V = 9.5


def _release_recovered_stop(services) -> None:
    """D-502: end a stop only the battery holds. The robot stays IDLE until a new command."""
    safety = services.safety
    if not safety.release_recovered_battery_stop():
        return
    services.modes.release_emergency()
    services.state.set_estop(False)
    if safety.estop:  # a person's stop arrived between those lines; put EMERGENCY back over it
        services.state.set_estop(True, safety.estop_source)
        services.modes.transition(Mode.EMERGENCY)


def _charge_return_active(services) -> bool:
    """D-1029: a live charge-return lease and navigation in progress. Any doubt is False (latch).

    Navigation, not ``fleet_goal()``: a trip goal carries a correlation id only with a goal lease (off by default)."""
    try:
        return bool(services.trip_lease.charge_return_active()
                    and not services.nav.docking_active_provider()
                    and services.nav.nav_state not in _NAV_IDLE)
    except Exception:
        return False


def apply_voltage(services, voltage: float) -> None:
    """Run one battery reading through the policy chain.

    `services` is the `CoreServices` container; only `battery`, `state`,
    `power`, `safety`, `modes` and `nav` are touched, plus `docking`.
    """
    if not math.isfinite(voltage):
        return

    battery = services.battery
    battery.on_voltage(voltage)

    percent = battery.percent
    if percent is None:
        return

    # D-502: the battery return comes back only when the debounced level is OK
    # (exit hysteresis and samples) and this reading is above warning: the level
    # lags the first readings after a fall, which must not re-enable it.
    recovered = (battery.level is BatteryLevel.OK
                 and percent > services.safety.battery_policy.warning_percent)
    if recovered:
        services.safety.battery_return_suppressed = False

    services.state.set_battery(percent, voltage)
    services.state.set_battery_status(battery.status())
    services.power.on_battery_alert(battery.level.value)

    if recovered and voltage <= MAX_PLAUSIBLE_PACK_V:
        _release_recovered_stop(services)

    if battery.level is BatteryLevel.DEEP:
        services.safety.trigger_estop("battery_deep")

    services.docking.on_battery_level(battery.level)

    action = services.safety.on_battery_percent(percent)
    safety, lease = services.safety, services.trip_lease
    if lease.critical_deferred:
        # D-1029: kept while the pack stays critical, through any other stop; it latches once the return has been
        # over for INACTIVE_LATCH_S (a reading between two legs is not the end) and nothing else holds the robot.
        now = time.monotonic()
        if percent > safety.battery_policy.critical_percent:
            lease.critical_deferred, lease.critical_inactive_since = False, None
        elif _charge_return_active(services):
            lease.critical_inactive_since = None
        elif lease.critical_inactive_since is None:
            lease.critical_inactive_since = now
        elif (now - lease.critical_inactive_since >= INACTIVE_LATCH_S and not safety.estop
              and not services.nav.docking_active_provider()):
            lease.critical_deferred, lease.critical_inactive_since = False, None
            safety.trigger_estop("battery_policy")
            return
    elif action in ("RETURN_HOME", "STOP") and _charge_return_active(services):
        lease.critical_deferred, lease.critical_inactive_since = True, None
        services.events.publish("battery.critical_deferred", severity="warning", source="safety_manager",
                                data={"percent": percent})
        return
    if action == "RETURN_HOME":
        if services.nav.docking_active_provider():
            return
        if services.safety.battery_return_suppressed:
            # D-502: after an e-stop the robot does not drive itself home; a
            # critical crossing latches again until a new command moves it.
            services.safety.trigger_estop("battery_policy")
            return
        localization = services.localization  # None on a robot without D-395
        gate = localization.gate if localization is not None else contextlib.nullcontext()
        with gate:
            try:
                # D-395: not LOCALIZED means the home goal cannot be dispatched.
                if localization is not None and not localization.autonomy_allowed():
                    raise RuntimeError("robot localization is not LOCALIZED")
                services.nav.home(source="battery_policy")
            except Exception:
                services.safety.trigger_estop("battery_policy")
    elif action in ("STOP",):
        services.safety.trigger_estop("battery_policy")
