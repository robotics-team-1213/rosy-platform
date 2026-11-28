
# v1

**Parent context:** `../AGENTS.md`

## Purpose

REST routers under `/api/v1/*` (API Ref §5). One module per domain; `routes.py` only collects them.

## Key Files

| File | Description |
|------|-------------|
| `routes.py` | Aggregator: re-exports every router for `app.py`. No endpoints live here |
| `common.py` | `viewer`/`operator`/`admin` role deps and `enter_navigation_mode` (D-2) |
| `safety.py` | SAF-001 stop/release, SAF-004 limits, SAF-005 battery policy |
| `motion.py` | D-603 `POST/GET/DELETE /motion/rotate_to`: bounded in-place turn (lease owner or named operator) |
| `swarm.py` | SWM-002 follow/cancel/state. 501 when the capability does not declare `swarm.follow` |
| `trip_lease.py` | D-541 Fleet trip lease open/renew, release, takeover (fence lives in `common.require_calibration_owner`) |

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
- **Router-facing domain types come from `api.deps`.** `Mode`, `NavigationError`, `Dock*`, `LineFollowMode`, `valid_costmap_scope`, `worst`, `SwarmError`, `Waypoint` are re-exported there — v1 modules must not import `core_features` directly (결합도 평가 2026-09-19 §7-5; pinned by `middleware/core/gateway/test/test_v1_import_boundary.py`).
- Tests that patch a route helper must name the domain module (`core.api.v1.host._agent`); patching the aggregator re-export has no effect.

### Testing Requirements

`python3 -m pytest middleware/core/gateway/test/test_api.py -v`

### Common Patterns

`Depends(viewer|operator|admin)` + `get_services`. Return pydantic `model_dump()`.

## Dependencies

### Internal

- `api.deps` (auth + re-exported domain types), `HostAgentClient`

### External

- FastAPI, pydantic
