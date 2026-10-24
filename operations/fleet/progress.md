---
module: fleet
logical_modules:
- M07
- M11
owner: FLEET
last_verified:
  commit: bed604ef
  date: 2026-09-30
gates:
  SOURCE:
    state: GO
    evidence: 패키지 순수성·hub CORE import 경계 계약 시험 통과 (2026-09-17, 6 passed). server/
      추가 후에도 rclpy 금지 유지
    cmd: python3 -m pytest src/fleet/test/test_boundaries.py -q
  LOCAL:
    state: GO
    evidence: Fleet suite 676 passed/5 skipped including ER2 proposal/admission, durable
      Mission Action dispatcher with persisted stable grant and restart GetAction
      reconciliation, independent goal evidence provenance, and SQLite WAL/index contracts.
      API web 70 passed/13 skipped, OMX adapter 85 passed/3 skipped, foundation 102
      passed. Synthetic indexed Mission queries improved by three orders of magnitude
      locally; this is not target-device evidence. D-348 producer registry, token-scoped
      evidence ingress, SQLite idempotency, terminal-action verification, and grace-timeout
      HOLD are implemented and covered by host tests. Dispatcher remains explicit
      opt-in and automatic policy dispatch remains disabled; no live observation producer,
      configured OMX service/driver, ROS-SIM, or physical stop/goal proof. SOURCE/LOCAL
      only. D-392 provider-neutral model tool contract and per-call SQLite journal
      are covered by 1,128 Fleet tests (6 skipped) on 2026-10-01. Interactions and
      Live API-shaped conformance fixtures use fake provider envelopes only; they
      do not prove a production Live adapter, ROS-SIM, ARTIFACT, DEVICE, or FIELD
      acceptance. A pinned Jazzy in-process integration fixture now joins Mission
      admission, SO_PEERCRED UDS grant/receipt, local Action journal, and one ROS
      ActionServer goal; it verifies callback acceptance, nonterminal Mission state,
      and restart UNKNOWN/no replay. It is not vendor Gazebo, physical stop/goal evidence,
      ARTIFACT, DEVICE, or FIELD acceptance. 2026-10-07 — the console bird's-eye now detects
      a stale camera calibration (still-robot tracking offset over 0.4 m for 3 consecutive
      polls) and falls back to the metric view with a warning instead of projecting the map
      onto a re-aimed camera; node tracking-layer 12 passed and a mutation-proven browser
      regression cover it (ROSY_RUN_BROWSER_TESTS=1).
    cmd: python3 -m pytest src/site/fleet/test -q
  ROS-SIM:
    state: HOLD
    blocker: 'D-87: 현재 트리의 colcon install/setup.bash가 없다. 2026-09-17 WSL Task 14 로그는
      설계 입력이며 GO가 아니다 (D-89)'
    cmd: python3 src/gz_sim/scripts/swarm_bench.py --robots <robots.yaml> --leader
      rosy_01 --scenario follow|hold
  ARTIFACT:
    state: PARKED
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs:
- D-775
- D-801
- D-693
- D-687
- D-679
- D-681
- D-684
- D-652
- D-620
- D-5
- D-10
- D-12
- D-18
- D-20
- D-21
- D-30
- D-31
- D-59
- D-60
- D-90
- D-93
- D-106
- D-114
- D-116
- D-157
- D-159
- D-268
- D-269
- D-288
- D-289
- D-290
- D-291
- D-293
- D-300
- D-306
- D-316
- D-318
- D-331
- D-333
- D-334
- D-336
- D-392
- D-407
- D-413
- D-439
- D-443
- D-451
- D-453
- D-455
- D-456
- D-488
- D-489
- D-490
- D-472
- D-497
plans:
- docs/plans/2026-10-24-neutral-transfer-closure-and-producer-design.md
- docs/plans/2026-10-24-managed-transfer-capability-design.md
- docs/plans/2026-10-11-mapless-fleet-control.md
- docs/plans/2026-10-11-stable-map-readouts-design.md
- docs/plans/2026-10-04-d442-omx-preempt-recovery.md
- docs/plans/2026-10-04-d443-signal-supervision.md
- docs/plans/2026-09-29-er2-mission-action-contract-closure.md
- docs/plans/2026-09-29-fleet-mission-control-arbitration-implementation.md
- docs/plans/2026-09-29-policy-evidence-contract.md
- docs/plans/2026-09-14-site-middleware-role-fabric-design.md
- docs/plans/2026-09-14-site-middleware-role-fabric.md
- docs/plans/2026-09-08-swarm-formation-slice-design.md
- docs/plans/2026-09-08-swarm-formation-slice.md
- docs/plans/2026-09-08-swarm-formation-slice-results.md
- docs/plans/2026-09-15-module-harness-design.md
- docs/plans/2026-10-02-platform-architecture-v02-migration.md
- docs/plans/2026-09-21-fleet-signals-integration-design.md
- docs/plans/2026-09-22-fleet-signals-integration.md
- docs/plans/2026-09-27-uiux-surface-closure.md
- docs/plans/2026-09-28-site-camera-preview-rectification.md
- docs/plans/2026-09-29-er2-semantic-actions-mission-implementation.md
- docs/plans/2026-10-01-model-tool-contract-implementation.md
---
## 현재 상태 (2026-09-27)

