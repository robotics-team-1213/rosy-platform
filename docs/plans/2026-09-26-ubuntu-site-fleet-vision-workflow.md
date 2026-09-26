# Ubuntu Site Fleet and Vision Workflow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 상시 가동 Ubuntu RTX 노트북에서 인증된 웹 관제, 영속 Fleet 상태, 로봇 이벤트, 천장 카메라 관측을 연결하고, 권한 있는 운영자 요청과 현장 수용된 정책 증거만 같은 추적 가능한 작업 경로로 처리한다. 자동 이동은 별도 정책 증거 계약과 신선도·검출 품질 현장 게이트가 통과한 뒤에만 활성화한다.

**Architecture:** 로봇별 DDS와 안전 루프는 로봇 안에 둔다. 사이트 호스트는 독립 Fleet, 관측, GPU, 저장 서비스로 나누며 영상 바이트는 Fleet에 넣지 않는다. D-257 sighting과 별도인 정책 적격 증거 계약이 수용되기 전까지 자동 source를 닫아 둔다. 자동·수동 요청은 권한 확인 후 하나의 작업 검증/추적 경로에 합류하고, Fleet은 CORE 원자 액션과 D-55에 따라 수용된 로봇 로컬 manipulation 능력만 호출한다.

**Tech Stack:** Ubuntu 24.04 x86_64, Docker Compose, Python/FastAPI, 기존 `fleet`/`overhead` 패키지, SQLite 초기 저장소, 별도 OpenCV·NVIDIA GPU worker. GPU 컨테이너는 호스트 드라이버·NVIDIA Container Toolkit 조합을 실측해 선택한다.

**Decision:** [D-267](../adr/D-267-ubuntu-site-fleet-and-vision-workflow.md) Proposed. [D-268](../adr/D-268-policy-eligible-vision-evidence-for-fleet-tasks.md)는 sighting과 자동 정책 증거의 경계를 제안하며 Proposed 동안 자동 source를 열지 않는다. D-55의 manipulation 장치 수용은 집기 활성화의 별도 필수 게이트다.

**현재 목표 범위:** 이번 목표는 단계 0~3과 천장 카메라 기반 자동 이동의 승인된 현장 게이트까지다. 단계 4의 핑키/로봇암 영상과 자동 집기는 별도 ADR·계획·goal로 추적한다. 이 단계들은 현재 목표의 완료를 막지 않으며, 집기 경로는 D-55 수용 전 비활성이다.

---

## 현재 기준선과 중지 조건

