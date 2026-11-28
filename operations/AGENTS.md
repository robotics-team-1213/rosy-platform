# operations

**Parent context:** `../AGENTS.md`

## Purpose

D-427 operations part and a `colcon_roots` entry: site orchestration and ledgers, current World observations, Situation facts, Decision proposals, processes, site devices and operator UI. Wheel folders carry `COLCON_IGNORE`. Actual roots and import ownership in `tools/harness/platform_parts.yaml` win over this file; the folder guide is [platform-folder-responsibilities.md](../docs/reference/platform-folder-responsibilities.md). Folders: `fleet`, `monitoring` (D-876), `notifications` (D-997, D-998; Fleet stays the sending owner), `decision` (D-637), `apps`, `processes`, `signal_observation` (D-748, no signal command owner), `overhead`, `site_ui`, `site_devices`, `site_execution`, `world`, `prediction` (D-782), `situation` (D-630). Each has its own `AGENTS.md` where it has local rules.

## For AI Agents

### Working In This Directory

- Fleet consumes the robot contract; it does not modify `middleware/core/gateway` to add a field. No ROS inside Fleet (D-18).
- Decision uses only `rosy.decision`; there is no `fleet.ai` shim. Proposal/tool validation and the shared Fleet SQLite transaction stay in the same distribution.
- Console source is `applications/fleet/web`, backend `operations/fleet/fleet/server`; installed resources stay `fleet/server/web`; URL, CSP and API authority are unchanged.
- `site_execution/` is `rosy-execution`; the local policy loader is `middleware/robot_execution/local/` (`rosy-execution-local`). Do not merge them.
- Site vision sends derived sighting JSON only: no JPEG to Fleet, no `/cmd_vel`.
- World owns `rosy.world.state.projections.map_pose`; consumers import it directly, no Fleet alias (D-752). `source=bridged` is odom dead reckoning after the last sighting or pin, not a forecast.
- `prediction/` (D-782) is a checker and shadow recorder with no admission or command authority. Do not create empty folders without implementation, contracts and consumers.

### Testing Requirements

D-584: pytest runs on a remote test PC from committed HEAD; compare known failures. Vision and Cam name their own procedures.

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<name>/operations" -- operations/fleet/test operations/apps/games/test -q
python test/known_failures.py "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<name>/operations/run-1.txt"
```

Harness modules keep `progress.md`, `logs.md`, `index.md` beside `AGENTS.md`; wheels do not unless a harness entry says so.