- 2026-10-07 D-488 M1 검토 반영: 경유지 층 A*·길이 0 간선 거절·계획 불가 지도 활성화 거절·`TRIP_PLAN_FAILED`·이름 있는 초안 저장. ADR 번호는 D-488/489/490(옛 D-484/485/486), API Ref v1.111.
- 2026-10-07 D-488 M1(SOURCE/LOCAL): `rosy.site_map/1` 스키마·초안/활성 버전 저장·이름 있는 운영자 활성화(차선 경로 진행 중 거절)·`--site-map-import` 첫 지도, `default_graph()` 하드코딩 제거(`/route`·만남 기하가 활성 지도를 읽음), D-489/D-490 차로 단위 상태 A* 계획기와 `POST /trip` 계획 응답(실행 없음, `/trips/{id}/start` 501), `/console/site-map` 보기·초안 편집·경로 미리보기. Gazebo·실차·로봇 능력 필드·trip 실행은 M2 이후다.
- 2026-10-07 D-494 5(SOURCE/LOCAL, 브랜치 `feat/d491-fleet-trip-loop`): 계획 본문 저장, `/trips/{plan_id}/start`·`/cancel`·`/confirm-replan`·`GET /trips`, 상태기계와 0.5 s 루프, 활성화 가드를 진행 중 trip으로 교체, 콘솔 지도 화면 운행 칸. 능력(1항)·지도 자세(3항)·교차로 API(4항) 제공자는 형제 브랜치가 착지한 뒤 연결한다. 기본 연결은 `TRIP_ROBOT_CAPS_UNKNOWN`으로 시작을 거절한다. Gazebo·실차는 미실행.
- 2026-10-05 CLI 구조 후속: 기존 Mission·Cell·evidence·카메라 pairing·등록 TLS 생성 본문을 91줄 console builder로 옮겼다. optional imports, 기존 CLI 거절·alias, enrollment load→roster sync 및 한 번의 create_app 조립은 유지한다. CLI는 652→586줄이다. 기존 CLI/TLS 55 passed/Windows symlink 1 skipped와 본문 AST 동등·새 interpreter의 비활성 optional dependency 미로드를 확인했다. 런타임 권한·배포·기기 gate는 바꾸지 않았다.

- 2026-10-05 D-456 등록 TLS 전송: 기존 암호화 등록 ID만 공개 origin·CA DER 지문에 묶어 HTTPS/WSS 발견 주소를 인증한다. 주소·ciphertext·principal·만료는 바꾸지 않는다. 공개 downgrade 방지 기록은 설정 누락·교체·재시작에도 남으며, 정상 로그아웃이 확인된 등록 행 삭제에만 함께 지운다. 관련 기존 회귀 206 passed/Windows 파일 권한·symlink 2 skipped, 마지막 새 테스트 23 passed/symlink 1 skipped, 독립 tail 5 passed와 SOURCE Safety 검토를 기록했다. TLS marker·CA·신원·WSS·await 경계 6개 실제 소스 변이는 각각 RED 뒤 원본 GREEN으로 확인했다. 실제 사이트 관리자 설정·TLS/WSS handshake·장기 승인 갱신·운용 수용은 별도다.

