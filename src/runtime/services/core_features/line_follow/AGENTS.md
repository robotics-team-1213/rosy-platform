<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-25 | Updated: 2026-09-25 -->

# line_follow

## Purpose

Turn a `FOLLOW` decision into a capped speed (D-228, D-229). Pixels stay in `control/sensing/perception`. This package reads numbers already on `LineObservation`.

## Key Files

| File | Description |
|------|-------------|
| `manager.py` | Mode, loss latch, the speed formula, obstacle hold (D-422 body gap along the intended path, ultrasonic fusion), and the manual-ladder angular cap (D-344 §11/§13) |
| `clearance.py` | ROS-free LiDAR geometry: front sector minimum, swept-corridor path clearance, D-407 body clearances, D-422 swept-body gap, rotation gap, ultrasonic cone points |
| `model.py` | Modes, observations, config (incl. D-407 `recovery_*`, URDF `body_*`), decisions |
| `stuck_recovery.py` | D-407 ROS-free stuck state machine: ask console, answers by stuck id, local back-off, re-judge |
| `stuck_wiring.py` | Manager mixin feeding the machine; the back-off is the manager's own decision (D-2) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Call `lane_recovery_rule` before the speed formula. `FOLLOW` is the only path that sets a non-zero command.
- Do not import `control.sensing` or OpenCV.
- Do not publish `cmd_vel`. `CommandManager` remains the logical source.

### Testing Requirements

`src/runtime/gateway/test/test_line_follow.py`, `test_line_follow_body_stop.py`, `test_line_follow_stuck.py`, `test_line_follow_stuck_api.py`, `src/runtime/services/test/test_line_stuck_recovery.py`

## Dependencies

### Internal

`core_features.decision`, `core_common.protocol.schemas`

### External

None.

<!-- MANUAL: -->
