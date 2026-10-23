# D-856 첫 동작 계약: simulation TRIP의 독립 조회와 접수 대조

**Status:** P1 상세 설계, 구현 전 계약 검토 대상 (2026-10-24). 상위 목표는 [D-856](../adr/D-856-application-action-boundary.md), 실행 순서는 [P0–P5](2026-10-24-harbor-rosy-application-action-boundary.md)다. 이 문서는 API reference가 갱신되고 공급자 구현이 검증되기 전까지 현행 기능 선언이 아니다.

## 첫 범위와 남는 범위

첫 중립 흐름은 기존 `TRIP`으로 한 등록 장소까지 이송 차량을 이동시키는 simulation 작업이다. 항만 화물·팔레트·공정 recipe는 입력으로 받지 않는다. 앱은 물류 업무 의미를 소유하고 Fleet은 기존 계획·lease·claim·stop epoch·도착 판정을 소유한다.

`CELL_TRANSFER`의 기하 검증을 단순 제거해 팔 동작을 공개하지 않는다. 현행 `AnalyticCellTransferPlanner`는 승인 cell hash·recipe별 물체 폭/파지 깊이/높이·기하/보정을 검증한다. 이 보장을 중립 물리 프로필로 옮기는 상세 설계와 Harbor ADR 0005의 도달 사전 검증 조회는 후속이다. 첫 TRIP 통과로 전체 팔 공정 분리가 완료됐다고 표시하지 않는다.

## 기존 계약의 보존

`POST /api/fleet/trip-jobs`의 후보 요청과 응답은 유지한다. named operator의 호출은 승인·시작 의미이며 제안 전용 API가 아니다. 기존 1–8개 고유 후보·1–8개 step·principal/key/body 중복 방지·다음 후보로의 busy 전용 전환과 simulation profile을 유지한다. 이번 추가는 조회뿐이며 dispatch·rearm·stop 동작을 바꾸지 않는다.

P1에서 발견한 누락은 TRIP job의 공개 단건/요청-key 조회다. 현재 cell-job 읽기는 resolved cell proposal을 요구하므로 trip job을 조회하는 경로로 사용할 수 없다. bounded `/work` 목록은 identity와 모든 step/attempt를 안정적으로 대조하는 단건 계약을 대신하지 않는다.

## 추가할 공개 읽기

| 경로 | 입력 | 결과 |
|---|---|---|
| `GET /api/fleet/trip-jobs/{mission_id}` | 저장된 실행 ID | 해당 호출 principal이 생성한 TRIP job의 중립 snapshot |
| `GET /api/fleet/trip-jobs?request_key=...` | 후보 요청의 원본 key | 같은 principal/key로 이미 접수된 TRIP job의 중립 snapshot |

두 경로는 기존 read guard·viewer 인증을 거친다. 생성 principal과 동일할 때만 읽는다. 다른 principal·없는 ID/key·Cell job·TRIP이 아닌 혼합 작업은 404 `TRIP_JOB_NOT_FOUND`다. 이름 있는 다른 운영자도 이 API에서 자동으로 타 앱 작업을 읽지 않는다. 사이트 전체 관제 목록의 기존 권한은 그대로다. 인증 없음/권한 부족은 기존 401/403을 유지한다.

요청-key query는 후보 요청과 같은 1–128자·trim·제어문자 금지 규칙을 사용한다. slash·비ASCII·예약문자는 query 인코딩으로 보존한다. 내부 `trip-pool:` namespace는 소비자에게 노출하지 않는다. legacy `robot_id` 방식은 실행 ID로 읽을 수 있으며 request key는 null이다.

닫힌 profile에서도 이미 저장된 실행을 조회할 수 있어야 한다. 따라서 읽기 route는 store가 있을 때 설치하고, 쓰기 route/runner 설치와 profile gate를 구분한다. 조회는 lease·claim·job 상태·사건·재시작 복구를 변경하지 않는다.

## 중립 snapshot

응답은 `{job: TripJobSnapshot}`이다. `TripJobSnapshot`은 `mission_id`, 원본 `request_key` 또는 null, `request_digest`, `robot_id`, `status`, `current_step_index`, 순서대로 정렬한 `steps`, `reason`, `updated_at`만 가진다. 상태는 저장된 실제 job 상태를 보존하며 새 업무 상태를 만들지 않는다.

각 step은 `step_index`, `step: {to, via}`, `status`, `action_id`, `attempt_id`, `reason`만 가진다. 아직 시작하지 않은 action/attempt는 null이다. TRIP의 attempt는 기존 trip identity이며 새로 발급하지 않는다. recipe/cell/process hash, pallet/layer, 공정 문서, 타 principal identity, 장치 credential과 내부 grant는 노출하지 않는다.