- D-306의 Fleet 목표 지정 개선으로 지도에 키보드 좌표 선택, 대상·좌표 확인, 취소 후 포커스 복귀를 추가했다. 브라우저 회귀 18건과 확인 계약 3건을 LOCAL에서 검증했다. 지도 1920/390/320 상태별 G2 판정과 실물 이동은 아직 별도다.
- Formation geometry(FOR-001), slot assignment(FOR-002), relay(D-31), formation session(FOR-004), 그리고 SiteHub의 HELLO/HEARTBEAT/EVENT 수집과 REST scatter(D-59)는 CORE API 경계를 유지한다. Browser/SiteHub는 DDS/ROS에 직접 연결하지 않는다.
- G-S3 신호등 연동은 상태 수집과 명령 표시를 제공하지만 안전 인터록은 아니다. CORE의 로컬 stop/safety 책임을 대체하지 않는다.
- 별도 `fleet_pairing_token`으로 연결된 CORE Agent의 HELLO/HEARTBEAT/EVENT 경로를 candidate에서 확인했다. 이벤트는 authenticated API로 조회되며 SQLite에서 Fleet restart 이후에도 유지된다.
- Operator web/API와 task queue를 검증했다. navigation 요청은 `REQUESTED → QUEUED`에서 멈췄다. 합성 `nav.completed`는 별도 synthetic event이므로 task의 실제 완료나 로봇 동작으로 해석하지 않는다.
- Overhead WSS → CPU ArUco → Fleet sighting 경로와 SQLite restart 보존을 확인했다. 합성 sighting의 `quality`는 `null`이므로 D-268 policy evidence가 아니다. 자동 이동/집기는 HOLD다.
- 자세한 candidate image/hash와 실행 범위는 `docs/validation/2026-09-26-site-stack-container-smoke.md`에 기록했다. LOCAL 증거는 Windows Docker Desktop `linux/amd64` 및 synthetic fixture 한정이다. Ubuntu/RTX 5080/GPU, 현장 TLS/LAN, 실물 phone/CORE/robot은 아직 미검증이다.
- D-413 Task 7 재생 checkpoint에서 Fleet과 OMX SQLite를 각각 다시 열었다. 로컬 수락 뒤 submit 응답을 잃은 경우 Fleet은 같은 Action/attempt를 조회하고 재제출하지 않으며, 늦은 `SUCCEEDED`만으로 `HOLD`나 자원 점유를 풀지 않는다. 독립적인 새 카메라·그리퍼 증거가 목표를 확인하면 완료한다. Fleet 이벤트 watermark와 Action phase journal 전진도 함께 확인했다. 재생 계약 1건, Fleet 1371 passed/7 skipped, OMX ActionStore 23 passed. Gazebo/Jazzy는 이 호스트에서 실행하지 않았다.

## 다음 gate

- 2026-10-05: 목표 취소 직후 Escape·1920×1080 기본 화면 적합·카메라 미지원 중복
  조회를 수정했다. 기존 시작점 저장·재로드·권한 변경·지도 교체 회귀를 유지했다.
  실제 Chromium fixture 증거이며 현장 명령·연결 수용이나 기존 HOLD 해제를 뜻하지 않는다.

1. Ubuntu 24.04 현장 호스트에 immutable candidate를 설치하고 Docker/Compose, 재부팅 복구, loaded image ID, TLS/FQDN/firewall 및 RTX 5080 driver를 확인한다.
2. 실제 CORE와 천장 phone을 연결해 pairing/authentication, reconnect, event/task correlation, timestamp/freshness 및 sighting 품질을 관찰·기록한다.
3. D-268 evidence 형식과 freshness/false-trigger 수치를 합의·측정하기 전까지 자동 policy task 생성을 비활성으로 둔다. 통과 이후에도 운영자 승인과 CORE 안전 조건을 확인하는 별도 제한 시험이 필요하다.
4. 로봇암 집기와 Pinky/로봇 onboard camera는 각각 별도 계약과 장치 gate로 검증한다.

