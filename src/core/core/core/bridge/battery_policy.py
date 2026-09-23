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
9. Then the SAF-005 action. A `RETURN_HOME` that cannot be dispatched escalates
   to e-stop: refusing to move is safe, believing you are driving home when you
   are not is not. A dock run under way *is* the return home: a Nav2 home goal
   would preempt it (and navigation refuses goals while docking), so it is
   left alone.
"""

from __future__ import annotations

import math

from core_common.protocol.schemas import DockState
from core_features.power.battery import BatteryLevel


def apply_voltage(services, voltage: float) -> None:
    """Run one battery reading through the policy chain.

    `services` is the `CoreServices` container; only `battery`, `state`,
    `power`, `safety` and `nav` are touched, plus `docking`.
    """
    if not math.isfinite(voltage):
        return

    battery = services.battery
    battery.on_voltage(voltage)

    percent = battery.percent
    if percent is None:
        return

    services.state.set_battery(percent, voltage)
    services.state.set_battery_status(battery.status())
    services.power.on_battery_alert(battery.level.value)

    if battery.level is BatteryLevel.DEEP:
        services.safety.trigger_estop("battery_deep")

    services.docking.on_battery_level(battery.level)

    action = services.safety.on_battery_percent(percent)
    if action == "RETURN_HOME":
        if services.docking.state is DockState.DOCKING:
            return
        try:
            services.nav.home(source="battery_policy")
        except Exception:
            services.safety.trigger_estop("battery_policy")
    elif action in ("STOP",):
        services.safety.trigger_estop("battery_policy")
