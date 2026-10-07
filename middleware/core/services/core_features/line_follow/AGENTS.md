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
| `body_stop.py` | D-422 manager mixin: body gap along the intended path, derived/override stop gaps, LiDAR blind floor, ultrasonic echo freshness |
| `model.py` | Modes, observations, config (incl. D-407 `recovery_*`, URDF `body_*`), decisions |
| `stuck_recovery.py` | D-407 ROS-free stuck state machine: ask console, answers by stuck id, local back-off, re-judge |
| `stuck_wiring.py` | Manager mixin feeding the machine; the back-off is the manager's own decision (D-2) |
| `lane_return*.py` | D-468 local lane return: evidence ledger, checkpoint/retrace/search controller, arbitration inside the manager lock |
| `lane_bridge.py` | D-476 expected-road bridge (default off): slow drive along the D-468 checkpoint lane's extension on a short loss, swept by D-422, then hand-over to D-468 |
| `junction.py` | D-491 decision 4 junction instruction gate: one pending instruction, keeps or zeroes the tick's decision (waiting, unresolved, stop after measured odom); never adds motion |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Call `lane_recovery_rule` before the speed formula. `FOLLOW` is the only ordinary path that sets a non-zero command; D-407 back-off, D-468 return and D-476 bridge are the bounded exceptions and each needs its own evidence.
- `body_stop.py` and `clearance.py` are `concern: safety` (D-430). Call them; change them only under safety change control.
- Do not import `control.sensing` or OpenCV.
- Do not publish `cmd_vel`. `CommandManager` remains the logical source.

### Testing Requirements

`middleware/core/gateway/test/test_line_follow.py`, `test_line_follow_body_stop.py`, `test_line_follow_stuck.py`, `test_line_follow_stuck_api.py`, `middleware/core/services/test/test_line_stuck_recovery.py`, `test_lane_return*.py`, `test_lane_bridge.py`, `test_line_junction.py`, `middleware/core/gateway/test/test_line_junction_api.py`

## Dependencies

### Internal

`core_features.decision`, `core_common.protocol.schemas`

### External

None.

<!-- MANUAL: -->
