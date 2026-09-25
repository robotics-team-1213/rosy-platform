# ROSY 장비-서버 계약 감사 및 연동 구현 계획

> **Execution:** 각 작업은 failing contract test부터 시작하고 단계별로 검증한다.

**Goal:** 천장 카메라, Fleet 브라우저, 로봇 CORE, CORE FleetAgent가 각자의 버전 계약·자격 증명·데이터 경계를 지켜 RTX 5080 Ubuntu 사이트 서버와 연동되는 경로를 만들고, 장비별 현장 증거를 남긴다.

**Architecture:** Ubuntu 사이트 서버는 HTTPS operator API, CORE Agent telemetry WebSocket, overhead camera ingress, 제한된 vision worker를 함께 운영하지만 각 경로의 schema·권한·저장·장애 처리는 나눈다. 로봇 CORE만 DDS와 최종 동작을 소유한다. Fleet은 CORE의 검증된 원자 REST 명령을 요청하고, 영상 결과는 sighting과 정책 증거를 구분한다.

**Tech Stack:** Python 3.12, FastAPI/Starlette, Pydantic shared schemas, `websockets` ≥ 14, Android Kotlin/CameraX, SQLite, Docker Compose(사이트 호스트 후보; 로봇 제품 Compose와 분리), Ubuntu 24.04 x86_64, ROS 2 Jazzy 로컬 로봇.

**Contracts:** [Proposed D-269](../adr/D-269-device-server-contracts-and-ros-boundary.md), D-18, D-59, D-118, D-170, D-177, D-193, D-257, D-261, D-267, D-268.

## 0. 기준선과 범위

- 코드는 `src/site/fleet`, `src/site/overhead`, `src/runtime/services/core_features/fleet_agent`, `src/contracts/foundation/core_common/protocol`이 각각 가진다. Fleet 패키지는 ROS-free를 유지한다.
- 현재 LOCAL baseline: overhead 45 passed, Fleet 전체 409 passed/5 skipped, Hub/app 32 passed, CORE FleetAgent 8 passed (2026-09-26 Windows).
- 현장 Ubuntu/RTX SSH 대상과 승인된 배포 revision은 아직 확인되지 않았다. 공개 저장소 `origin/main`보다 로컬 `main`이 17 commits 앞선 상태였으므로 해당 커밋 전체를 push하지 않는다.
- 초기 동작 연결은 로컬만 수행하며 합성 자격 증명을 쓴다. 실제 전화·로봇 토큰, IP, 프레임은 공개 저장소와 시험 fixture에 넣지 않는다.

## 진행 상태 (2026-09-26)

