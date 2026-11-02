"""What the robot's heat readings set in motion. ROS-free, like battery_policy.

`motor/health` (bringup, every 2 s) is stored as it arrives; once a second the bridge re-reads
the SoC temperature and the firmware throttle bits and the safety manager's ThermalMonitor
(core_features.safety.thermal) decides the level that `SafetyManager.clip` applies. A missing
file is "no reading", never hot, so a development host without these files drives as before.
One event per level change; heat never latches the e-stop.
"""

from __future__ import annotations

import json
import logging

_log = logging.getLogger(__name__)


def on_motor_health(services, text: str, now: float) -> None:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return
    services.safety.thermal.on_motor_health(payload, now)


def tick(services, now: float):
    """The new level, or None when the evaluation itself failed (logged; the old level stays)."""
    try:
        thermal, probe = services.safety.thermal, services.runtime_probe
        before = thermal.level
        level = thermal.update(probe.temperature(), probe.throttled(), now)
        data = {"from": before, "reasons": list(thermal.reasons), "soc_c": thermal.soc_c}
        if level != before and level == "hot":
            services.events.publish("thermal.hot", severity="critical", source="safety_manager", data=data)
        elif level != before and level == "warm":
            services.events.publish("thermal.warm", severity="warning", source="safety_manager", data=data)
        elif level != before:
            services.events.publish("thermal.ok", severity="info", source="safety_manager", data=data)
        return level
    except Exception:  # the diagnostics tick that calls this must keep running
        _log.exception("thermal evaluation failed")
        return None
