# Station Charging Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in this session. Steps use checkbox syntax for tracking. Independent safety review remains required before integrating safety changes; do not assume a reviewer is available.

**Goal:** 스테이션 이동 시 새 좌표를 검증·공유하고 배터리 잔량·건강도·작업 비용에 따라 복귀, 정밀 접안, 충전 완료 확인, 이안과 재투입까지 연결한다.

**Architecture:** Fleet은 검증된 스테이션 위치 버전·예약·충전 세션·에너지 정책을 소유한다. Vision은 출처와 오차 근거가 있는 관측만 제공하고 CORE는 로컬 접안·정지·충전 확인·이안을 소유한다. 기존 trip·작업 원장·admission을 연결하며 별도 범용 실행기를 만들지 않는다.

**Tech Stack:** Python, Pydantic, SQLite, FastAPI, 기존 ArUco/교정 모듈, ROS 2 Jazzy, 원격 pytest·Gazebo.

**Spec:** [승인 설계](2026-10-16-station-charge-lifecycle-design.md). 기준 checkout은 `436d52a55`, 브랜치는 `docs/station-charge-lifecycle`. 사용자 실행 승인: 2026-10-16 "그럼 그걸 토대로 목표를 잡아서 실행해줄래?". 현재 세션에서 직접 순차 구현한다.

## Global Constraints

- 스테이션 1개, 이동 로봇 1대의 전체 사이클을 먼저 검증한다. 다중 로봇 전체 수용을 주장하지 않는다.
- CORE가 최종 속도 writer다. Fleet·Vision이 ROS 모터 출력을 발행하지 않는다.
- 명령 ACK·소프트웨어 정지·실제 정지를 구분한다. 미측정 SOH와 운행 시간은 unknown이다.
- 목표 위치는 station/map/revision/위치 버전에 결속한다. 위치 변경 시 이전 시도 종료 확인 전에 새 목표를 실행하지 않는다.
- 기존 SAF-005·접점 인터록·수동/E-stop 우선권을 유지한다. 만충 이벤트 하나로 자동 출발하지 않는다.
- 공개 계약 변경은 SRS·API reference·공유 schema·producer/consumer 시험을 함께 갱신한다. ADR 번호와 API 버전은 기존 예약 도구로 선점한다.
- 제품 변경은 현재 worktree에서만 한다. main 착지·push·실기 capability 활성화는 이 계획의 실행 완료와 구분한다.
- pytest와 Gazebo는 원격에서 수행한다. 로컬 pytest 우회는 없다. 원격은 커밋된 SHA만 시험하므로 각 RED/GREEN 후보를 먼저 커밋한다.
- 실물 임계·공차·제조사 충전 조건은 측정된 장치 프로필에 둔다. 결측 프로필은 실행 거절이다. 시뮬레이션 접안 비교 기준은 위치 20 mm·방향 5°다.

## Review Focus

1. 복귀 중 스테이션 위치 버전이 바뀌면 오래된 목표와 새 목표가 겹치지 않아야 한다(Task 2, 7).
2. 충전 종단으로 charging=false가 된 직후에도 정상 완료와 접촉 불량을 구분해야 한다(Task 4).
3. 카메라가 스테이션과 함께 이동하면 오래된 지도 교정으로 새 위치를 확정하지 않아야 한다(Task 3).
4. 배터리 교체·센서 결측·부하 변경을 건강도 회복 또는 에너지 증가로 오인하지 않아야 한다(Task 5).
5. 완료 이벤트 중복·Fleet/CORE 재시작·이안 결과 불명에서 중복 출발이나 작업 재발행이 없어야 한다(Task 6, 8).

## 작업 파일과 책임

아래 새 파일은 계획상의 경로다. 기존 import 별칭은 각 모듈 source mapping과 package 설정을 유지한다. 변경 직전 최신 main 및 `device-power-port`, `robot-map-anchor` 진행 브랜치와 중복 여부를 다시 확인한다. 다른 브랜치를 검증 없이 의존성으로 가져오지 않는다.

실행 부기: Fleet 크기 검사에 따라 Task 2의 station_store/service/routes는 `operations/fleet/fleet/server/site_observation/`에 배치했다. 기존 sightings·tracking/교정도 같은 holder에 두며 `fleet.server.*` import는 유지한다. Task 2 조회 installer는 opt-in이며 실제 app 구성·producer 인증 연결은 Task 9에서 함께 수행한다.

실행 현황(2026-10-16): Task 1 공유 계약과 Task 2 위치 원장은 원격 검증을 마쳤다.
후속 안전 검토로 카메라 위치·충전기 종단의 원본 표본 시각을 추가했고 API는 v1.251다.
Task 3의 카메라 기하/관측 어댑터, Task 4의 착좌·정상 종단, Task 5의 순수 에너지 정책,
Task 6의 자원 예약·영속 실행 의도·장애 시 정지, Task 7의 로컬 CORE 연결을 검증했다.
Task 9 중 CORE 위치 수락·관측·접안 시작·현재 근거 조회 API를 먼저 연결했다.
관제 principal과 session/native boot/generation을 결속하며 수락만으로 이동하지 않는다.
원격 fa44d4ee4에서 관련 127개 시험을, e2e24c3145에서 기존 도킹/API/공유 계약 회귀를 통과했다.
명시적 station_ingress와 source 전용 현재 scope 조회, 전용 카메라 worker/publisher를 연결했다.
원격 22288420c에서 전체 overhead·관련 Fleet·구조/안전 시험 719개를 통과했다.
27427874e의 실제 JPEG→Fleet/CORE HTTP→기존 접안 제어기 시험은 이상적 운동학 SIM에서
위치 20 mm·방향 5° 이내 정렬, 접촉·측정 정지 없을 때 착좌 차단, 정상 종단 후
CHARGED_HOLD와 예약 유지, 표식 손실 시 확인 해제를 검증했다. 광학·접촉·BMS는 합성이다.
이 시험에서 이전 카메라의 만료가 다음 측정 scope에 상속되는 갱신 단절을 발견해
독립 RED 87c6522a1 뒤 497c4a595에서 수정했다. 기존 착좌 근거의 수명을 연장하지 않는다.
95e680d74에서 CORE의 현재 착좌·충전·완료 근거를 Fleet 영속 세션 상태에 반영했다.
접안 성공 이후 native operation ID를 유지하고 현재 intent/correlation·boot·배터리·지도·ACK와
만료를 대조한다. 완료로 자원을 해제하지 않으며 이후 근거 유실은 HOLD다.
987bea4e4의 54개 관련 시험에서 실제 이미지/HTTP/제어기와 Fleet 상태 반영을 함께 검증했다.
복귀 trip handover·readiness·에너지 예산은 이 시험에서 명시적 SIM 대체물이다.
다음 구현은 Fleet 실제 trip/native 포트, 운영 API/표시, 주기 스케줄러, 자동 이안·재투입과
연속 시뮬레이션이다. 실기 프로필·현장 수용은 미검증이다.
CORE station 설정은 기본 비활성이며 명시적 simulation 프로필만 구성한다.
Task 7의 CORE 복귀 허가·정지 후 인계 경계를 d5c1a61e4의 원격 283개 시험에서 검증했다.
기존 trip lease의 정확한 소유자·ID·trip·job_id=session과 native boot/generation을 결속하고,
최종 출력에서 원본 lease/허가 만료를 비차단 검사한다. 실제 scope 손실은 latch하고
상태/native/lease lock 경합은 해당 주기만 차단한다. finish는 IDLE·새 측정 표본의 연속 정지를
확인해 BOUND로 넘길 뿐 도착이나 trip 성공을 입증하지 않는다. NAVIGATION 허가는 동일 lease
소유자의 후보 출력에 대한 허가이며 특정 경로 검증이 아니다. 전체 사이클 완료로 보지 않는다.
실제 Fleet 포트는 진입 정렬 전에 lease·허가를 수락하고 route/에너지·trip terminal을 따로 확인해야 한다.
Task 3의 절대 지도 기준을 갖춘 재발견 producer와 CLI/설치 프로필 구성은 아직 남아 있다.

| 책임 | 생성/수정 파일 |
|---|---|
| 공유 typed 계약 | 새 `contracts/foundation/core_common/protocol/station_charging.py`, 수정 `docking.py`, `power_health.py` |
| 스테이션 위치 원장 | 새 `operations/fleet/fleet/server/station_store.py`, `station_service.py`, `station_routes.py` |
| 카메라 관측 | 새 `operations/overhead/rosy_vision/station_observation.py`, 수정 기존 `worker.py`, `publish.py`, 교정 설정 |
| 로컬 관측·정착 | 새 `middleware/drive/behaviors/docking/station_feed.py`, 수정 `parking_phases.py`, `manager.py`, gateway `core/drive/docking.py` |
| 충전 완료 근거 | 새 docking `completion.py`, 수정 `agent.py`, `charging.py`, `strategies.py`, `manager.py`와 도크 firmware 계약 |
| 순수 에너지 결정 | 새 `operations/site_execution/src/rosy/execution/site/charge_policy.py`, `battery_evidence.py` |
| durable 충전 세션 | 새 Fleet `charge_store.py`, `charge_service.py`, `charge_routes.py`; 기존 admission·trip·task 연결 |
| API와 운영 표시 | CORE `api/v1/docking.py`, Fleet `app.py`, Console 전원/상태 표시와 공유 계약 문서 |

## Task 1: 계약과 변경 범위 확정

**Files:** 위 공유 계약 파일; `docs/spec/ROSY CORE SRS.md`, `docs/spec/ROSY FLEET SRS.md`, `docs/reference/ROSY API & Protocol Reference.md`; 새 ADR; `contracts/foundation/test/test_station_charging_schema.py`.

**Interfaces:** 새 계약은 `StationPoseRecord`, `StationPoseAck`, `StationObservation`, `MapPoseEvidence`, `SeatingEvidence`, `ChargeCompletionEvidence`, `BatteryEnergyEvidence`, `ChargePolicyProfile`, `ChargeDecision`, `ChargeSessionStatus`다. 전부 extra=forbid, 유한 수·시각·단위 검증을 가진다. `MapPoseEvidence`는 robot_id·map_id/revision·관측 시각·boot/odom 세대·x/y/yaw·오차 근거를 담는다. `ChargeDecision`은 결정 enum과 reason·근거 버전을 담는다.

- [ ] RED: `test_rejects_future_wrong_frame_and_nonfinite`, `test_unknown_health_is_not_full_capacity`, `test_pose_revision_is_separate_from_calibration_and_session`. null SOH가 100으로 변하지 않고 map revision/위치 버전 누락은 제어용 수락 불가임을 단언한다.
- [ ] ADR/API 예약 도구로 번호를 선점하고 producer→consumer, source credential 범위, 정책 활성화와 취소 계약을 문서화한다. 위치·관측·세션 readback/입력 경로는 이 ADR에서 고정한 뒤 해당 API 테스트에 문자열을 그대로 고정한다.
- [ ] typed 필드를 구현한다. 위치 기록은 station/map/revision/pose_revision/x/y/yaw/evidence/validity/진입 구간, 관측은 robot/station/session/boot/sequence/촬영 시각·오차/좌표계·교정, 에너지는 battery_id·측정 방법·수치·나이·capacity revision을 요구한다. 미측정 수치의 None을 보존한다.
- [ ] RED와 GREEN을 각각 커밋해 원격 `contracts/foundation/test/test_station_charging_schema.py`와 기존 docking/power schema 시험을 실행한다. 인접 공개 export와 API 버전 검사를 함께 통과시킨다.

## Task 2: 스테이션 위치 원장과 버전 수락

**Files:** 새 station_store/service/routes와 Fleet `app.py`; `operations/fleet/test/test_station_store.py`, `test_station_pose_service.py`, `test_station_routes.py`.