- **Task 1 완료:** 현재 브라우저/Fleet, Fleet/CORE REST, CORE Agent/SiteHub, overhead phone/ingress, 내부 DDS 및 미정 Pinky/팔 경계를 D-269 Proposed와 ADR Log에 기록했다.
- **Task 2 완료:** `robots.yaml`의 선택적 `fleet_pairing_token`을 추가하고 REST token 재사용을 거부한다. pairing token 미설정 robot은 Agent pairing 대상에서 제외된다. 자세한 실제 장비 secret provisioning 절차는 Ubuntu 배포 전용 후속 단계다.
- **Task 3 완료 (LOCAL):** 실제 `FleetAgent`를 loopback Uvicorn으로 실행해 동일 `fleet console` 앱에서 hello/welcome, heartbeat, event, disconnect/offline, reconnect를 확인했다. `/registry`는 console token을 검사한다. protocol major mismatch도 pairing 전에 거부한다.
- **Task 4 진행 중:** overhead 수신기는 source→token map을 요구하고 HTTP Authorization token과 hello의 source를 묶어 검증한다. token 미설정/다른 source/unknown source, token 재사용은 fail-closed다. CLI token은 `--source-name` 하나에만 귀속하며 unauthorized source는 shared vector `4401`로 거절하고 Android가 fatal `Unauthorized`로 표시한다. Python server 49 passed, Android unit test `:app:testDebugUnitTest` 통과 (LOCAL).
- **Task 5 진행 중:** shared `SiteSightingPayload`와 API Ref §10.6, source-scoped `POST /api/fleet/sightings`, operator-only `GET` readback을 추가했다. source identity는 credential에서 서버가 정하고, source token은 console/robot REST/CORE Agent pairing token과 다르면 안 되도록 app 생성 때 검사한다. 잘못된 로봇/map/calibration/코너, stale/future/out-of-order 입력은 거부한다. 이미지/URL/policy/client source identity는 schema에서 금지한다. service/API 전체는 RAM latest-only이며 자동 작업과 연결되지 않는다. Fleet 423 passed/5 skipped, gateway 1325 passed/16 skipped, video-relay guard 2 passed (LOCAL).
- **LOCAL 결과:** `src/site/fleet/test` 416 passed / 5 skipped, CORE FleetAgent 8 passed, overhead 45 passed, `git diff --check` 통과.
- **문서 harness 제한:** `test/test_network_topology_contracts.py test/test_harness_contracts.py`는 68 passed / 2 failed다. 실패 2건 모두 기존 `src/hmi/dashboard/logs.md` 네 항목의 `- 증거:` 누락이고, `rosy_harness.py lint`도 동일한 4 errors와 19 기존 `last_verified` warnings를 보고했다. 해당 append-only 로그는 이 작업에서 수정하지 않았다.
- **Task 4 남음:** 운영자용 token 발급·회전·폐기와 QR 비밀 전달 절차, Android emulator/실제 phone→receiver LAN 연결, 연속 frame freshness와 재시작 시험.
- **Task 5 남음:** 설정을 실제 Fleet CLI/배포에 연결하고, 최신 overhead JPEG→vision worker→sighting publisher→Fleet readback의 source/seq/map/calibration lineage를 합성 프레임과 실제 localhost 서비스로 입증한다. D-268 policy evidence endpoint와 자동 실행은 이 경로에 넣지 않는다.
- **아직 미수용:** vision worker 완성, 사이트 Compose/저장/복구, 사용자 역할·감사·공통 작업 수명주기, Ubuntu RTX/실물 CORE 시험은 Task 5–8이다. DEVICE/FIELD, 자동 이동, 집기, Pinky 및 팔 카메라 연동은 계속 HOLD다.
- **배포/형상:** 현재 결과는 Windows localhost LOCAL 증거뿐이다. 현장 Ubuntu 호스트 수용이나 원격 배포 증거가 아니며, 원격 push/deploy는 호스트와 승인 revision이 확인될 때 별도 진행한다.

## Task 1 — 현재 wire contract·권한 감사 고정

**Files:** D-269 ADR, this plan, `docs/reference/ROSY ADR Log.md`; read API Ref §5–8, D-118/D-170/D-177/D-193/D-257/D-261, Android/Python overhead implementation, Fleet HTTP transport, SiteHub, CORE FleetAgent.

1. 계약 표의 각 링크에 producer, consumer, path/version, payload owner, credential owner, retry/freshness, current proof tier를 적는다.
2. REST 제어 토큰/Agent pairing token/console token/카메라 source token을 분리하는 제약과 WSS 경계를 D-269에 기록한다.
3. `docs/reference/ROSY ADR Log.md`에 D-269 Proposed를 등록한다. D-257/D-268을 Accepted로 취급하지 않는다.
4. `python tools/harness/rosy_harness.py generate`, ADR/harness contracts를 실행하고 계약 표가 실제 코드와 맞는지 재검토한다.

## Task 2 — Agent pairing credential을 CORE REST token과 분리

**Files:** modify `src/site/fleet/fleet/swarm/robots.py`, `src/site/fleet/fleet/hub/hub.py`, Fleet CLI/config tests, relevant examples and API/deployment docs.

