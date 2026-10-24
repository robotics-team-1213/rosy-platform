# 업무 앱의 지원 계약과 남은 경계

확인일: 2026-10-21. 소스 기준 `afa2d0373e`, [API reference](ROSY%20API%20%26%20Protocol%20Reference.md) **v1.290**. 이는 문서 버전이며 서버의 기능 협상 응답이 아니다. 이 표는 새 API·실물 profile을 활성화하지 않는다.

후속 D-836 구현은 API reference **v1.292**에서 후보 운송 요청을 추가하고 기존 cell-app 문서 계약의 외부 소비를 구현했다. 아래 후보 배정 항목은 이 구현 범위이며 운영 배포·실물 수용 확인은 아니다.

## 외부 HTTP 소비

| 목적 | 현재 경로·producer | 권한·의미 | 소비 제한 |
|---|---|---|---|
| 장치·사이트 조회 | `GET /api/fleet/state`, `/api/fleet/site-map`, `/api/fleet/observations`; `console/console_routes.py` | read guard와 사이트 read 권한 | 관측은 시각·출처와 함께 사용한다. 조회는 예약이 아니다. |
| 업무 요약 | `GET /api/fleet/work`; `work/work_routes.py` | viewer; `FleetWorkSummary` | `ended`는 물리 성공 판정이 아니다. |
| 제안·해석 | `POST /api/fleet/proposals`, `/{proposal_id}/resolve`; `missions/mission_routes.py` | proposer, cell 역할·principal scope 검사 | resolve는 admit·실행 완료가 아니다. 지원 candidate/compiler만 가능하다. |
| 승인·거절 | `POST /api/fleet/missions/{mission_id}/admit`, `/reject`; 같은 route | operator와 generation·재해석 검사 | 앱의 업무 우선순위가 이 검사를 대신하지 않는다. |
| 진행·재연결 | `GET /api/fleet/missions/{mission_id}`, `/events`; 같은 route | viewer 및 principal scope; event cursor | action 결과와 goal evidence를 별도로 본다. cursor reset/만료 시 snapshot과 재대조한다. |
| cell 작업 조회 | `GET /api/fleet/cell-jobs/{mission_id}`; 같은 route | resolved cell proposal, scope 검사 | 현재 compiler의 공정 범위만 지원한다. 범용 항만 procedure API가 아니다. |
| 운송 작업 | `POST /api/fleet/trip-jobs`; `trips/trip_job_routes.py` | named operator, 현재 TRIP simulation profile | 기존 `robot_id` 또는 v1.292의 `candidate_robot_ids`+`request_key`. Fleet의 기존 lease/claim으로 배정하며 재접수는 같은 원장을 읽는다. |
| 공정 문서 제안 | `POST /api/fleet/cell-app/compile`, `/proposals`; `cell/cell_app_routes.py` | named operator, 설정된 service·compiler, 문서 digest 확인 | 설치된 공정의 재컴파일·제안이다. 승인이나 물리 실행 완료가 아니다. |
| 장치별 이동 | `POST /api/fleet/robots/{robot_id}/goal`; `ledger/task_dispatch_routes.py` | 기존 operator·admission 검사 | 임의 장치 명령 또는 업무 완료 근거로 사용하지 않는다. |
| 취소·정지 | `/api/fleet/tasks/{task_id}/cancel`, `/robots/{robot_id}/cancel`, `/cancel-all`, `/estop`; 같은 route | 기존 route의 operator·dispatch 검사 | 취소 요청은 물리 정지·화물 해제 확인이 아니다. 앱이 자동 rearm하지 않는다. |
| 목표 근거 수신 | `POST /api/fleet/goal-evidence`; `missions/mission_routes.py` | 인증된 evidence producer | 업무 앱이 계획을 관측으로 위조하는 쓰기 경로로 쓰지 않는다. |

소스 경로는 `operations/fleet/fleet/server/` 기준이다. 실제 permission·body·응답은 API reference와 해당 schema/route를 따른다. 외부 앱은 HTTP/JSON만 소비하며 플랫폼 Python·DB·ROS를 설치하거나 직접 접근하지 않는다. D-822의 gateway는 Fleet 내장 조립이며 외부 앱 독립성의 검증 사례로 간주하지 않는다.

## 정본·복구 책임

| 정보 | 생산자·정본 | 앱의 사용·복구 |
|---|---|---|
| 목적·업무 순위·회수 제안 | 업무 앱 | 계획 버전을 보존한다. 제안을 관측 위치에 덮어쓰지 않는다. |
| 실행 identity·시도·결과 | Fleet 원장, `missions/mission_progress.py` → `rosy.execution.site.workflow.project_progress` | task/attempt/revision과 event cursor를 보존한다. 과거 시도·stale 결과로 다음 단계를 열지 않는다. |
| 목표 확인 | 인증된 관측 producer → goal-evidence 원장·투영 | 단순 접수·action 성공과 구별한다. 없는 화물 인계·퇴피 근거를 생성하지 않는다. |
| 장치 실행·정지 | CORE/팔 owner | 최종 허가와 물리 정지를 owner가 판단한다. 앱 timeout으로 완료를 만들지 않는다. |
| 장치 claim | Fleet `ledger/action_claims.py`, cell/trip 원장 | UNKNOWN의 물리 점유는 TTL 만료로 해제하지 않는다. owner와 원장을 대조한다. |
| 통행 공간 | `rightofway/traffic_reservations.py` 및 현장 관측 | lease와 실제 통행/점유를 구별한다. 앱에 별도 전역 lock 서버를 만들지 않는다. |
| 에너지 admission | Fleet `ledger/charge_policy_admission.py` + `rosy.execution.site.charge_policy` | 검증된 예산·관측이 없으면 대기한다. 임의 SOC 기준으로 허가하지 않는다. |
| 수동 충전·정비 제외 | 앱의 운영 제약, 실제 가용성은 Fleet/owner | 후보에서 제외할 수 있으나 후보 포함이 실행 허가는 아니다. 도착을 충전 시작으로 보지 않는다. |

## 구현 판정과 후속 작업

1. **그대로 재사용:** proposal/admit 구분, 원장·진행·cursor, claim·에너지·통행 admission, owner 정지 권한. W1/W2는 기존 시험을 대조한 뒤 실제 누락만 보완한다.
2. **앱에서 구현:** 적층·업무 순위·회수 제안·합법 임시 위치·장비 역할·수동 운영 제외. 플랫폼 공통 타입으로 옮기지 않는다.
3. **후속 검증·계약 필요:** 항만 설치 binding의 실제 도달·기하·공유구역 검증, 화물 보유·팔 퇴피·하역·복구 위치의 인증된 출처/시도/freshness가 있는 근거 연결. 후보 요청은 v1.292 지원 서버에만 보내며 Vault `DEFERRED`를 픽업 완료로 바꾸지 않는다.
4. **미검증:** 고정 서버 외부 앱 통합, 실제 병렬 운행·자동 도킹·충전 시작·장치·현장 수용. 순수 앱 시험은 이 항목의 증거가 아니다.

W0는 지원 범위와 누락을 식별하는 문서 작업이다. D-827~829의 방향에 따라 앱 정책을 먼저 분리하되 각 공개 계약의 상태 변경·버전 선점·producer–consumer 시험은 W1~W3의 별도 변경에서 수행한다.
