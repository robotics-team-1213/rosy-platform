<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-25 | Updated: 2026-09-25 -->

# line_follow

## Purpose

Turn a `FOLLOW` decision into a capped speed (D-228, D-229). Pixels stay in `control/sensing/perception`. This package reads numbers already on `LineObservation`.

## Key Files

| File | Description |
|------|-------------|
| `manager.py` | Mode, loss latch, and the speed formula |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Call `lane_recovery_rule` before the speed formula. `FOLLOW` is the only path that sets a non-zero command.
- Do not import `control.sensing` or OpenCV.
- Do not publish `cmd_vel`. `CommandManager` remains the logical source.

### Testing Requirements

`src/core/core/test/test_line_follow.py`

## Dependencies

### Internal

`core_features.decision`, `core_common.protocol.schemas`

### External

None.

<!-- MANUAL: -->