**Interfaces:** `StationStore.propose(record: StationPoseRecord) -> StationPoseRecord`, `confirm(station_id: str, *, expected_revision: int) -> StationPoseRecord`, `invalidate(station_id: str, *, expected_revision: int, reason: str) -> None`; `StationService.accept_ack(ack: StationPoseAck) -> bool`. 관측자는 후보를 내며 권위 있는 버전 발행은 Fleet만 한다.

- [ ] RED: 동시 confirm은 하나만 성공, 낮은 버전 ACK·다른 robot boot ACK 거절, 지도 revision 교체 시 invalid, 위치 바뀐 동일 station은 ID 유지, 다른 station ID는 별개임을 시험한다.
- [ ] SQLite 기존 migration 패턴으로 후보/확정/무효화 기록과 감사 내역을 저장한다. 버전은 원자적으로 증가시키며 invalidate를 이전 계획과 예약 소비자에게 전달한다.
- [ ] active 설치 기록과 접근 구간이 없는 위치를 복귀 가능으로 노출하지 않는다. 위치 유효기간 만료와 source epoch 변경을 invalid로 처리한다.
- [ ] 원격 해당 3개 시험 GREEN과 재시작 영속성 시험을 확인하고 커밋한다.

## Task 3: 스테이션 재발견·상대 관측 producer

**Files:** 새 station_observation.py와 기존 Vision worker/publish; `operations/overhead/test/test_station_observation.py`; 새 docking station_feed.py와 `middleware/core/services/test/test_station_feed.py`.

**Interfaces:** `station_map_pose(robot_map: MapPoseEvidence, relative: StationObservation) -> StationPoseRecord`는 공통 프레임/시각의 유효 근거가 있을 때만 변환 후보를 반환한다. `StationObservationFeed.ingest(observation: StationObservation, *, received_at: float) -> bool`, `relative_pose() -> DockObservation | None`는 기존 검출기 Protocol에 맞춘다. 절대 지도 기준이 없는 상대 관측은 설치 위치 confirm에 사용하지 않는다.

- [ ] RED: ±90° 회전·병진·마커 offset 변환을 독립 계산 참값과 비교한다. station과 함께 이동한 카메라의 구 교정, 상대 관측만의 절대 위치 확정, 다른 target/boot/session, 미래·역순·만료 관측을 거절한다.
- [ ] 기존 ArUco와 승인 교정을 재사용하고 station 마커를 robot sighting과 별도 식별한다. 고정 카메라 방식, 지도 마커 방식, 유효한 robot map pose와 상대 관측의 합성 방식을 출처로 구분한다.
- [ ] remote/local 시계는 전달 지연 상한과 송신 나이를 검증해 변환하고 odom 시각 짝을 요구한다. 검증된 시계 결속이 없는 입력은 제어용으로 사용하지 않는다.
- [ ] 사각지대·카메라 미교정은 invalid로 내보내고 bounded 재설치/재탐색 상태를 제공한다. 시야 밖의 이동을 검출했다고 표시하지 않는다.
- [ ] 원격 두 모듈 시험과 기존 마커/교정 회귀를 통과시키고 커밋한다.

## Task 4: 착좌·실제 정지와 충전 종단 근거

**Files:** docking completion.py, manager/parking_phases/charging/agent/strategies; `middleware/core/services/test/test_station_seating.py`, `test_charge_completion.py`, `test_docking_review_fixes.py`; 도크 README/firmware와 `test/test_dock_contract.py`.

**Interfaces:** `SeatingGate.update(evidence: SeatingEvidence, *, now: float) -> bool`; `ChargeCompletionTracker.update(evidence: ChargeCompletionEvidence, *, now: float) -> bool`, `reset(session_id: str) -> None`. Gate의 속도·위치·debounce 임계는 검증된 프로필에서 주입한다.

- [ ] RED: stop 명령만 수신·odom 만료·접촉 미확인·위치 밖이면 false; 연속 실측 정지+착좌+허용 위치일 때만 true다. 접촉이 남아도 움직이면 false다.
- [ ] RED: manager의 실제 tick 순서로 `정상 충전→충전기 정상 종단→charging=false`를 재현하고 완료가 유지됨을 단언한다. 동일 전류 false라도 종단 근거 없음/접촉 상실/fault면 자동 출발 불가다. 이전 세션 완료 입력은 거절한다.
- [ ] 충전 중 확인 창의 reset과 세션 완료 근거를 분리한다. 기본 전압 전략은 진단/기존 호환으로 유지하고 새 자동 운영의 출발 근거로 사용하지 않는다. 도크가 정상 종단 이유를 계측하지 못하면 UNKNOWN을 보존한다.
- [ ] 전류·종단·센서 상태 추가는 기존 필수 필드를 유지하는 장치 계약으로 문서화한다. firmware가 측정하지 않은 값을 생성하지 않고 미지원으로 보고한다. MCU 부하 인터록은 로컬 유지한다.
- [ ] 원격 서비스 시험과 도크 계약 GREEN을 확인하고 safety 경로 독립 검토 요청 대상을 기록한 뒤 커밋한다.

## Task 5: 배터리 근거와 작업별 에너지 예산

**Files:** charge_policy.py, battery_evidence.py; 기존 consumer 시험 소유 위치에 `operations/fleet/test/test_charge_policy.py`, `operations/fleet/test/test_battery_energy_evidence.py`; battery.health producer와 power_health.py. execution wheel과 site gateway의 packaging/source closure도 검증한다.

**Interfaces:** `evaluate_charge_policy(battery: BatteryEnergyEvidence, profile: ChargePolicyProfile, *, work_wh: float | None, return_wh: float | None, reserve_wh: float, dock_valid: bool) -> ChargeDecision`. 결정은 `WORK_ALLOWED`, `RETURN_REQUIRED`, `WAIT`, `MAINTENANCE_HOLD`와 근거를 포함한다. 실행 명령을 내지 않는다.

- [ ] RED: 사용 가능 에너지와 작업+귀환+대기/접안+예비의 경계값, 열화 용량 감소, 불확실성 상한, 긴 귀환 경로, profile/battery ID 변경과 stale를 시험한다. 전압 증가를 SOH 회복으로 해석하지 않는다.
- [ ] 측정 SOH가 없으면 unknown을 보존하고 승인된 보수적 최대 시간/잔량 프로필에만 fallback한다. 이 프로필도 없으면 작업 수락 불가다. 팩 계측과 도크 계측을 혼동하지 않는다.
- [ ] 제조사 한도/실측 capacity 프로필을 입력으로 받고 부분 충전 출발은 별도 승인 프로필이 없으면 비활성이다. 주기 재평가와 사건 재평가 모두 같은 순수 함수를 호출한다.
- [ ] 원격 두 시험과 기존 배터리·저배터리 정책 시험 GREEN을 확인하고 커밋한다.

## Task 6: 예약·충전 세션 영속성과 장애 복구

**Files:** charge_store/service/routes, Fleet dispatch_admission.py 및 ledger/task_store.py 연동; `operations/fleet/test/test_charge_store.py`, `test_charge_recovery.py`.

**Interfaces:** `ChargeService.request_return(robot_id: str, station_id: str, *, pose_revision: int, reason: str) -> ChargeSessionStatus`, `reconcile(session_id: str) -> ChargeSessionStatus`, `cancel(session_id: str, *, reason: str) -> ChargeSessionStatus`. store가 단일 트랜잭션으로 기존 robot/station claim과 충전 세션을 결속한다.

- [ ] RED: 작업 배정과 복귀 예약 경쟁, 중복 복귀 요청, 로컬 저배터리 복귀 선행, station invalidation, 재시작 중 dispatching UNKNOWN을 시험한다. 두 움직임이 동시에 제출되지 않음을 fake port 호출로 단언한다.
- [ ] 기존 claim/admission/세션 기록을 확장해 lifecycle을 저장한다. 이벤트 ID/attempt/boot로 멱등 처리한다. 재시작 시 CORE·도크 readback 전에는 이안/복귀를 재발행하지 않는다.
- [ ] DB 오류·전송 후 응답 소실은 UNKNOWN/HOLD로 저장하고 자동 재시도하지 않는다. 기존 CORE 저배터리 긴급 처리는 우선한다.
- [ ] 원격 새 시험과 기존 task scheduler/admission 회귀 GREEN을 확인하고 커밋한다.

## Task 7: 위치 버전을 가진 실제 복귀·로컬 접안 연결

**Files:** Fleet trips/trip_ports.py와 charge_service.py; CORE docking database/manager와 core/drive/docking.py, API docking.py; gateway `test/test_station_docking_wiring.py`; Fleet `test/test_charge_return.py`.

**Interfaces:** `ChargeReturnPort.start(session: ChargeSessionStatus) -> str`는 기존 trip/native operation ID를 반환한다. `stop(operation_id: str) -> None`, `read(operation_id: str) -> dict`로 기존 owner 결과를 대조한다. `StationObservationFeed`는 Task 3 인터페이스를 그대로 사용한다.

- [ ] RED: 새 위치 수락 전/다른 지도/검증된 진입 연결 없음이면 모터 출력과 trip start 0회. 복귀 중 위치가 바뀌면 stop 요청 후 terminal 확인까지 새 start 0회다.
- [ ] 기존 trip으로 검증된 진입점까지 이동하고 CORE native dock으로 넘긴다. CORE에 없는 지도 변환을 가정하지 않고 상대 관측만 최종 접근에 사용한다. 기존 원장 작업을 끝내지 못한 상태에서 충전 복귀를 빼앗아 시작하지 않는다.
- [x] 실제 free navigation이 ARRIVED 후 arbitration NAVIGATION을 유지하는 경로에 terminal/quiescence 기반 IDLE 인계를 연결했다. owner lock 아래 active goal/admission/callback 부재를 증명하고 MANUAL/E-stop을 보존한다. 인계 시점 이후의 원본 odom으로 새 정지 dwell을 충족해야 finish가 성공한다. 활성 backend를 취소하지 않고 거절한다. API v1.252·SRS·명시적 409 의미를 갱신했으며 통합 시험의 수동 IDLE 전환을 제거했다. 50a6ef719 원격 35개 통과, NEW 0. 실제 backend/계측·전체 cycle 수용은 별도다.
- 검증 추가: 002ee166e 원격 CORE 322개·Fleet/공유 계약/구조/안전/설치/harness 291개 통과, 각 NEW 0/skip 0. 운영 bootstrap과 전체 충전/이안/재투입 cycle은 여전히 미완료다.
- [x] ChargeRobotHttp를 기존 ChargeService·TripRunner·실제 CORE HTTP에 조합했다. c3ac314b5의 원격 144개에는 영속 예약/위치 수락→실제 trip→terminal 정지 인계→렌더된 영상의 상대 접안→착좌/충전 확인→정상 완료 대기까지 연속 흐름이 포함된다. 이전 native goal이 진행 중이면 다음 lookahead/finish를 보내지 않으며 세션 한정 중단은 응답 유실·근거 만료에서도 같은 실행만 닫는다. 3f44891bd Fleet 회귀 149개 통과, 각 NEW 0/skip 0. 주행 plant·전역 map pose·접점/BMS·에너지는 명시적 SIM이며 운영 설정과 3회 이안/재투입 cycle 수용은 남아 있다.
- 최종 관련 검증: 39f94f151에서 CORE 237개와 Fleet·구조·안전·설치·harness 486개가 모두 통과했다(각 NEW 0/skip 0). charge_goal_gate만 Safety로 추적하고 기존 Decision 경로 계산기 전체를 재분류하지 않는다. 공통 도착 대기 제한, 공개 API를 통한 통합 시험, v1.253 이력과 정확한 Vision 관측 경로·명령 금지를 포함한다. 확대 검사에서 발견한 누락은 수정했으며 전체 CI 통과나 실기 수용을 주장하지 않는다.
- [ ] 관측 유실 시 해당 제어 틱에서 zero 요청, 위치 버전 만료 시 로컬 중단, 종료 확인 뒤 새 버전으로 경로·에너지 재평가를 연결한다. 목표 좌표의 캐시를 실행 중 조용히 변경하지 않는다.
- [ ] 원격 두 새 시험과 docking mode ownership/release·localization gate 시험 GREEN을 확인하고 커밋한다.

