# operations

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-11

## Purpose

D-427 operations part and a `colcon_roots` entry. Site orchestration and ledgers, current World observations, Situation facts, Decision proposals, processes, site devices and operator UI live here. Wheel folders carry `COLCON_IGNORE`. The actual roots and import ownership in `tools/harness/platform_parts.yaml` win over this file.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `fleet/` | Fleet server, formation, admission/dispatch and shared SQLite ledger; Console serving and the distribution that installs Decision (see `fleet/AGENTS.md`) |
| `decision/` | Existing ER2/tool proposals under `src/rosy/decision`, import `rosy.decision`; installed by the same Fleet distribution (see `decision/AGENTS.md`, D-637) |
| `apps/` | Games ROS package and the site gateway wheel (see `apps/AGENTS.md`) |
| `processes/` | Cell and palletizing processes (see `processes/AGENTS.md`) |
| `vision/` | Overhead vision worker `rosy_vision` (see `vision/AGENTS.md`) |
| `ui/` | Console source `ui/console` and Rosy Cam Android app (see `ui/AGENTS.md`) |
| `site_devices/` | Dock and signal firmware (see `site_devices/AGENTS.md`) |
| `execution/` | Wheel `rosy-execution`: PlanBundle and authority projections (see `execution/AGENTS.md`) |
| `world/` | Wheel `rosy-world`: observation/evidence API and current-state MapPose projection; Fleet keeps service/transaction consumers (see `world/AGENTS.md`, D-630) |
| `situation/` | Fact-only situation service: `rosy_situation/analyzers` and `incidents`; old module identities remain aliases (see `situation/AGENTS.md`, D-630) |

## For AI Agents

### Working In This Directory

- Fleet consumes the robot contract. It does not modify `middleware/core/gateway` to add a field.
- Decision uses only `rosy.decision`; there is no `fleet.ai` shim. Proposal/tool validation and the existing shared Fleet SQLite transaction remain in the same distribution.
- Console source is `operations/ui/console`; backend source is `operations/fleet/fleet/server`. Installed resources remain `fleet/server/web`; URL, CSP and API authority stay unchanged.
- `execution/` here is `rosy-execution`. The local policy loader is `middleware/robot_execution/local/` (`rosy-execution-local`). Do not merge them.
- Site vision sends derived sighting JSON. It does not send JPEG to Fleet and it does not publish `/cmd_vel`.
- World owns `src/rosy/world/state/projections/map_pose.py`; `fleet.localization.map_pose` is its identity facade. The odom `predicted` state is current-state dead reckoning, not future action-conditioned rollout.
- The complete current manifest-root guide is [platform-folder-responsibilities.md](../docs/reference/platform-folder-responsibilities.md). Decision and Console now have actual source holders (D-637). Action-conditioned future prediction remains planned; do not create empty folders without implementation, contracts and consumers.

### Testing Requirements

D-584 requires pytest on a remote test PC from committed HEAD. Keep logs in the X session and compare known failures. Vision and Cam name their own procedures.

```bash
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<name>/operations -- operations/fleet/test operations/apps/games/test -q
python test/known_failures.py X:/DevTemp/<name>/operations/run-1.txt
```

### Common Patterns

Harness modules keep `progress.md`, `logs.md`, and `index.md` beside `AGENTS.md`. Wheels do not, unless a harness entry says they are modules.

## Dependencies

### Internal

- Robot HTTP contract from CORE. Schemas from `contracts/foundation`.
- `shared/web/` for operator UI pieces.

### External

- FastAPI and httpx on the Fleet server. No ROS inside Fleet (D-18).

## Manual Notes
