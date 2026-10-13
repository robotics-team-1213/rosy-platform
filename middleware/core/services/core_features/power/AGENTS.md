<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# power

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

PWR-001–004 duty cycling and SAF-005 battery integrity. Policy only: no GPIO, no halt, no cmd_vel. STANDBY is the deepest sleep (D-25); OS halt is D-27 via sentinel.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `manager.py` | `PowerManager`, `PowerConfig`, `PresenceConfig`, `LidarPolicy`; wake reasons |
| `devices.py` | Per-device power policy: `DeviceLevel`, `DevicePolicy`, `DevicePolicyConfig` (bench switch), `DevicePowerPort`, `parse_device_policy` |
| `battery.py` | `BatteryCurve`, `BatteryMonitor`, hysteresis, LED intent, shutdown sentinel |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Design docs: `docs/plans/2026-09-01-deep-power-states-design.md`, `2026-09-02-battery-integrity-low-battery-alert-design.md`.
- Presence detection needs truly consecutive valid near samples and `min_presence_s`; invalid and hysteresis-band samples break the streak (D-24 amendment 2026-10-04).
- `on_command(source)` (accepted command REST calls via `core_api_web.api.command_activity`) and `on_activity("cmd_vel")` (a nonzero final cmd_vel) reset the inactivity timer. Never call either from a GET, telemetry or WS subscription path.
- Devices are declared by the robot package `core.yaml` (`power.device_policy.devices`). The policy acts only when `power.device_policy.enabled` (bench switch, default false) or the device's own `enabled` is true. Undeclared devices stay on. Adapters live in `middleware/core/gateway/core/bridge/device_power.py`.
- A device that was OFF is ready again only after `wake_ready_s` **and** a ready report (`report_device_ready`; for the LiDAR a received scan). Time alone never makes it ready: `motion_ready()` stays false and CORE's final cmd_vel stays zero (D-440 5).
- `LidarPolicy.standby_stop` (legacy per-robot opt-in for the lidar entry) **defaults off**. Do not flip it until `docs/deployment/power-bench-verification.md` passes. Bridge calls start/stop motor services when it is on.
- Sentinel JSON is an observation. Host `rosy-lowbatt-shutdown` unit executes halt.

### Testing Requirements

```bash
python3 -m pytest middleware/core/gateway/test/test_power.py middleware/core/gateway/test/test_battery.py -v
# D-24 amendment / D-440: policy in services, routes + config + bridge adapters in the gateway
python3 -m pytest middleware/core/services/test/test_power_wake_inputs.py middleware/core/services/test/test_power_device_policy.py middleware/core/gateway/test/test_power_command_routes.py middleware/core/gateway/test/test_power_device_adapters.py -v
```

### Common Patterns

Injected clock; enter/exit sample counters; hysteresis percent.

## Dependencies

### Internal

- `protocol.schemas` PowerMode / BatteryLevel
- Wired in `services.py` from `rosy_default.yaml`

### External

None.

<!-- MANUAL: -->
