# ROSY 장비-서버 계약 감사 및 연동 구현 계획

> **Execution:** 각 작업은 failing contract test부터 시작하고 단계별로 검증한다.

**Goal:** 천장 카메라, Fleet 브라우저, 로봇 CORE, CORE FleetAgent가 각자의 버전 계약·자격 증명·데이터 경계를 지켜 RTX 5080 Ubuntu 사이트 서버와 연동되는 경로를 만들고, 장비별 현장 증거를 남긴다.

**Architecture:** Ubuntu 사이트 서버는 HTTPS operator API, CORE Agent telemetry WebSocket, overhead camera ingress, 제한된 vision worker를 함께 운영하지만 각 경로의 schema·권한·저장·장애 처리는 나눈다. 로봇 CORE만 DDS와 최종 동작을 소유한다. Fleet은 CORE의 검증된 원자 REST 명령을 요청하고, 영상 결과는 sighting과 정책 증거를 구분한다.

**Tech Stack:** Python 3.12, FastAPI/Starlette, Pydantic shared schemas, `websockets` ≥ 14, Android Kotlin/CameraX, SQLite, Docker Compose(사이트 호스트 후보; 로봇 제품 Compose와 분리), Ubuntu 24.04 x86_64, ROS 2 Jazzy 로컬 로봇.

**Contracts:** [Proposed D-269](../adr/D-269-device-server-contracts-and-ros-boundary.md), D-18, D-59, D-118, D-170, D-177, D-193, D-257, D-261, D-267, D-268.

## 0. 기준선과 범위

- 코드는 `src/site/fleet`, `src/site/overhead`, `src/runtime/services/core_features/fleet_agent`, `src/contracts/foundation/core_common/protocol`이 각각 가진다. Fleet 패키지는 ROS-free를 유지한다.
- 시작 시 LOCAL baseline은 overhead 45 passed, Fleet 409 passed/5 skipped, Hub/app 32 passed, CORE FleetAgent 8 passed였다. 아래 최신 LOCAL 결과와 구분한다.
- 현장 Ubuntu/RTX host와 승인된 배포 revision은 아직 확인되지 않았다. 현재 실행 증거는 로컬 Windows Docker Desktop의 Linux containers다.
- 초기 동작 연결은 로컬만 수행하며 합성 자격 증명을 쓴다. 실제 전화·로봇 토큰, IP, 프레임은 공개 저장소와 시험 fixture에 넣지 않는다.

## 진행 상태 (2026-09-26)

- **Task 1 완료:** 현재 브라우저/Fleet, Fleet/CORE REST, CORE Agent/SiteHub, overhead phone/ingress, 내부 DDS 및 미정 Pinky/팔 경계를 D-269 Proposed와 ADR Log에 기록했다.
- **Task 2 완료:** `robots.yaml`의 선택적 `fleet_pairing_token`을 추가하고 REST token 재사용을 거부한다. pairing token 미설정 robot은 Agent pairing 대상에서 제외된다. 자세한 실제 장비 secret provisioning 절차는 Ubuntu 배포 전용 후속 단계다.
- **Task 3 완료 (LOCAL):** 실제 `FleetAgent`를 loopback Uvicorn으로 실행해 동일 `fleet console` 앱에서 hello/welcome, heartbeat, event, disconnect/offline, reconnect를 확인했다. `/registry`는 console token을 검사한다. protocol major mismatch도 pairing 전에 거부한다.
- **Task 4 코드·LOCAL 완료:** source→token map과 hello identity 결합, TLS/WSS pairing `tls=1`, Android secure 설정이 연결됐다. 인증/다른 source/unknown source/token 재사용은 fail-closed다. overhead 69 tests와 Android `testDebugUnitTest` 통과. 실물 폰 LAN·인증서·장시간 신선도는 DEVICE gate다.
- **Task 5 코드·LOCAL 완료:** shared `SiteSightingPayload`, CLI/config, 분리 credential, CPU ArUco detector/projector, latest-only worker, publisher, SQLite latest state와 accepted-event history/backup을 연결했다. 잘못된 map/calibration/코너와 stale/future/out-of-order 입력은 거부한다. quality는 미측정 `null`; 자동 작업과 연결되지 않는다.
- **Task 6 LOCAL 완료:** Ubuntu 24.04 Fleet·vision·Caddy 이미지 세 개를 빌드하고 Compose를 기동했다. TLS healthcheck, Caddy upstream 인증서 검증, 합성 JPEG WSS→vision→HTTPS Fleet API→SQLite readback 및 Fleet restart 뒤 seq 78 복원을 재확인했다. secret mount 환경 변수 이름 변경 후에도 Compose 재빌드·기동·정리까지 확인했다.
- **CORE 이벤트 보존 코드·LOCAL 검증:** paired Agent 이벤트를 64 KiB 제한·민감 필드 검사 후 sighting과 같은 영속 SQLite 파일의 append-only 테이블에 기록한다. 인증된 `/api/fleet/events` cursor API, 재전송 멱등성과 변경된 `event_id` payload 거절을 추가했다. Fleet **443 passed / 5 skipped**, protocol/version tests passed. Docker Compose 재빌드 뒤 synthetic phone WSS→vision→Fleet와 실제 `FleetAgent` 클라이언트의 trusted WSS→SQLite audit를 같은 stack에서 통과했고 Fleet 재시작 뒤 sighting과 event를 모두 API에서 재조회했다. 실물 CORE 하드웨어/Ubuntu 호스트 증거는 아직 아니다. local image IDs: Fleet `sha256:6f23b869…`, vision `sha256:c83f20b9…`, proxy `sha256:b92f2f5a…`.
- **집중 회귀:** overhead 95 passed, API 계약 버전 3 passed, Android Gradle `testDebugUnitTest` 성공, gateway sighting contract 15 passed, Docker synthetic end-to-end 및 재시작 후 Fleet API readback 통과, 세 서비스 healthy, `git diff --check` 통과. secret scanner 변경 파일 검사는 깨끗하다.
- **저장소 전체 회귀 한계:** main 통합 상태 전체 ROS-free 세트는 4,415 passed / 150 skipped / 4 failed였다. 그중 FastAPI 버전 표시는 수정했고, 신규 코드 secret scanner 경고도 제거했다. 전체 세트는 수정 후 재실행하지 않았다. 나머지 3개 실패는 main 단독에서도 재현된 기존 `host.py` 파일 크기 verdict, Wi-Fi 입력 UI를 secret으로 잡는 scanner 오탐, 기존 `api_web` 테스트 파일 BOM이다.
- **운영 인계 전 남음:** D-177 command correlation/ACK와 공통 operator/policy task lifecycle은 미구현이며 D-177/D-268는 Proposed다. 현장 host/hostname/CA·phone provisioning, surveyed geometry와 CORE endpoint/credentials, 백업 복구 리허설, host 방화벽 및 전원 복구 시험도 남았다. RTX/GPU와 실물 CORE/phone은 Task 8 field gate다.
- **수용 경계:** Docker 로컬 증거는 Ubuntu 배포나 DEVICE/FIELD 수용이 아니다. D-257/D-268 상태를 승격하지 않으며 자동 이동, 집기, Pinky 및 팔 카메라 연동은 계속 HOLD다.

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