## Task 8: 충전 완료 후 이안·작업 재투입

**Files:** charge_service와 ledger/task_service.py, task_scheduler.py; CORE manager/이안 포트; `operations/fleet/test/test_charge_redeployment.py`, gateway `test/test_charge_departure_gate.py`.

**Interfaces:** `ChargeService.evaluate_departure(session_id: str) -> ChargeSessionStatus`는 Task 4 완료 근거와 Task 5 예산으로 출발 허가를 만든다. 일반 작업 가용성은 완료 상태가 아닌 이안 완료·접점 이탈·경로 확인 이후에만 true다.

실행 구성(2026-10-16): API v1.254를 D-772 이안/측정 release 용도로 예약했다. 기존 DockingManager의 native undock와 CORE 최종 출력 경로를 사용한다. 첫 1대/1스테이션 프로필은 회전 없는 제한 후진이며 실제 dock type의 거리·속도를 프로필과 대조한다. 후속 작업의 방향 전환은 이안 후 기존 작업 항법이 맡는다. 프로필과 로컬 source adapter가 없으면 이안하지 않는다.

1. `StationDeparturePermit`은 session/attempt/boot/battery/map/pose revision, 선택 task/request digest, 정책·용량 revision과 native generation을 결속한다. `StationDepartureReceipt`는 같은 범위의 native undock 종료와 접점 이탈·정지·공간·출력 차단 표본을 결속한다. DTO 생성 자체는 실행/완료 근거가 아니다.
2. 로컬 `StationDepartureFeed`는 설치한 producer의 원본 공간·relay/current·접점·motion 시각과 source epoch/sequence를 보존한다. 재생·clock 변경·만료·경합은 출력 불가다. CORE HTTP로 이 근거를 주입하는 경로는 만들지 않는다. 실측 adapter가 없는 SIM 시험만 합성 근거를 넣는다.
3. 정상 완료와 최신 출발 근거가 있는 단 한 번의 scoped `station-undock`만 native 이안을 시작한다. `station-departure` 갱신은 같은 실행/작업만 유지하며 재시작하지 않는다. 출력 차단 확인은 이미 차단된 실제 relay 상태를 요구한다. 차단 명령/인터록은 설치 장치 owner가 제공해야 하며 미지원 장치를 차단됐다고 가정하지 않는다.
4. 최종 출력은 매번 현재 공간·무전류·차단·허가·local scope를 재검사한다. native SUCCEEDED 후에도 새 정지 cutoff/dwell·접점 이탈·route clear를 확인한 `station-departure/finish` 전에는 작업 가용성을 열지 않는다. 잃어버린 응답은 같은 owner readback으로 재조정하며 이안 명령을 반복하지 않는다.
5. Fleet은 기존 원장의 UNDOCKING intent를 전송 전에 저장하고 승인된 대기 task와 에너지 budget을 결속한다. 정상 receipt를 저장한 뒤에만 WORK_AVAILABLE과 claim 해제/기존 task dispatcher 재투입으로 간다. 중간 실패와 결과 불명은 claim을 유지한다. 같은 CORE/Fleet/runtime을 연속 3회 cycle에서 검증한다.

- [x] CORE 로컬 이안: 7d3f6418d 원격 194개 통과, NEW 0/skip 0. 실제 native 직선 후진과 새 실측 이탈/정지 Receipt를 분리했다. TTL은 센서별 원본 시각과 monotonic 잔여 수명에 제한하며, 시계 복구·표본 교체·다른 native generation·완료 근거 재조회가 권한을 늘리지 않는다. 프로필과 물리 facts는 명시적 SIM이며 장치 수용이 아니다.
- [x] CORE API 구현: v1.254 시작/갱신/실측 완료, 정확한 선행/진행 중 중단과 simulation 빈 피드 설치를 연결했다. 독립 안전 검토 scoped PASS. 1216b3f7b 원격 API·권한 행렬·native/owner·구조/안전/harness 412개 통과, 1f8569773의 Fleet/API 버전 계약 96개 통과, 각 NEW 0/skip 0. 앞선 194개와 범위가 겹치므로 합산하지 않는다. HTTP 정상 경로는 실제 native owner와 명시적 SIM 측정을 조합한 adapter 시험이며 전체 lifecycle/DEVICE/FIELD 수용이 아니다.
- [x] 기존 ChargeStore/TaskStore의 같은 트랜잭션에 선택된 QUEUED 작업 ID/digest·정책/용량 근거와 UNDOCKING intent를 저장한다. 실제 HttpRobotClient의 1회 제출·허가 갱신·실측 Receipt 조회를 연결하고, 정상 Receipt 저장 이후에만 claim을 해제한다. 기존 dispatcher가 그 작업을 최종 재검사해 배정한다. 요청 응답 유실은 재시작 허가가 아니다. 9286f5f77 실제 HTTP/native SIM 및 Fleet 원격 검증 근거는 아래에 기록했다.
- [x] 연속 cycle 전 CORE WORK_AVAILABLE의 이전 session은 새 IDLE·정지·부트/지도/배터리 검증 아래에서만 새 binding으로 교체한다. 과거 Receipt를 새 세션의 이탈 근거로 사용할 수 없다. a4ead2712 원격 282개 검증. 일반 작업의 native 완료→IDLE 인계 및 전체 연속 순환은 아래 후속 경로에 남는다.

- [x] 완료+작업 없음은 대기, 완료+승인 작업+최신 정상 근거는 이안 1회다. CORE 공간·전류·접점·local scope 거절과 Fleet의 작업 취소·수동·stale·미승인 정책/claim 경로는 관련 owner/runtime 시험에서 이동/해제를 막는다. 전체 연속 fault matrix는 Task 10에 남는다.
- [x] 이안 ACK·요청 응답 유실만으로 배정하지 않는다. 선택 task와 최초 motion fence를 보존하며 허가 갱신은 같은 실행만 유지한다. 원격 HTTP 시험에서 시작 응답 유실은 HOLD/claim 유지/재제출 0회, 완료 응답 유실은 동일 live Receipt GET 복구 또는 HOLD다. 전체 프로세스 재시작/3회 cycle 수용은 별도다.
- [ ] 최신 근거를 동작 직전 로컬 owner에서 다시 검사한다. 충전 중 스테이션 이동/접촉 상실은 이안 성공이 아니다. 기존 이안의 후방 검증 부족은 측정된 새 프로필 없이는 실기에서 열지 않는다.
- [ ] 원격 새 시험과 task queue/native operation 회귀 GREEN을 확인하고 커밋한다.

## Task 9: 운영 설정·readback·배포 경로

추가 실행 범위: 기존 app lifespan에 opt-in `charge_runtime_factory`를 연결한다. 실제 TripRunner·TaskStore·ChargeStore·StationService·HTTP client 객체가 다르거나 source 어댑터가 없으면 구성을 거절한다. 주기 평가와 실제 task 최종 admission은 원본 TTL을 유지하며, 선택 작업의 ID와 요청 digest를 에너지 budget에 결속한다. 재시작/site stop은 충전 claim을 UNKNOWN으로 유지하고 자동 재승인을 막는다. 이 내부 구성 추가는 REST/공유 DTO 변경이 아니며 API v1.253을 유지한다.

- [x] 주기 저SOC/작업+귀환+접안+예비 예산, 미측정 SOH·만료·scope 거절, DB 장애·취소·종료·설정 변경 회귀를 구현했다.
- [x] 기존 app lifecycle과 실제 객체 결속, 작업 claim 전 에너지 검사와 최종 task/request 결속을 연결했다.
- [x] 같은 버전의 새 전역 관측을 기존 CORE binding에 동기화하고, ACK가 계속 신선해도 원래 위치 수명의 만료를 놓치지 않도록 실제 owner 조회와 연결했다. 만료 binding·재사용 capture·만료 측정 권한은 거절한다.
- [ ] 실측 source 어댑터와 현장 설정·CLI/배포 프로필·운영 화면까지 검증한다. factory 설치 가능성을 실기 활성화 증거로 취급하지 않는다.

**Files:** Fleet app/charge_routes/station_routes, CORE docking readback, Console power-health-view.js; site 설정 예제와 배포 구성; `operations/fleet/test/test_charge_api.py`, Console browser tests, `test/test_station_charge_deployment.py`.

**Interfaces:** Task 1에서 고정한 경로와 schema만 사용한다. 운영 화면은 위치 확인 중·복귀·충전·완료 대기·출발 검사·HOLD와 각각의 근거/현재 버전을 표시한다.

- [ ] RED: viewer는 읽기만, 관측 credential은 등록 source/대상만 쓰기, 일반 운영자가 교정/배터리 계측 근거를 위조할 수 없음, 충전 중 일반 배정 차단을 시험한다.
- [ ] 정책과 실측 profile을 설정하되 실기 기본 활성화는 하지 않는다. packaging/source mapping과 프로필 누락 거절까지 연결한다. 현재 BatteryHealth를 SOH 수치로 표시하지 않는다.
- [ ] 원격 API·패키징·영향 browser 시험 GREEN을 확인하고 커밋한다.

## Task 10: 연속 사이클·스테이션 이동 원격 시뮬레이션

**Files:** 기존 simulation harness 구조를 따라 새 `tools/sim/station_charge_cycle.py`, `test/test_station_charge_harness.py`; `docs/validation/station-charge-2026-10-16/`에 실제 시험 시점의 결과 기록.

- [ ] RED: harness가 카메라 관측/착좌/충전기 종단/이안/작업 배정의 호출 경로를 건너뛰면 실패하도록 한다. ground truth 좌표를 제어기 입력으로 넣지 않는다.
- [ ] 원격 시뮬레이션 호스트를 `python tools/remote/remote_pytest.py --pick sim`으로 선택한다. 배터리·종단·SOH 모사는 SIM으로 명시하고 물리 계측으로 표시하지 않는다.
- [ ] 작업→복귀→정밀 접안→충전→이안→재투입을 3회 연속 실행한다. 독립 참값에서 위치 ≤0.020 m, 방향 ≤5°를 기록한다.
- [ ] 스테이션 병진·회전 이동, 접근 중 이동, 카메라 동반 이동, 사각지대, 지도 revision 변경, 통신 끊김, 재시작, 긴 귀환 비용, 충전 fault를 각각 주입한다. 이전 버전 목표 실행·중복 이안·허위 완료가 한 번이라도 있으면 실패다.
- [ ] 원격 pytest 로그·시뮬레이션 raw 결과·사용 SHA·환경·미검증 범위를 기록한다. safety 변경은 독립 리뷰 근거와 함께 검토한다.

## Task 11: 실기 계측과 현장 수용

**Files:** 실측 장치 프로필과 템플릿·벤치 절차·검증 기록. 실주소와 자격증명은 private에만 둔다.

- [ ] 설치 배터리/BMS/충전기의 신호를 확인하고 팩 전류·온도·capacity·정상 종단 계측 가능 여부를 기록한다. 불가능하면 필요한 계측 하드웨어를 명시하고 SOH 적응 수용은 미완료로 둔다.
- [ ] 카메라 교정·정지 속도 근거·리밋·접점 무부하 차단·정상 종단·후방 공간을 벤치에서 검증한다. 장치 사양과 독립 측정으로 실기 공차/예비량을 고정한다.
- [ ] 실제 스테이션 이동 후 관제 기록과 로봇 수락 버전, 복귀 경로와 독립 위치 오차를 비교한다. 적재/열화 조건과 장기 대기/재충전/재투입을 시험한다.
- [ ] 실기·현장 게이트를 충족한 구성에서만 capability와 운영 정책 활성화를 별도로 진행한다. 하드웨어/현장 접근 부재는 소프트웨어 성공으로 대체하지 않는다.

## 실행·검증 명령과 인계

