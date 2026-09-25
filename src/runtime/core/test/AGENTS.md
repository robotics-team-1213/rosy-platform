<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-24 -->

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
| `test_dashboard.py` | Embedded `/dashboard` assets and CSP |
| `test_host_cards.py` | Dashboard host/network/release cards |
| `test_host_runtime.py` | `HostRuntimeProbe` read-only telemetry |
| `test_ros_graph_monitor.py` | ROS graph snapshot bounds |
| `test_runtime_config.py` | YAML merge / ROSY_CONFIG |
| `test_fleet_agent.py` | FleetAgent stays disconnected |
| `test_initial_pose.py` | AMCL covariance, occupancy map id |
| `test_bridge_translate.py` | ROS message → domain dict conversion, with duck-typed messages |
| `test_swarm_api.py` | SWM-002 REST contract, including the 501 on a capability that says false |
| `test_swarm_stream.py` | `/ws/swarm/pose` envelope and `/ws/swarm/reference` ingest |
| `test_diagnostics_api.py` | DIAG-001 rollup, unknown component, agreement with `/metrics` |
| `conftest.py` | `core_client` fixture: the one place a test stands a robot up |
| `test_goal_tracker.py` | Nav2 goal generations: stale results, the cancel-before-accept window |
| `test_event_catalogue.py` | §8 catalogue vs the emit sites across all five core packages: names, payload keys, severity, sender |
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
- A new event needs a row in §8 of the API reference before `test_event_catalogue.py` passes, with its real payload keys and severity. That is deliberate: an undocumented event sits outside the deprecation policy, so it can vanish without anyone having broken a promise.
- That test reads the emit sites, not a list of known events. An earlier version kept an exclusion list and the list hid `battery.deep` — a `critical` event — so a guard made of hand-maintained names drifts exactly like the document it guards. The four relay bodies it trusts (`_emit`/`_emit_all`) are pinned by fingerprint; editing one means re-reading it and updating `PINNED_RELAYS`.

### Testing Requirements

```bash
python3 -m pytest src/runtime/core/test/ -v
python3 -m pytest src/runtime/core/test/test_battery.py src/runtime/core/test/test_api.py -v
```

### Common Patterns

FastAPI `TestClient`; construct `CoreServices` with temp paths.

## Dependencies

### Internal

- `core` package (source tree import)

### External

- pytest, fastapi, pydantic, httpx

<!-- MANUAL: -->
