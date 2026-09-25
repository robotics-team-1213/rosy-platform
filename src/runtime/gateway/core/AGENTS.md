<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-20 -->

# core (Python package)

## Purpose

Importable middleware kernel. `main.py` starts rclpy; `node.py` wires the process and starts the API thread; `services.py` builds `CoreServices` by assembling managers from `core_features`, schemas/profile/identity/capability from `core_common`, and the event bus / audit log from `core_events`. All ROS I/O is confined to `bridge/ros_bridge`.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `main.py` | Entry (`core=core.main:main`): applies Cyclone RMW via `core_common.rmw`, then `rclpy.init` → `RosyCoreNode.run` → shutdown |
| `node.py` | Assembles profile/capabilities/services (`SOFTWARE_VERSION` from `core_common.identity`), starts uvicorn thread |
| `services.py` | `CoreServices` DI: ModeMachine/CommandManager, Docking*, Navigation*, Swarm, Power*, SafetyManager, StateManager (`core_features`), EventBus/FileAuditLog (`core_events`), inventory/protocol/evidence (`core_common`); `SHUTDOWN_SENTINEL_NAME` |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `bridge/` | All ROS I/O (see `bridge/AGENTS.md`) |
| `system/` | Host probe, ROS graph (see `system/AGENTS.md`) |

Feature managers, protocol schemas, config/identity/profile, and the API no longer live here: see `../../services/core_features/AGENTS.md`, `../../../contracts/foundation/core_common/AGENTS.md`, `../../events/core_events/AGENTS.md`, and `../../api_web/core_api_web/AGENTS.md`. Operator screens are `src/hmi/dashboard`.

## For AI Agents

### Working In This Directory

#### Split criteria — before making a module a package, or splitting a file

Full reasoning: `docs/plans/2026-09-06-module-split-criteria.md` (repo root). Operative rules:

- **Size is never a reason.** `waypoints/` is 85 lines and is a package; `docking/manager.py` is 511 and is one file.
- **Promote a module only if all three hold:** it owns a requirement family no package claims, it needs a second file with a
  different role *today* (or one is scheduled under a requirement ID), and ≥2 packages import it. One file, one role → stays.
- **Split a file only on a defect.** C1: it cannot be imported by host pytest and hides a decision → extract a ROS-free sibling
  (`bridge/translate.py`, `bridge/goal_tracker.py`). C6: a dependency reached via `hasattr`/`getattr` → declare the member;
  `test/test_module_criteria.py` fails on any new reach. C7: one service field spanning two requirement families.
- **Record the "leave it alone" verdicts too.** They are what stops the next round of churn.

- `SOFTWARE_VERSION` lives in `core_common.identity` and must match this package's `package.xml`. `node.py` imports it.
- Waypoint store (`core_features.waypoints`) defaults to `~/.rosy/waypoints.json` (on Pi, `HOME=/var/lib/rosy`).
- `SHUTDOWN_SENTINEL_NAME = "battery-shutdown-request.json"` in `services.py`. Dock database JSON lives beside waypoints.
- Optional ROS pkgs: wrap slam_toolbox (and similar) in constructor try/except.

### Testing Requirements

See sibling `../test/AGENTS.md`.

### Common Patterns

Managers take an injected clock. Events via `EventBus.publish(type, source, data)` (bus lives in `core_events`).

## Dependencies

### Internal

- `core_common` (schemas, config, identity, profile, capability, domain, rmw), `core_events`, `core_features`, `core_api_web` — assembled only in `node.py` / `services.py`

### External

- rclpy (node/main/bridge only), yaml, fastapi/uvicorn (API thread via `core_api_web`)

<!-- MANUAL: -->
