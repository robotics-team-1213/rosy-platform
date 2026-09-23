<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-09 | Updated: 2026-09-17 -->

# fleet

## Purpose

Fleet-side seed (ROSY-FLEET-SRS-001 FOR-001~004). Formation geometry (FOR-001), slot
assignment (FOR-002), a reference-stream relay from one leader to N followers (D-31), and
the FOR-004 formation session (arm → relay → watch → hold), the CLI that opens a
session, and the **Fleet 서버 v1** (`fleet console`) — 관제 PC 에서 N대를 한 화면에
모으고 로봇별 목표·취소·전체 정지를 내리는 사이트 오케스트레이터다(site-fabric 설계 §2,
전환 순서 3단계). SiteHub는 계약 gather/scatter이며 ROS가 없다. SiteHub 자체는 UI가
아니다 — UI 는 `server/` 가 들고, scatter 는 SiteHub 를 통해 나간다. Consumes the robot contract
only — it never modifies `core` — and imports `core_common.protocol.schemas` for
schema reuse (D-18). No ROS imports anywhere in this package.

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_python; `core_common` is an `exec_depend` for colcon build order only — this package's code has no ROS import (D-18, D-126) |
| `setup.py` | Console script `fleet=fleet.cli:main` |
| `fleet/formation/geometry.py` | `Formation`, `SlotOffset`, `slots()` — FOR-001, pure functions |
| `fleet/formation/assignment.py` | `SlotAssigner` protocol, `GreedyDistanceAssigner` — FOR-002, pure functions |
| `fleet/swarm/robots.py` | `RobotEndpoint`, `load_robots()` / `write_robots()` for `robots.yaml` (per-robot token, D-30) |
| `fleet/swarm/transport.py` | `RobotClient` protocol and `HttpRobotClient` (httpx + websockets) — the only place that calls the robot contract |
| `fleet/swarm/relay.py` | `Relay`: leader pose socket 1 → follower reference sockets N, byte-for-byte fan-out (D-31) |
| `fleet/swarm/arming.py` | `FormationSpec` + pure pre-check/assignment planning, finished before the relay is touched |
| `fleet/swarm/session.py` | `FormationSession`: arm → relay → watch → FOR-004 (HOLD/ABORT policy) |
| `fleet/hub/registry.py` | Online snapshot and event seq |
| `fleet/hub/hub.py` | Envelope handle + scatter_estop |
| `fleet/cli.py` | `fleet relay ...` / `formation ...` / `console ...` |
| `fleet/server/console.py` | `FleetConsole`: N대 상태 gather + goal/cancel/e-stop scatter. 하달한 목표를 기억하는 곳(D-12) |
| `fleet/server/signals.py` | 신호등 계약(ROSY-SIGNAL-001) 클라이언트: signals.yaml 로더(`observer_url`·`observer_map` 포함), `HttpSignalClient`, `SignalConsole`(의도 재단언·all_red scatter·**3자 교차 검증 `verify` 행**), `cross_check()`, `HttpSignalObserver` — `swarm/` 과 별개 계약이라 별도 파일 |
| `fleet/server/app.py` | FastAPI 표면 — `/api/fleet/*` 와 `/console` UI |
| `fleet/server/web/` | 관제 UI 정적 자산 (CSP `style-src 'self'` — 인라인 스타일 금지) |
| `test/fakes.py` | Fake `RobotClient` + `FakeClock` shared by relay/session tests — no network |
| `test/fake_signals.py` | Fake `SignalClient` — 장치의 409/403/충돌 가드 응답 모양을 고정 + `FakeObserver`/`observed_body()` (관측 v0.3 본문) |
| `test/conftest.py` | Puts `src/site/fleet`, `src/core/core_common`, and `src/core/core_features` on `sys.path` so pytest runs without colcon install |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `fleet/formation/` | Pure geometry and slot-assignment functions — no transport, no ROS (see `fleet/formation/AGENTS.md`) |
| `fleet/swarm/` | Robot endpoints, transport, relay, arming, and the formation session (see `fleet/swarm/AGENTS.md`) |
| `fleet/hub/` | D-59 SiteHub: hello/heartbeat/event gather, REST scatter — no rclpy, no cmd_vel, no Image (see `fleet/hub/AGENTS.md`) |
| `fleet/server/` | 관제 PC 의 Fleet 서버와 UI (see `fleet/server/AGENTS.md`) |
| `test/` | pytest for geometry, assignment, robots, transport, relay, arming, session, CLI, hub, and the import-boundary check (see `test/AGENTS.md`) |
| `resource/` | ament index marker `fleet` |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- `formation/` and `swarm/arming.py` are pure — no `httpx`, `websockets`, `asyncio`, or `rclpy` imports. `test/test_boundaries.py` enforces this by walking the import graph.
- The relay forwards leader frames byte-for-byte and never synthesizes one. A stream that stops must read 0 Hz, not repeat the last frame.
- HOLD (FOR-004's whole-formation hold) is made by pausing the relay, not by a new endpoint (design §6.4, D-35 candidate).
- Everything that can be refused without touching a robot is decided in `arming.py` before `relay.pause()` is called — a rejected `reform` must leave a running formation exactly as it was.
- Never modify `core` from here. If the robot contract is missing something this package needs, that is a finding for an API Ref cycle, not a local patch.
- Tests use fakes (`test/fakes.py`) and `settle()`-style polling, never wall-clock `sleep`.

### Testing Requirements

```bash
python -m pytest src/site/fleet/test -v
python -m flake8 src/site/fleet --max-line-length=120
```

No ROS required — `conftest.py` puts `src/core/core_common` on `sys.path` for the schema import.

### Common Patterns

- `robot_id → RobotEndpoint(base_url, token)` loaded from `robots.yaml`; tokens are device-local (D-30).
- `SlotAssigner` is a `Protocol` so the greedy v1 assigner can be swapped for a Hungarian one without touching callers (FOR-002).
- `FormationSession` state machine: `IDLE` / `ARMING` / `RUNNING` / `HOLDING` / `STOPPED`; `pending_triggers` accumulate while holding and block `resume()` until cleared.

## Dependencies

### Internal

- `core_common` — schema reuse only (`core_common.protocol.schemas`, D-18); colcon build order via `exec_depend` (D-126)

### External

- fastapi + uvicorn (`fleet console` 만 쓴다 — 릴레이·대형 CLI 는 없이도 돈다)
- httpx
- websockets ≥ 14 (`InvalidStatus`, new asyncio client; 17 in dev)
- PyYAML
- pydantic

<!-- MANUAL: -->
