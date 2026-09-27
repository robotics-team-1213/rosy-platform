<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# led

## Purpose

Python LED service server (`led_service_server`) wrapping `rosylib.LED`. Services `set_led` and `set_brightness` (`interfaces`).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_python (description + Apache-2.0 license filled in 2026-09-23, guarded by `test/test_package_metadata.py`) |
| `setup.py` / `setup.cfg` | Package install |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `led/` | `led_server.py` (see `led/AGENTS.md`) |
| `test/` | ament copyright/flake8/pep257 |
| `resource/` | ament marker |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- CORE battery/LED policy calls `set_led` through `ros_bridge`; do not drive the strip from CORE.
- `rosylib` is a hardware helper, not in this repo.

### Testing Requirements

```bash
# linters only unless hardware is present
python3 -m pytest src/hardware/led/test/ -v
```

### Common Patterns

Commands `set_pixel` and `fill` with RGB tuples.

## Dependencies

### Internal

- `interfaces` (`SetLed`, `SetBrightness`)

### External

- rclpy, rosylib

<!-- MANUAL: -->