## 현재 유효한 금지사항

- `formation/`과 `swarm/arming.py`는 `httpx`/`websockets`/`rclpy`/`asyncio`를 import하지 않는다(순수성, `test_boundaries.py`가 강제).
- `hub/`는 `core.protocol.schemas` 외 `core`의 무엇도 import하지 않는다(D-18, D-59).
- Hub는 `COMMAND` envelope, `cmd_vel`/`image`/`twist` 페이로드, `PEER` 참조 소스 scatter를 `ROLE_VIOLATION`으로 거절한다(D-59, D-31).
- 관제 UI 가 로봇 `cmd_vel`·DDS 에 붙지 않는다(설계 §6). 내리는 것은 원자 액션뿐이다.
- `map` 프레임을 로봇별로 접두하지 않는다. CORE 가 `map` 고정으로 pose 를 읽고 목표를 받는다(`ros_bridge._map_frame`).
- `core`를 이 패키지에서 수정하지 않는다. 로봇 계약에 없는 것은 API Ref 사이클의 finding이지 로컬 patch가 아니다.

### 2026-10-10 D-623 current image and recovery context

SOURCE implemented; remote verification pending. No Fleet REALIGN activation or field motion proof.

### 2026-10-12 D-685 최소 사람 개입과 학습 원본

승인된 autonomous_robots의 WAIT/완료 YIELD 재관측, 같은 사건 예산 유지, UNKNOWN durable freeze와 정확한 CORE 사건 종료 확인, 범위 내 검증된 trip 재계획을 구현했다. SharedGather refresh의 센서/state 원장을 bounded durable 저장하고 read_guard 조회와 hash export로 AI 학습 원본을 준비한다. labels/model activation은 자동 생성하지 않는다. 7c0e4f049 원격 238 pass/NEW 0 및 Node 52 pass; 최종 최신 main 착지 gate 별도. SOURCE 증거이며 설치·실기·FIELD gate는 유지한다.


### 2026-10-16 D-772 기존 TripRunner의 충전 복귀 포트

`ChargeReturnTrip`은 충전 세션의 계획·lease·correlation을 첫 RPC 전에 저장하고 기존 TripRunner를 한 번만 제출한다. 명시적인 active route map→station map 결속, 실제 경로 끝점·에너지 admission·현재 설치 버전·세션 예약을 재검사한다. 실제 trip 도착과 CORE 정지 handover ACK 후에만 SUCCEEDED이며 충전 예약은 유지한다. 재시작과 finish 응답 불명은 재제출하지 않는다. DB 장애·경합 전에 실행 token을 차단하고 정확한 CORE/trip/lease 정리를 시도한다.

fbdb175a7 원격 179개 시험 이후 bb966bcb6의 Fleet·구조·안전·harness 393개 시험과 d87c81995의 CORE·이미지 통합 148개 시험을 통과했다. 각 NEW 0, skip 0이며 두 SHA 사이 변경은 이미지 시험의 소스 경로 보완뿐이다. CORE 복귀 포트는 이 시험에서 SIM이며 실제 HTTP 포트·운영 bootstrap·주기 배터리 정책·안전 이안/재투입·실기 수용은 미완료다. 자동 활성화와 FIELD gate는 유지한다.

### 2026-10-16 D-772 실제 HTTP 복귀 허가와 측정 정지 인계