각 task는 명시한 시험 경로를 다음 명령의 `<task-paths>` 자리에 넣어 실행한다. 로그 위치는 저장소 밖이며 후보 SHA를 고정한다.

```powershell
python tools/remote/remote_pytest.py --sha HEAD --log-dir C:/DevTemp/station-charge/task-N -- <task-paths> -q
python test/known_failures.py C:/DevTemp/station-charge/task-N/run-1.txt
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
git diff --check
```

RED는 새 시험의 의도된 단언 실패, GREEN은 해당 시험의 통과와 NEW 0으로 판정한다. 공통 contracts 변경으로 FULL 선택이 요구되면 영향 시험을 전체 CI의 대체로 취급하지 않는다. 실험 기록은 판정 가능한 SHA와 로그에 결속한다. 각 task 시작 시 D-766 크기 한도와 현재 baseline을 확인하고 기능을 추가할 공간이 없으면 기존 소유 범위 안의 응집된 분리와 계약 검증을 같은 task에 포함한다. 크기 예산을 임의 증액해 우회하지 않는다.

현재 Git 작성자 정보가 없어 초안 커밋 시도가 실패했다. 구현 실행에 들어가기 전 저장소의 정당한 작성자 설정을 확인해야 하며 다른 사람의 최근 커밋에서 신원을 복사하거나 전역 설정을 임의 변경하지 않는다. 커밋된 후보를 만들 수 없으면 원격 RED/GREEN도 실행할 수 없다.

계획 검토 후 권고 실행 방식은 현재 세션 직접 구현이다. 관측·계약·세션·실행의 의존성이 높아 같은 맥락에서 순서대로 진행한다. 별도 에이전트 위임은 지금 요청하지 않으며 safety 독립 리뷰 시 필요한 절차를 적용한다. 구현·시험·실기 확인을 모두 완료하기 전 전체 목표를 완료 처리하지 않는다.

## 2026-10-16 주기 runtime 실행 증거

- fad32a155: 원격 task-9-runtime-continuous 129 PASS/0 skip/NEW 0. 저SOC 주기 판단→실제 TripRunner/native return→JPEG 상대 접안→실측 신호 형식의 SIM 착좌·정상 종단→CHARGED_HOLD를 연결했다. 주행 plant·접점·BMS·에너지는 SIM이다.
- a692cb51e: task-9-charge-final 154 PASS/0 skip/NEW 0. 기존 app 시작·종료, 공유 객체 결속, 작업별 최종 에너지 입장 검사, DB·취소·정책·설정 변경, 재시작/site stop의 예약 보존을 검사했다.
- 209bfafc4: task-9-schema-retry 170 PASS/0 skip/NEW 0. 크기·안전·설치·DB 이관 및 실제 app/충전/재시작을 확인했다. 앞선 a692 guard 380 PASS/1 FAIL의 크기 실패와 548 이관 함수 추출 누락을 수정한 재검증이다. 범위가 겹치므로 통과 수를 합산하지 않는다.
- scoped 독립 안전 리뷰 완료. 미측정 profile·hardware, 장시간 위치 갱신, 이안/재투입·독립 전역 위치 producer·3회 전체 cycle는 미완료이며 전체 목표를 완료 처리하지 않는다.
- 209bfafc4: task-9-selection-final 65 PASS/0 skip/NEW 0. 영향 선택과 기존 Fleet CI shard 비용 상한도 유지했다.

## 2026-10-16 같은 버전 위치 갱신 실행 증거

- 40d405e5e의 RED 5건과 3e579caae의 실제 runtime 위치 만료를 재현했다. ACK가 계속 신선해도 CORE target은 원래 시각에 만료됐으므로 owner 조회 때도 새 위치 근거를 동기화했다.
- f1726a72e 원격 Fleet/guard 178개, 1f45569ca CORE/HTTP 190개, 741c9b95f 충전 유지·완료 수명/영상/sensor 134개 통과. 각 NEW 0/skip 0이며 범위는 일부 겹친다.
- 최초 2초 위치 lease 및 충전 시작 때의 lease를 넘겨 3초 동안 CHARGING을 유지하고 정상 종단을 처리했다. global 후보·plant·BMS/접점·에너지는 SIM이다. 실제 StationService 및 runtime/TripRunner/native/JPEG/인증 HTTP 경로를 사용했으며 독립 global producer의 운영 수용을 주장하지 않는다.
- 같은 capture의 TTL 연장과 만료 binding 부활, stale/future 권한은 차단하고 camera/feed·착좌·완료 수명을 보존한다. scoped 독립 안전 검토 완료. 이안·재투입·3회 전체 cycle·실측 profile/현장 수용은 계속 미완료다.
- a78e502f5: 원격 task-9-target-contract-final의 behavior 소유권·영향 선택/CI 비용·harness 계약 166개 통과, NEW 0/skip 0. source는 1f45569ca 이후 바뀌지 않았다.

## 2026-10-16 선택 작업 이안·재투입 실행 증거

- c6abafd83: 현재 permit/원본 실측 Receipt readback 원격 407 PASS/0 skip/NEW 0. 원본 UTC/monotonic 수명, 접점/시계 모순 후 재생 금지와 기존 owner lock을 보존한다.
- 13421ca4b: 영속 선택 작업·claim·이안 intent·같은 실행 허가 갱신 원격 103 PASS/0 skip/NEW 0. 최초 motion generation과 active lease를 분리하고 최신 fence보다 오래된 Receipt는 거절한다.
- aff57b47a: 실제 HttpRobotClient에서 같은 native 이안을 최초 permit 수명 너머 유지하고 완료 Receipt GET을 확인한 transport/API 원격 208 PASS/0 skip/NEW 0.
- 9286f5f77: 실제 ChargeRuntime→ChargeService→ChargeRobotHttp/HttpRobotClient→CORE native 실행→새 실측 이탈/정지→동일 원장 Receipt+WORK_AVAILABLE+claim 해제→기존 scheduler의 선택 작업 claim→새 에너지 입력의 최종 작업 허가. task-8-redeployment-http-final 253 PASS와 task-8-redeployment-fleet-final 151 PASS, 각 0 skip/NEW 0/exit 0. 시험 범위는 겹치므로 합산하지 않는다.
- 초기 충전 완료 상태, native plant, 접점·후방 공간·차단/전류와 BMS/에너지는 SIM이다. 앞선 실제 JPEG/TripRunner/충전 경로와 이번 이안을 한 번에 연속 수행한 증거는 아직 없다. 새 session binding과 3회 전체 cycle, 독립 전역 이동 producer/운영 설치, 실측 프로필·DEVICE/FIELD 수용은 계속 진행한다. 전체 목표 ACTIVE.

## 2026-10-16 다음 충전 세션 boundary 실행 증거와 남은 연속 경로

- a4ead2712 task-8-rebind-green 원격 282 PASS/0 skip/NEW 0/exit 0. 실제 CORE owner/gateway는 긴 정상 작업 후 만료된 예전 target/Receipt를 빌리지 않고 새 installed motion의 정지 dwell로 새 session/attempt를 받는다. source timestamp span과 monotonic span을 모두 검사하며 현재 local/native 범위, retired session, 실제 feed watermark를 보존한다. 기존 native writer/작업 중 이동 중재는 유지한다.
- 이 검증의 초기 완료/작업 종료 상태와 측정은 SIM이다. 기존 test_station_camera_pipeline.py의 full_return은 실제 TripRunner/JPEG/충전 경로지만 아직 CHARGED_HOLD에서 끝나고, 새 test_station_redeployment_http.py는 충전 완료 상태부터 시작한다. 두 시험의 통과를 한 연속 cycle로 합산하지 않는다.
- 다음 연속 시험은 실제 FleetTaskService의 선택 navigation 제출→HttpRobotClient/CORE native 실행→실제 CORE nav.completed 이벤트의 TaskStore 반영까지 포함한다. 단순 scheduler claim이나 task 상태 직접 전이로 작업 완료를 대체하지 않는다. return_sim의 plan ID는 session별로 구별하고 같은 service/runtime/store/CORE/worker를 재사용한다.
- 확인된 연결 공백: 일반 native navigation 완료는 backend/receipt가 끝나도 Mode.NAVIGATION에 남는 반면 다음 충전 request/binding은 실측 IDLE을 요구한다. 이미 return 전용으로 있는 locked terminal-navigation handover는 return authority가 있어야 하므로 일반 작업에 그대로 호출할 수 없다. 실제 CORE native/transport가 terminal이며 새 작업이 없는 것을 잠금 아래 검증하는 정상 작업 인계 경로를 설계·구현하고, 그 뒤 새 정지 dwell→새 session binding을 진행해야 한다. SIM에서 modes를 직접 IDLE로 바꿔 이 연결을 건너뛰지 않는다.
- 이후 최초 1회 전체 순환을 같은 경로로 검증하고 3회로 늘린다. 전역 위치 후보와 initial measurement permission, plant·BMS·차단/공간은 SIM 범위를 명시하며 실제 카메라 상대 위치는 계속 JPEG/worker/인증 HTTP로 전달한다. 독립 전역 이동 producer/운영 설치 및 실측 DEVICE/FIELD 수용은 계속 미완료다.

## 2026-10-16 일반 작업의 완료 항법→IDLE 인계 구현 단위

- 예약된 v1.255의 새 POST navigation/handover는 정확한 boot/run/correlation/generation과 현재 ARRIVED/SUCCEEDED·quiescent backend를 Nav lock 안에서 검증한다. Nav lock 이후 modes.idle_admission을 비차단 획득하고 현재 lease/manual/safety/line-follow guards를 실행한 다음 최신 proof를 확인한다. candidate clear와 조건부 NAVIGATION→IDLE만 수행하며 새 이동/취소/물리 정지 판정을 만들지 않는다. 같은 terminal proof의 IDLE 재조회만 멱등이다.
- 일반 Fleet 작업의 실제 완료·원래 선택 task/digest·native receipt/attempt를 원장에서 재검증한 뒤 이 인계를 호출하는 어댑터를 연결한다. 그 뒤 원본 motion의 새 정지 dwell과 다음 session binding을 진행한다. API 단독 GREEN을 Fleet 연결이나 전체 3회 cycle의 증거로 쓰지 않는다.

## 2026-10-16 v1.255 수동 항법 인계와 실제 client 검증

- [x] CORE exact terminal handover: 560a2ff27 task-10-navigation-handover-final 387 PASS/0 skip/NEW 0. 기존 return 인계, calibration/trip/native 소유권, 실제 잠금 경합, API/구조/안전/harness를 포함한다. 별도 live version pin 회귀 93 PASS/0 skip/NEW 0. 외부 계약은 도구로 예약한 v1.255, envelope 1.0 유지다.
- [x] 실제 HttpRobotClient 연결: 0ba8294c9 task-10-navigation-transport-green 261 PASS/0 skip/NEW 0. 실제 native/HTTP 인계와 기존 귀환·재투입·JPEG 접안/충전 회귀를 검증했다. 통신 책임을 분리해 기존 파일 600→573줄, 크기 한도 증액 없음. 새 transport는 단일 guarded POST와 정확한 ACK만 사용한다.
- [x] FleetTaskService의 실제 작업 완료 인계: 현재 native run/correlation에 대응하는 COMPLETED task와 원래 ACK/outcome의 exact boot/run/attempt·SUCCEEDED, 기존 native outcome reconciler의 safe_released, 현재 dispatch/robot 자원을 확인한 뒤 이 API를 호출한다. task의 native claim 해제는 기존 Task outcome owner가 actual quiescent readback으로 수행하며 충전 원장이 대신 해제하지 않는다. 여러 정상 작업 뒤에도 과거 charge session 하나가 후속 모든 작업을 영구 소유하는 구조는 만들지 않는다.
- [x] ChargeRobotHttp의 optional work_handover를 기존 bootstrap context.task_service의 실제 bound method에 연결하고 동일 store/clients의 소유권 검사를 보존한다. Runtime이 RETURN_REQUIRED인데 일반 항법 mode가 남은 경우에만 수동 인계하고 새 원본 source를 읽어 request_return으로 이어간다. 새 binding의 실측 정지 dwell은 여전히 별도로 필요하다.
- [x] 같은 TaskService/runtime/CORE/worker에서 실제 작업 제출→native 실행→실제 CORE 이벤트 원장 반영→native safe-release/IDLE→새 정지/세션→귀환/JPEG 접안/충전/이안/재투입을 먼저 1회, 이후 3회 수행한다. c2cc1551d의 연속 SIM 근거와 범위는 아래에 기록했다. 실기 수용은 계속 별도다.

