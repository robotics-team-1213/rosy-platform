# operations

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-26

## Purpose

D-427 operations part and a `colcon_roots` entry. Site orchestration and ledgers, current World observations, Situation facts, Decision proposals, processes, site devices and operator UI live here. Wheel folders carry `COLCON_IGNORE`. The actual roots and import ownership in `tools/harness/platform_parts.yaml` win over this file.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `fleet/` | Fleet server, formation, admission/dispatch and shared SQLite ledger; Console serving and the distribution that installs Decision (see `fleet/AGENTS.md`) |
| `monitoring/` | Independent `rosy-monitoring` observation/configuration/cache wheel; collector/API/UI follow later (see `monitoring/AGENTS.md`, D-876) |
| `decision/` | Existing ER2/tool proposals under `src/rosy/decision`, import `rosy.decision`; installed by the same Fleet distribution (see `decision/AGENTS.md`, D-637) |
| `apps/` | Games ROS package; Fleet app composition moved to `applications/fleet/gateway` (see `apps/AGENTS.md`) |
| `processes/` | Cell and palletizing processes (see `processes/AGENTS.md`) |
| `signal_observation/` | Lamp-state observation facts, no signal command owner (D-748) |
| `overhead/` | Overhead vision worker `rosy_vision` (see `overhead/AGENTS.md`) |
| `site_ui/` | Rosy Cam and media service; Fleet UI moved to `applications/fleet/web` (see `site_ui/AGENTS.md`) |
| `site_devices/` | Dock and signal firmware (see `site_devices/AGENTS.md`) |
| `site_execution/` | Wheel `rosy-execution`: PlanBundle and authority projections (see `site_execution/AGENTS.md`) |
| `world/` | Wheel `rosy-world`: observation/evidence API and current MapPose. Fleet imports `rosy.world.state.projections.map_pose` directly (D-752) and keeps the service and the ledger (see `world/AGENTS.md`) |
| `prediction/` | D-782 action-conditioned prediction: OMX pre-execution checker and shadow recording; no command or admission authority (see `prediction/AGENTS.md`) |
| `situation/` | Fact-only situation service: `rosy_situation/analyzers` and `incidents`; old module identities remain aliases (see `situation/AGENTS.md`, D-630) |

## For AI Agents

### Working In This Directory

- Fleet consumes the robot contract. It does not modify `middleware/core/gateway` to add a field.
- Decision uses only `rosy.decision`; there is no `fleet.ai` shim. Proposal/tool validation and the existing shared Fleet SQLite transaction remain in the same distribution.
- Console source is `applications/fleet/web`; backend source is `operations/fleet/fleet/server`. Installed resources remain `fleet/server/web`; URL, CSP and API authority stay unchanged.
- `site_execution/` here is `rosy-execution`. The local policy loader is `middleware/robot_execution/local/` (`rosy-execution-local`). Do not merge them.
- Site vision sends derived sighting JSON. It does not send JPEG to Fleet and it does not publish `/cmd_vel`.
- World owns `src/rosy/world/state/projections/map_pose.py`. Consumers import `rosy.world.state.projections.map_pose` directly. There is no Fleet alias (D-752). `source=bridged` is odom dead reckoning after the last sighting or operator pin, not an action-conditioned future rollout.
- The complete current manifest-root guide is [platform-folder-responsibilities.md](../docs/reference/platform-folder-responsibilities.md). Decision and Console now have actual source holders (D-637). Action-conditioned prediction lives in `prediction/` (D-782) as a checker and shadow recorder; it is not wired to admission or an owner. Do not create empty folders without implementation, contracts and consumers.

### Testing Requirements

D-584 requires pytest on a remote test PC from committed HEAD. Keep logs in the X session and compare known failures. Vision and Cam name their own procedures.

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<name>/operations" -- operations/fleet/test operations/apps/games/test -q
python test/known_failures.py "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<name>/operations/run-1.txt"
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
