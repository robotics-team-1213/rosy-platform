# operations

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-11

## Purpose

D-427 operations part and a `colcon_roots` entry. Fleet console, games, vision, cell, palletizing, the Cam app, site-device firmware, and the ROS-free site wheels. Wheel folders carry `COLCON_IGNORE`. The part map in `tools/harness/platform_parts.yaml` wins over this file.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `fleet/` | Fleet server, formation, and the console UI (see `fleet/AGENTS.md`) |
| `apps/` | Games ROS package and the site gateway wheel (see `apps/AGENTS.md`) |
| `processes/` | Cell and palletizing processes (see `processes/AGENTS.md`) |
| `vision/` | Overhead vision worker `rosy_vision` (see `vision/AGENTS.md`) |
| `ui/` | Rosy Cam Android app (see `ui/AGENTS.md`) |
| `site_devices/` | Dock and signal firmware (see `site_devices/AGENTS.md`) |
| `execution/` | Wheel `rosy-execution`: PlanBundle and authority projections (see `execution/AGENTS.md`) |
| `world/` | Wheel `rosy-world`: observation/evidence API and current-state MapPose projection; Fleet keeps service/transaction consumers (see `world/AGENTS.md`, D-630) |
| `situation/` | Fact-only situation service: `rosy_situation/analyzers` and `incidents`; old module identities remain aliases (see `situation/AGENTS.md`, D-630) |

## For AI Agents

### Working In This Directory

- Fleet consumes the robot contract. It does not modify `middleware/core/gateway` to add a field.
- `execution/` here is `rosy-execution`. The local policy loader is `middleware/execution/local/` (`rosy-execution-local`). Do not merge them.
- Site vision sends derived sighting JSON. It does not send JPEG to Fleet and it does not publish `/cmd_vel`.
- World owns `src/rosy/world/state/projections/map_pose.py`; `fleet.localization.map_pose` is its identity facade. The odom `predicted` state is current-state dead reckoning, not future action-conditioned rollout.
- The complete current manifest-root guide is [platform-folder-responsibilities.md](../docs/reference/platform-folder-responsibilities.md). Future prediction/decision/UI holders require real consumers; do not create empty folders from a planning tree.

### Testing Requirements

`python -m pytest operations/fleet/test operations/apps/games/test -q` for the ROS-free host suites. Vision and Cam name their own commands.

### Common Patterns

Harness modules keep `progress.md`, `logs.md`, and `index.md` beside `AGENTS.md`. Wheels do not, unless a harness entry says they are modules.

## Dependencies

### Internal

- Robot HTTP contract from CORE. Schemas from `contracts/foundation`.
- `shared/web/` for operator UI pieces.

### External

- FastAPI and httpx on the Fleet server. No ROS inside Fleet (D-18).

## Manual Notes
