<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# safety

## Purpose

SAF-001–005: e-stop, teleop timeout, speed limits, battery policy hooks. ROS-free. Does not command motors or halt the OS.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `manager.py` | `SafetyManager`, `TeleopWatchdog`, `SpeedLimits`, `BatteryPolicy` |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Battery *integrity* (curve, hysteresis, sentinel) is `power/battery.py`, not this package. Keep SAF-005 policy flags here (`warning`/`critical`/`RETURN_HOME`).
- Do not implement halt in SafetyManager (D-27 is host-side).
- Prefer extending `manager.py`. Do not add a second watchdog module.

### Testing Requirements

`test_core_logic.py`, `test_battery.py` (policy integration).

### Common Patterns

Timeouts in milliseconds for teleop; percent for battery thresholds.

## Dependencies

### Internal

- Used by `command.manager` and `services.py`

### External

None.

<!-- MANUAL: -->