### 완료 작업 인계 검증 근거와 남은 연속 경로

70827fd97의 task-11-task-runtime-handover-final은 원격 267 PASS/0 skip/NEW 0이다. 실제 CORE 이벤트의 완료 상태와 native 자원 해제를 구분하고, 현재 boot/run/attempt와 원본 정책 boot를 결속한 인계·명시적 bootstrap callback·새 source 재평가를 검증했다. 초기 DB 검증은 off-loop이며 전송 직전 DB contention은 즉시 거절한다. DB 조회 후에도 원본 source와 monotonic budget을 재확인한다.

다음 단계에서는 같은 객체들의 실제 작업 종료부터 CORE의 새 IDLE motion dwell, 새 session binding, 귀환·JPEG 접안·충전·이안·재투입을 연속 실행한다. IDLE mode ACK가 물리 정지의 근거가 되지 않으며 source adapter가 boundary를 일찍 선언해 새 binding이 HOLD되는 진행성 문제를 시험해야 한다. 원본 stop gate를 우회하거나 SIM에서 mode/Task 완료를 직접 바꿔 3회 완료로 간주하지 않는다.
기존 실제 귀환·JPEG 접안/충전·이안/재투입·target refresh·transport·harness 회귀도 같은 SHA에서 290 PASS/0 skip/NEW 0이다. 두 시험군은 겹치므로 합산하지 않는다.

## 2026-10-16 동일 객체의 3회 연속 충전·재투입 근거

ad979adf8의 task-12-console-continuous는 동일 TaskService/ChargeRuntime/CORE/카메라 worker에서 귀환→JPEG 상대 인식/접안→착좌/실측 정지→정상 충전 종단→이안→선택 작업의 실제 Console/native 실행·완료를 3회 통과했다. 후속 충전 세션으로 넘어가는 두 경계는 실제 CORE 이벤트 반영·기존 Task outcome owner의 safe release·boot/run/attempt 결속 인계·새 IDLE motion dwell·새 session binding을 거쳤다. Mode.IDLE이나 Task.COMPLETED를 시험에서 직접 설정하지 않았다.

운동학 plant는 제어기 desired candidate와 applied twist를 분리한다. ARRIVED/IDLE을 포함한 모든 step에서 실제 CommandManager→cmd_vel_cycle→기존 power/readiness/station 최종 게이트를 거친 출력만 적분한다. 따라서 정지 명령만 받았다는 사실이나 backend의 terminal 결과가 측정 정지로 바뀌지 않는다. 접안 상대 포즈는 실제 렌더 JPEG→기존 마커 worker→인증 Fleet/CORE HTTP로만 전달한다.

0268fe909의 관련 원격 161 PASS/0 skip/NEW 0에는 기존 두 JPEG variant, 최초 연속 경로와 ingress/scope/안전 회귀가 포함됐다. 이 시험에서 이안 중 전역 위치 갱신에 필요한 측정 범위가 끊기는 실제 결함을 발견했다. UNDOCKING을 현재 세션의 측정 상태에 포함해 수정했으며 동일 출처·claim·CORE binding·odom·TTL 검증을 유지한다. HOLD/WORK_AVAILABLE은 닫혀 있고 측정 범위는 이동·충전 완료·자원 해제 권한이 아니다. 독립 scoped 안전 검토를 마쳤다.

증거의 한계: 시간은 deterministic 수동 tick이며 plant/지도 위치·localization/contact/isolation/rear space/energy/global 설치 관측/신규 session의 최초 측정 permission은 명시적 SIM이다. 실시간 서버 lifespan 운용, 독립 절대 위치 재발견 producer와 스테이션 이동, 운영 CLI/설치 프로필 및 실기 DEVICE/FIELD 수용은 완료하지 않았다. 이 목록을 별도 구현·수용 항목으로 유지한다.
최종 c2cc1551d의 task-12-continuous-final은 원격 239 PASS/0 skip/NEW 0/exit 0이다. 위 3회 actual Console 경로와 두 후속 session 인계에 더해 RETURNING·DOCKING·UNDOCKING·WORK_AVAILABLE 각 첫 이동에서 실제 power-readiness gate를 한 주기 닫아 출력 0과 plant 위치 불변을 확인했다. 기존 귀환/native 인계·ingress/scope·구조/안전 회귀를 포함하며 전체 CI나 실시간 lifespan 검증으로 확대 해석하지 않는다.

## Task 13: 고정 지도 카메라의 스테이션 위치 producer

기존 Task 3의 고정 카메라 경로를 구현한다. 지도에 고정된 별도 카메라가 스테이션에 설치된 전용 마커를 읽고, 승인된 station-marker 높이 평면의 image→map 교정과 marker mount를 적용한다. 상대 접안용 로봇 마커와 지도 위치용 스테이션 마커는 설치 프로필에서 구분한다. 카메라가 스테이션과 함께 움직이는 구성에는 fixed-map 교정을 재사용하지 않는다.

1. 기존 ArUco/quad 변환 검증을 공용 leaf로 추출하고 상대 관측의 결과를 보존한다. 새 고정 지도 교정은 station/map/source/epoch/revision·marker plane·mount·유효성·측정 오차·접근 offset을 명시하며 모든 승인 조건을 확인한다.
2. 기존 latest-only VisionWorker와 source-only SightingPublisher를 재사용해 실제 JPEG에서 StationPoseRecord CANDIDATE만 POST한다. 활성 로봇 session이나 기존 CORE binding이 없어도 재발견할 수 있으며 Fleet이 위치 버전·접근 검증·확정을 소유한다. 표식 소실/불량/만료는 새 좌표를 만들지 않고 원래 수명으로 만료된다.
3. 원본 frame 시각과 monotonic 잔여 수명을 검사하고 같은/역순 frame을 재전송하지 않는다. 실제 인증 Fleet ingress/위치 원장에 연속 새 영상들을 보내 기존 위치 즉시 무효화→새 위치 일관성 확인→새 version 확정·이전 ACK/계획 거절을 검증한다. optics·map 교정·접근 설치 검증은 명시적 SIM이며 DEVICE/FIELD 수용으로 간주하지 않는다.

원격 RED는 93911bb35 test_station_map_worker에서 생성 중이다. 이후 safety source는 독립 검토 후 커밋하며, 기존 상대 카메라/worker 및 실제 3회 충전 경로를 회귀한다. 설치 CLI/profile 구성과 실시간 lifespan/장애 수용 항목은 계속 별도다.

고정 지도 카메라의 승인 H와 `fixed_map_anchor=True`만으로는 현재 카메라 고정을 증명하지 못한다. 독립 안전 검토에 따라 매 frame에서 스테이션과 독립된 고정 표식 네 개의 ID·등록된 rectified pixel quad를 대조한다. 등록 quad·coverage hull은 볼록하고 영상에서 분해 가능한 크기여야 하며, 스테이션 마커 전체가 coverage 안에 있어야 한다. 누락·ID 교환·반사·고정 표식 이동·카메라 이동은 candidate POST를 차단한다. 설치 프로필은 측정된 pixel 허용 오차와 그 허용 범위를 포함한 전체 위치·각도 오차를 명시한다. 바닥 landmark를 station-marker 높이 H로 투영하거나 스테이션 표식으로 H를 재교정하지 않는다. 승인된 렌즈 보정 결과의 pixel 좌표를 비교하며 preview용 조정은 사용하지 않는다.

e81c69307의 task-13-camera-bump-red는 영상 전체 이동이 잘못된 스테이션 좌표로 POST되는 기존 결함을 재현했다(예상 실패 1). fd96e9120의 task-13-relocation-route는 원격 2 PASS/0 skip/NEW 0이며, 고정 카메라 가정하의 작업 사이 이동→revision 2→3회 연속 충전/재투입과 복귀 중 이동→HOLD·실제 출력 0·claim 유지를 검증했다. 네 고정 표식 보강 후 같은 경로를 다시 검증한다.

`uncertainty_m/rad`는 허용된 anchor residual을 포함해 실측한 전체 교정 오차이며 pixel threshold로 추정하거나 부족분을 보충하지 않는다. 카메라가 이동했거나 고정 표식이 누락되면 새 후보를 내지 않으며, 설치 변경 후에는 재측정·승인 및 source calibration revision 갱신이 필요하다. 합성 영상 통과는 실제 교정/anchor 설치 수용 증거가 아니다.

3621458a6의 task-13-anchors-order는 원격 245 PASS/0 skip/NEW 0/exit 0이다. 실제 JPEG의 네 독립 고정 표식 검증·카메라 전체 이동 거절·스테이션 단독 이동 허용·불량 숫자/기하·기존 상대 관측/worker/publisher·실제 인증 ingress/CORE/최종 속도 게이트의 전체 3회 충전·재투입 및 복귀 중 이동 정지를 포함한다. 독립 safety review scoped PASS와 safety trailer 검사가 완료됐다. 최초 anchors-final은 같은 이름의 Fleet/CORE test_trip_lease 모듈 충돌로 pipeline 3건 ImportError였으며, gateway 시험 모듈을 먼저 로드하는 기존 조립 규칙을 적용해 같은 SHA에서 전체 재검증했다. 이 경과를 기존 실패 목록에 추가하지 않았다.

남은 기준: 운영 CLI/설치 프로필 구성, 실제 서버 lifespan과 재시작·장애 matrix, 실측 광학·BMS/충전기·접점/이안 장치 프로필과 DEVICE/FIELD 수용. 이번 시험의 plant·접촉·에너지·접근 경로 승인은 SIM이며 실제 하드웨어 구성은 미정이다. 전체 목표는 ACTIVE이고 main 착지·push·실기 활성화는 하지 않았다.

## Task 14: 설치된 스테이션 카메라 실행 진입점

기존 Task 3/9의 CLI·프로필 구성을 진행한다. `rosy-vision station-vision --config <JSON>`은 기존 IngestServer, source-only SightingPublisher, 상대/지도 worker factory를 조합한다. 일반 display-only vision 명령의 구성을 변경하지 않는다. 설치 JSON은 source별 역할, robot ID(상대 관측만), 원래 교정, 승인된 pinhole 렌즈 교정·출력 크기·원본 frame 회전, max age, Fleet URL과 서로 다른 phone/source 토큰의 환경변수 이름을 명시한다. 인라인 비밀과 미지원 교정·누락 프로필은 수신기 시작 전에 거절한다. 렌즈와 plane/marker/anchor 교정은 같은 source·epoch·설치 revision에 결속하고 preview 조정을 재사용하지 않는다. 영상 크기·회전이 다르거나 decoding/measurement가 실패하면 새 좌표를 만들지 않는다.

원격 RED 후 구현하고 safety leaf의 독립 검토를 받는다. strict JSON 프로필과 비밀 유출 없는 거절, 실제 JPEG→프로필 렌즈 변환→기존 worker의 authenticated HTTP, 실제 WebSocket 수신기 시작/종료와 취소 정리를 검증한다. 이 명령은 CORE capability나 장치를 활성화하지 않으며 profile 값은 설치자의 승인 기록이다. 재연결 시 phone sequence가 초기화돼도 원본 source epoch를 재활용해 이전 관측을 되살리지 않는다. source epoch/revision 변경과 기존 세션 정합성은 별도 새 설치로 다룬다. 실제 광학 수용과 Fleet/CORE 전체 lifespan·장애 matrix는 별도 기준이다.

