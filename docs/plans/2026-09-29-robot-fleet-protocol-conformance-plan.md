# 로봇 ↔ 사이트 관제 통신 적합성 계획 (D-382)

**ADR:** [D-382](../adr/D-382-robot-site-console-protocol-conformance.md) (Proposed)
**작성:** 2026-09-29. 기준 커밋 `main` 9b3cfb59.
**목표:** 로봇(CORE)과 관제(Fleet)가 ROSY-API-REF-001대로 실제로 통신하는지 판정한다. 판정은 두 쪽이 함께 읽는 계약 스냅샷과, 실물 로봇에 읽기 전용으로 붙는 탐침으로 한다. 마지막에 관제 DEVICE 증거 다섯 항목(D-382 Decision 5)을 모은다.

## 범위 밖

- 천장 카메라 페어링: D-341, 브랜치 `docs/d341-overhead-console-pairing`. 이 계획은 그 설계를 다시 정하지 않는다. S4 벤치는 카메라 경로를 켜 둔 채 로봇 경로만 본다.
- 관제 지도 사이트 레이어: 브랜치 `feat/console-site-map-layer`(D-257, `GET /api/fleet/site-map`). 로봇 프로토콜을 건드리지 않는다. S5의 지도 항목 ②는 로봇 `map` 표시만 보며, 사이트 사각형 레이어가 합쳐져 있으면 같은 화면에서 함께 기록한다.
- 로봇 이미지 재빌드·서명·배포, TLS 도입, PRT-004 envelope 상관(D-297), 이동·정지 명령의 실물 시험.

## 규칙

- 단계마다 먼저 실패하는 시험을 쓰고, 고치고, 단계 끝에 커밋한다. 커밋 메시지는 `Co-Authored-By` 줄로 끝난다.
- Windows에서는 `python`을 쓴다. pytest는 `--basetemp`를 `X:\DevTemp\...` 아래로 준다.
- 토큰은 환경 변수로만 다룬다. 저장소·로그·보고서에 남기지 않는다. 보고서에는 `***`로 가린다.
- 실물 로봇에는 S3 탐침의 읽기 전용 모드와 S5의 명시적 회차만 붙는다. SSH 금지.
- 모듈 기록: 바꾼 모듈의 `logs.md`에 추가하고, gate가 바뀌면 `progress.md`를 고치고, `python tools/harness/rosy_harness.py generate` 후 `lint`.

## S1 — 계약 스냅샷과 판 올림 규칙

**왜:** 발견 2·3. 로봇이 어느 판을 서빙하는지 알 수 없고, `main`의 정렬 시험이 실패 중이다.

**파일**
- 새 `tools/protocol/snapshot_core_openapi.py`: `src/runtime/gateway/test/conftest.py`와 같은 경로·설정으로 `create_app().openapi()`를 만든다. 키를 정렬하고 `description`·`info`의 판 문자열을 떼어 정규화한 뒤 `docs/reference/contracts/core-openapi.v1.json`과 `.sha256`을 쓴다.
- 새 `docs/reference/contracts/core-openapi.v1.json`, `core-openapi.v1.sha256`.
- `src/runtime/api_web/core_api_web/api/app.py`: description을 문서 판(v1.56 → 이 변경으로 v1.57)으로 맞춘다. `info.version`을 올린다. `GET /api/v1`에 `contract_version`, `schema_sha256`을 더한다(additive, 공개 유지).
- `docs/reference/ROSY API & Protocol Reference.md`: 헤더 v1.57, 변경 이력 행. §5에 `GET /api/v1` 응답 필드. 발견 9의 문서 정정(Hub 경로·포트, `correlation_id` 본문 필드, `long_term_token` 미발급, `last_event_seq`)을 Clarify로 함께 적는다. `/metrics`·`/openapi.json`·`/docs`의 공개 여부를 적는다.

