
# test

**Parent context:** `../AGENTS.md`

## Purpose

pytest for fleet geometry, assignment, robots, transport, relay, arming,
session, CLI, hub, and the import-boundary check. No ROS. Fakes only — no network.

## Key Files

| File | Description |
|------|-------------|
| `conftest.py` | Puts `operations/fleet`, `contracts/foundation`, `middleware/core/services` on `sys.path` so pytest runs without colcon install |
| `fakes.py` | Fake `RobotClient` + `FakeClock` shared by relay/session/hub tests — no network |
| `test_package.py` | Package import and D-18 schema reuse |
| `test_robots.py` | `robots.yaml` load/write and per-robot tokens (D-30) |
| `test_transport.py` | `HttpRobotClient` REST, including e-stop `POST /api/v1/safety/stop` |
| `test_relay.py` | D-31 byte-for-byte fan-out; a stopped stream reads 0 Hz |
| `test_boundaries.py` | Package-wide `rclpy` ban; hub may import `core_common.protocol.schemas` only |
| `test_hub.py` | SiteHub gather/scatter and role-violation tests (D-59) |
| `test_server_holder_imports.py` | D-798: every `SERVER_HOLDERS` file still resolves as `fleet.server.<name>` |
| `test_trip_loop_offset.py` | D-432 start offset of the 0.5 s trip loop: first tick at once, then one period plus the offset |
| `test_site_rules.py`, `test_site_rules_http.py` | D-982 site rules: defaults equal the old constants, safety bounds, draft/activate/audit, judge tables, live wiring, HTTP surface |

## Subdirectories

None (ignore `__pycache__/`).

## For AI Agents

### Working In This Directory

- Tests use fakes (`fakes.py`) and `settle()`-style polling, never wall-clock `sleep`.
- SiteHub tests live in `test_hub.py`. Do not stand up a listen server or touch `core`.
- `test_boundaries.py` walks the import graph; a new hub/swarm file that imports `rclpy` fails here.

### Testing Requirements

```bash
python -m pytest operations/fleet/test -v
```

No ROS required — `conftest.py` puts `contracts/foundation` on `sys.path` for the schema import.

## Dependencies

### Internal

- `fleet` package (source tree import)
- `core_common.protocol.schemas` (D-18)

### External

- pytest, httpx, pydantic