D-774는 기존 preview 수요를 가장하지 않는 전용 measurement source 예외를 정의한다. 일반 vision/추적의 D-691 규칙과 폰 발열 보호를 유지한다. e5771fa8c의 최초 원격 전체 overhead·구조/안전 시험은 780 PASS/1 FAIL/0 skip이며 유일한 실패는 ingest.py의 기존 크기 ratchet 증가다. 허용치를 올리지 않고 기존 인증 미리보기·field/map proposal 응답 전체를 ingest_preview.py로 분리했다. 기존 메서드 진입점과 응답/수요 의미를 유지하며, 이동한 실행 AST 동일성과 미해결 전역 참조 0건을 정적으로 확인했다. 575행 수신기와 343행 preview leaf는 각각 600행 아래이며 기존 초과 ratchet 행을 삭제했다. 같은 전체 시험군으로 다시 검증한다.

0b816554c의 task-14-install-final은 원격 전체 overhead 및 구조·안전 회귀 781 PASS/0 skip/NEW 0/exit 0이다. strict JSON 승인·중복 키·비밀 분리·교정 source/epoch/revision, 실제 비영 렌즈 보정의 pixel corner 검증, 실제 JPEG→source HTTP, 실제 WebSocket config/measurement demand→후보 전송→demand 해제/연결 종료, 소비 task 비정상 종료·취소·demand-off 예외에도 나머지 자원 종료를 검증했다. 기존 lens hello·preview 인증/대기·proposal·연결 교체와 안전 구조도 포함한다. frame 처리 오류는 기존 worker의 log/retry이고, supervision은 소비 task 자체 종료 범위다. e5771fa8c와 0b816554c 모두 독립 Safety-Review scoped PASS 및 trailer 검사를 거쳤다. 중간 후보의 크기 검사 실패는 최종 검증으로 대체하며 전체 브랜치 CI/착지 준비 완료를 주장하지 않는다.

설치 안내: [station-vision.md](../../operations/overhead/docs/station-vision.md). 카메라 전용 CLI·프로필 조립은 구현됐으나 실제 카메라 결속·capture 설정 고정·광학 오차 수용은 별도다. 이어서 Fleet/CORE 운영 설정에서 선택 작업·예산·관측 source·장치 feed를 일관되게 조립하고 전체 서버 lifespan/재시작·장애 matrix를 검증한다. 하드웨어 미정, DEVICE/FIELD 미수용, 전체 목표 ACTIVE를 유지한다.

## Task 15: Fleet 앱 소유 실행기의 실제 충전 조립

설치 설정을 열기 전에 기존 factory 경로의 실행 정합성을 검증한다. 이전 3회 연속 시험은 실제 HTTP/native owner와 최종 출력을 사용하지만 return helper가 별도로 만든 TripRunner와 직접 tick한 runtime이었다. 새 구성은 create_app이 만든 TripRunner와 같은 지도·TaskStore·StationIngress·HTTP client를 install_charge_runtime에 연결한다. 복귀 목표도 앱의 실제 Console→CORE command/lease/native 경로를 사용한다. 조립 과정에서 owner guard·source/claim·boot/generation 경계가 충돌하면 우회하지 않고 생산자/소비자 결속을 수정한다.

먼저 기존 SIM plant/JPEG의 composed variant로 factory·owner 연결을 검증하고, 이후 실제 Fleet lifespan 시작/종료·재시작·장애 시 HOLD/원본 claim 보존·중복 명령 방지를 확인한다. 장치 사실과 시간 진행은 명시적 SIM이며 개별 단계 증거를 전체 실시간/실기 수용으로 확대하지 않는다. 운영 설정에서 선택 작업·예산·신뢰 source·장치 feed를 조립하는 기준은 계속 유지한다.

74e7a9f45 composed 원격 RED는 첫 충전·재투입·실제 작업 후 두 번째 복귀에서 `TRIP_ROBOT_BUSY`를 재현했다. CORE의 수동적 Task 인계 뒤 Console에 이전 goal/route/목표 lease projection이 남아 있었다. 기존 busy 검사와 claim 권위를 유지하면서, 실제 검증된 완료 Task/operation을 내부 completion callback으로 전달해 원본 정책·Task·dispatch·claim을 인계 ACK 뒤에도 재검사한다. 별도 leaf는 goal/route/lease 객체와 값·현재 client·manager·새 전송/정지 세대 및 held/formation/pending/queued/yielding 부재를 전후 확인한 뒤 await 없이 projection만 정리한다. source 부재·응답 불명·동시 새 명령은 기록 삭제 허가가 아니다. `_seen`과 durable claim은 변경하지 않는다.

인계 후 projection 정리가 보류되면 `_handover_pending`을 유지한다. 다음 원본 source가 IDLE이라고 보고해도 완료 절차를 건너뛰지 않고 다시 검증한 뒤 첫 복귀 session을 만든다. ee878e82e의 원격 회귀는 이 재확인 호출을 통과했지만 고정 SIM ACK의 만료 시각에 도달한 새 fixture와 Fleet root 크기 검사 2건이 실패했다. fixture의 명시적 정책 주기를 0.1초로 정해 ACK를 갱신하지 않고 재검사한다. 목표 lease 모듈 전체를 D-750의 기존 ledger holder로 옮겨 canonical `fleet.server.goal_lease`를 보존하며 root 초과 한도는 16021에서 실측 15834로 낮췄다. 크기 제한을 올리지 않는다.

cb43b5da1의 task-15-retire-final은 원격 Fleet 인계·경합·bootstrap/runtime·기존 goal lease·구조/안전 229 PASS/0 skip/NEW 0/exit 0이다. 같은 SHA의 task-15-composed-final은 gateway lease와 카메라 전체 5 variant 117 PASS/0 skip/NEW 0/exit 0이다. composed 경로에서 실제 앱 소유 TripRunner와 같은 지도·TaskStore·StationIngress·클라이언트·충전 runtime을 사용했고 복귀도 실제 Console→CORE HTTP로 보냈다. 세 충전·재투입 사이 두 인계에서 `_engaged`의 `goal → None`을 관찰해 이전 목표가 지워졌음을 확인했다. busy 검사를 완화하지 않았으며 다른 variant의 기존 relocation HOLD도 유지됐다. 모든 safety source delta와 모듈 이동은 독립 scoped review 및 trailer 검사를 거쳤다.

이번 증거는 factory/owner 조립과 수동 SIM tick이다. Fleet/CORE의 실제 lifespan·재시작/프로세스 장애 matrix 및 운영 설정/원본 source adapter 조립을 완료한 증거는 아니다. 중간 커밋의 크기 검사 실패가 있어 전체 브랜치 CI·착지 준비 완료도 주장하지 않는다. 실제 카메라·배터리/충전기 프로필과 DEVICE/FIELD는 별도이고 목표 ACTIVE를 유지한다.

## Task 16: 실제 lifespan과 도착 증거의 정합성

먼저 연속 SIM의 작업 완료 receipt가 실제 최종 출력으로 이동한 목표 위치·방향과 일치하는지 검증한다. 기존 양의 x 전용 이상적 navigation은 이동된 스테이션에서 뒤쪽 작업 목표를 이미 통과한 것으로 오인할 수 있다. 목표 오차 assertion으로 원격 RED를 확인하고 전후 방향·평면 오차를 사용하는 명시적 SIM 제어로 고친다. 생산 제어·인계·claim 경계는 유지한다. 이어서 Fleet lifespan 소유 runtime/TripRunner/dispatcher로 수동 tick·dispatch를 대체하고 종료 및 재시작 보류를 검증한다. 개별 통과는 전체 운영·실기 수용을 의미하지 않는다.

22e7ae4a5의 task-16-arrival-red는 연속/앱 조립 두 variant 모두 두 번째 작업의 약 46mm 목표 오차를 검출했다. b7860877b는 continuous 경로의 x 통과 조기 성공을 제거하고 실제 평면 거리 5mm·wrapped yaw 0.01rad 안에서만 native 성공을 만든다. 음의 방향도 bounded 속도 후보로 이동하며 최종 cmd_vel_cycle 출력만 plant에 적용한다. 생산 navigation이나 실기 제어기를 바꾼 증거는 아니다. task-16-arrival-green은 기존 전체 5 variant와 gateway lease 117 PASS/0 skip/NEW 0/exit 0이다.

새 lifespan variant는 실제 Fleet 시작/종료, 앱 생성 TripRunner.run·ChargeRuntime.run, 기존 dispatcher의 작업 배차와 HTTP 결과 조정을 사용한다. 시험은 원래 SIM 센서/시간·JPEG/CORE bridge·plant만 공급하며 runtime/runner tick·작업 dispatch/completion을 직접 호출하지 않는다. 실제 runtime tick의 condition은 진행 관측용이다. 종료는 runtime의 닫힘과 관측한 단일 runtime task의 완료를 단언한다. 모든 background task나 CORE ROS lifespan·프로세스 재시작을 각각 검증한 것은 아니다.

b27b9c45c의 최초 task-16-lifespan은 첫 복귀에서 CHARGE_RETURN_CORE_SCOPE_CHANGED로 HOLD했다. fd97129bb는 실패 시 실제 readback과 예상 target을 남기는 관측만 추가했고 task-16-lifespan-scope에서 3회 연속·빈 스테이션 이동/새 좌표 복귀·실제 dispatcher 작업 완료·runtime 종료가 1 PASS/0 skip/NEW 0이었다. 재실행 성공은 최초 간헐 실패의 해결 증거가 아니다. owner.reason이 없는 invalid binding과 일치하는 후보로 motion snapshot의 비차단 lock 경합이 있으나 최초 실패 원인으로 확정하지 않는다.

6da412cb7의 task-16-motion-busy는 실제 CORE 동기 readback 동안 실제 motion feed lock을 점유했다. snapshot이 None을 반환하면 HTTP grant 경로가 binding을 거절하고 Fleet HOLD로 전파되는 것을 1 PASS/0 skip/NEW 0/exit 0으로 확인했다. 이후 12회 원본 센서 공급에서도 adapter start_return 진입은 1회이고 native navigation·속도 출력·물리 이동은 없으며 session 하나와 robot/station claims가 유지됐다. 이 횟수는 CORE grant POST 전송 횟수가 아니다. fail-closed publisher나 unknown 요청 재전송 경계를 완화하지 않았다. 최초 간헐 실패의 실패 지점 원본 상태 분류·재시작/프로세스 장애 matrix·운영 설정/원본 source 조립 및 DEVICE/FIELD는 계속 미완료이며 목표 ACTIVE다.

fd97129bb의 task-16-final은 원격 gateway lease와 전체 6 variant 118 PASS/0 skip/NEW 0/exit 0이다. 실제 Fleet lifespan variant의 정상 3회 사이클은 두 원격 실행에서 통과했지만 최초 실패 사유를 확정하거나 해소한 것으로 승격하지 않는다. 6da412cb7에서 추가한 강제 경합 variant는 별도 1 PASS이며 이 SHA에서 전체 시험군을 다시 실행했다고 주장하지 않는다. 상세 외부 로그는 C:/DevTemp/station-charge/task-16-final/run-1.txt와 task-16-motion-busy/run-1.txt다. branch affected의 FULL 선택은 유지하며 장치 활성화·착지·push는 하지 않았다.

## Task 17: 진행 중 Fleet 종료와 보류 세션 재구성

실제 lifespan 운행 중 RETURNING·CHARGING·UNDOCKING 경계에서 종료를 요청한다. 새 admission을 닫고 원본 intent에 대한 정지를 시도하며 session/robot/station claims를 HOLD로 보존해야 한다. 최종 publisher를 계속 구동해 실제 출력 0과 위치 불변을 확인한다. SQLite를 새 store로 열고 새 Service/Runtime/Console/HTTP client/Fleet lifespan을 구성한 뒤, 선택 작업이 대기해도 HOLD를 자동 해제하거나 이전 목표·grant·접안·이탈 명령을 재전송하지 않는지 검증한다. 원본 intent/operation ID와 claims를 전후 대조한다. 이는 정상 서버 종료와 동일 CORE가 살아 있는 서버 재구성 범위이며 kill·전원 상실·CORE boot 변경과 실기 수용은 별도다. 간헐 readback 실패는 해결로 간주하지 않는다.