`StationReturnHttp`가 기존 인증 클라이언트의 station binding·return permit·finish·exact lease DELETE를 사용한다. native generation은 첫 grant 전에 원장에 고정한다. 갱신은 같은 원래 범위만 허용하며 만료와 불명 응답을 재제출로 바꾸지 않는다. 명시적인 standstill 409만 RUNNING 대기로 처리한다. ChargeMotion은 만료된 캐시 ACK를 실제 CORE readback으로 갱신하고 원래의 TTL과 robot/session/map 범위를 재검사한다. a6382343c 원격 91개 시험 통과, NEW 0이며 실제 TripRunner/HTTP/CORE owner를 조합했다.

3a7348119에서 lost finish reply·성공 후 readback 유실을 포함한 HTTP/Fleet/transport/구조/안전/harness 337개와 기존 CORE 권한·이미지 접안/충전 148개를 통과했다. 각 NEW 0/skip 0이며 실제 자동 lifecycle 수용 범위는 아래 제한을 따른다.

이 시험의 motion backend·에너지·odom 정지 표본과 IDLE 전환은 SIM이다. 실제 NavigationManager는 ARRIVED 후 arbitration 모드를 자동 IDLE로 바꾸지 않는 것을 확인했다. 따라서 terminal native owner/quiescence를 확인하는 제한된 NAVIGATION→IDLE 인계가 다음 필수 구현이며, Task 7 전체는 아직 미완료다. 운영 bootstrap·배터리 주기 정책·안전 이안/재투입·실기 수용도 남아 있다.

후속 50a6ef719에서 실제 terminal NavManager·GoalTracker의 quiescence를 확인해 CORE가 조건부 IDLE 인계를 수행하도록 연결했다. TripRunner/HTTP 통합 시험의 수동 IDLE 전환을 제거했고 관련 35개 시험을 통과했다(NEW 0). backend 결과·plant·에너지·odom은 여전히 SIM이며 운영 bootstrap·전체 cycle과 실기 수용은 미완료다.

### 2026-10-16 D-772 연속 HTTP 복귀·영상 접안·충전 확인

ChargeRobotHttp가 ChargeService의 bind/return/dock/read/stop 포트를 실제 인증 클라이언트와 기존 TripRunner에 연결한다. 연속 시험에서 native navigation이 진행 중인데 다음 lookahead를 보내던 문제를 재현했다. 충전 job은 명시적 readiness 의존성이 없으면 거절하며, 실제 native 상태를 읽어 다음 목표와 finish를 지연한다. route 도착 후 terminal 대기는 stall_s로 제한하고 자원 예약은 유지한다. 같은 위치 버전의 시각/유효기간 갱신은 불변 좌표·출처 비교와 별도 TTL 검증으로 처리한다.

c3ac314b5 원격 CORE/HTTP 144개, 3f44891bd Fleet 회귀 149개 통과, 각 NEW 0/skip 0. 연속 경로는 request_return부터 CHARGED_HOLD까지이며 상대 접안 입력은 실제 JPEG 검출 결과다. 전역 map pose·주행 모델·접점/BMS·에너지는 SIM이다. 운영 bootstrap·주기 정책·안전 이안/재투입·스테이션 이동의 실시간 전역 producer·3회 전체 cycle·실기 수용은 미완료이며 goal은 계속 진행 중이다.

후속 39f94f151에서 실제 charge_goal_gate를 별도 Safety 모듈로 추출하고 native/정지 대기의 공통 제한을 검증했다. CORE 237개와 Fleet·공유 계약·구조·안전·설치·harness 486개, 총 723개가 같은 SHA에서 통과했다(각 NEW 0/skip 0). 전체 CI나 실기 gate를 승격하지 않으며 위의 운영·주기 정책·이안/재투입·현장 수용 항목은 남아 있다.

### 2026-10-16 D-772 주기 평가와 기존 app의 충전 worker

이전 기록의 주기 정책·app bootstrap 미연결은 소프트웨어 범위에서 보완했다. 명시적 factory로 같은 TripRunner/TaskStore/ChargeStore/StationService/HTTP client를 결속하고 원본 에너지 근거로 복귀를 주기 평가한다. 최종 task admission은 task/request digest를 대조하며 초기 미평가와 만료·저SOC·불명 건강도에서는 새 작업을 수락하지 않는다. 정지용 exact intent 캐시는 재승인에 사용하지 않는다. 재시작/site stop은 충전 robot/station claim을 UNKNOWN으로 보존한다.