**시험 (먼저 실패)**
- 새 `src/runtime/gateway/test/test_core_openapi_snapshot.py`: 현재 `openapi()` 정규화 결과 == 스냅샷, 해시 == `.sha256`, `GET /api/v1`의 `schema_sha256` == 스냅샷 해시, `contract_version` == 문서 헤더.
- 기존 `test_protocol_version_alignment.py`가 통과해야 한다(지금 1 failed).
- 규칙 시험: 스냅샷 해시가 바뀌었는데 문서 판이 그대로면 실패하도록 `.sha256` 옆에 판 번호를 함께 기록하고 비교한다.

**완료 기준:** 위 시험 통과. gateway 스위트 회귀 없음. `python tools/protocol/snapshot_core_openapi.py --check`가 0으로 끝난다.

## S2 — 두 쪽이 같은 벡터를 읽는 계약 시험, Hub·Agent 결함 재현

**왜:** 공유 벡터가 없다. 발견 6(Hub 세션 결속)·7(재시작 뒤 seq)을 시험으로 먼저 잡는다.

**파일**
- 새 `test/fixtures/protocol/`:
  - `envelopes/hello.json`, `welcome.json`, `heartbeat.json`, `event.json`, `error_duplicate_identity.json`
  - `rest/robot_state.response.json`, `map.response.json`, `navigation_goal.request.json`(`correlation_id` 포함), `navigation_goal.request.legacy.json`(없음)
  - `README.md`: 각 벡터의 원천(스냅샷 경로 또는 `schemas.py` 모델)
- 새 `src/runtime/gateway/test/test_protocol_vectors_core.py`: envelope 벡터가 `schemas.py` 모델로 왕복한다. REST 벡터가 스냅샷 스키마로 검증된다(`jsonschema`가 없으면 스냅샷에서 필요한 필드만 읽는 작은 검사기).
- 새 `src/site/fleet/test/test_protocol_vectors_fleet.py`: `transport.py`가 만드는 요청 본문이 벡터와 같고, 벡터 응답을 Fleet이 파싱한다. CORE 코드를 import하지 않고 스냅샷 JSON만 읽는다(D-18/D-59, `test_boundaries.py`).
- 결함 재현 시험:
  - `src/site/fleet/test/test_hub.py`: 로봇 A로 짝지은 소켓이 `robot_id=B` 이벤트를 보내면 거절한다. 연결이 끊긴 로봇 id로 HELLO 없이 보낸 HEARTBEAT를 거절한다. (지금 실패)
  - `src/runtime/gateway/test/test_fleet_agent.py`: Agent 재시작 후 WELCOME `last_event_seq`가 이전 프로세스의 큰 값이어도 새 이벤트가 전송된다. Agent가 보낸 뒤에도 EventBus 링 버퍼의 `seq`는 바뀌지 않는다. `stop()`이 예외 없이 끝난다. (지금 실패)
- 고침: `src/site/fleet/fleet/hub/hub.py`·`server.py`(소켓별 인증 id, 끊기면 해제, `hmac.compare_digest`), `src/runtime/services/core_features/fleet_agent/agent.py`(사본에 seq 부여, 재시작을 구분하는 부팅 세대, 올바른 구독 해제). envelope에 필드가 늘면 `schemas.py`와 API Ref MINOR를 같은 커밋에서 올리고 S1 스냅샷 규칙을 따른다.

**완료 기준:** 새 시험과 기존 `test_console_hub_integration.py` 통과. Fleet·gateway·services 스위트 회귀 없음.

## S3 — 읽기 전용 적합성 탐침 `tools/protocol/conformance_probe.py`

**파일**
- 새 `tools/protocol/conformance_probe.py`. 표준 라이브러리 + `httpx`·`websockets`, `zeroconf`는 선택.
  - `--base http://192.168.1.202:8080`, 또는 `--mdns rosy-pinky-8kcn`으로 `_rosy._tcp`를 찾는다.
  - 공개 등급(기본): `GET /api/v1`, `GET /openapi.json`를 정규화해 스냅샷과 비교(경로·스키마 차이 목록), `GET /metrics` 형식, 토큰 없는 `robot/state`·`map`·`events` → 401, WS `/ws/state`·`/ws/events` → 4401, TXT 대조(프로파일 표).
  - viewer 등급: `ROSY_CORE_TOKEN`이 있을 때만. `system/info`, `robot/state`(신선도: 수신 시각 − 본문 `ts`), `map`(크기·해상도·frame), `events?limit=20`, WS `/ws/events` 5초 수신. 쓰기 요청은 코드에 없다.
  - Fleet 등급: `--fleet http://127.0.0.1:8090`과 `ROSY_FLEET_TOKEN`이 있을 때만. `/healthz`, 관제 roster·이벤트 조회 API.
  - 출력: `--out <json>` 보고서(판정 PASS/FAIL/SKIP, 원인, 서빙 판·스냅샷 판, 차이). 토큰은 어디에도 쓰지 않는다.