c7abdcfc8의 최초 task-17-shutdown 3건은 모두 테스트가 재시작 직후 rearm 성공을 잘못 기대해 실패했다. 실제 TaskService 시작은 retain_charge_claims_for_stop으로 남은 charge claims를 UNKNOWN으로 보존하며, 미확정 Action이 있으면 기존 rearm은 거절한다. 이 경계를 완화하지 않고 49e4cb188에서 거절·control 불변·정확한 charge owner와 UNKNOWN phase를 기대하도록 시험을 고쳤다.

49e4cb188의 task-17-shutdown-final은 원격 3 PASS/0 skip/NEW 0/exit 0이다. RETURNING은 실제 양의 속도 출력 중, CHARGING은 JPEG 착좌와 실제 정지/충전 근거 확인 후, UNDOCKING은 실제 음의 속도 출력 중 종료한다. 해당 phase를 놓치고 일반 정상 사이클로 통과하지 못하도록 checkpoint를 강제했다. 각 종료 후 원본 session/attempt/operation/correlation ID와 claims를 보존하고, 최종 publisher 출력 0과 plant 위치 불변을 확인했다.

새 SQLite store·StationService·TaskService·ChargeService·ChargeRuntime·Console·HTTP client와 실제 Fleet lifespan을 구성했다. 새 runtime의 첫 tick과 후속 12 tick에서 기존 HOLD가 그대로 유지되며 policy/source/plan/submit callback을 호출하지 않았다. 별도로 queue는 대기 상태이고 CORE navigation/docking/trip-lease mutation은 없으며 두 resource는 정확한 원본 charge owner의 UNKNOWN claim으로 남는다. queued work 미실행은 dispatch closure와 UNKNOWN claims가 함께 보호하는 결과다. runtime의 terminal HOLD 경계는 실제 반복 tick과 callback 미호출로 확인했다.

이 시험은 살아 있는 같은 CORE와 명시적 SIM 계측을 사용한 graceful Fleet 종료 및 새 구성의 HOLD 수용이다. 새 구성의 route plan은 기본 volatile store이며 이전 route 재실행/자동 복구를 검증한 것이 아니다. 모든 background 종료·kill/전원 상실·CORE 재시작·실제 BMS/광학 프로필 수용과 운영 CLI 조립은 별도다. Task 16의 최초 간헐 readback 실패도 해결로 판정하지 않는다. 원격 로그: C:/DevTemp/station-charge/task-17-shutdown-final/run-1.txt. 기존 전체 시험군을 이 SHA에서 재실행한 것으로 합산하지 않으며 전체 목표 ACTIVE를 유지한다.

## Task 18: 설치된 Fleet 충전 입력과 실제 운영 조립

D-776에 따라 기존 Task 9의 운영 설치 단계를 진행한다. 먼저 원본 motion/battery 사실의 로컬 승인 파일 포트와 durable sequence/hash/UTC·mono 수명·재시작 watermark를 RED→GREEN으로 검증한다. 파일에는 선택 작업·예산·미래 세션·명령을 받지 않는다. 이어서 Fleet의 실제 Task 선택/World MapPose/활성 그래프/승인 비용 계수로 예산과 복귀 계획을 만들고 CLI의 명시적 설정으로 기존 ingress/runtime factory에 연결한다. 시간·회전·대기·접안·reserve 비용과 지원하지 않는 작업은 보수적으로 WAIT한다. 원본 자료가 없으면 policy/readiness를 추정하지 않는다. 새 세션의 invisible bootstrap은 원본 motion 시간과 실제 session/승인 교정을 결속하고 측정 관측을 가장하지 않는다. CLI는 CORE capability나 장치 수용을 활성화하지 않는다.

Task 18의 source/time 단계: e436466b2의 task-18-source-red는 module 부재 36 FAIL이었다. 518f2eeec의 task-18-source-green은 새 source·기존 policy/runtime/battery·구조/안전 원격 151 PASS/0 skip/NEW 0/exit 0이다. 승인된 POSIX 파일의 원본 motion/Battery만 기존 TaskStore에 watermark를 저장한 뒤 반환한다. 실제 CLI/factory와 Fleet 경로 예산은 아직 연결하지 않았다. 계약 안내: [station-charge-source.md](../reference/station-charge-source.md).

독립 검토가 발견한 clock read gap/반환 TTL 및 새 motion으로 같은 battery lease를 연장하는 두 경로를 첫 source 커밋 전에 수정했다. mono-before/UTC/mono-after 순서, I/O 이전 시작점, 마지막 mono까지의 TTL 절단과 독립 battery capture/hash/deadline으로 수명을 보존한다. 독립 clock epoch/진행 속도·읽기 지연, 동일 배터리 재사용, 재시작 새 원본 요구, path/한계 변경과 재생, 만료·부분 파일·duplicate/nonfinite·권한·DB 실패를 포함한다. source epoch/UID/프로필의 설치 승인은 장치 정확도의 증거가 아니며 BMS 계측을 추정하지 않는다. 전체 목표 ACTIVE, 운영 조립·간헐 readback 원인·남은 장애 matrix·DEVICE/FIELD는 계속 미완료다.

Task 18의 실제 작업 선택 단계: `ChargeWorkSelector`는 같은 TaskStore의 read transaction에서 READY 대기 작업을 실제 scheduler의 priority/queued_at/task_id 순서로 읽는다. 만료 작업은 쓰기 없이 제외하며, 선두 작업이 미지원·불량·유효 lease 보유 상태이면 다른 작업으로 우회하지 않는다. 정확한 navigate goal과 request digest, dispatch authority epoch/generation, 원본 queue/expiry를 불변 값에 결속한다. transaction 종료 뒤 새 조회로 정지/재승인 세대를 확인하고 조회 완료 시각에도 원래 expiry를 검사한다. `matches()`는 같은 선택을 다시 수행한다. robot/station claim, scheduler lease, Task 상태를 변경하지 않는다.

7ee01f51e의 원격 RED는 module 부재 15 FAIL이다. 독립 검토에서 발견한 Decision의 private timestamp parser import를 제거하고 safety leaf 내부에 명시적 timezone 검사를 두었다. bbb785a31의 task-18-selection-green은 실제 SQLite 작업 선택·충전 이탈 원장·기존 scheduler/policy·구조/안전 원격 129 PASS/0 skip/NEW 0/exit 0이다. 선택 변경·취소·선두 우선순위 변경·stop/rearm·두 snapshot 사이 실제 stop·DB 실패·조회 중 만료·중복 JSON key·UTC 역행과 원본 charge claim 유지를 포함한다. 이 선택기는 아직 CLI/factory에 연결되지 않았으며 실행이나 비용 승인 권한을 부여하지 않는다.

비용 조립의 다음 선행 조건은 World 위치와 같은 원본 CORE odom stamp/boot/epoch의 결속이다. 현재 일반 navigate Task는 goal만 전달하므로 차로 planner의 길이를 실제 주행거리 상한으로 쓸 수 없고 ETA는 정체·재계획의 시간 상한이 아니다. 실제 실행 경로와 중간 귀환 가능한 공간 범위, 집행되는 시간 상한이 검증되기 전에는 유한 work budget을 승인하지 않는다. 단순 current/after-work 두 끝점 비용만으로 작업 중 귀환 reserve를 입증하지 않는다.

2026-10-17 실기 우선순위: 사용자가 하드웨어 활성화와 당일 실습을 요청했다. Fleet PC 사이트 스택과 두 물리 로봇의 등록 기록을 읽었으나 두 등록 모두 needs_new_code이며 저장 주소의 SSH/CORE와 현재 호스트 이름 연결이 확인되지 않았다. 실제 전원/네트워크 확인을 요청한 상태다. 로봇 설치 릴리스·실제 카메라/충전기/BMS/착좌 센서는 미확인이고 설정 변경·재등록·모터 구동은 수행하지 않았다. 현장 연결 후 읽기 진단과 정상 페어링을 진행하며 구동 승격은 실제 현장 담당자의 바퀴 들어올림 확인을 요구한다. 기존 STATION_DEVICE_ACCEPTANCE_REQUIRED를 우회하지 않는다.

같은 날 사용자 지적 후 기존 현장 경로를 재확인했다. OpenRB 두 대, 상부·전면 USB camera producer와 기존 viewer/readiness 서비스가 이미 실행 중이었다. 두 JPEG의 실제 수신과 follower 여섯 모터의 현재 위치를 기존 검증 observer의 2초/19 sample/exit 0으로 확인했다. 지도 version 5와 과거 로봇 위치도 존재한다. 따라서 새 위치/장치 경로를 가정해 만들기 전에 기존 source와 reader를 재사용한다. 현재 이동 로봇 위치 기록은 약 4일 전이고 상부 영상은 조회 시 과소노출이었다. 이 관측은 암·카메라 연결 확인이며 충전 정밀도와 기구/충전 수용은 아니다. 상세 범위와 도구 hash는 [현장 재확인 기록](../validation/station-existing-hardware-2026-10-17/result.md)에 보존했다.

Task 18의 World 출처 경계: 기존 World tracker를 사용하는 선택적 local scope를 추가했다. 첫 source 선언과 boot/CORE epoch/client/map ID 변경 시 기존 tracker/cache를 무효화하고 generation 이전의 늦은 REST/hub 완료와 unqualified sink를 차단한다. 새 원본 odom과 경계 이후 camera anchor가 있어야 LOCALIZED 자세를 반환한다. 관측된 map 변경 뒤 이전 map으로 돌아와도 old ticket은 복원되지 않는다. 잘못된 원본 입력 뒤 마지막 sample 재생도 proof를 복원하지 않는다. 현재 선언은 신뢰된 조립자의 입력이며 native boot 자체의 검증이 아니다.

ce5e9cce4의 원격 RED는 출처 경계 미구현 13 FAIL이었다. 34006ca39의 첫 회귀는 Fleet root 크기 증가 15834→15853 때문에 구조 검사 1건이 실패했다. 크기 한도를 올리지 않고 MapPoseService 전체를 D-750의 기존 site_observation holder로 옮겼으며 canonical import를 유지했다. 이동 전후 실행 AST 동일, 두 경로 기반 검사 대상 유지, root 한도 15558로 하향을 확인했다. 최종 source 1eeaeb653에서 관련 동작·구조 회귀를 다시 실행한다.

독립 검토가 지적한 public safety anchor와 World accessor 이후 만료/clock/current-ticket 재검사를 반영했다. 실제 boot bracket와 원본 timestamp 결속, map revision 확인, 실행 경로·시간 비용 상한, CLI/factory는 아직 남아 있다. 이 local prerequisite를 실제 설치나 장치 수용으로 승격하지 않으며 전체 목표 ACTIVE를 유지한다.

1eeaeb653의 task-18-pose-scope-final은 원격 265 PASS/0 skip/NEW 0/exit 0이다. 출처 선언 변경, 원본 epoch/robot/map/시간 불일치, same-sample 재생, 늦은 hub/REST 완료, operator pin 제외, roster 제거, 관측된 map flipback, accessor 도중 만료·clock 역행과 기존 World/공유 state/경계/charge source·구조/안전 회귀를 포함한다. 독립 safety review와 trailer 검사도 통과했다. 실제 native boot bracket나 원격 장치 동작을 실행한 시험은 아니다.

