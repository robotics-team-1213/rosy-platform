<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-21 -->

# navigation

## Purpose

NAV-001–004/006 facade. ROS-free. Nav2 action client lives behind `NavExecutor` (implemented by `RosBridge`). Follow lives in `core.swarm` (D-60).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `manager.py` | `NavigationManager`, `NavGoalSpec`, `NavExecutor` protocol, `NavigationError` |
| `readiness.py` | ROS-free hardware lifecycle/motor readiness gate used by navigation and command output |
| `initial_pose.py` | AMCL covariance for `/initialpose` (zero covariance is ignored) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- `save_map` returns `map_id` (filename + checksum, D-13). Bridge computes the hash.
- Mapping start is readiness-gated just like goals; the active backend decides whether AMCL/map-server or SLAM Toolbox must be active.
- Stuck timeout is SAF/NAV-006 — honor `stuck_timeout_s` from config.
- **Recorded exception (C7):** `NavigationManager` also carries NAV-005 mapping-session state (`mapping_active`,
  `start/stop/save/reset_mapping`) although this package claims NAV-001~004/006. Accepted — there is no `mapping`
  service for it to move to. It unblocks on the `mapping/` re-entry trigger in
  `docs/plans/2026-09-06-module-split-criteria.md`. Do not deepen it: new mapping state waits for that package.

### Testing Requirements

`test_core_logic.py`, `test_sprint2.py`

### Common Patterns

Goals in `map` frame with x, y, yaw.

## Dependencies

### Internal

- `protocol.schemas.NavigationState`
- Executor: `bridge.ros_bridge`

### External

None (in this package).

<!-- MANUAL: -->