1. `robots.yaml`에서 `robot_id`, `base_url`, REST `token`, 선택적 `fleet_pairing_token`을 읽는 시험을 먼저 쓴다. pairing secret은 omitted일 수 있고, REST token을 pairing fallback으로 사용하지 않는 것을 검증한다.
2. `SiteHub`가 별도 pairing credential map만으로 HELLO를 검증하도록 구현한다. 잘못된/누락된 pair token, unknown robot, UUID/serial drift, mismatched protocol은 거절한다.
3. robot config `fleet.hub_url`/`fleet.pairing_token`과 site `fleet_pairing_token`의 구성 절차를 문서화한다. 값은 로그/URL/query에 쓰지 않고 파일 접근권한을 제한한다.
4. 해당 Fleet 및 CORE FleetAgent tests를 실행한다. 기존 `robots.yaml`의 REST-only 운영 모드는 계속 가능하고 Agent 미설정은 telemetry OFF여야 한다.

## Task 3 — 같은 Fleet app에서 CORE Agent telemetry를 수신

**Files:** modify `src/site/fleet/fleet/hub/server.py`, `fleet/server/app.py`, `fleet/server/console.py`, `fleet/cli.py`; create `src/site/fleet/test/test_console_hub_integration.py`.

1. 실제 Uvicorn loopback listener를 쓰는 integration test를 작성한다. 동일한 `fleet console` ASGI app에서 `FleetAgent` HELLO/WELCOME, heartbeat, event를 왕복한다. 운영자 API와 registry readback은 각각 기대 토큰을 요구한다.
2. RED를 확인한 뒤 Hub WebSocket route를 재사용 가능한 route installer로 분리하고, console startup이 pair-configured robots만 SiteHub에 등록하게 한다. `/registry`는 console auth와 같은 보호 경계를 갖는다.
3. reconnect 이후 online/freshness/event sequence, unknown robot/wrong pair token, disconnect offline 처리와 server shutdown을 시험한다. polling REST는 fallback으로 남기며 상태 출처를 응답에서 혼동하지 않는다.
4. fleet/CORE focused suites와 no-ROS import boundary를 실행한다. 서버 앱 연결이 물리 CORE DEVICE 결과라고 표기하지 않는다.

## Task 4 — 카메라 ingress의 source별 자격 증명·프레임 계약 확인

**Files:** modify `src/site/overhead/overhead/ingest.py`, `protocol.py`, Kotlin `OverheadLink.kt` and settings only with a paired schema update; tests on both sides.

1. 서로 다른 source token이 다른 `source` 이름을 위조할 수 없는 RED test를 추가한다. 현재 단일 global token 동작은 legacy/local-only로 명확히 제한한다.
2. pairing/admin flow가 발급한 source-bound, revoke 가능한 credential을 받아들인다. raw token을 URL, path, query, logs, SQLite, frame header에 넣지 않는다.
3. shared `protocol/vectors.json`로 header/hello/config/bad-version, duplicate connection, seq rollover, oversized JPEG와 latest-only 성질을 Kotlin/Python 양쪽에서 검증한다.
4. localhost Android emulator→receiver 통합, reconnect/stale/report 시험을 수행한다. 실제 천장 폰은 별도 DEVICE gate다.

## Task 5 — 영상 처리 결과의 Fleet wire contract

**Gate:** D-257/D-268 수용 전 자동 정책 경로를 열지 않는다.

**Files:** API Reference, `core_common.protocol.schemas.py`, overhead `detect.py`/`project.py`/`publish.py`, Fleet API/console/tests.

