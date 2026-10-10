<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-25 | Updated: 2026-10-07 -->

# line_follow

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Turn a `FOLLOW` decision into a capped speed (D-228, D-229). Pixels stay in `control/sensing/perception`. This package reads numbers already on `LineObservation`.

## Key Files

| File | Description |
|------|-------------|
| `manager.py` | Mode, loss latch, the speed formula, obstacle hold (D-422 body gap along the intended path, ultrasonic fusion), and the manual-ladder angular cap (D-344 §11/§13) |
| `clearance.py` | ROS-free LiDAR geometry: front sector minimum, swept-corridor path clearance, D-407 body clearances, D-422 swept-body gap, rotation gap, ultrasonic cone points |
| `body_stop.py` | D-422 manager mixin: body gap along the intended path, derived/override stop gaps, LiDAR blind floor, ultrasonic echo freshness |
| `authority.py` | D-517 4 (M2) manager mixin: Fleet movement authority (`POST /line-follow/authority`), wall-stamped odom path log for `pose_stamp`, stop at remaining ≤ D-424 stop gap, non-shrinking, `ttl_s` expiry; only ever zeroes the tick's final decision |
| `crosswalk_gate.py` | D-573 crosswalk gate (default off, `concern: safety` path): stop before a D-491 camera zone at max(g(v), range_min - (front - lidar) + margin), look with LiDAR rays only (no return / shadow / blind = unknown), cross after `crosswalk_look_s` of empty scans, no timeout, `crosswalk_blocked` D-407 stuck after `crosswalk_report_s`; manager mixin applies its cap with `min` after the authority gate |
| `crosswalk_report.py` | D-573 6 개정 `line_follow.crosswalk` view, gate on or off: own per-epoch camera zone list (dropped only when the back-off reach is past), watched-ground run with blind-gap restart; `null` / `inside` / `ahead` / `unknown` |
| `model.py` | Modes, observations, config (incl. D-407 `recovery_*`, URDF `body_*`), decisions |
| `recovery/stuck_recovery.py` | D-407 ROS-free stuck state machine: ask console, answers by stuck id, local back-off, re-judge |
| `recovery/stuck_wiring.py` | Manager mixin feeding the machine; the back-off is the manager's own decision (D-2) |
| `progress_watch.py` | D-407 개정 / D-607 ROS-free odom-vs-issued-twist watch: `no_progress` / `dithering` while commanded but still (half URDF body length, `no_progress_yaw_deg`, restuck drift); intentional gate holds reset it |
| `recovery/lane_return*.py` | D-468 local lane return: evidence ledger, checkpoint/retrace/search controller, arbitration inside the manager lock |
| `recovery/lane_bridge.py` | D-476 expected-road bridge (default off): armed by confident following (rev 1, no D-468 containment), slow drive along the followed lane's straight extension on a short loss, swept by D-422 (plus the D-468 floor proof when enforce), then hand-over to D-468 or today's HOLD/LOST |
| `recovery/motion_admit.py` | D-507 6 `motion_admitted(now, linear, angular, kind, map_id)`: the one motion admission for D-468 return/retrace, D-476 bridge and D-495 junction motion; D-400 enforce proof, else the `site_floor_map_id` site basis (IR verdict per kind, path + URDF body, fresh scan, D-422 sweep of the twist); site-basis reverse only for `retrace` |
| `recovery/junction/` | D-494 decision 4 / D-495 junction instruction gate and bounded turn (`gate.py`): one pending instruction, keeps or zeroes the tick's decision (waiting, unresolved, stop after measured odom); D-507 expected window and pivot approach (`approach.py`), map bend pass (`bend.py`). Its own size unit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `arc/` | D-520 map-guided arc mixin (`lane_arc.py`): after a junction instruction's turn with `exit_segment`, drive omega = g*v*kappa on odom length to the next place, IR one-time correction, `segment_end` pivot; own size unit (`docs/plans/2026-10-08-line-follow-arc-subpackage.md`); same manager lock and generation |
| `recovery/` | Lane recovery mixins of `LineFollowManager` (D-407 stuck, D-468 return, D-476 bridge, D-495 junction); same manager lock and generation, no own lock, thread, store or publisher |

## For AI Agents

### Working In This Directory

- A live D-520 arc owns the tick (`_arc_tick` in `_tick_locked`): keeper reasons, the loss clock, D-468, D-476, D-407 and the junction gate do not run. `recovery` never imports `arc`; it calls the mixin methods.
- Call `lane_recovery_rule` before the speed formula. `FOLLOW` is the only ordinary path that sets a non-zero command; D-407 back-off, D-468 return and D-476 bridge are the bounded exceptions and each needs its own evidence.
- `body_stop.py` and `clearance.py` are `concern: safety` (D-430). Call them; change them only under safety change control.
- Do not import `control.sensing` or OpenCV.
- Do not publish `cmd_vel`. `CommandManager` remains the logical source.

### Testing Requirements

`middleware/core/gateway/test/test_line_follow.py`, `test_line_follow_lost_resume.py` (D-407 개정 2026-10-10), `test_line_follow_body_stop.py`, `test_line_follow_stuck.py`, `test_line_follow_stuck_api.py`, `test_line_follow_stuck_no_progress.py` (D-607), `middleware/core/services/test/test_line_stuck_recovery.py`, `test_lane_return*.py`, `test_lane_bridge.py`, `test_line_junction.py`, `test_lane_arc.py` (+ `test_lane_arc_off_golden.json`), `middleware/core/gateway/test/test_line_junction_api.py`, `test_line_arc_api.py`, `middleware/core/services/test/test_line_authority.py`, `middleware/core/gateway/test/test_line_authority_api.py`, `middleware/core/services/test/test_crosswalk_gate.py`, `middleware/core/gateway/test/test_crosswalk_gate_wiring.py`

## Dependencies

### Internal

`core_features.decision`, `core_common.protocol.schemas`

### External

None.

<!-- MANUAL: -->
