<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# emotion

## Purpose

LCD emotion GIFs (`set_emotion` service) and PWR-003 info-card renderer (`info_screen.py`). Info-screen is ROS-free PIL so tests do not need an LCD.

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_python; python3-pil, interfaces |
| `setup.py` / `setup.cfg` | Package install |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `emotion/` | Python package `emotion` (LCD node, info-screen renderer, hardware LCD helper) + emotion GIFs (see `emotion/AGENTS.md`) |
| `test/` | `test_info_screen.py` + ament linters (see `test/AGENTS.md`) |
| `resource/` | ament marker |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- `info_screen.py` draws 320×240 landscape; LCD code rotates/resizes. Keep that contract.
- CORE publishes `display/info` JSON; this package renders it. Do not put PIL in `core`.

### Testing Requirements

```bash
PYTHONPATH=src/hmi/face python3 -m pytest src/hmi/face/test/test_info_screen.py -v
```

### Common Patterns

Share-dir lookup: `get_package_share_directory('emotion')/emotion`.

## Dependencies

### Internal

- `interfaces/Emotion`
- Power manager wake/info hold in `core`

### External

- PIL, rclpy, hardware LCD via `rosy_lcd.py`

<!-- MANUAL: -->
