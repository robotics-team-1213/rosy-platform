<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-09 | Updated: 2026-09-17 -->

# fleet

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

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
| `fleet/server/signals.py` | 신호등 계약(ROSY-SIGNAL-001) 클라이언트: `HttpSignalClient`, `SignalConsole`(의도 재단언·all_red scatter·**3자 교차 검증 `verify` 행**), `cross_check()`, `HttpSignalObserver` — `swarm/` 과 별개 계약이라 별도 파일 |
| `fleet/server/signal_config.py` | signals.yaml 로더·라이터와 신호등 endpoint 형식 (`observer_url`·`observer_map` 포함) |
| `fleet/server/app.py` | FastAPI 표면 — `/api/fleet/*` 와 `/console` UI |
| `fleet/server/web/` | 관제 UI 정적 자산 (CSP `style-src 'self'` — 인라인 스타일 금지) |
| `fleet/site_map.py` | D-488 `rosy.site_map/1` 스키마(장소·방향 있는 차로·회전 금지)와 `lane_graph.yaml` 가져오기. 순수 |
| `fleet/routing/` | D-489/D-490 경로 계획기: 차로 단위 상태 A*(`graph`·`cost`·`planner`·`snap`·`trip`). 표준 라이브러리만, 네트워크·DB·시계 없음 |
| `fleet/server/site_map_store.py`, `site_map_routes.py`, `trip_routes.py` | 지도 초안·활성 버전 저장과 활성화(이름 있는 운영자, 진행 중 trip이 있으면 거절), `POST /trip` 계획 응답과 계획 본문 저장 |
| `fleet/server/trip_runner.py` | D-494 5 / D-517 서버 trip 루프(로봇마다 trip 하나, 반복 운행): 시작 검사·상태기계(재시작 뒤 `stopped`)·0.5 s 루프(`lane` 교차로 지시, `free` D-463 점)·다음 장소 재계획 대기. 능력·지도 자세·교차로 지시는 `trip_ports.py`의 포트로 주입, 실행 가능 규칙은 `fleet/routing/execute.py`, trip 중 다른 이동 거절은 `trip_guard.py` |
| `fleet/traffic/lane_traffic.py` | D-517 3 (M1) `TrafficService`: 열린 trip 전부를 `fleet/traffic/blocks.py` 고정 블록 표로 계산해 `GET /api/fleet/traffic`에 보인다. 로봇에 보내지 않는다(M2). trip 루프의 교차로 보류(`holds`)와 고정 점유 갱신도 여기서 한다. 운행 블록 허가를 쓰는 곳은 이 모듈 하나다 |
| `fleet/traffic/handover.py` | D-517 5 (M4) Fleet 해결기의 순수 판단: 교착 순환에서 다음 장소 뒤의 막힌 차로를 피해 갈 수 있는 한 대만 `replan`(운영자 확인 `replan_hold`), 나머지 `wait`, 피할 수 없거나 같은 경로 두 번째면 `human`, 30 s 넘는 UNKNOWN은 `human`. `GET /api/fleet/traffic` `resolver` |
| `fleet/traffic/trip_lease.py` | D-541 7 Fleet trip lease: 현장 설정 `fleet.trip_lease_required`(기본 false)가 참일 때만 연다. trip마다 새 `lease_id`(uuid, 재사용 없음)로 `PUT /trip-lease`, 주기마다 자기 슬롯에서 renew, 끝에서 정지 뒤 `DELETE`. renew가 404·409·`renewed:false`·`ttl_s` 동안 확인 없음이면 trip은 `stopped`/`lease_lost`로 끝나고 다시 열지 않는다. lease 주인은 로봇 REST 토큰이다: Fleet 전용이어야 하고(D-541 1), 관제 토큰과 같으면 app.py가 거절한다 |
| `fleet/server/trip_laps.py` | D-517 2 반복 운행의 순수 계산: 바퀴 경로(`lap_arcs`), 바퀴 끝 판정(`lap_due`), 실패한 바퀴 검사 재시도(`lap_retry_due`), 다음 바퀴 잇기·지난 바퀴 정리(`carry_on`). 로봇을 부르지 않는다 |
| `fleet/server/trip_halts.py` | D-494/D-517 로봇 정지: `TripHalts.halt_robot`, 재시작 뒤 열려 있던 trip의 로봇 정지(`run_restart`, `halt_restarted`). 교차로·취소 포트만 쓴다 |
| `test/fakes.py` | Fake `RobotClient` + `FakeClock` shared by relay/session tests — no network |
| `test/fake_signals.py` | Fake `SignalClient` — 장치의 409/403/충돌 가드 응답 모양을 고정 + `FakeObserver`/`observed_body()` (관측 v0.3 본문) |
| `test/conftest.py` | Puts `operations/fleet`, `contracts/foundation`, and `middleware/core/services` on `sys.path` so pytest runs without colcon install |
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
| `tools/` | Developer-only Fleet tools, not installed: `fleet_gather_bench.py` (D-131 polling-gather scale bench; `python -X utf8 operations/fleet/tools/fleet_gather_bench.py --robots 20`) |
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
python -m pytest operations/fleet/test -v
python -m flake8 operations/fleet --max-line-length=120
```

No ROS required — `conftest.py` puts `contracts/foundation` on `sys.path` for the schema import, and appends `test/` so browser tests import `browser_harness`.

Browser tests (`*_browser.py`) are opt-in with `ROSY_RUN_BROWSER_TESTS=1` (the older `ROSY_BROWSER_TESTS=1` also works). Run only the ones a change reaches: `t=$(python test/browser_scope.py <changed paths...>) && ROSY_RUN_BROWSER_TESTS=1 python -m pytest $t`. Run the full browser set on the site PC or model PC, not the dev laptop (`docs/reference/developer-guide.md` 「브라우저 시험」). Serve test pages through `browser_harness.safe_listener()`, never port 0.

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