후보 요청의 `request_digest`는 기존 접수 구현과 동일한 canonical JSON `{candidates: 후보 순서, steps: [{to,via}]}`의 SHA-256이다. key·시각·현재 지도는 digest 계산에 포함하지 않는다. query로 결과를 찾은 앱은 이 digest·step·선택된 robot의 후보 포함을 함께 검사한다. GET 404는 그 시점의 조회 결과이며, 지연 중인 POST의 최종 미접수를 증명하지 않는다. 따라서 404여도 자동 POST·새 key·다른 후보 재발행을 하지 않는다.

## Harbor 소비 경계

`RosyClient.trip_job(mission_id)`와 `trip_request(request_key)`를 표준 라이브러리 GET adapter로 추가한다. payload는 플랫폼 Python 없이 소비하며 기존 HTTPS/loopback·Bearer·redirect 금지·응답 크기 제한을 그대로 사용한다. `trip`은 기존 시작 의미를 유지한다.

업무 측 이송 의도는 원본 key·후보·장소 step·업무 참조와 canonical digest를 제출 전에 보존한다. 성공 응답도 새 GET snapshot으로 결속을 대조한다. 응답 유실은 HOLD/미확인으로 남기고 원본 key 조회로만 대조한다. 서버가 도착을 보고해도 화물 내려놓기·팔 퇴피·반출 완료를 참으로 만들지 않는다. 해당 업무 조건은 현재 Harbor 장부와 독립 관측 계약에 남는다.

진행 중인 Harbor workflow/퇴피/용어 변경을 덮어쓰지 않도록 소비자 작업은 독립 브랜치에서 수행한다. 변경은 먼저 HTTP adapter·독립 이송 의도 소비와 관련 시험에 한정하고, 최신 Harbor 업무 장부와의 결합은 해당 소유 변경을 다시 읽은 뒤 적용한다.

## 안전·호환 대응

| 보장 | 유지 위치 | 이번 변경 |
|---|---|---|
| 후보 배정·중복·claim | `trip_candidates.py`, `TripJobRows.create` | 재사용, 변경하지 않음 |
| route 계획·지도/장소 검증 | 기존 trip planning | 재사용 |
| stop epoch·lease·재시작 HOLD | `TripRunner`, `JobTripSteps` | 쓰기 변경 없음, 닫힌 profile read로도 재개하지 않음 |
| 관제·최종 장치 권한 | Fleet admission·CORE | 읽기가 권한을 발급하지 않음 |
| 업무 도착/완료 | Harbor | robot arrived와 별도 |
| 기존 Cell API·팔 기하 검증 | 기존 Cell 조립·OMX owner | 이번 흐름에서 변경하지 않음 |

## 구현과 검증

1. `contracts/foundation/core_common/protocol/trip_jobs.py`에 snapshot/step/read response와 query-key validation 타입을 추가하고 `schemas.py`에서 재수출한다. API 버전은 적용 직전 기존 관문으로 선점한다.
2. `TripJobRows.read(principal_id, *, mission_id=None, request_key=None)`는 하나의 읽기 transaction으로 해당 소유자·TRIP 전용 행을 확인하고 중립 projection을 반환한다. 정확히 하나의 조회 identity만 받는다. 기존 DB를 재사용하며 새 테이블·migration을 만들지 않는다.
3. `trip_job_routes.py`에 읽기 두 경로를 설치한다. profile gate 밖에서 read를 설치하되 closed profile의 기존 HOLD 복구와 write route 설치 조건을 바꾸지 않는다. SQLite 읽기는 `asyncio.to_thread`로 실행한다.
4. `operations/fleet/test/test_trip_job_read_api.py`에서 실제 SQLite와 FastAPI 경계를 검증한다. 소유자 읽기, 타 principal·Cell·혼합 kind 은닉, key 인코딩/validation, 접수 결과 유실 후 조회, 닫힌 profile 읽기, started/arrived/restart snapshot, 조회 전후 원장/claim/lease 불변을 포함한다.
5. palletizing import를 거부하는 깨끗한 Python subprocess에서 Fleet 조립과 TRIP 읽기를 검증한다. test-only Cell compiler fixture를 사용해 독립성을 가리지 않는다.
6. Harbor 단독 시험은 URL 인코딩·snapshot 결속·반복 조회·불명 접수·다른 digest/attempt·robot arrived와 업무 완료 구별을 검사한다. 실제 HTTP 시험은 고정 플랫폼·Harbor SHA와 자체 simulation 서버를 사용하며 skip 0을 확인한다.

기존 `test_trip_candidates.py`, `test_job_trip_steps.py`, Cell 접수·승인·복구 회귀를 함께 원격 검증한다. 실물·ARM64·현장 수용은 이번 증거가 아니다.
