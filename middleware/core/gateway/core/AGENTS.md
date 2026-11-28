
# core (Python package)

**Parent context:** `../AGENTS.md`

## Purpose

Importable middleware kernel. `main.py` starts rclpy; `node.py` wires the process and starts the API thread; `services.py` builds `CoreServices` from `core_features` managers, `core_common` schemas/profile/identity/capability, and `core_events` (event bus, audit log). All ROS I/O is confined to `bridge/ros_bridge`. `trip_lease.py` is D-541 `TripLeaseManager` (one lease, monotonic TTL, policy only); `line_follow_wiring.py` only re-exports `drive/line_follow.py` (D-627). `bridge/`, `system/` and `drive/` (no new runtime or writer, D-627) have their own guides.

Feature managers, schemas/config/identity, events and the API live elsewhere: `../../services/core_features/AGENTS.md`, `../../../../contracts/foundation/core_common/AGENTS.md`, `../../events/core_events/AGENTS.md`, `../../api/core_api_web/AGENTS.md`. Operator screens are `middleware/robot_ui/robot`.

## For AI Agents

### Working In This Directory

#### Split criteria — before making a module a package, or splitting a file

Full reasoning: `docs/plans/2026-09-06-module-split-criteria.md`. Operative rules:

- **Size is never a reason.** `waypoints/` is 85 lines and a package; `docking/manager.py` is 511 and one file.
- **Promote a module only if all three hold:** it owns a requirement family no package claims, it needs a second file with a different role *today* (or one is scheduled under a requirement ID), and ≥2 packages import it.
- **Split a file only on a defect.** C1: host pytest cannot import it and it hides a decision → extract a ROS-free sibling (`bridge/translate.py`, `bridge/goal_tracker.py`). C6:
- a dependency reached via `hasattr`/`getattr` → declare the member (`test/test_module_criteria.py` fails on any new reach).
- C7: one service field spanning two requirement families.
- **Record the "leave it alone" verdicts too.** They stop the next round of churn.

- `SOFTWARE_VERSION` lives in `core_common.identity` and must match this package's `package.xml`.
- Waypoint store defaults to `~/.rosy/waypoints.json` (on Pi, `HOME=/var/lib/rosy`); dock database JSON lives beside it. `SHUTDOWN_SENTINEL_NAME = "battery-shutdown-request.json"` in `services.py`.
- Optional ROS pkgs: wrap slam_toolbox (and similar) in constructor try/except.
- Managers take an injected clock. Events via `EventBus.publish(type, source, data)`.
- `core_common`, `core_events`, `core_features`, `core_api_web` are assembled only in `node.py` / `services.py`.

### Testing Requirements

See sibling `../test/AGENTS.md`.
