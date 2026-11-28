
# fleet (Python package)

**Parent context:** `../AGENTS.md`

## Purpose

The `fleet` package is ROSY Platform's site coordinator: it sees every robot, decides who goes where and in what order, admits and records that work in its ledgers, and asks each robot's CORE to do it. It backs the Rosy Fleet screens (`applications/fleet/web`). No ROS imports (`test/test_boundaries.py`).

## Fleet's role in the platform

| Owner | Owns | Does not own |
|---|---|---|
| **Fleet** | Site map, trips, order and gaps, traffic blocks, charge-bay plan, task/mission ledgers, admission, claims, dispatch, site e-stop fan-out, stuck/incident handling, app sessions | Final wheel command, local safety latch, a robot's own docking/line motion |
| **CORE** (per robot) | Final `/cmd_vel`, safety latch (10 %·5 % battery, E-stop), line following, docking motion | Site order, other robots, site map |
| **World** | Map pose projection; `source=bridged` is dead reckoning, not a forecast | Ledgers, dispatch |
| **Vision / Decision** | Ceiling-camera sightings / candidates and model proposals | Ledger writes, robot commands |
| **Business apps** (Harbor) | Own business ledger, read through Fleet HTTP only | Robots, approval, charging |

Human authentication follows [Account ownership](../../account/AGENTS.md). Contracts: [app responsibilities](../../../docs/reference/app-responsibilities.md), [Fleet rulebook](../../../docs/reference/fleet-rulebook.md) (observe, law, candidate, admission, dispatch, readback), [folder responsibilities](../../../docs/reference/platform-folder-responsibilities.md). D-941 7: Fleet plans charging, CORE moves, Harbor only shows.

## For AI Agents

### Working In This Directory

- Authority labels: pure = no I/O; view = read-only; ledger = writes Fleet tables; robot = sends to a robot or host. `swarm/` (`HttpRobotClient`) is the only robot-contract client; a new robot-calling module goes through `swarm/transport.py`.
- A new ledger writer is added to root `test/architecture/test_fleet_ledger_writers.py` after review.
- `charge_bays.py`, `station_recovery.py` (D-721; an approval is recorded, never executed in S1), `lane_progress.py`, `speed_table.py` (D-941) are read-only views (`dispatch: false`). Dispatching from them needs CORE reverse-in docking and the charge-return exception first, with a safety review.
- `host_control.py` reboots/restarts only allowlisted site, AI and model hosts. `incidents/` (D-661) has no device authority.
- Do not import `rclpy`. Never modify `core`; a missing robot-contract field is an API reference finding.
- The CLI must not leave followers armed on SIGINT: `stop()` tears the session down.

### Testing Requirements

Remote only (D-584): `tools/remote/remote_pytest.py -- operations/fleet/test`; see the root `AGENTS.md`.
