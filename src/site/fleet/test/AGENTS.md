<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# test

## Purpose

pytest for fleet geometry, assignment, robots, transport, relay, arming,
session, CLI, hub, and the import-boundary check. No ROS. Fakes only — no network.

## Key Files

| File | Description |
|------|-------------|
| `conftest.py` | Puts `src/site/fleet`, `src/contracts/core_common`, `src/runtime/core_features` on `sys.path` so pytest runs without colcon install |
| `fakes.py` | Fake `RobotClient` + `FakeClock` shared by relay/session/hub tests — no network |
| `fake_signals.py` | Fake `SignalClient` — 장치의 409/403/충돌 가드 응답 모양 고정 + `FakeObserver`/`observed_body()` (관측 `/observed` v0.3 본문) |
| `test_server_signals.py` | signals.yaml 로더·상태 파서·`SignalConsole`(재단언·부분 실패·**3자 교차 검증 verify**)·`cross_check` 판정군·`/api/fleet/signals*` 엔드포인트 |
| `test_package.py` | Package import and D-18 schema reuse |
| `test_geometry.py` | FOR-001 formation slot offsets |
| `test_assignment.py` | FOR-002 greedy slot assignment |
| `test_robots.py` | `robots.yaml` load/write and per-robot tokens (D-30) |
| `test_transport.py` | `HttpRobotClient` REST, including e-stop `POST /api/v1/safety/stop` |
| `test_relay.py` | D-31 byte-for-byte fan-out; a stopped stream reads 0 Hz |
| `test_arming.py` | Pure pre-check/assignment planning before the relay is touched |
| `test_session.py` | FormationSession arm → relay → watch → HOLD/ABORT |
| `test_cli.py` | CLI parsing and wiring |
| `test_boundaries.py` | Package-wide `rclpy` ban; hub may import `core_common.protocol.schemas` only |
| `test_hub.py` | SiteHub gather/scatter and role-violation tests (D-59) |

## Subdirectories

None (ignore `__pycache__/`).

## For AI Agents

### Working In This Directory

- Tests use fakes (`fakes.py`) and `settle()`-style polling, never wall-clock `sleep`.
- SiteHub tests live in `test_hub.py`. Do not stand up a listen server or touch `core`.
- `test_boundaries.py` walks the import graph; a new hub/swarm file that imports `rclpy` fails here.

### Testing Requirements

```bash
python -m pytest src/site/fleet/test -v
```

No ROS required — `conftest.py` puts `src/contracts/core_common` on `sys.path` for the schema import.

## Dependencies

### Internal

- `fleet` package (source tree import)
- `core_common.protocol.schemas` (D-18)

### External

- pytest, httpx, pydantic

<!-- MANUAL: -->
