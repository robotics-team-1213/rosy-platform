<!-- Parent: ../AGENTS.md -->

# test

**Parent context:** `../AGENTS.md`

## Purpose

pytest for core policy, API, dashboard, and protocol. Most tests import Python modules directly and do not spin rclpy. `conftest.py` holds the `core_client` fixture, the one place a test stands a robot up. `ls` shows the test files (named for their subject).

## For AI Agents

### Working In This Directory

- Use FastAPI `TestClient` and construct `CoreServices` with temp paths. Inject clocks. Power, battery, and docking tests advance time explicitly.
- Do not import `ros_bridge` at module top in these tests (optional ROS deps).
- Build API clients through the `core_client` fixture, not a local copy of `CoreServices.build`. That wiring keeps growing (docking provider, session-closed and e-stop listeners) and a stale copy passes while diverging from production.
- Swarm tests import `from core.swarm` (`SwarmManager`, `follow_goal`, `ReferencePose`), not `core.navigation.swarm` (D-60: navigation does not import swarm).
- A `FakeNav`-style double proves the caller, not the seam. Swarm's two worst defects (a HOLD whose cancel never reached Nav2, NAV-006 silently disabled) lived between the real managers: keep `test_swarm_integration.py` covering that path.
- Asserting that a source file contains a string proves only the wiring. Where a value matters, put the computation in a ROS-free module (`bridge/translate.py`, `navigation/initial_pose.py`) and assert the value.
- When adding an API field, assert it here **and** in `protocol/schemas.py`.
- A new event needs a row in §8 of the API reference before `test_event_catalogue.py` passes, with its real payload keys and severity: an undocumented event sits outside the deprecation policy and could vanish without anyone breaking a promise.
- `test_event_catalogue.py` reads the emit sites, not a list of known events (a hand-kept exclusion list once hid the `critical` `battery.deep`). The four relay bodies it trusts (`_emit`/`_emit_all`) are pinned by fingerprint; editing one means re-reading it and updating `PINNED_RELAYS`.
- `test_cmd_vel_cycle.py` pins the `bridge/cmd_vel.py` order (select → readiness HOLD → wheels → power/announce); the SAF-002 `safety.watchdog` announcement comes once per lapse, after the stop reaches the wheels.

### Testing Requirements

```bash
python3 -m pytest middleware/core/gateway/test/ -v
```

<!-- MANUAL: -->
