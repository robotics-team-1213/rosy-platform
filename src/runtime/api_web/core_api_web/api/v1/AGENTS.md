<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-21 -->

# v1

## Purpose

REST routers under `/api/v1/*` (API Ref §5). One module per domain; `routes.py` only collects them.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `routes.py` | Aggregator: re-exports every router for `app.py`. No endpoints live here |
| `common.py` | `viewer`/`operator`/`admin` role deps and `enter_navigation_mode` (D-2) |
| `system.py` | IDN-003 identity, CAP-001 capabilities, SEC-101 tokens, host runtime |
| `robot.py` | State/pose/battery/velocity, sensors, PWR-001 power modes |
| `control.py` | `POST /mode`, `POST /teleop` |
| `safety.py` | SAF-001 stop/release, SAF-004 limits, SAF-005 battery policy |
| `navigation.py` | NAV-001~004/006 goals, NAV-005 SLAM session, `/localization/initialpose` |
| `map.py` | MAP-003 occupancy and costmap snapshots (`svc.maps`) |
| `waypoints.py` | WPT-002 waypoint CRUD (`svc.waypoints`) |
| `docking.py` | DNC-003/005 dock registry, teach, dock/undock |
| `swarm.py` | SWM-002 follow/cancel/state. 501 when the capability does not declare `swarm.follow` |
| `observability.py` | EVT-003 events, LOG-001 audit, DIAG-001 diagnostics, OBS-101 `/metrics` |
| `host.py` | Host Agent relay: network, release, commissioning |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Prefixes are the contract. Do not rename `/api/v1/robot/state` etc. without API ref + tests.
- Map snapshots: `GET /api/v1/map`, `/navigation/path`, `/map/costmap?scope=global|local`. Missing grid is 404; empty path is `[]`.
- `POST /mode` allows IDLE|MANUAL|NAVIGATION only (not DOCKING/EMERGENCY via this body).
- Host card endpoints proxy Host Agent; never fabricate telemetry (`host_agent_client`).
- Docking and battery routes were extended on `feat/battery-integrity-low-battery-alert`.
- A new endpoint goes in its domain module, never in `routes.py`. A new domain gets a module and one line in the aggregator.
- **One module, one owning service (C5).** List the `svc.<field>` names a module's endpoints *mutate*, or that a router is
  *named after* — reads do not count — minus the ambient `{state, events, capability, modes, config}`. Two owners backed by
  different packages is a finding: split, or record why not. `control.py`, `safety.py` are recorded accepts; see
  `docs/plans/2026-09-06-module-split-criteria.md`. Router count is not the test — `robot.py` has three routers and one owner.
- `slam_router` lives in `navigation.py` because there is no `mapping` service to own it, not because `nav` is its owner.
- SLAM save names are safe basenames only; do not allow callers to choose an arbitrary filesystem path.
- **Router-facing domain types come from `api.deps`.** `Mode`, `NavigationError`, `Dock*`, `LineFollowMode`, `valid_costmap_scope`, `worst`, `SwarmError`, `Waypoint` are re-exported there — v1 modules must not import `core_features` directly (결합도 평가 2026-09-19 §7-5; pinned by `src/runtime/gateway/test/test_v1_import_boundary.py`).
- Tests that patch a route helper must name the domain module (`core.api.v1.host._agent`); patching the aggregator re-export has no effect.

### Testing Requirements

`python3 -m pytest src/runtime/gateway/test/test_api.py -v`

### Common Patterns

`Depends(viewer|operator|admin)` + `get_services`. Return pydantic `model_dump()`.

## Dependencies

### Internal

- `api.deps` (auth + re-exported domain types), `HostAgentClient`

### External

- FastAPI, pydantic

<!-- MANUAL: -->