**Files:** `deploy/site/compose.yaml`, `Dockerfile.fleet`, `Dockerfile.vision`, `Dockerfile.proxy`, site config template/runbook, persistent SQLite schema/backup tests.

1. loopback-only fixture smoke와 Compose contract test를 먼저 쓴다: least privilege, read-only rootfs, network separation, health/restart, secret mount, persistent data volume, retention, backup/restore.
2. Fleet API, camera ingress, vision worker를 논리적으로 분리한다. GPU를 쓰지 않는 CPU detector smoke를 제공하고 Ubuntu RTX에 같은 image digest를 배포한다.
3. TLS reverse proxy, named volumes, preflight/rollback, log rotation, clock sync, restart-after-power-loss 절차를 문서화한다.
4. Linux `amd64` Ubuntu 24.04 Fleet·vision·proxy image build, Compose preflight 및 synthetic WSS→vision→HTTPS Fleet/SQLite smoke를 로컬 Docker에서 확인했다. 이것은 SITE/ARTIFACT/DEVICE를 자동 승격하지 않는다.

## Task 7 — 수동·자동 작업과 역할·이력

**Files:** Fleet task/policy service, storage schema, console UI/API, relevant shared task/evidence contracts.

1. viewer/operator/policy-admin의 deny-by-default, lease expiry, credential revoke, user/action/source/evidence audit rows 테스트를 쓴다.
2. manual operator action과 automatic policy action이 동일한 task validation/transition/history service를 통과하게 한다. status는 `REQUESTED/ACCEPTED/RUNNING/COMPLETED/FAILED/UNKNOWN/HOLD`로 receipt와 실제 결과를 구분한다.
3. `correlation_id`/ACK는 D-177/API Ref/schema와 한 change로 구현한다. timeout 또는 unknown result는 자동 재발행 대신 `UNKNOWN/HOLD`로 정지한다.
4. fail-closed stale/missing evidence, auth revocation, duplicate/replay, crash recovery와 storage migration 시험을 수행한다. automatic enable remains OFF.