- 새 `test/test_conformance_probe.py`: 가짜 CORE(FastAPI TestClient 또는 로컬 uvicorn)로
  - 스냅샷과 같으면 PASS, `GoalRequest.correlation_id`가 빠진 openapi면 FAIL과 차이 항목 이름.
  - 토큰이 없으면 viewer 검사는 SKIP.
  - 탐침 코드에 POST/PUT/DELETE/PATCH 호출이 없음을 소스 검사로 고정.
  - 보고서 JSON에 토큰 문자열이 나오지 않음.
- `tools/sim/probe_*.sh`: 토큰을 받거나 새 탐침을 가리키도록 고친다(발견 10).

**완료 기준:** 단위 시험 통과. 실물 공개 등급 실행 결과를 `docs/validation/2026-09-2x-robot-fleet-conformance-readonly.md`에 남긴다. 2026-09-29 수동 관측과 같은 차이(상관 ID 없음, 판 v1.41)를 탐침이 자동으로 보고해야 한다.

## S4 — Windows 벤치 런북: 이 PC의 Fleet ↔ 실물 로봇

**기준선(2026-09-29, 병행 벤치):** 이 PC(192.168.1.102)에서 Fleet `127.0.0.1:8090`(`robots.yaml` → `http://192.168.1.202:8080`, 토큰 대기), Vision `0.0.0.0:8095`, Caddy `127.0.0.1:8443`, S21 휴대폰이 Vision으로 송출.

**파일**
- 새 `docs/deployment/windows-fleet-bench-real-robot.md`. 내용:
  1. `robots.yaml`은 저장소 밖 `X:\DevTemp\...\bench\robots.yaml`에 둔다. `robot_id`, `base_url: http://192.168.1.202:8080`, `token`(CORE 운영자 토큰, 따옴표 문자열), 선택 `fleet_pairing_token`(REST 토큰과 달라야 함, `swarm/robots.py:46`).
  2. REST만 볼 때(관제 ①②): `fleet console --host 127.0.0.1 --port 8090 --robots <path> --token-env ROSY_FLEET_TOKEN --events-db <path> --tasks-db <path>`(`fleet=fleet.cli:main`; 설치 없이 `src/site/fleet`을 `PYTHONPATH`에 두고 `python -m fleet.cli console ...`). 루프백에서는 `--token`이 없어도 뜨지만 그러면 모든 API가 `site-console` 운영자로 통과한다(`server/app.py:459-460`). 벤치에서도 `--token-env`를 쓴다. 기존 `tools/fleet_console.ps1`(LAN 공개, `%LOCALAPPDATA%\rosy\robots.yaml`)과 겹치는 부분은 런북이 그 스크립트를 가리킨다.
  3. 이벤트 이력까지 볼 때(관제 ③): 로봇이 PC에 닿아야 한다. `--host 0.0.0.0`(또는 192.168.1.102)이면 `fleet/cli.py:312-315`대로 `--token`/`--token-env` 또는 `--users-file`, 그리고 `--tasks-db`가 필수다. Windows 방화벽에서 8090 인바운드를 이 LAN에만 연다. 로봇 쪽 `fleet.hub_url`·`fleet.pairing_token` 설정은 사용자가 로봇 대시보드/운영 절차로 넣는다(이 계획은 로봇에 SSH하지 않는다). Caddy 8443 경로를 쓰면 로봇이 사이트 CA를 믿어야 하므로 `fleet.discovery.ca_file` 절차를 따른다(`deploy/site/README.md`).
  4. 확인 순서: S3 탐침 공개 → viewer → Fleet 등급.
  5. 정리: 벤치 파일 삭제, 로봇 측 `hub_url` 원복 여부를 사용자와 확인.