원격 fad32a155 연속 runtime/실제 trip·HTTP·영상·충전 회귀 129개, a692cb51e app/충전/task 154개, 209bfafc4 DB 이관/구조/안전/설치/재시작 170개가 각각 NEW 0/skip 0으로 통과했다. 서로 겹치는 범위이며 합산하지 않는다. 앞선 guard의 크기 실패와 중간 migration 추출 누락도 수정 후 해당 경로를 재검증했다. scoped 독립 안전 검토를 수행했으며 전체 CI·FIELD gate는 승격하지 않는다.

하드웨어는 미정이다. 원본 시각·팩 ID·SOH/용량·온도·경로 비용을 제공하는 실측 adapter와 CLI/배포 구성은 별도 필요하다. 같은 버전 위치의 장시간 충전 갱신, 안전 이안·재투입, 독립 전역 위치 producer, 3회 전체 cycle 및 실기·현장 수용은 남아 있다. 전체 목표는 ACTIVE다.

### 2026-10-16 D-772 같은 버전 위치의 장기 세션 갱신

기존 ACK 갱신만으로는 CORE의 원래 target 수명을 늘릴 수 없던 단절을 보완했다. 실제 owner 조회마다 새 전역 위치 근거를 동기화하며 기존 binding이 살아 있을 때만 같은 session/target의 새 capture를 수락한다. feed·착좌·완료 근거의 수명은 유지한다. 이전 기록의 장시간 같은 버전 갱신은 소프트웨어 범위에서 검증됐으며, 독립 전역 producer·실측 profile·이안/재투입·3회 전체 cycle와 FIELD는 남아 있다.

원격 f1726a72e Fleet/guard 178개, 1f45569ca CORE/HTTP 190개, 741c9b95f 충전 유지와 완료 수명/영상/sensor 134개가 각각 NEW 0/skip 0으로 통과했다. 범위 중복으로 합산하지 않는다. 2초 SIM 위치 lease를 넘겨 3초 CHARGING을 유지했으며 전역 후보·주행·BMS·접점·에너지는 SIM이다. scoped 독립 검토를 거쳤고 실기 capability는 활성화하지 않았다.

## 2026-10-17 · D-775 실측 교정 운영 연결

실측 수치 묶음의 목적별 승인·영속 저장·현재 촬영 session 확인·미리보기·철회 경로를 추가했다.
기존 tracking/sighting 승인과 World/CORE 권한은 유지한다. 원격 시험의 커밋·실행·실패 수정·skipped와
실측 근거의 한계는 [구현 검증 기록](../../docs/validation/measured-camera-lifecycle-2026-10-16/result.md)에 모은다. 기존 모듈 gate의 물리 수용 범위를
넓히지 않는다. D-598의 현재 현장 readback·로봇별 오차 계수는 아직 확보하지 못했다.

## 2026-10-24 · D-856 두 표본 물리 검사

source205의 내부 validator는 World 사실과 설치 정책/durable attempt context를 대조한다. 물체 model origin의 source/target pose, 전체 참가자9개 링크의 정지·엄격한 구역 이탈, 두 표본 freshness/순서/경계 이후 조건을 검사한다. quaternion norm 오차와 직접 축소 descriptor를 회귀로 보완했다. 집중67 passed/skip0, affected 전체 두 묶음4587 passed/189 skipped와6312 passed/336 skipped·각exit0/known0 NEW와 독립 재검토를 확인했다. 범위 중복과 skips는 합산/수용으로 세지 않는다.

credential ingress·현재 원장에서 만든 context/fence·physical create/approval·claim 해제 transaction·Harbor ARM은 아직 연결하지 않았다. validator 성공은 receipt나 점유 해제 권한이 아니다. [검증과 한계](../../docs/validation/harbor-physical-evaluator-2026-10-24/result.md)를 따른다. 기존 모듈/현장 gate의 수용 범위를 넓히지 않는다.