Task 18의 native pose reader: e801f1e01은 실제 전송 client가 발행한 불변 공유 REST receipt와 boot → state → boot 대조를 추가했다. 기존 한 요청/로봇 공유와 일반 Mapping 응답의 객체 동일성을 유지하고, receipt cache와 tracker ingestion을 분리했다. `ChargeWorldPoseSource`는 원본 facts/map revision/client/CORE epoch와 두 boot 응답을 확인한 뒤 같은 World tracker를 읽는다. 정상적인 새 odom/camera 대기는 None이며, 실제 모순·오류와 발급 proof의 최종 guard 실패는 scope를 폐기한다.

ffc783998의 원격 RED는 reader module 부재 8 FAIL이었다. e801f1e01의 task-18-native-pose-green은 새 reader·World·공유 읽기·앱 조립·경계·구조/안전 원격 250 PASS/0 skip/NEW 0/exit 0이다. native client는 명시적 Fake이며 실제 장치 boot 확인을 뜻하지 않는다. 기존 app의 기본 공유 reader 변경은 실제 HTTP/JPEG/SIM lifespan 회귀로도 별도 확인한다. 새 pose reader 자체는 아직 그 충전 factory에 연결하지 않았다.

독립 검토에서 최종 거절 뒤 client/map 복원으로 proof가 되살아나는 경로, 같은 facts의 재조회 및 A→B→A로 monotonic 수명이 늘어나는 경로를 첫 구현 커밋 전에 수정했다. facts/odom/anchor 각각의 최초 수명과 facts capture watermark를 유지한다. 자체 점검에서는 첫 odom이 scope cutoff 이전일 때 매 poll 경계를 재설정하는 진행성 문제를 발견해, 두 boot 확인 뒤 같은 scope의 fresh pre-boundary sample만 입력하지 않고 기다리도록 고쳤다. 첫 qualified odom 이후의 역순/불량 sample은 계속 거절한다. 독립 검토는 이 delta까지 scoped PASS였다. 예산의 실제 경로/중간 귀환/집행 시간 상한·운영 factory/CLI 및 DEVICE/FIELD는 여전히 남고 전체 목표 ACTIVE다.

추가 통합 확인에서 e801f1e01의 task-18-native-pose-lifespan은 기존 실제 HTTP/SIM lifespan 시나리오 1 FAIL/NEW 1이다. CHARGE_OPERATION_SUBMISSION_UNKNOWN과 CHARGE_RETURN_CORE_SCOPE_CHANGED로 HOLD했으며 Task 16의 미해결 증상을 다시 관측했다. bb6e03272의 task-18-readback-diagnostic은 정상 lifespan 1 FAIL과 강제 motion_busy 1 PASS다. 실패 당시 ACK는 수락됐고 실제 motion lock 획득은 성공했으나 snapshot이 None이었다. 0fb3a8492의 task-18-readback-sample도 1 FAIL/NEW 1이며 lock 보유 중 원본 sample 자체가 None임을 확인했다. source/local 시각은 모두 100.55로 유지됐다. 이번 실패를 lock 경합이나 오래된 샘플로 단정하지 않는다.

1d7af41f5는 sample clear의 마지막 네 호출 stack을 기록하는 시험 전용 진단이며 독립 scoped PASS다. 생산 TTL·판정·재시도·이동 권한은 변경하지 않는다. 원격 task-18-readback-clear는 시험 PC busy로 대기 중이다. 정적 비교에서는 시나리오의 무조건 owner.tick 호출과 실제 CORE 브리지의 session 존재 조건 차이를 발견했지만, clear 호출 증거와 수정 후 회귀 전에는 원인 해결로 판정하지 않는다. 원격 로그는 저장소 밖 C:/DevTemp/station-charge/각 task 디렉터리에 둔다.

## Task 18: SIM 초기 브리지 호출 순서 회귀

1d7af41f5의 task-18-readback-clear는 원격 lifespan 1 PASS/0 skip/NEW 0/exit 0으로 끝났다. 실패가 없어서 해당 실행에서 원래 실패의 clear stack은 얻지 못했다. 이 재실행 성공을 원인 해결로 판정하지 않는다.

e25e08ff3은 실제 lifespan worker의 첫 평가를 event로 지연해 CORE 틱이 최초 session binding보다 먼저 실행되는 순서를 고정했다. 실제 runtime tick은 여전히 worker가 호출하며, 첫 CORE 틱 후 session=None·UNBOUND·기존 원본 motion 보존을 검사한다. task-18-startup-order-red는 원격 1 FAIL/NEW 1/exit 1로, 직접 owner.tick 호출 직후 session은 없지만 상태가 HOLD임을 재현했다. 이 경로는 _valid의 미연결 거절→invalidate→motion.clear를 실행하며, 실제 production 브리지는 session이 없으면 legacy manager만 tick한다. 이후 비동기 bind가 BOUND/reason=None으로 바뀌어도 샘플을 복원하지 않는 스케줄은 기존 ACK 수락/lock 성공/sample=None 관측을 설명한다. 모든 과거 간헐 실패가 같은 원인이라고 일반화하지 않는다.

79226ce97은 시험의 직접 owner.tick 호출을 실제 core.bridge.docking_mode.tick으로 교체했다. 기존 native/manual 동기화·미연결 fallback·state projection을 같은 경로로 실행하고, runtime event와 최초 계측 보존 assertion을 유지했다. 생산 owner/readback/TTL/final publisher는 변경하지 않았다. 독립 scoped 안전 검토 PASS이며 task-18-bridge-startup-green에서 전체 pipeline 10 variant와 gateway lease·station wiring·mode ownership/release·motion feed 회귀를 원격 검증 중이다. 통과 결과 확인 전에는 통합 검증 완료로 판정하지 않는다.

79226ce97의 task-18-bridge-startup-green은 원격 185 PASS/0 skip/NEW 0/exit 0이다. 전체 pipeline 10 variant(실제 Fleet lifespan의 3회 충전/재투입·이동 스테이션 재발견, 강제 motion_busy HOLD, RETURNING/CHARGING/UNDOCKING 종료/재구성), gateway trip lease·station wiring·mode ownership/release·motion feed를 포함한다. 초기 worker event 대기 중 실패한 RED도 원격 종료가 끝났으며, GREEN은 같은 worker/생산 브리지 경로에서 최초 sample 보존을 확인했다. source 79226ce97의 소프트웨어 SIM 근거이고 전체 CI·실제 CORE ROS executor·실측 충전 장치 수용은 아니다. 이미 실패했던 모든 비결정적 실행의 원인이 이 경로였다는 증거로 확대하지 않는다. 운영 입력·실제 집행 비용 상한·factory/CLI와 DEVICE/FIELD는 남아 있으며 전체 목표 ACTIVE다. 원격 로그: C:/DevTemp/station-charge/task-18-bridge-startup-green/run-1.txt.

## Task 18: 목표 임대의 만료 경계 복구

운영 예산의 시간 상한을 검토하며 기존 D-550 목표 임대의 계약 위반을 발견했다. NavigationManager.renew_goal_lease는 기존 만료 시각을 확인하지 않아, 시각상 만료됐지만 5 Hz timer가 아직 실행되지 않은 창에서 같은 토큰의 갱신을 수락했다. 다른 토큰에는 만료 오류 대신 FORBIDDEN을 먼저 반환했다. API reference의 기존 GOAL_LEASE_NOT_ACTIVE와 갱신으로 만료 목표를 되살리지 않는 규칙에 어긋난다.

8d6e8b7ed의 task-18-goal-lease-deadline-red는 같은/다른 토큰 × 정확한 만료 시각/만료 직후 네 경우 모두 원격 FAIL/NEW 4/exit 1이었다. 1558c56b4는 기존 RLock 안에서 monotonic을 한 번 읽고 기존 deadline 이상이면 owner 검사보다 먼저 거절한다. 거절은 원래 lease/native generation/mode/전송을 변경하지 않고, 기존 timer가 원래 정확한 run을 한 번만 취소한다. 허용 갱신도 같은 시각으로 새 deadline을 계산한다. 기존 공개 shape·오류 코드·version과 native cancel 경로는 유지하며 manager는 591줄이다.

1558c56b4의 task-18-goal-lease-deadline-green은 원격 200 PASS/0 skip/NEW 0/exit 0이다. 목표 임대 전체·core logic/sprint2·native owner/완료 인계·Fleet loss 및 구조/안전 회귀를 포함한다. 독립 scoped 안전 검토와 safety trailer 검사도 통과했다. 기존 실제 HTTP 복귀와 trip lease 회귀는 task-18-goal-lease-return에서 별도 확인 중이다.

이 수정은 만료 경계의 복구이며 총 작업 시간 상한이 아니다. 살아 있는 임대는 계속 갱신할 수 있고, 목표 좌표만으로 실제 NAV 경로 상한을 얻을 수 없다. 유한 renew 발행 횟수만으로 운행 시간·지연 요청·초기 제출·최종 출력·공간 범위를 모두 제한할 수 있는지도 실제 경로로 별도 검토한다. 검증 전에는 에너지 budget의 유한 값이나 WORK_ALLOWED를 생성하지 않는다. 운영 factory/CLI와 실측 프로필·DEVICE/FIELD, 전체 목표는 계속 미완료/ACTIVE다.

1558c56b4의 task-18-goal-lease-return도 원격 186 PASS/0 skip/NEW 0/exit 0이다. 실제 CORE/Fleet HTTP 복귀, native 정지 인계와 station return authority 및 gateway trip lease를 포함한다. 앞선 200개와 범위가 겹칠 수 있으므로 합산하지 않는다.

독립 경로 검토는 갱신 발행 횟수 K를 제한해도 현재 ordinary NAV의 물리 시간·공간 상한이 보장되지는 않는다고 판정했다. 현재 K 제한이 없고, lease expiry는 5 Hz cancel 요청이며 최종 publisher가 ordinary NAV lease를 직접 검사하지 않는다. 최초 POST의 늦은 수락과 correlation 재사용도 CORE 수락 기한/정확한 run 경계 없이 해결되지 않는다. StationReturnAuthority의 최종 게이트는 RETURNING에 적용되며 WORK_AVAILABLE의 일반 작업에는 적용되지 않는다. 따라서 다음 단계는 CORE의 기존 단일 final publisher에 결속된 native 실행 한계 계약이다. 단순한 TTL 설정·ETA·endpoint 거리·갱신 횟수를 유한 에너지 근거로 승격하지 않는다.

## Task 18: 공통 운행 한계의 내부 계산 단계

[운행 한계 설계](2026-10-17-bounded-station-execution-design.md)와 [구현 순서](2026-10-17-bounded-station-execution.md)를 추가했다. 첫 source는 CommandManager의 기존 holder 안에 둔 미연결 private 계산 모듈이다. 최대 물리 속도/각속도×최초 window 전체 경과 시간으로 경로·회전 상한을 계산해 표본 사이 왕복·완전 회전·대기 누락을 피한다. source clock/원본 수명·gap·epoch·위치 변화, 정지 tail·downstream watchdog, 전체 부하·공간 여유와 overflow를 검사한다. 한계 equality와 모순은 영구 STOP이다.

원격 RED 24건을 확인하고 독립 scoped 안전 검토에서 새 stamp의 불가능한 위치 점프와 큰 정수 산술 처리를 보완했다. 실제 writer/부트별 ID 소모 원장·fresh admission·native child·Fleet 전체 비용/factory/CLI는 아직 연결되지 않았다. 현재 energy_upper_j는 경과 시간+지금 정지할 tail의 상한이며 미래 작업 전체 비용으로 사용할 수 없다. 이 단계만으로 capability나 실기 profile을 수용하지 않는다.

[현장 재관측](../validation/station-existing-hardware-2026-10-17b/result.md)에서 기존 카메라·Fleet 서비스는 살아 있으나 상부 영상은 UNDEREXPOSED, 두 이동 로봇의 위치는 여전히 약 4일 전이며 등록은 needs_new_code였다. 사용자는 현장 담당자가 나중에 확인할 수 있다고 답했다. 현재 연결 자산은 그대로 재사용하며 현장 확인·장치 수용과 전체 목표는 계속 남아 있다.