- `deploy/site/robots.yaml.example`: 로봇 광고가 `tls=none`, 8080임을 주석으로 적고 `http://` 예를 함께 둔다(발견 5).

**완료 기준:** 런북 절차를 벤치에서 한 번 따라가고 출력 요약을 validation 문서에 붙인다(LOCAL + DEVICE 읽기 전용).

## S5 — 관제 DEVICE 증거 회차

**전제:** 사용자 입회, CORE 운영자 토큰, `fleet_pairing_token`과 로봇 쪽 설정. ④에는 v1.44 이상 이미지.

| 항목 | 방법 | 기록 |
|---|---|---|
| ① roster·신선도 | 관제 화면 + 탐침 Fleet 등급 | 수신 시각 − `ts`, 5분 동안 끊김 수 |
| ② 지도 | 관제 지도 캡처(사이트 레이어 있으면 함께) | `map` 크기·해상도·frame |
| ③ 이벤트 이력 | FleetAgent HELLO 수락 → 이벤트 SQLite 누적 → Fleet 재시작 → 이력 유지. S2 수정이 들어간 이미지에서는 CORE 재시작 뒤 이벤트가 이어짐 | 이벤트 수, seq 연속성 |
| ④ 비이동 왕복 + 상관 | 사용자가 고른 비이동 명령. 상관이 실리는 경로가 `navigation/goal`뿐이면 이 항목은 입회 하 별도 승인까지 HOLD | `correlation_id` 왕복 |
| ⑤ 정지 소유 | 명령을 보내지 않는다. CORE `safety/state`를 읽고 Fleet이 정지 사실을 자체 판정하지 않음을 관찰 | 읽은 값 |

**파일:** `docs/validation/2026-09-xx-robot-fleet-console-device.md`, `src/site/fleet/progress.md`의 DEVICE gate(다섯 항목이 모두 있을 때만 GO, 아니면 HOLD와 blocker), `src/site/fleet/logs.md`, `src/runtime/gateway/logs.md`.

**완료 기준:** 다섯 항목 기록. 이미지가 v1.44 미만이면 ④ HOLD, 관제 DEVICE는 HOLD로 둔다.

## S6 — 진행 중 브랜치와의 연결

- `docs/d341-overhead-console-pairing`: 합쳐지면 `site-lan-discovery-profile.md`의 두 줄 추가와 S3 탐침 TXT 표가 같은 표를 읽는지 확인한다. 로봇 FleetAgent 페어링은 D-341이 바꾸지 않으므로 S2와 겹치지 않는다. 합치는 쪽이 `harness.yaml`의 D-341 예약을 지운다.
- `feat/console-site-map-layer`: `GET /api/fleet/site-map`은 Fleet 전용이며 스냅샷(CORE) 범위 밖이다. S5 ②에서 화면 기록만 함께 한다.
- 사이트 mDNS 브리지(발견 8): 공통 TXT 검사를 넣는 변경은 D-341 머지 뒤 `deploy/site/mdns-bridge.py`와 `test/test_site_mdns_bridge.py`에서 한다. 기존 이미지(공통 TXT 없음) 허용 규칙(프로파일 26행)은 유지한다.
- `docs/progress.md:88`의 낡은 "FleetAgent·Hub 미구현" 문구를 S1 커밋에서 고친다.

## 사용자가 줄 것

1. CORE 운영자 토큰(최소 viewer; S5 ④는 operator) — 환경 변수로.
2. `fleet_pairing_token` 값과, 로봇에 `fleet.hub_url`(또는 discovery + CA)·`fleet.pairing_token`을 넣는 것 — 로봇 쪽 설정은 사용자가 한다.
3. S5 ④에 쓸 비이동 명령 선택과 입회.
4. ④를 위한 v1.44 이상 이미지 배포 시점.
5. 벤치 동안 로봇이 192.168.1.202(또는 mDNS)로 닿는다는 확인, 8090 방화벽 개방 동의.
