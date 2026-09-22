<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-15 -->

# test

## Purpose

pytest for core policy, API, dashboard, and protocol. Most tests import Python modules directly and do not spin rclpy.

## Key Files

| File | Description |
|------|-------------|
| `test_protocol_schemas.py` | Envelope/event schema (P1-19, D-10/D-18) |
| `test_core_logic.py` | State, command mux, safety, waypoints |
| `test_api.py` | FastAPI routes, auth roles, battery/docking endpoints |
| `test_sprint2.py` | Later P1 slices |
| `test_power.py` | IDLE/STANDBY/proximity wake |
| `test_battery.py` | Curve, hysteresis, deep shutdown sentinel (SAF-005, D-27) |
| `test_docking.py` | Dock SM, staging vs sensor closed-loop |
| `test_dashboard.py` | Embedded `/dashboard` assets and CSP |
| `test_host_cards.py` | Dashboard host/network/release cards |
| `test_host_runtime.py` | `HostRuntimeProbe` read-only telemetry |
| `test_ros_graph_monitor.py` | ROS graph snapshot bounds |
| `test_runtime_config.py` | YAML merge / ROSY_CONFIG |
| `test_fleet_agent.py` | FleetAgent stays disconnected |
| `test_audit.py` | LOG-001 file audit retention |
| `test_initial_pose.py` | AMCL covariance, occupancy map id |
| `test_bridge_translate.py` | ROS message → domain dict conversion, with duck-typed messages |
| `test_swarm.py` | SWM follow state machine via `from core.swarm`, 2 Hz cap, stream-loss HOLD |
| `test_swarm_api.py` | SWM-002 REST contract, including the 501 on a capability that says false |
| `test_swarm_stream.py` | `/ws/swarm/pose` envelope and `/ws/swarm/reference` ingest |
| `test_diagnostics_api.py` | DIAG-001 rollup, unknown component, agreement with `/metrics` |
| `conftest.py` | `core_client` fixture: the one place a test stands a robot up |
| `test_goal_tracker.py` | Nav2 goal generations: stale results, the cancel-before-accept window |
| `test_teleop_watchdog_event.py` | SAF-002 expiry announces `safety.watchdog` once per lapse, after the stop reaches the wheels |
| `test_cmd_vel_cycle.py` | `bridge/cmd_vel.py` order: select → readiness HOLD → wheels → power/announce; the bridge calls it once |
| `test_swarm_integration.py` | Real `NavigationManager` + replayed bridge callbacks — the seam a `FakeNav` hides |
| `test_navigation_swarm_boundary.py` | D-60: navigation tree does not import swarm |

## Subdirectories

None (ignore `__pycache__/`).

## For AI Agents

### Working In This Directory

- Inject clocks. Power, battery, and docking tests advance time explicitly.
- Do not import `ros_bridge` at module top in these tests (optional ROS deps).
- Build API clients through the `core_client` fixture, not a local copy of `CoreServices.build`. That wiring keeps growing (docking provider, session-closed and e-stop listeners) and a stale copy passes while diverging from production.
- Swarm tests import `from core.swarm` (`SwarmManager`, `follow_goal`, `ReferencePose`). Do not import `core.navigation.swarm`.
- A `FakeNav`-style double proves the caller, not the seam. Swarm's two worst defects (a HOLD whose cancel never reached Nav2, NAV-006 silently disabled) both lived between the real managers — keep `test_swarm_integration.py` covering that path.
- Asserting that a source file contains a string proves only the wiring. Where a value matters, put the computation in a ROS-free module (`bridge/translate.py`, `navigation/initial_pose.py`) and assert the value.
- When adding an API field, assert it here **and** in `protocol/schemas.py`.

### Testing Requirements

```bash
python3 -m pytest src/core/core/test/ -v
python3 -m pytest src/core/core/test/test_battery.py src/core/core/test/test_api.py -v
```

### Common Patterns

FastAPI `TestClient`; construct `CoreServices` with temp paths.

## Dependencies

### Internal

- `core` package (source tree import)

### External

- pytest, fastapi, pydantic, httpx

<!-- MANUAL: -->
