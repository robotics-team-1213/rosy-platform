<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-21 | Updated: 2026-09-21 -->

# firmware

## Purpose

Arduino/ESP32 reference firmware for the traffic signal controller.

## Key Files

None at this level.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `rosy_signal/` | Sketch `rosy_signal.ino` (see `rosy_signal/AGENTS.md`) |

## For AI Agents

### Working In This Directory

Rules in order: (1) boot into fail-safe flash, (2) supervisor silence → fail-safe flash, (3) never red+green, (4) authenticated commands only, (5) answer the supervisor's poll tick.

### Testing Requirements

`test/test_signal_contract.py` scans sources. Hardware bench is manual.

### Common Patterns

Arduino sketch layout (`rosy_signal/rosy_signal.ino`).

## Dependencies

### Internal

- `../README.md` contract

### External

- Arduino IDE / ESP32

<!-- MANUAL: -->
