
# line_follow

**Parent context:** `../AGENTS.md`

## Purpose

Turn a `FOLLOW` decision into a capped speed (D-228, D-229). Depends on `core_features.decision` and `core_common.protocol.schemas`. Pixels stay in `control/sensing/perception`; this package reads numbers already on `LineObservation`. Files are named for their decision (`manager.py`, `clearance.py`, `body_stop.py`, `authority.py`, `model.py`, `observation.py`); `ls` shows the rest. `crosswalk_{gate,report,zone}.py` are compatibility exports; new code imports `core_features.line_follow.crosswalk.*`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `arc/` | D-520 map-guided arc mixin (own size unit, `docs/plans/2026-10-08-line-follow-arc-subpackage.md`) |
| `crosswalk/` | D-491 zone, D-573 gate/report mixins (own size unit, `docs/plans/2026-10-10-core-line-follow-size-unit.md`) |
| `signal/` | D-525/D-620 virtual junction signal mixin (same plan) |
| `recovery/` | D-407 stuck, D-468 return, D-476 bridge, D-495 junction; `recovery/stuck/` and `recovery/junction/` are own size units |

All mixins share the manager lock and generation; none has its own lock, thread, transport, store or publisher.

## For AI Agents

### Working In This Directory

- A live D-520 arc owns the tick (`_arc_tick` in `_tick_locked`): keeper reasons, loss clock, D-468, D-476, D-407 and the junction gate do not run. `recovery` never imports `arc`; it calls the mixin methods.
- Call `lane_recovery_rule` before the speed formula. `FOLLOW` is the only ordinary path that sets a non-zero command; D-407 back-off, D-468 return and D-476 bridge are the bounded exceptions and each needs its own evidence.
- `recovery/motion_admit.py` `motion_admitted(...)` (D-507 6) is the one motion admission for D-468 return/retrace, D-476 bridge and D-495 junction motion: D-400 enforce proof, else the `site_floor_map_id` site basis; site-basis reverse only for `retrace`.
- `authority.py` (D-517 4, D-760): Fleet movement authority only ever zeroes the tick's final decision; non-shrinking unless `shrink` (a shrink never grants); `ttl_s` ≤ 5 s; enforced once CORE's trip lease was seen open.
- Crosswalk gate (D-573, default off, `concern: safety`): stop before a D-491 zone, look with LiDAR rays only (no return / shadow / blind = unknown), cross after `crosswalk_clear_s` of continuous empty scans, no timeout; the manager applies its cap with `min` after the authority gate.
- `body_stop.py`, `clearance.py` and `crosswalk/gate.py` are `concern: safety` (D-430). Call them; change them only under safety change control.
- Do not import `control.sensing` or OpenCV. Do not publish `cmd_vel`; `CommandManager` remains the logical source.

### Testing Requirements

`test_line_*`, `test_lane_*` and `test_crosswalk_gate*` under `middleware/core/gateway/test` and `middleware/core/services/test` (`rg -l line_follow` there).
