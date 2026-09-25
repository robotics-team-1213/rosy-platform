<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# firmware

## Purpose

Arduino/ESP32 reference firmware for the charging dock.

## Key Files

None at this level.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `rosy_dock/` | Sketch `rosy_dock.ino` (see `rosy_dock/AGENTS.md`) |

## For AI Agents

### Working In This Directory

Rules in order: (1) never energise without load, (2) de-energise on load removal/fault/boot, (3) serve `/status` with required fields, (4) answer quickly for the robot's poll tick.

### Testing Requirements

`test/test_dock_contract.py` scans sources. Hardware bench is manual.

### Common Patterns

Arduino sketch layout (`rosy_dock/rosy_dock.ino`).

## Dependencies

### Internal

- `../README.md` contract

### External

- Arduino IDE / ESP32

<!-- MANUAL: -->