**Task 7 implementation progress (LOCAL, partial):** the operator `/goal` route,
navigation intents through `/api/fleet/do`, and internal policy entry point share
configured-robot/finite-goal validation, SQLite
task projection plus append-only transitions, and idempotency handling. The console
uses a random request key; replay returns the original task without redispatch.
Definite rejection is `FAILED`; ambiguous post-dispatch results are `UNKNOWN`.
The externally reachable CLI requires both operator authentication and
`--tasks-db`; site Compose uses `/var/lib/rosy/fleet.sqlite3` for tasks, sightings,
and CORE event history. The current shared token is attributed to `site-console`.
Policy submissions stay `HOLD` without dispatch. Focused task/API/CLI/docs tests
passed (36); the full Fleet suite passed (461 passed, 5 skipped). Linux/amd64
Docker images rebuilt, Compose configuration validated, and all three services
became healthy. An authenticated navigation request to an intentionally
unreachable smoke endpoint persisted as `UNKNOWN`; Fleet restart restored its
task/history, and same-key replay returned the same task. This is local Docker
evidence only. Browser RBAC/revocation, per-user identity,
`correlation_id`/CORE ACK and final-result reconciliation, and UNKNOWN resolution
remain open. Startup recovery now
converts any persisted `REQUESTED` task to `UNKNOWN` with a system audit row and
does not redispatch it. This does not complete Task 7 or accept D-268/D-177.

## Task 8 — Ubuntu RTX host와 각 장비별 수용

1. 접속 대상 hostname/OS/user, network/TLS termination, NVIDIA driver, Docker Engine/Compose, disk/data backup, time sync를 inventory하고 private evidence에 기록한다.
2. 먼저 호스트 `nvidia-smi`에서 RTX 5080과 driver를 확인한 다음 NVIDIA Container Toolkit으로 Docker runtime을 설정하고 `docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi`가 GPU를 읽는지 확인한다. test image digest와 출력을 private evidence에 남긴다. 이는 GPU runtime preflight이며 추론 수용이 아니다.
3. revision-pinned images/build manifest/SBOM을 배포한다. 실제 모델/framework/image를 선택한 후 Blackwell 호환 GPU 코드, model revision, peak VRAM, thermal behavior, capture-to-Fleet latency를 실측한다. 현재 CPU ArUco sighting은 별도 관측 경로로 유지하고, GPU 의존 evidence가 불가할 때 정책 task를 닫는 동작을 검증한다. 이때 해당 vision 서비스에만 Compose GPU reservation을 부여한다.
4. actual ceiling phone + markers + surveyed map, actual CORE robot, network interruption, process restart, token revoke를 DEVICE/FIELD runbook에 따라 실행한다.
5. automatic movement stays disabled until D-268 accepted contract and per-task false-trigger/freshness metrics pass. OMX pick, Pinky camera and robot-arm camera require separate ADRs and DEVICE goals.

**GPU preflight clarification:** CUDA 12.8 Blackwell compatibility requires the
application binary to carry native Blackwell cubin or compatible PTX; the
version label alone is not proof. The current candidate vision worker is CPU
ArUco and has no GPU reservation/model. Therefore the container visibility test
does not satisfy model, latency, or SITE/DEVICE acceptance.

**Task 8 preparation status (LOCAL):** `deploy/site/build_candidate.py` now
requires a clean source revision, builds commit-tagged `linux/amd64` images,
generates per-image SPDX SBOMs with Docker Scout, and exports an image archive
plus image/config checksums in `release.json`. The bundle carries only Compose,
proxy, runbook, and placeholder config templates. Its clean-tree/platform/output
guards have host pytest coverage (3 passed). Candidate `845a266a47721453d281d3566fbce76ac8d468bd`
was built on Windows 11 through Docker Desktop's Linux/amd64 engine. Fleet,
vision, and proxy image IDs are respectively `sha256:7e61ff41f61859177bc7244474fd585d837d03dde557c1e822b71f3ebb5d0c12`,
`sha256:db17cd53e028d2e884609d7773f975300aadb9bb4ad211f98809059bbdccfd00`,
and `sha256:92285397b659eb03fbe532a76d061738d5f9b0f7f45027a68c662caa44276c3f`.
The `images.tar` SHA-256 is
`35af4954fde65ba8da42bfb21ebaa6098caed254e9121b65b3fab2463ce44315`; all
three SPDX reports were generated. The archive was loaded, then its packaged
Compose file was started with `--no-build`; Fleet, vision, and proxy became
healthy. An authenticated operator task survived Fleet restart and same-host
readback. This is a workstation Docker smoke, not native Ubuntu, NVIDIA GPU,
physical phone/CORE, or SITE/DEVICE/FIELD acceptance. Target-host access remains
unidentified, and GPU/model/latency acceptance remains open.

## 완료 조건

- API Ref/shared schemas/Android-Python protocol vectors와 producer-consumer test가 서로 일치한다.
- local integration에서 해당 장치 credential로만 연결되고 허용하지 않은 호출은 fail closed다.
- 운영 앱에서 상태/event, source/seq/freshness, operator action receipt와 최종 결과가 한 correlation trail로 읽힌다.
- `deploy/site`는 revision-pinned image, persistent state backup/restore, health/restart, TLS/auth 운영 절차를 가진다.
- Ubuntu host, phone, robot, optional GPU 각각의 SITE/DEVICE/FIELD evidence를 따로 남긴다. 자동 이동·집기·추가 카메라를 계획 단계나 합성 시험으로 활성화하지 않는다.
