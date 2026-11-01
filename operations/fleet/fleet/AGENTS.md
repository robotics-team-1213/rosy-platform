<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-11-02 -->

# fleet (Python package)

**Parent context:** `../AGENTS.md`
**Updated:** 2026-11-02

## Purpose

The `fleet` package is ROSY Platform's site coordinator: it sees every robot on the site, decides
who goes where and in what order, admits and records that work in its ledgers, and asks each
robot's CORE to do it. It is the service behind the Rosy Fleet screens (`applications/fleet/web`).
No ROS imports anywhere (`test/test_boundaries.py`).

## Fleet's role in the platform

| Owner | Owns | Does not own |
|---|---|---|
| **Fleet** (this package) | Site map, trips, order and gaps, traffic blocks, charge-bay plan, task/mission ledgers, admission, claims, dispatch, site e-stop fan-out, stuck/incident handling, accounts | Final wheel command, local safety latch, a robot's own docking/line motion |
| **CORE** (on each robot) | Final Base command (`/cmd_vel`), safety latch (10 %·5 % battery, E-stop), line following and the 20 Hz following loop, docking motion | Site order, other robots, the site map |
| **World** (`operations/world`) | Current map pose projection; `source=bridged` is dead reckoning, not a forecast | Ledgers, dispatch |
| **Vision / Decision** | Ceiling-camera sightings / candidates and model proposals | Ledger writes, robot commands |
| **Business apps** (Harbor) | Their own business ledger and proposals, read through Fleet HTTP only | Robots, approval, charging |

Contracts behind this table: [app responsibilities](../../../docs/reference/app-responsibilities.md),
[Fleet rulebook](../../../docs/reference/fleet-rulebook.md) (observe → law → candidate → admission →
dispatch → readback), [folder responsibilities](../../../docs/reference/platform-folder-responsibilities.md).
D-941 7 places charging in ROSY: Fleet plans, CORE moves, Harbor only shows.

## Packages and modules

Authority: **pure** = no I/O, inputs to outputs; **view** = read-only route or journal;
**ledger** = writes Fleet's own tables; **robot** = sends a request to a robot or host.

| Path | Role | Authority |
|---|---|---|
| `server/` | FastAPI app, routes, ledgers, trip runner, dispatchers (see `server/AGENTS.md`) | ledger, robot |
| `swarm/` | Robot endpoints and `HttpRobotClient` — the only robot-contract client; relay and FOR-004 formation session (see `swarm/AGENTS.md`) | robot |
| `hub/` | D-59 SiteHub: hello/heartbeat/event gather, REST scatter, site e-stop (see `hub/AGENTS.md`) | robot |
| `traffic/` | D-517 block table, junction holds, wait-cycle resolver; `trip_authority` sends CORE its movement authority when enabled | pure, robot |
| `stuck/` | D-438/D-577 stuck board, rules and resolver loop that answers CORE stucks (see `stuck/AGENTS.md`) | ledger, robot |
| `incidents/` | D-661 named incident ownership and team notifications; no device authority (see `incidents/AGENTS.md`) | ledger |
| `observe/` | Credential-free CORE event and observation journals | view |
| `localization/` | D-395 pose arbiter: bounded cue scoring, decides only with a margin (see `localization/AGENTS.md`) | pure |
| `routing/` | D-489/D-490 lane A* planner, snapping, teaching rules | pure |
| `formation/` | FOR-001/002 slot geometry and assignment (see `formation/AGENTS.md`) | pure |
| `meet/` | Algorithms for robots meeting on one lane; the resolver sends their order | pure |
| `guide/` | D-536 robot situation and guide, read by `server/guide_service.py` | pure |
| `site_map.py` | D-488 `rosy.site_map/1`: places, directed lanes, bans, crosswalks | pure |
| `lane_route.py` | Ordered lane edges to one polyline and the next point | pure |
| `charge_bays.py` | D-941 5/7 charge-bay plan: who goes to which bay, when to leave; `GET /api/fleet/charge-bays` | pure (shown, not dispatched) |
| `lane_progress.py` | D-941 2 loop progress `s`, leader and gap; `GET /api/fleet/platoon` | pure (shown, not dispatched) |
| `speed_table.py` | D-941 3 speed table v(s): lane cap, measured curve cap, stripe slow zones, braking ahead | pure (not sent yet) |
| `host_control.py` | Allowlisted reboot/restart of site, AI and model hosts | robot (hosts) |
| `cli.py`, `console_site_config.py` | `fleet relay` / `formation` / `console` entry points and site config | — |
| `bench.py` | Public surface for the Gazebo swarm bench (D-148) | — |

## For AI Agents

### Working In This Directory

- A new module that calls a robot goes through `swarm/transport.py`; a new ledger writer is
  added to the root `test/architecture/test_fleet_ledger_writers.py` after review.
- D-941 views are read-only (`dispatch: false`). Dispatching from them needs CORE's reverse-in
  docking and the charge-return exception first, with a safety review.
- Do not import `rclpy`. Never modify `core` from this package; a missing robot-contract field is
  an API reference finding.
- The CLI must not leave followers armed on SIGINT: `stop()` tears the session down.

### Testing Requirements

Remote only (`tools/remote/remote_pytest.py -- operations/fleet/test`); see the root `AGENTS.md`.

## Dependencies

### Internal

- `core_common.protocol` (schema reuse, D-18), `rosy.world` (MapPose, D-752), `rosy.execution`

### External

- fastapi, httpx, websockets, pydantic, PyYAML
