<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# power

## Purpose

PWR-001–004 duty cycling and SAF-005 battery integrity. Policy only: no GPIO, no halt, no cmd_vel. STANDBY is the deepest sleep (D-25); OS halt is D-27 via sentinel.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `manager.py` | `PowerManager`, `PowerConfig`, `PresenceConfig`, `LidarPolicy`; wake reasons |
| `battery.py` | `BatteryCurve`, `BatteryMonitor`, hysteresis, LED intent, shutdown sentinel |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Design docs: `docs/plans/2026-09-01-deep-power-states-design.md`, `2026-09-02-battery-integrity-low-battery-alert-design.md`.
- Invalid range samples are ignored (`min_valid_m` / `max_valid_m`).
- `LidarPolicy.standby_stop` **defaults off**. Do not flip it until `docs/deployment/power-bench-verification.md` passes. Bridge calls start/stop motor services when it is on.
- Sentinel JSON is an observation. Host `rosy-lowbatt-shutdown` unit executes halt.

### Testing Requirements

```bash
python3 -m pytest src/runtime/gateway/test/test_power.py src/runtime/gateway/test/test_battery.py -v
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