- `src/site/fleet/fleet/server/`는 REST gather와 웹 콘솔이다. `src/site/fleet/fleet/hub/server.py`의 WS 수신과 `src/runtime/services/core_features/fleet_agent/agent.py`의 outbound Agent는 구현돼 있지만 기본 설정에서 Agent는 비활성이며 아직 Fleet 콘솔의 운영 경로로 연결되지 않았다.
- `fleet.hub.server.create_hub_app()`는 독립 FastAPI 앱을 만든다. `fleet console`은 `fleet.server.app.create_app()`만 Uvicorn에 전달하므로 Task 3.1에서 통합 ASGI 구성이 필요하다.
- `src/site/overhead/`는 폰 JPEG 수신 전용이다. 인식·Fleet sightings·실물 폰 수용은 없다. D-257은 Proposed다.
- `docs/adr/D-55-mobile-manipulation-is-a-robot-local-mission-capability.md`에 따라 OMX capability는 DEVICE payload 시험 전 비활성이다. 집기 API를 구현/광고하거나 자동 활성화하지 않는다.
- API 경로·envelope 필드를 새로 정할 때는 `docs/reference/ROSY API & Protocol Reference.md`와 `src/contracts/foundation/core_common/protocol/schemas.py`를 같은 변경에서 갱신한다(D-18). 이 계획의 새 이름은 내부 구현 후보이며 외부 계약 확정이 아니다.
- 다른 세션의 WIP를 보존한다. 각 단계는 전용 worktree에서 구현하고 명시 경로만 stage한다. 로그·실기 영상·스크래치는 `X:\DevTemp\` 또는 공개 저장소의 `private/` 규칙(D-226)을 따른다.

## 단계 0: 계약과 권한을 닫고 측정 기준을 고정

### Task 0.1: D-257 표시 계약, 정책 증거, 명령 추적 계약 선행 결정

**Files:** Review `docs/adr/D-257-site-lane-map-and-overhead-sightings.md`, `docs/adr/D-170-prt-004-deferred-until-central-fleet.md`, `docs/adr/D-177-prt-004-activation-design.md`; modify the matching ADR/Log only after field and API decisions. Test `test/test_harness_contracts.py`, `src/site/fleet/test/test_no_video_relay.py`.

1. D-257의 `map_id`, sighting 신선도, 읽기/쓰기 권한을 검토하고 누락된 현장 보정·소스 식별 결정을 별도 ADR에서 확정한다. sighting은 계속 표시·대조 전용이다.
2. 작업 ID → CORE 명령 `correlation_id` → 실행 결과의 세 단계와 응답 유실 재조회 경로를 설계로 검토한다. D-170의 지연 결정을 임의로 건너뛰지 않는다. 실제 PRT-004 활성화와 schema/API Ref/로봇 구현은 중앙 Fleet 작업 경로를 여는 Task 3.2와 같은 변경에서 한다(D-177).
3. Proposed D-268에서 sighting과 정책 적격 증거의 경계를 검토·수용한다. D-267이 먼저 Accepted가 되더라도 D-268 수용, API Reference/schema 갱신, LOCAL/DEVICE/FIELD 확인 전에는 자동 작업 입력 endpoint와 자동 source를 열지 않는다.
4. 정책 적격 증거는 사전 등록된 출처/대상/증거 종류, 300 ms end-to-end freshness, 지도·보정·모델 revision, 검출 품질 acceptance를 모두 확인한다. 수치 검출/오탐 기준과 필요한 신선 증거 가용성은 현장 시험 전 acceptance plan에서 승인한다.
5. D-136 대역·D-257 freshness와 적용할 drop/seq 조건을 계약 시험으로 고정한다. `python -m pytest test/test_harness_contracts.py src/site/fleet/test/test_no_video_relay.py -q`와 `python tools/harness/rosy_harness.py lint`를 실행한다. 변경된 계약만 commit한다.

**Gate:** D-257 또는 D-268/추적 계약이 Proposed인 동안 정책 자동 실행 경로는 열지 않는다. 기존 REST 관제와 수동 경로는 별도 인증·권한 검증 및 기존 CORE 안전 게이트를 통과한 경우에만 유지할 수 있다.

### Task 0.2: 웹 사용자와 서비스 자격 증명 권한 계약

**Files:** Create or update a security ADR and access-control matrix under `docs/adr/`; read `src/site/fleet/fleet/server/app.py`, current console auth, D-59, D-81 and D-267. External endpoints, shared schema/API Reference and role tests are updated together when implementation starts.

1. 개인별 principal과 세 권한을 고정한다: `viewer`는 상태/증거/거절 사유 읽기, `operator`는 작업 요청·중지·취소, `policy-admin`은 작업 조건 등록·수정·활성화·비활성화. 공유 bearer token을 이동 또는 정책 변경 권한으로 재사용하지 않는다.
2. 모든 변경 요청에 principal과 감사 기록을 남기고 endpoint별 권한을 fail-closed로 적용한다. 읽기와 명령 권한은 분리한다. 브라우저 cookie 세션을 선택하면 CSRF 방어도 포함한다.
3. 비전 서비스 자격 증명은 서버 측에서 source, 허용 대상, 허용 증거 종류에 묶고 개별 회전·폐기를 지원한다. source identity는 제출 본문이 아닌 인증 자격에서 가져오고 만료·폐기·재생·교차 대상 제출을 거부한다.

**Gate:** 이 권한 계약과 사용자별 인증이 수용되기 전에는 원격 이동·자동 조건 변경 endpoint를 공개하지 않는다.

## 단계 1: Ubuntu 사이트 서버 산출물

### Task 1.1: Fleet 전용 컨테이너와 호스트 설정

**Files:** Create `deploy/site/Dockerfile.fleet`, `deploy/site/compose.yaml`, `deploy/site/.env.example`, `deploy/site/README.md`, `test/test_site_fleet_deploy.py`; read `src/site/fleet/setup.py`, `src/hmi/web/` 공유 자산, `src/site/fleet/fleet/cli.py`.

1. 정적 계약 시험을 먼저 작성한다: `fleet console` 진입점, 읽기 전용 `robots.yaml`/신호 설정, 비밀 파일의 이미지 미포함, 포트·restart·health 설정, 로봇 DDS host network/privileged 불필요.
2. `python -m pytest test/test_site_fleet_deploy.py -q`가 실패하는 것을 확인한 뒤 Fleet 이미지와 Compose를 최소 구현한다. 웹 정적 자산이 설치본에서 실제 서빙되는지 포함한다.
3. `docker compose -f deploy/site/compose.yaml config`와 로컬 컨테이너 `/console`·인증된 `/api/fleet/state` 스모크를 Ubuntu 호스트에서 실행한다. Windows 개발 Docker는 compose 문법과 CPU 컨테이너 시험에 쓸 수 있지만, 실제 Ubuntu 네트워크·서비스 재시작·GPU 수용 근거로 승격하지 않는다.
4. 운영 문서에 전원 복귀 자동 시작, 절전 비활성화, 유선망 우선, 시간 동기화, 백업/복원, 로그 상한, 비밀 파일 권한과 브라우저 HTTPS 진입점을 적는다. 백업에는 암호화/접근 권한/보존·삭제 기간과 복원 시 비밀 재주입 절차를 정하고 해당 파일만 commit한다.

**Gate:** 이미지 빌드·Compose 기동은 사이트 ARTIFACT/LIVE 증거다. 로봇 실물 이동 승격 근거가 아니다.

### Task 1.2: 사이트 데이터와 상태 복구

**Files:** Create `src/site/fleet/fleet/server/store.py`, `src/site/fleet/test/test_server_store.py`; modify `src/site/fleet/fleet/server/console.py`와 앱 수명주기 배선. Read Fleet SRS DAT-001/002.

1. 재시작 뒤 미션/명령/감사 상태가 읽히고, 실행 중 명령은 확인 전 `UNKNOWN` 또는 보류로 남으며 자동 재송신하지 않는 실패 시험을 쓴다.
2. SQLite 마이그레이션과 저장소를 구현한다. 영상 원본은 저장하지 않고 evidence의 메타데이터·결과·출처만 보관한다. DB 단일 writer/백업 복원 경계를 정한다.
3. `python -m pytest src/site/fleet/test/test_server_store.py src/site/fleet/test/test_server_app.py -q`를 실행하고 재시작/손상/중복 요청 시험을 확인한 뒤 commit한다.

## 단계 2: 천장 영상에서 관측 결과까지

### Task 2.1: 실물 폰 전송 먼저 계측

**Files:** Read `src/site/overhead/progress.md`, `docs/plans/2026-09-26-overhead-camera-android-app-design.md`; save dated evidence under `docs/validation/overhead-device-YYYY-MM-DD/` only when collected and safe to publish.

1. 실물 폰·현장 LAN에서 30분 이상 송신하고 capture→inference/projection→Fleet evidence acceptance age, 수신 fps, drop/seq gap, 대역, 발열, 재연결을 측정한다(D-261 A3). NTP 상태와 양 끝 시계 오차도 기록한다. p50/p95/max와 300 ms 이내 정책 적격 증거 비율을 함께 남긴다.
2. 각 정책 입력은 D-257의 300 ms 상한을 만족해야 한다. D-261의 기본 3 fps는 프레임 간격이 약 333 ms이므로 실제 신선도 가용성이 자동 작업에 충분한지 별도로 판정한다. 필요한 가용성/표본 기준은 시험 전에 acceptance plan에서 승인한다. freshness·D-136 대역·drop/seq·열·재연결 기준 중 하나라도 미달 또는 미정이면 인식/자동 작업 투입을 보류한다.
3. 캡처/로그의 저장 위치와 접근 권한을 정한다. 원본 영상은 공개 저장소에 넣지 않는다.
4. 작업 종류별 정답 프레임/현장 장면과 라벨을 준비해 detection precision/recall 또는 동등한 승인 지표, false-trigger 허용치, 표본 규모와 입회자를 시험 전에 기록한다. 자동 트리거는 사전 합의한 기준 통과 전까지 비활성이다.

### Task 2.2: 관측 어댑터와 Fleet sighting 연결

**Files:** Create `src/site/overhead/overhead/detect.py`, `src/site/overhead/overhead/project.py`, `src/site/overhead/overhead/publish.py`, matching `src/site/overhead/test/test_detect.py`, `test_project.py`, `test_publish.py`; modify `src/site/fleet/fleet/server/app.py`, `console.py`, matching Fleet tests. Follow D-257 design and its API Ref/schema prerequisite.

1. 합성 마커 프레임에서 4코너·로봇 위치와 yaw가 올바르고 누락 코너에는 결과가 없는 실패 시험을 작성한다. 오래된 seq, 다른 `map_id`, 만료 시각, 미등록 source, 교차 source/대상 위조, 허용되지 않은 증거 종류, 폐기/재생 자격 증명을 거절하는 시험을 작성한다.
2. `detect.py`에만 cv2를 두고 최신 프레임 하나에서 좌표를 산출한다. D-257 sighting은 관제 표시·대조에만 보낸다. 자동 작업 입력은 D-268 수용 뒤 별도 정책 적격 증거 contract로 보내며 자격 증명 identity로 source를 결정한다.
3. `python -m pytest src/site/overhead/test src/site/fleet/test/test_no_video_relay.py src/site/fleet/test/test_server_app.py -q`를 실행한다. 합성 LOCAL 결과는 DEVICE로 표기하지 않는다. 해당 슬라이스만 commit한다.

### Task 2.3: RTX 작업자 배치와 확장 슬롯

**Files:** Create `deploy/site/Dockerfile.vision` with a separate test target, `services/ai_worker/worker.py`, `services/ai_worker/test/test_worker.py`; modify `deploy/site/compose.yaml`. Read `docs/architecture/10_ROSY_Compute_Fabric.md`, D-118, D-231. GPU 서버는 colcon `src/site/`에 넣지 않는다.

1. CPU 마커 처리와 GPU 고급 추론을 별도 worker로 나누는 계약 시험을 작성한다. GPU worker 중단·모델 revision 불일치·지연 결과가 정책 적격 증거를 만들지 못하는지 검증한다. 검출 품질은 Task 2.1에서 사전 합의한 labeled field set 기준으로 평가한다.
2. 같은 Dockerfile의 `test` target을 LOCAL에서 빌드해 synthetic ArUco 프레임 및 fixture로 처리 시험을 실행한다. 입력 fixture는 read-only bind mount, 컨테이너 root filesystem은 read-only, `--network none`으로 실행한다. 결과는 구조화된 좌표/판정 JSON만 내고 Fleet·DDS·실제 로봇 명령과 연결하지 않는다. 기존 입력을 찾지 못하거나 코너·보정 조건이 불충분하면 결과가 없어야 한다.
3. 개발 PC의 `linux/amd64` CPU 컨테이너에서 OpenCV 처리·파일 입출력·fixture 재현성을 확인한다. 이 결과는 LOCAL CPU 증거다. Windows Docker Desktop GPU 시험은 WSL2 backend와 NVIDIA GPU/driver가 있을 때만 선택한다. AMD 개발 PC에서 GPU pass로 기록하지 않는다.
4. Ubuntu RTX 5080 사이트 호스트에서 NVIDIA Container Toolkit을 통해 같은 deployable image의 실제 GPU 접근을 확인하고, 모델/VRAM/end-to-end 지연을 측정한다. GPU request는 고급 모델 worker에만 둔다. 마커 인식에는 GPU를 필수로 만들지 않는다.
5. `docker build --target test -f deploy/site/Dockerfile.vision -t rosy-vision:test .`, containerized `python -m pytest services/ai_worker/test/test_worker.py -q`, Ubuntu GPU smoke와 실제 모델 revision을 각각 기록한 뒤 해당 파일만 commit한다. CPU fixture 통과는 Ubuntu GPU, 모델 정확도, 카메라 DEVICE 또는 로봇 행동 수용이 아니다.

## 단계 3: 하나의 작업 경로와 이벤트 추적

### Task 3.1: 로봇 이벤트를 Fleet에 연결

**Files:** Modify `src/site/fleet/fleet/hub/server.py`, `src/site/fleet/fleet/server/app.py`, `src/site/fleet/fleet/server/console.py`, `src/site/fleet/fleet/cli.py`, `src/runtime/services/core_features/fleet_agent/agent.py`, `src/runtime/gateway/core/services.py` only where the existing Agent needs integration, shared schema/API Ref; test `src/site/fleet/test/test_hub_server.py`, `test_server_app.py`, `test_console_hub_integration.py`, `src/runtime/gateway/test/test_fleet_agent.py`.

1. hello/heartbeat/event 인증, 단절, seq gap, 중복 이벤트, 이벤트 순서, 재접속 시험을 실패 상태로 작성한다.
2. `create_hub_app()`을 `fleet console`이 실제 Uvicorn에 전달하는 ASGI 앱에 결합한다. 기존 `SiteHub`를 관제 상태의 이벤트 출처로 연결하고 CORE outbound를 설정 시에만 연다. REST 폴링 fallback의 명시 조건을 둔다. 새 WS 클라이언트가 로봇 ROS 토픽에 직접 붙지 않게 한다.
3. 단위 Hub 테스트 외에 같은 console 앱에서 인증된 `/ws/robots` hello/heartbeat/event/reconnect 통합 시험을 한다. `python -m pytest src/site/fleet/test/test_hub_server.py src/site/fleet/test/test_server_app.py src/site/fleet/test/test_console_hub_integration.py -q`와 해당 CORE 시험을 실행하고 sim의 두 로봇 이벤트를 확인한 뒤 commit한다.

### Task 3.2: 자동·수동 공통 작업 입구

**Files:** Create `src/site/fleet/fleet/server/tasks.py`, `src/site/fleet/fleet/server/policy.py`, `src/site/fleet/test/test_server_tasks.py`, `test_server_policy.py`; modify `src/site/fleet/fleet/server/app.py`, `store.py`, 웹 자산, API Ref/schema together before external paths are introduced.

1. 같은 활성 작업 정의에 맞는 fresh policy evidence와 운영자 요청이 동일 검증기를 통과하는 시험을 쓴다. 미등록 작업, stale/보정·지도 불일치, capability 없음, 중복, 로봇 busy, 권한 부족이면 명령을 보내지 않는 시험도 쓴다. PRT-004의 correlation ID 보존·ack 상태 전이·구 클라이언트 호환 시험도 이 변경에 포함한다(D-170/D-177).
2. 역할은 `viewer` / `operator` / `policy-admin`으로 검사한다. 초기 콘솔은 정책 조건의 보기·등록·활성화·비활성화와 현재/최근 증거 및 거절 사유를 보여준다. operator는 등록된 작업을 요청·중지·취소할 수 있고 policy-admin만 자동 조건을 변경한다. 각 변경은 principal·source·evidence ID를 감사 저장한다.
3. 자동 조건은 D-268 Accepted와 작업별 DEVICE/FIELD freshness·검출 품질 acceptance가 완료됐을 때만 활성화한다. `source=automatic|operator`, principal, evidence ID(automatic), 작업/명령 correlation ID를 저장한다. 운영자의 중지·취소는 진행 작업을 닫고 재개는 현재 상태 확인 뒤 별도 권한 검사를 거치는 요청으로 처리한다.
4. CORE 명령 수락과 로봇 완료 이벤트를 구분해 단계 상태를 갱신한다. 명령 결과가 불명확하면 `UNKNOWN`에서 멈추고 재조회하며 자동 재전송하지 않는다. `python -m pytest src/site/fleet/test/test_server_tasks.py src/site/fleet/test/test_server_policy.py src/site/fleet/test/test_server_app.py -q`를 실행한 뒤 commit한다.

**Gate:** D-268 수용, 사용자/서비스 권한 시험, 동일 console 앱의 Hub 통합, 시뮬과 입회 실기에서 관측·작업 추적·freshness·검출 품질을 닫기 전 자동 이동을 활성화하지 않는다. 한 조건이라도 `UNKNOWN`, stale, 불일치 또는 미수용이면 automatic source는 비활성이다.

## 단계 4: 후속 카메라와 집기

### Task 4.1: 후속 목표 — 핑키·로봇암 카메라의 전용 미디어 계약

**Files:** New ADR and design under `docs/adr/`, `docs/plans/`; future source adapter under `src/site/` and robot-owned camera path after D-118 review. Test `src/site/fleet/test/test_no_video_relay.py` and future source/adapter tests.

1. 각 카메라의 목적, 구독 시점, 압축 형식, 해상도/fps, 전송 대역, 시간·보정 revision, 개인정보/보존 정책을 실기와 네트워크에서 측정한다.
2. D-118을 바꾸어야 하는 정확한 경로가 확인되면 후속 ADR에서 그 범위만 다룬다. 로봇 DDS/Image를 Fleet으로 직접 연결하지 않는다.
3. source별 좌표계와 영상 결과를 공통 evidence에 매핑하되 로봇 카메라와 천장 카메라를 같은 `map` 위치로 추측해 합치지 않는다.

### Task 4.2: 후속 목표 — 로봇 로컬 manipulation 능력 수용 후 Fleet 단계 연결

**Files:** Follow `docs/adr/D-55-mobile-manipulation-is-a-robot-local-mission-capability.md`, `src/devices/omx/adapter/`, robot capability/API Ref, future manipulation tests; update Fleet task tests only after robot contract exists.

1. OMX/MoveIt 모델, 장착, 전원, hand-eye, 충돌, payload, 재시작/링크 단절 HOLD와 파지/배치 실물 결과를 먼저 계측한다.
2. 로봇이 수용한 하나의 로컬 manipulation 액션을 별도 목표에서 Fleet 단계로 호출한다. 로컬 action/state machine이 approach·perception·grasp·transport·placement transaction과 recovery를 소유한다. Fleet은 작업 orchestration과 단계 추적을 맡고 관절 경로·그리퍼 폐루프 또는 베이스 `cmd_vel`을 만들지 않는다.
3. 알려진 물체·고정 배치 fixture에서 성공, 실패, 물체 미확인, 링크 중단과 복구를 DEVICE/FIELD로 판정한 뒤에만 별도 goal에서 자동 집기 정책을 켠다. possession/arm/gripper 결과가 UNKNOWN이면 자동 retry 없이 HOLD하고 operator reconciliation을 요구한다. retry는 로컬 action이 안전하다고 명시적으로 판정한 결과에만 허용한다.

## 최종 검증과 인계

- **SOURCE/LOCAL:** 문서·schema·권한·중복·고장 주입·영상 미유입 계약 시험을 통과한다. `python tools/harness/rosy_harness.py lint`와 영향을 받은 Fleet/overhead/CORE 시험을 실행한다.
- **ROS-SIM:** 두 로봇의 상태·이벤트·목표·취소·Fleet 재시작을 재현한다. 영상 합성 입력으로 자동 작업 생성만 검증하고 실물 인식이라고 부르지 않는다.
- **SITE ARTIFACT:** Ubuntu 호스트에서 Compose 이미지 digest, 설치 설정, DB 재시작/복원, 웹 인증·HTTPS, GPU 접근과 실제 모델 revision을 읽어 확인한다.
- **DEVICE/FIELD:** 천장 폰의 장시간 송신, capture-to-Fleet age, 신선 증거 가용성, 검출 품질/오탐, 로봇 실제 위치 오차, 현장 무선 대역·지연, 자동 목표의 실제 도착 결과를 각각 기록한다. 자동 이동은 D-268을 Accepted로 전환하고 승인된 acceptance 기준을 모두 통과한 뒤에만 켠다. 자동 집기와 후속 카메라는 별도 goal이며 D-55 독립 실기 게이트가 통과할 때까지 HOLD다.
- **운영 인계:** 관제/영상/GPU 각 서비스의 시작·중단·업데이트·롤백, 비밀 회전, 장애별 축소 상태, 작업 재조회와 수동 중단 절차를 `deploy/site/README.md`에 남긴다.

## Implementation checkpoint (2026-09-26): per-principal site API gate

- D-276 establishes individual SHA-256 token digests and the `viewer` / `operator` / `policy-admin` role matrix. Fleet API read routes accept configured principals; command routes require `operator`.
- Authenticated API mutations are recorded in the durable task SQLite database before dispatch, with principal, role, method, path, and response code. If the audit write fails, the route returns `503` before issuing a CORE request. Operator task history now uses the authenticated principal ID.
- `deploy/site/compose.yaml` requires `/run/rosy-config/site-users.yaml`. The tracked example contains placeholders only. Legacy `--token` is retained for the separate CORE registry endpoint and does not replace individual API credentials.
- `policy-admin` mutation routes do not exist yet; automatic policy submissions remain `HOLD`. Token replacement/revocation requires updating the protected config and restarting Fleet.
- This implementation checkpoint is source/local evidence only. Ubuntu host rollout, individual token handoff/revocation exercise, real CORE readback, and browser UI role affordances remain open.

## 외부 근거

- [Docker Compose production](https://docs.docker.com/compose/how-tos/production/): 단일 서버 운영·재시작 정책.
- [Docker Desktop GPU support for Windows](https://docs.docker.com/desktop/features/gpu/): Windows 컨테이너 GPU 시험은 WSL2와 NVIDIA GPU/driver를 요구한다.
- [Docker multi-platform builds](https://docs.docker.com/build/building/multi-platform/): `linux/amd64`와 `linux/arm64` 이미지 아키텍처 선택 및 빌드.
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html): Ubuntu Docker GPU 접근. 실제 노트북 드라이버와 컨테이너 동작은 현장에서 별도 검증한다.