1. API Ref와 Pydantic shared schema에서 sighting과 policy-eligible evidence를 별도 타입·권한으로 정의한다. source/frame sequence/captured+received timestamps/map/calibration/processor revision/freshness/rejection 이유를 고정한다.
2. schema/API contract test를 먼저 추가한다. Fleet이 JPEG/image URL을 거부하고, adapter write credential이 명령·e-stop을 호출하지 못하는지 확인한다.
3. synthetic ArUco frames에서 코너 누락, 잘못된 source/seq, stale, calibration/map mismatch, 저신뢰도 결과가 sighting/정책 근거를 내지 않게 구현한다.
4. 같은 source/seq lineage가 receiver→vision→Fleet display까지 보존되는 localhost end-to-end test를 수행한다. 사람이 확인한 결과는 표시·대조 전용이다.

## Task 6 — 같은 사이트 호스트의 배포 산출물·상태 저장

**Files:** `deploy/site/compose.yaml`, `Dockerfile.fleet`, `Dockerfile.vision`, site config template/runbook, persistent SQLite schema/backup tests.

1. loopback-only fixture smoke와 Compose contract test를 먼저 쓴다: least privilege, read-only rootfs, network separation, health/restart, secret mount, persistent data volume, retention, backup/restore.
2. Fleet API, camera ingress, vision worker를 논리적으로 분리한다. GPU를 쓰지 않는 CPU detector smoke를 제공하고 Ubuntu RTX에 같은 container digest를 배포한다.
3. TLS reverse proxy, named volumes, preflight/rollback, log rotation, clock sync, restart-after-power-loss 절차를 문서화한다.
4. Linux `amd64` CPU 이미지 build와 site Compose read-only validation을 수행한다. 이것은 ARTIFACT/DEVICE를 자동 승격하지 않는다.

## Task 7 — 수동·자동 작업과 역할·이력

**Files:** Fleet task/policy service, storage schema, console UI/API, relevant shared task/evidence contracts.

1. viewer/operator/policy-admin의 deny-by-default, lease expiry, credential revoke, user/action/source/evidence audit rows 테스트를 쓴다.
2. manual operator action과 automatic policy action이 동일한 task validation/transition/history service를 통과하게 한다. status는 `REQUESTED/ACCEPTED/RUNNING/COMPLETED/FAILED/UNKNOWN/HOLD`로 receipt와 실제 결과를 구분한다.
3. `correlation_id`/ACK는 D-177/API Ref/schema와 한 change로 구현한다. timeout 또는 unknown result는 자동 재발행 대신 `UNKNOWN/HOLD`로 정지한다.
4. fail-closed stale/missing evidence, auth revocation, duplicate/replay, crash recovery와 storage migration 시험을 수행한다. automatic enable remains OFF.

## Task 8 — Ubuntu RTX host와 각 장비별 수용

1. 접속 대상 hostname/OS/user, network/TLS termination, NVIDIA driver, Docker Engine/Compose, disk/data backup, time sync를 inventory하고 private evidence에 기록한다.
2. revision-pinned images/build manifest/SBOM, GPU container access, model revision/VRAM, capture-to-Fleet latency, CPU/GPU fallback을 실측한다.
3. actual ceiling phone + markers + surveyed map, actual CORE robot, network interruption, process restart, token revoke를 DEVICE/FIELD runbook에 따라 실행한다.
4. automatic movement stays disabled until D-268 accepted contract and per-task false-trigger/freshness metrics pass. OMX pick, Pinky camera and robot-arm camera require separate ADRs and DEVICE goals.

## 완료 조건

- API Ref/shared schemas/Android-Python protocol vectors와 producer-consumer test가 서로 일치한다.
- local integration에서 해당 장치 credential로만 연결되고 허용하지 않은 호출은 fail closed다.
- 운영 앱에서 상태/event, source/seq/freshness, operator action receipt와 최종 결과가 한 correlation trail로 읽힌다.
- `deploy/site`는 revision-pinned image, persistent state backup/restore, health/restart, TLS/auth 운영 절차를 가진다.
- Ubuntu host, phone, robot, optional GPU 각각의 SITE/DEVICE/FIELD evidence를 따로 남긴다. 자동 이동·집기·추가 카메라를 계획 단계나 합성 시험으로 활성화하지 않는다.
