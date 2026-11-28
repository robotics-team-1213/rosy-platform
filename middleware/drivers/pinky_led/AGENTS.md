
# led

**Parent context:** `../AGENTS.md`

## Purpose

Python LED service server (`led_service_server`) wrapping `rosylib.LED`. Services `set_led` and `set_brightness` (`interfaces`).

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `led/` | `led_server.py` (see `led/AGENTS.md`) |
| `test/` | ament copyright/flake8/pep257 |
| `resource/` | ament marker |

## For AI Agents

### Working In This Directory

- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
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
