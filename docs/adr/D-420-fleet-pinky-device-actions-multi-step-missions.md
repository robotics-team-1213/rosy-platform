## D-420 Fleet 다단계 Mission은 Pinky에 네 가지 Device Action으로 하달되고, Step은 상관 ID가 붙은 CORE 결과와 별도 목표 증거로 넘어간다

**번호 이력:** 브랜치에서 D-416으로 작성, main의 D-416·D-417(콘솔)과 겹쳐 2026-10-02 D-420으로 옮김. 참조 ADR도 D-415→D-419(SAF-003), D-417→D-421(전체 주행 취소)로 바뀜.

**Status:** Proposed (2026-10-02, 설계만; 사용자 승인 Task D; 검토 반영 개정 1·2 같은 날). D-399 §7 후속 5 가운데 Pinky 몫이다. 코드, API Reference, schema, 로봇 설정은 바꾸지 않는다. wire 이름·필드·HTTP 코드는 D-18에 따라 구현 변경에서 API Reference·공유 schema·생산자/소비자 시험과 함께 확정한다. 여기 적은 이름은 그 변경의 출발점이다. Mission 하달기 개방, ROS-SIM, DEVICE/FIELD 수용은 포함하지 않는다.

**다른 결정에 대한 개정 제안(이 ADR이 Accepted가 되면 효력):** D-419 §1·§3(§4.3), D-421 §2·§3(§4.2). 그 전에는 두 ADR의 원문이 그대로 유효하다.

## 배경

- **D-399(Proposed).** Fleet의 Mission Manager·Task Executor가 Step을 장치에 하달한다. 각 장치에는 Command Pipeline이 한 벌씩 있다(Action Gateway → 스킬 → Motion Intent → Arbiter → Safety Guard → 단일 writer). Fleet은 속도를 보내지 않는다. §7 후속 5는 장치별 Arbiter 우선순위 표를 정한다.
- **D-401/D-403(Proposed).** OMX Cell Job은 Step마다 `CELL_TRANSFER` Action 하나로 하달된다. Step k는 Step k−1이 `GOAL_CONFIRMED`이고 `authority_epoch`·정지 세대가 승인 때와 같을 때만 제출된다. D-403 §5는 목표 증거 출처 `sim_model_pose`를 더한다.
- **D-413(Accepted), [이전 계획](../plans/2026-10-02-platform-architecture-v02-migration.md).** 첫 전환은 고정 셀이다. Pinky 인계는 범위 밖이고, Task 9가 "Pinky agent/주행 Skill"을 후속 후보로 둔다. 사이트 Mission 원장과 장치 원장은 다른 사실의 정본이다(§2). Step 진행 규칙은 `rosy.execution.site`로 옮겨 간다. [설계 v0.2](../reference/ROSY_Platform_Architecture_Design_v0.2.md) §13.3은 Pinky–OMX 인계에 도킹 확인·구역 점유·출발 허용 근거를 요구한다.
- **D-298(Accepted), `CONCEPTS.md`.** Fleet Mission / Mission Step / Device Action / Local Transaction과 Action identity(`action_kind`, `action_id`, `attempt_id`)를 나눈다. 현재 `/api/fleet/tasks/*`는 이동 요청 원장이지 Mission 엔진이 아니다.
- **D-316(Accepted).** Fleet `attempt_id`가 CORE `POST /api/v1/navigation/goal`의 선택 필드 `correlation_id`로 가고, `nav.started`/`nav.completed`/`nav.failed`/`nav.canceled`가 그 값을 되돌려 준다. Fleet hub는 CORE Agent 이벤트를 `CoreEventStore`에 영속하고 `task_results.py`가 (robot, attempt, event id, seq)로 task에 투영한다. `nav.canceled`는 취소 요청을 냈다는 뜻일 뿐이다. 이 상관은 navigate에만 있다.
- **D-330/D-333(Accepted).** Fleet 발행 권한은 하나의 claim 트랜잭션(`dispatch_admission.py`, 자원 종류 `robot`·`workcell`·`object`·`pallet`, 단계 `CLAIMED`·`DISPATCHING`·`UNKNOWN`)으로 판정한다. 정지는 단조 증가 stop generation을 래치하고, 장치가 그 세대를 소비하는 계약이 시험되기 전에는 Mission dispatch를 열지 않는다. D-330 §4는 장치가 driver 호출 전에 발행 의도를 영속하라고 한다. 수락, 장치 결과, 목표 증거, 물리 정지는 다른 사실이다. 불명 결과는 자동 재발행하지 않는다.
- **Fleet 정지 세대는 이미 있다(D-330 구현).** `fleet_dispatch_control` 한 행(`authority_epoch`, `generation`, `dispatch_enabled`), `trip_stop_latch`(발행을 닫고 `CLAIMED` claim을 놓는다), `rearm_dispatch`(세대 +1, `DISPATCHING`/`UNKNOWN` claim이 남아 있으면 거절), `close_dispatch_for_startup`(재시작 때 `authority_epoch` +1), `dispatch_generation_is_current`(`task_store.py`). CORE에는 정지 세대나 epoch가 없다. `POST /api/v1/safety/stop`은 EMERGENCY 래치이고 해제는 Admin이다.
- **D-12(Accepted), D-55(Accepted).** Mission 실행기는 Fleet에만 둔다. 로봇은 원자 액션과 이벤트를 제공한다. 이동 조작의 접근·파지 같은 내부 흐름은 장치 로컬이다.
- **D-395(Proposed).** `POST /api/v1/localization/mission`은 `LOCALIZED`가 아닌 로봇에서만 열리는 제한된 확인 기동이다(`rotate_in_place`, `nudge_forward`, `lane_to_stopline`; `to_square`는 `unsupported`). Fleet `localization_service.py`의 사다리가 claim 없이 이 기동을 자동으로 낸다. `LOCALIZED`를 벗어나면 CORE가 자율 주행을 멈춘다.
- **D-400(Proposed).** CORE 안전 정책은 `off`·`shadow`·`enforce`이고 기본 `off`다. 어느 로봇에서도 집행하지 않는다.
- **D-419(Accepted on `feat/d415-saf003-fleet-loss`, main 미착지).** FleetAgent WS가 끊긴 순간 상관된 Nav2 goal이 진행 중이면, `safety.fleet_loss_timeout_s`(기본 3 s) 뒤 정책을 한 번 적용한다. `STOP`·`HOLD`는 같은 취소 `nav.cancel(source="fleet_loss", correlation_id=…)`이고, `HOLD`는 목표를 `held_goal`로 기록해 "Fleet이 같은 시도를 다시 보내 재개"할 수 있게 한다. `RETURN_HOME`은 상관 없는 `nav.home`, `CONTINUE`는 아무것도 하지 않는다. 이벤트는 `safety.fleet_lost`·`safety.fleet_restored`, 취소는 `nav.canceled {source: "fleet_loss"}`로도 보인다. 도킹·차선·대형은 범위 밖이다. 내부 `NavigationManager.cancel(correlation_id=…)`는 그 상관 goal이 진행 중이 아니면 조용히 `False`를 돌려준다.
- **D-421(Proposed on `feat/d414-fleet-cancel-all`, main 미착지; D-414에서 번호 변경).** 래치 없는 `POST /api/fleet/cancel-all`을 래치형 `/api/fleet/estop`과 나눈다. 로봇마다 상관 없는 `swarm/cancel` → `navigation/cancel` → `line-follow/mode OFF`를 보내고, 발행 겹침 울타리로 그 창과 겹친 Fleet 발행을 다시 취소한다. 도킹과 D-395 기동은 건드리지 않으며 열린 질문 1로 남겼다.
- **코드 현황(main `13e6d5e45`).**
  - Fleet `task_service.py`/`task_store.py`는 navigate 한 종류의 영속 task와 `attempt_id`만 안다. `console.py`의 양보 bay(`bays.py`)와 대형은 상관 ID 없는 `navigation_goal`을 보낸다. Fleet은 `line_follow_mode`를 `IR_LINE`/`OFF`로만 고른다(`swarm/transport.py` 250행; D-313 카메라 고장 시연 변경에서 들어온 제한). 레거시 `mission_store.py`(`fleet_missions`, `CHECK(action_kind='PICK_PLACE')`, Mission당 Step 하나)는 그대로 둔다.
  - `swarm/transport.py` `RobotClient`에는 dock/undock/docking cancel이 없다.
  - CORE `docking/dock`·`/undock`·`/cancel`과 `docking.*` 이벤트에는 상관 ID가 없다. `/navigation/cancel`과 `/docking/cancel`은 지금 진행 중인 것을 상관 없이 취소한다.
  - CORE는 지금 MANUAL에서 오는 상관 goal을 거절하지 않는다. 중재는 MANUAL → NAVIGATION 전환을 허용하고, NAVIGATION 진입이 teleop 입력을 버린다. `DockingManager.active`는 `DOCKING`/`UNDOCKING`만 보므로 `DOCKED`·`CHARGING` 상태의 로봇도 이동 goal을 받는다.
  - CORE `PUT /api/v1/line-follow/mode`는 정지선에서 끝나지 않는다. 정지선에서 스스로 끝나는 유일한 경로는 D-395 `lane_to_stopline`(`localization/mission.py` 240–254행)이다. 그 판정은 `road.stop_line_*`의 나이를 보지 않고, 이동 거리 상한에 닿으면 `done`(성공)으로 끝난다.
  - 목표 증거 경로는 PICK_PLACE 모양이다. `goal_evidence_registry.py`의 항목은 외부 생산자이고 `producer_id`·`token_env`(생산자 토큰)·`workcell_id`·`predicate_id`·`object_id`로 범위가 정해진다. `_EVIDENCE_SOURCES = {camera_observation}`. `goal_evidence.py` `GoalPredicate`는 `object_id`·`destination_id`를 필수로 하고 `condition: object_in_destination`만 받는다. `GoalEvidence`는 그리퍼 필드(`gripper_state` OPEN, `gripper_observed_at`)를 요구하고, `verify_goal`은 신선도를 본 뒤 생산자가 보낸 `evidence.satisfied`를 돌려준다(181행) — 판정은 생산자가 한다. `goal_evidence_service.py`(36–51행)는 레거시 `MissionService` 기록의 `mission["workcell_id"]`로 생산자를 찾는다. `goal_evidence_store.py`가 증거를 영속한다. D-403 §5의 `sim_model_pose`도 자기 토큰으로 밀어 넣는 생산자다.
  - Pinky Pro 제품 프로필은 `docking.supported: false`다. 도킹은 `capabilities.dock-enabled.yaml` 같은 별도 프로필에서만 켜진다.
  - CORE `CommandManager`의 출처 `fleet`(`arbitration.py` `Priority.FLEET = 6`)에는 생산자가 없다. `SpeedLimits.fleet_linear`/`fleet_angular`(`rosy_default.yaml` 0.20/0.80 — Pinky 프로필 최대와 우연히 같다; 키가 없으면 `max_linear`/`max_angular`)는 `clip(scope="fleet")`에서만 읽히는데 그 scope로 부르는 운영 코드가 없다. D-400 안전 파라미터 리졸버의 상한 목록(`node.py` 101행)에 들어가고, `feat/d400-plan2-rosim`의 `test_sim_safety_configs.py` `_caps()`도 같은 목록을 읽는다.
  - **Step 원장은 아직 정해지지 않았다.** C4 첫 계획판(`a37efddc3`) Task 6은 종류 CHECK 없는 `fleet_mission_steps`를 제안했다. C4 재계획(`439e6ff09`, `feat/rosy-cell-c4-fleet-route`)은 대신 main에 있는 `cell_job_store.py`(`fleet_cell_jobs`·`fleet_cell_steps`·`fleet_cell_events`, 버전 표 `fleet_component_migrations`)를 인계받는다. 그 표는 `CHECK(action_kind='CELL_TRANSFER')`이고 대상 장치와 레시피·셀 해시를 Job 머리의 NOT NULL 열로 둔다. C4 담당(세션 rosy-0d)은 Pinky Step이 C4의 Step 표를 재사용하는 데 동의했다. 사용자가 D-413 Task 5 착지까지 C4를 멈췄으므로 schema는 확정되지 않았다(2026-10-02). rosy-0d의 초기 의견: 종류 CHECK 없음 + 저장소·앱 층의 종류별 검증 hook(조정 메모 질문 2·10), 승인 epoch·세대를 Step 제출마다 기록(질문 7, 기울어 있음).

## 결정

### 1. Pinky Device Action은 네 종류다

Fleet이 Pinky에 하달하는 Step의 `action_kind`는 다음 넷이다. 각 Action은 CORE가 시작부터 끝까지 로컬로 실행하는 유한한 동작이다. Fleet은 시작 요청, 취소 요청, 결과 수집만 한다. "CORE 거절"은 상관된 시작 요청을 CORE가 받지 않는 조건이다. 지금 CORE가 판정하지 않는 것은 R 번호(§6)로 표시했다. Fleet의 사전 확인(§4)은 안내용이고 CORE 판정을 대신하지 않는다.

| `action_kind` | CORE 경로 | CORE 거절(현재 / 추가) | Action 결과(장치 사실) | `GOAL_CONFIRMED` 증거(Fleet 판정, §1.2) |
|---|---|---|---|---|
| `NAVIGATE_TO_POSE` | `POST /navigation/goal {x,y,yaw, correlation_id}` (있음) | 현재: `NOT_LOCALIZED`, `LINE_FOLLOW_ACTIVE`, 보정 lease, e-stop, 능력 보류, 도킹 진행 중, Nav2 미준비(readiness HOLD 503). 추가: MANUAL 모드, `DOCKED`·`CHARGING`(R9), FleetAgent 링크 끊김(R11) | 상관된 `nav.completed` / `nav.failed` | `robot_state`: `LOCALIZED`, map 자세가 Step 허용오차(xy, yaw) 안, 정지 |
| `FOLLOW_LANE_TO_STOPLINE` | 새 `POST /line-follow/run` (R3), `CAMERA_LINE` | R3가 새로 정함: `NOT_LOCALIZED`, MANUAL, 도킹 상태, e-stop, 보정 lease, 카메라 차선 증거나 정지선 관측(road evidence)이 신선하지 않음 | 상관된 차선 실행 종료, 성공 사유는 `stop_line` 하나 | 종료 사유 `stop_line` + `robot_state`: 정지선 관측이 신선하고 `stop_line_distance_m` ≤ 끝 문턱, 정지. Step이 정지선의 사이트 map 위치를 지정했으면 map 자세도 허용오차 안 |
| `DOCK` | `POST /docking/dock {dock, correlation_id}` (상관 추가, R1) | 현재: `DOCKING_ACTIVE`, `LINE_FOLLOW_ACTIVE`, `MODE_CONFLICT`, `EMERGENCY_ACTIVE`, `NOT_LOCALIZED`, 501(미지원) | 상관된 `docking.docked` / `docking.failed` | `robot_state`: 도킹 상태가 그 도크에 `DOCKED`(또는 `CHARGING`). 충전 확인(D-28)은 Step이 `require_charging`일 때만 추가 |
| `UNDOCK` | `POST /docking/undock {correlation_id}` (상관 추가, R1) | 현재: `NOT_DOCKED`, `LINE_FOLLOW_ACTIVE`, `NO_ODOMETRY`, `MODE_CONFLICT`, `EMERGENCY_ACTIVE`, 501 | 상관된 `docking.undocked` / `docking.failed` | `robot_state`: 도킹 상태 아님, 정지, (`LOCALIZED`이면) 도크 밖 자세 |

- **`DOCK`/`UNDOCK`은 당분간 시뮬레이션 전용이다.** Pinky Pro는 `docking.supported: false`다. 도킹이 켜진 프로필의 로봇에서만 Step으로 승인한다.
- **`FOLLOW_LANE_TO_STOPLINE`은 `CAMERA_LINE`을 쓴다.** Fleet이 차선 모드를 `IR_LINE`/`OFF`로만 고르게 한 D-313 시연의 제한은 `PUT /line-follow/mode`에 그대로 둔다. 이 ADR은 그 제한을 **좁게 개정하자고 제안**한다: Fleet은 R3의 끝 조건 있는 실행으로만 `CAMERA_LINE`을 시작할 수 있다. 끝 조건 없는 `CAMERA_LINE` 켜기는 계속 Fleet에 열지 않는다.

#### 1.1 공통 규칙

- **Action identity.** Step 하나의 하달 시도마다 Fleet이 `action_id`·`attempt_id`를 만든다. CORE에는 `attempt_id`만 `correlation_id`로 간다(D-316 §1의 확장). Fleet은 Mission/Step ID를 장치 명령 ID로 쓰지 않는다. 한 Step의 시도는 한 번이다. 결과가 불명이면 같은 시도를 다시 보내지 않는다. CORE도 최근 상관 ID의 재사용을 거절한다(R6). 새 시도는 운영자 재승인(§4.4) 뒤에만 연다(D-330 §4, D-333 §5).
- **수락과 결과는 다르다.** HTTP 2xx는 장치 수락일 뿐이다. 시작 이벤트가 `RUNNING`, 상관된 종료 이벤트가 `ACTION_SUCCEEDED` 또는 실패다. Fleet이 §1.2의 증거를 확인해야 `GOAL_CONFIRMED`다. Nav2나 도킹 상태기계의 성공만으로 Step을 넘기지 않는다(D-328, D-333 §6).
- **실패·시간 초과.** 상관된 실패 종료는 Step을 HOLD(사유)로 둔다. 자동 재시도는 없다. Step 본문에는 `max_time_s`가 있다. 넘으면 Fleet은 상관된 취소(R2)를 요청하고 Step을 HOLD(`result_unknown`)로 둔다. 상관된 최종 결과가 늦게 오면 그것으로 대조한다(D-316 §3과 취소 콜백 보강).
- **취소.** **Step 단위 취소는 항상 상관된 취소다(R2).** CORE는 지금 진행 중인 동작의 상관 ID가 다르면 거절한다. 그래서 Fleet은 운영자나 다른 출처가 시작한 동작을 끄지 않는다. **사이트 전체 주행 취소(D-421)의 navigate·대형·차선 단계와 비상 정지(`/api/fleet/estop`, CORE `safety/stop`)는 일부러 상관 없이 모든 동작을 멈추는 예외다.** 전체 취소의 도킹 단계는 예외가 아니다(§4.2). 취소 요청, 취소 이벤트, 최종 결과, 정지 readback은 서로 다른 사실이다. 취소 뒤 Step은 최종 결과가 올 때까지 HOLD(`cancel_pending`)다.
- **CORE 거절**은 수락 전 거절이다. Step은 HOLD(거절 코드)로 두고 시도는 닫는다.
- **정지 뒤 늦은 2xx.** 정지·전체 취소가 시작된 뒤 도착한 수락 응답에는 Fleet이 곧바로 상관된 취소를 보내고 Step을 HOLD(`late_accept_after_stop`)로 둔다(D-403 §6, D-421 §2-6과 같은 처리).
- **CORE가 스스로 끝낸 동작**(배터리 복귀, NAV-006 막힘, `LOCALIZED` 이탈, 단절 정책, e-stop)도 상관된 종료 이벤트와 출처(`source`)·사유를 내야 한다(R5). Fleet은 출처를 HOLD 사유로 옮긴다(§5.2 표).

#### 1.2 목표 증거

- **기존 증거 경로를 넓히는 실제 작업이다(F4).** 지금 경로는 PICK_PLACE 모양이다(배경 참고): 외부 토큰 생산자, workcell 범위, 물체·목적지 필수 predicate, 그리퍼 필드 필수 증거, 생산자가 정한 `satisfied`, 레거시 Mission 기록 기준 조회. "출처 하나 추가"로는 Pinky 증거가 들어가지 않는다. 필요한 변경:
  1. **내부 출처.** `robot_state`는 Fleet 내부 출처다. 생산자 토큰이 없고, Fleet이 CORE 상태 표본(FleetAgent 상태와 `GET /robot/state`)에서 직접 만든다. 등록부는 "토큰 생산자"와 "Fleet 내부 출처"를 구별한다. `overhead_pose`는 기존 머리 위 관측 경로(D-257 sightings)에서 Fleet이 읽는 내부 출처로 둔다.
  2. **조건별 필드 집합.** predicate와 증거 기록은 조건마다 필드 집합을 갖는다. `object_in_destination`은 지금 필드(물체·목적지, 그리퍼)를 유지하고, `pose_within`·`at_stop_line`·`docked_at`·`undocked`는 자기 필드(목표 자세·허용오차, 정지선 ID·문턱, 도크 ID)를 갖는다. 그리퍼 필드는 조작 조건에만 필수다.
  3. **생산자 범위는 "workcell 또는 robot".** 토큰 생산자도 로봇 범위로 등록할 수 있게 한다.
  4. **판정 주체.** 새 조건 넷은 Fleet이 원값으로 판정한다. 생산자의 `satisfied`를 받지 않는다. 기존 `camera_observation`은 지금처럼 생산자가 판정한다(이 ADR은 바꾸지 않는다). D-403 §5의 `sim_model_pose`도 밀어 넣는 생산자이며, 그 판정 방식은 C4가 정한다.
  5. **Step 기준 서비스.** 증거 서비스는 레거시 `MissionService` 기록이 아니라 Step(`mission_id`, `step_index`, `attempt_id`)을 키로 찾는다. predicate는 Step마다 저장한다(§3 S6). 레거시 PICK_PLACE 경로는 그대로 둔다.
- **수용 규칙.** (a) `robot_state` 표본의 CORE 시각 > 상관 종료 이벤트의 CORE 시각 + `settle_s`. 두 시각은 같은 CORE 시계다. `overhead_pose`는 사이트 PC 시계이므로 이 비교에 쓰지 않고, Fleet 수신 시각이 종료 이벤트 수신 시각 + `settle_s`보다 늦은지로 본다. (b) 연속 2개 이상의 `robot_state` 표본에서 선속도·각속도 < ε. (c) 출처마다 `max_age_s`(Fleet 수신 기준)를 넘은 표본은 쓰지 않는다. (d) `GOAL_CONFIRMED`까지 `goal_evidence_timeout_s`를 넘으면 HOLD(`goal_unconfirmed`).
- **독립성.** `robot_state`는 같은 로봇의 위치 추정이므로 OMX 조작의 "독립 관측"(D-333 §6)과 같은 등급이 아니다. 출처 이름을 증거에 남긴다. 머리 위 카메라(D-257) 자세가 있으면 `overhead_pose`로 함께 기록한다. Pinky–OMX 인계 Step(설계 v0.2 §13.3)은 `robot_state`만으로 확인하지 않는다. 인계에 필요한 독립 증거는 인계 ADR이 정한다.

#### 1.3 넣지 않는 종류

- **`PARK`(bay):** Device Action으로 두지 않는다. 주차는 Mission 템플릿 `NAVIGATE_TO_POSE`(도크 접근 자세) → `DOCK`(주차형 도크 유형)이다. 현재 `bays.py`의 bay는 교통 양보용 비켜설 자리이고, Fleet 콘솔이 상관 없는 이동 목표로 보낸다. 두 의미를 한 이름에 섞지 않는다.
- **`LOCALIZE`:** Mission Step으로 두지 않는다. 위치 확정 기동은 D-395 `localization_service.py`가 유일한 발행자다(§4.6의 예외 규칙).
- **끝 조건 없는 차선 추종:** Device Action이 아니다. Fleet이 끝을 판정하려면 네트워크 너머에서 정지를 결정해야 한다.

### 2. 하달 경로: Task Executor 하나, 장치별 전송 어댑터

- **Task Executor는 하나다.** OMX Step과 Pinky Step은 같은 Fleet 하달기가 같은 claim·세대 검사를 거쳐 낸다(D-330 §1). 하달기의 Step 진행 규칙은 D-413에 따라 `rosy.execution.site`로 옮기고, 지금 조합 위치는 `fleet/server/mission_dispatcher.py` 계열이다. 장치마다 전송 어댑터만 다르다.
  - OMX: 기존 `DeviceActionTransport`(UDS, `FleetActionGrant`, 영속 로컬 Action 원장).
  - Pinky: 새 `PinkyCoreTransport`. Step을 CORE REST 호출로 바꾼다. `swarm/transport.py` `HttpRobotClient`를 확장해 쓴다(F1).
- **공통 포트**는 "제출 → 수락/거절/불명", "상관된 취소 요청", "현재 상관 상태 조회(R8)" 세 가지다. 결과는 포트가 돌려주지 않고 아래 증거 경로로 들어온다. `FleetActionGrant`를 Pinky에 억지로 맞추지 않는다.
- **결과의 출처는 CORE 이벤트다.** CORE FleetAgent WS → Fleet hub `CoreEventStore`(영속 감사) → 투영. 투영 키는 D-316 §2와 같다(robot ID, 현재 `attempt_id`, 이벤트 종류, 이벤트 ID, seq). 중복과 오래된 seq는 상태를 되돌리지 않는다. `task_results.py`의 navigate 투영은 그대로 두고 Step 투영을 더한다(F3).
- **폴링은 대조와 목표 증거에만 쓴다.** `GET /robot/state`, `/docking/status`, `/line-follow`, R8 상관 상태. 폴링 결과로 Action 성공을 추정하지 않는다.
- **HTTP 송신은 claim 트랜잭션 밖에서 한다.** Fleet은 트랜잭션 안에서 세대·epoch를 다시 확인하고 claim을 `DISPATCHING`으로 바꿔 커밋한 뒤, 트랜잭션 밖에서 CORE를 부른다. 커밋과 송신 사이에 정지가 끼는 경합은 Fleet 재검사로 닫히지 않는다. 그 경합은 CORE의 세대 울타리(R4)가 닫는다.
- **기존 `/api/fleet/tasks/*` navigate**는 호환 경로로 남는다. 같은 `robot` claim을 Mission Step과 경쟁한다(D-330 §1).

### 3. Step 원장은 하나다: C4의 Step 표가 확정되면 그것을 쓴다

- **두 번째 Step 원장을 만들지 않는다.** Pinky Step은 C4가 확정하는 Step 표에 들어간다. 그 표의 이름과 schema는 C4 담당 rosy-0d가 정한다. 이 ADR은 표의 모양을 가정하지 않고, 아래를 **그 표에 대한 요구사항**으로 둔다. C4 schema가 이를 만족하지 않으면 C4 재개 때 함께 조정하고, Pinky 쪽이 별도 표로 우회하지 않는다.

| # | 요구 | 이유 |
|---|---|---|
| S1 | `action_kind`에 표 수준 CHECK가 없다. 허용 종류는 저장소·앱 층의 종류 등록부와 검증 hook(S11)이 판정한다(rosy-0d 초기 의견과 같음) | 다음 종류마다 SQLite 표 재구성을 반복하지 않는다. 현재 `fleet_cell_steps`의 CHECK는 이 요구를 만족하지 않는다 |
| S2 | 대상 장치가 **Step 행**에 있다(장치 종류 + 장치 ID) | Mission 하나에 Pinky Step과 OMX Step이 섞인다(인계) |
| S3 | 공정 전용 값(레시피·셀 해시, Job 문서)이 Step 표와 Mission 머리의 NOT NULL 공통 열이 아니다 | Pinky Mission에는 레시피·셀이 없다. Cell Job 의미와 기존 digest는 그대로 둔다 |
| S4 | `(mission_id, step_index)` 순서, 전역 UNIQUE `step_id` | Step k−1 → k 진행 |
| S5 | 시도 식별: `action_id`, `attempt_id`, `request_digest` | §1.1, D-316 투영 키 |
| S6 | Step별 goal predicate, 장치 결과, 목표 증거(출처 포함)를 따로 저장 | `ACTION_SUCCEEDED`와 `GOAL_CONFIRMED`의 분리, §1.2 |
| S7 | 상태 집합에 `WAITING`·`READY`·`RUNNING`·`ACTION_SUCCEEDED`·`GOAL_CONFIRMED`·`HOLD`가 있고 HOLD에 사유 코드가 붙는다(§5.2) | 실패·취소·불명을 새 상태 없이 HOLD + 사유로 표현 |
| S8 | `reconciliation_pending`, `cancel_requested_at`, `deadline_at` | 불명 결과 대조, 시간 초과 취소 |
| S9 | 승인 때의 `authority_epoch`·stop generation과 제출 때의 `dispatch_generation`이 **Step 제출마다** 남는다(rosy-0d 초기 의견: 그렇게 기운다) | §4 진행 조건, R4 |
| S10 | Step 진행·결과·증거가 같은 Mission 이벤트 표에 순서대로 남는다(멱등 이벤트 키) | 재시작 뒤 대조, 감사 |
| S11 | 저장소 함수(생성·승인·Step 시작·결과 기록·목표 확인)에 종류별 본문 검증 hook | Pinky가 Cell 코드를 고치지 않고 종류를 더한다 |
| S12 | 버전 있는 이관(진행 중 Step이 있으면 이관 거절, 이전 schema 유지) | 결과 불명 Action을 이관 도중 건드리지 않는다(D-330 §1) |

- **Pinky가 따로 더하는 것(Step 표 밖):** 종류 등록부 항목 네 개와 본문 schema(목표 자세·허용오차, 정지선 ID·거리 상한, 도크 ID, `max_time_s`, `settle_s`), 목표 증거 출처·조건(§1.2), claim 자원 종류 `dock`(`dispatch_admission.py`).
- **순서.** Pinky의 원장 관련 구현은 C4가 재개되어 Step 표를 확정하고 main에 착지한 뒤에 시작한다(§7).

### 4. Step 진행 조건과 정지

Pinky Step k는 다음이 **모두** 참일 때만 제출한다. 1–4는 claim 트랜잭션 안에서 다시 확인한다.

1. Step k−1이 `GOAL_CONFIRMED`다(첫 Step은 Mission 승인).
2. 하달기가 켜져 있다. 규칙은 D-403 §7과 같다: `simulation` 프로필의 시뮬레이션 identity 로봇에서만, 아래 정지 세대 시험이 통과한 뒤에만 켤 수 있다. 그 밖의 프로필에서 Pinky Mission 하달기는 꺼진 채로 거절한다(D-330 §2 보류 유지).
3. `authority_epoch`와 stop generation(`fleet_dispatch_control`)이 승인 때와 같고 `dispatch_enabled`가 켜져 있다. D-421의 전체 취소 울타리가 열려 있지 않다.
4. 이 Mission이 로봇 claim과 Step이 쓰는 `dock` claim을 쥐고 있다(§4.5 표).
5. 마지막 상태 표본에서 로봇이 **MANUAL 모드가 아니고**, e-stop 래치가 아니고, D-407 막힘이 열려 있지 않고, 보정 lease가 없다. `FOLLOW_LANE_TO_STOPLINE`이면 차선·정지선 관측이 신선하다. CORE도 R9·R3로 같은 조건을 거절한다.
6. 장치 쪽 세대 울타리(R4)가 이 로봇에서 동작한다는 것이 시험으로 확인됐다.
7. **증거 경로가 살아 있다.** 그 로봇의 FleetAgent WS가 연결돼 있고 `CoreEventStore`에 마지막으로 들어온 이벤트·하트비트가 T(기본 3 s, D-419 판정 시간과 같은 값) 안이다. REST가 되더라도 WS가 끊겨 있으면 결과를 받을 수 없으므로 제출하지 않는다. REST와 WS는 따로 끊긴다.
8. 로봇의 실효 SAF-003 정책이 `STOP` 또는 `HOLD`다(§4.3). `RETURN_HOME`·`CONTINUE`면 제출하지 않는다.

#### 4.1 사이트 비상 정지, CORE e-stop

- **사이트 비상 정지**(`/api/fleet/estop`): 세대를 래치하고 CORE `POST /safety/stop`을 보낸다. 진행 중 Step은 HOLD다. 재개는 §4.4뿐이다(D-330 §2, D-403 §6).
- **CORE e-stop 래치**(로컬·물리 포함): 진행 중 동작이 끝나고 상관된 종료(출처 `estop`)가 와야 한다. Step은 HOLD(`estop`)다. Admin 해제 뒤에도 자동 재개는 없다.

#### 4.2 D-421 전체 주행 취소에 대한 요구

D-421은 "주행"을 navigate·대형·차선으로 정하고 도킹과 D-395 기동을 열린 질문 1로 남겼다. Pinky Mission이 생기면 다음이 필요하다. 이것을 **D-421 §2·§3에 대한 요구**로 기록하고, 열린 질문 1에 대한 이 ADR의 답으로 둔다.

- 전체 주행 취소는 같은 울타리 안에서 **끝나지 않은 모든 Pinky Mission**(진행 중 Step뿐 아니라 `READY`, Step 사이 대기, `ACTION_SUCCEEDED`에서 증거 대기 포함)을 HOLD(`site_cancel`)로 옮긴다. 래치가 없더라도 Mission이 다음 Step으로 가지 않게 하려는 것이다.
- **차선 실행.** D-421이 보내는 상관 없는 `line-follow/mode OFF`는 진행 중인 R3 실행도 끝낸다. 이때 CORE는 그 실행의 상관된 종료 이벤트를 출처(`source`, 예: `line_follow_off`)와 함께 낸다(R3·R5). 별도 차선 취소 단계는 필요 없다.
- **도킹.** 상관 없는 `docking/cancel`은 SAF-005 저배터리 복귀까지 취소한다. 그래서 전체 취소는 도킹을 상관 없이 취소하지 않는다. 대신 R8의 `current`가 Mission 상관 도킹 동작을 보이는 로봇에만 그 `correlation_id`로 상관된 `docking/cancel`(R2)을 보낸다. 운영자·배터리 복귀 도킹은 건드리지 않는다.
- 진행 중 Step은 `CANCELED`로 쓰지 않고 상관된 종료를 기다린다(D-421 §2-5와 같은 원칙). 그 뒤 Mission 재개는 §4.4다.

#### 4.3 SAF-003(Fleet 단절)과 D-419

이 ADR은 D-419를 다음처럼 **개정하자고 제안**한다.

- **D-419 §1(적용 범위):** 상관된 Nav2 goal에 더해 상관된 도킹 동작(R1)과 상관된 차선 실행(R3)도 대상이다. 같은 판정기(`FleetLossMonitor`)가 셋 중 진행 중인 상관 동작 하나를 본다.
- **D-419 §3(`HOLD`의 재개):** "Fleet이 같은 시도를 다시 보내 재개"는 Mission 시도에 쓰지 않는다. CORE는 같은 상관 ID의 재사용을 거절하고(R6), Mission은 §4.4로만 재개한다. `held_goal` 기록은 대조 자료로만 쓴다.
- **정책 제한:** Mission을 받을 수 있는 로봇의 실효 정책은 `STOP` 또는 `HOLD`여야 한다. 시뮬레이션 단계부터 적용한다. Fleet은 `GET /safety/state`의 `fleet_link`(D-419 §5)와 `safety/limits`로 이를 확인하고, 아니면 Step 제출을 거절한다(§4.8). `RETURN_HOME`은 상관 없는 귀환 동작이 Mission claim 아래에서 움직이게 하고, `CONTINUE`는 결과를 받을 수 없는 동작을 계속하게 하기 때문이다.
- **D-419가 다루지 않는 것.**
  - *반쯤 열린 TCP.* 로봇 쪽 판정은 keepalive가 소켓을 닫을 때까지(최대 약 40 s) 늦을 수 있다. Fleet 쪽은 §4.7의 신선도 T로 먼저 안다. 진행 중 Step의 로봇이 T를 넘겨 이벤트·하트비트가 없으면, Fleet은 REST로 상관된 취소(R2)를 보내고 Step을 HOLD(`evidence_link_lost`), claim을 `UNKNOWN`으로 둔다. REST도 닿지 않으면 같은 HOLD로 두고 로봇 쪽 SAF-003에 맡긴다.
  - *끊긴 동안의 새 시작.* D-419 §1은 끊긴 뒤 REST로 온 Fleet 목표를 막지 않는다. Mission에는 결과를 받을 길이 없는 시작이다. **R11:** FleetAgent가 설정된 로봇은 링크가 끊긴 동안 상관된 시작 요청을 409 `FLEET_LINK_DOWN`으로 거절한다. 상관 없는 요청은 그대로다.
  - *Step 도중 정책 변경.* 정책은 `PUT /safety/limits`로 언제든 바뀐다. Fleet은 상태 표본마다 실효 정책을 다시 읽고, Step 진행 중 `RETURN_HOME`·`CONTINUE`로 바뀌면 상관된 취소를 보내고 HOLD(`policy_changed`)로 둔다.
- **이름은 D-419의 것을 쓴다.** 단절로 끝난 상관 동작은 `nav.canceled {source: "fleet_loss", correlation_id}`(도킹·차선 실행은 같은 `source`의 종료 이벤트)와 `safety.fleet_lost`로 보인다. Fleet은 재연결 뒤 버퍼 재전송으로 이를 받고 Step을 HOLD(`fleet_loss`)로 둔 뒤 R8로 대조한다. 같은 시도를 다시 보내지 않는다.

#### 4.4 재개는 Mission 전체 재승인이다

- 운영자 재개는 **Mission 전체를 다시 승인하면서 그때의 `(authority_epoch, generation)`을 기록**하는 것 하나로 정한다. 많은 HOLD(`site_cancel`, CORE 거절, `action_failed`, `goal_unconfirmed`)는 세대를 바꾸지 않고, rearm은 발행이 닫혀 있을 때만 된다. 그래서 재승인은 세대 변경을 요구하지 않고 현재 값을 새 기준으로 남긴다. 사이트 정지 뒤라면 rearm으로 이미 세대가 바뀌어 있고, 재승인은 그 새 값을 기록한다.
- 재승인은 첫 번째로 `GOAL_CONFIRMED`가 아닌 Step부터 새 시도로 진행하고, 이미 확인된 Step은 다시 실행하지 않는다. Step 하나만 다시 보내는 별도 동작은 두지 않는다.
- 재승인 전에 운영자는 HOLD 사유와 R8 상관 상태로 직전 시도를 대조한다. `reconciliation_pending`이 남아 있거나 claim이 `UNKNOWN`이면 재승인을 거절한다.
- 재승인은 놓인 `robot:`·`dock:` claim을 기록한 세대로 다시 잡는다. 다른 Mission·task가 그 사이 자원을 잡았으면 HOLD로 남는다.

#### 4.5 Step 상태와 claim 단계

| Step 상태(사유) | robot·dock claim 단계 | 놓기·다시 잡기 |
|---|---|---|
| Mission 승인 직후, `WAITING`/`READY`(Step 사이 포함) | `CLAIMED`(Mission 전 기간, 승인 때 robot과 Mission이 쓰는 모든 dock을 함께 잡는다) | `trip_stop_latch`가 `CLAIMED`를 놓는다 → Mission HOLD(`site_stop`) |
| 제출 커밋 ~ `RUNNING` | `DISPATCHING` | 정지 래치로 놓이지 않는다. `rearm_dispatch`는 이 claim이 있는 동안 거절된다 |
| D-421 전체 취소 뒤, 상관 종료 이벤트 전(`RUNNING`, Mission은 `site_cancel` 표시) | `DISPATCHING` 유지 | 상관 종료가 오면 `CLAIMED`로 내리고 HOLD(`site_cancel`). `goal_evidence_timeout_s` 안에 종료가 없거나 로봇이 응답하지 않았으면 `UNKNOWN`, HOLD(`result_unknown`) |
| `ACTION_SUCCEEDED`(증거 대기) | 상관 종료가 확인됐으므로 `CLAIMED`로 내린다 | 위 첫 줄과 같다 |
| `GOAL_CONFIRMED`(마지막 Step) | 모두 놓는다 | — |
| HOLD(`result_unknown`, `cancel_pending`, `fleet_loss`, `late_accept_after_stop`, `evidence_link_lost`, `policy_changed` 종료 전) | `UNKNOWN` | 운영자 대조로 결과가 정해지기 전에는 놓지 않는다. rearm도 거절된다(D-330 §1) |
| HOLD(CORE 거절, 상관 실패 종료 확인, `goal_unconfirmed`, `site_cancel` 뒤 종료 확인, `not_localized`, `estop`) | `CLAIMED` | 운영자 중단으로 놓거나 §4.4 재승인 때 기록한 `(authority_epoch, generation)`으로 claim을 이어 잡는다 |

#### 4.6 다른 Fleet 구성요소와의 경계

- **D-395 위치 확정 사다리.** 사다리는 claim 없이 자동으로 기동을 낸다. Mission claim이 **없는** 로봇에는 지금처럼 동작한다. Mission claim이 **있는** 로봇에 대해서는 **기록된 단일 예외**로 둔다. 조건: 로봇이 `NOT_LOCALIZED`이고, 그 Mission이 Step 진행 없이 HOLD(`not_localized`)이며 claim이 `CLAIMED`일 때만이다. `DISPATCHING`/`UNKNOWN` claim이 있는 로봇에는 사다리가 기동을 내지 않는다. 사다리 기동은 Mission 이벤트에 기록한다. 이 검사는 `localization_service.py`에 새로 넣어야 한다(F9). 대안(사다리가 `direct_action` claim을 잡음)은 Mission claim과 충돌하므로 채택하지 않는다.
- **콘솔 교통.** Step을 진행 중인 로봇(`DISPATCHING`)은 콘솔 교통이 양보 bay로 보내거나 취소하지 않는다. 교통 충돌이 생기면 상대 로봇(Mission 없는 로봇)이 비킨다. Mission claim이 `CLAIMED`인 로봇(Step 사이, HOLD)에 대한 양보·대형·직접 이동은 거절하거나 미룬다(D-330 §1 직접 조작 혼합 HOLD). 그러려면 Mission의 `NAVIGATE_TO_POSE`·`FOLLOW_LANE_TO_STOPLINE` 경로를 콘솔 교통 정리에 등록해야 한다(F7). Step 로봇끼리 충돌할 때의 우선순위는 F7이 정한다. F7 전에는 시뮬레이션 실행을 **움직이는 로봇 한 대**로 제한한다.

### 5. CORE 출처 `fleet`과 `fleet_linear`, 그리고 종료 출처

#### 5.1 `fleet` 출처는 명령 출처에서 뺀다. `fleet_linear`는 Fleet Action 상한으로 남긴다

- **선택: 출처 `fleet`과 `Priority.FLEET`를 은퇴시킨다.** D-399가 Fleet은 속도를 보내지 않는다고 정했고, 생산자도 없다. Pinky Arbiter 순서는 EMERGENCY > SAFETY > MANUAL > DOCKING > NAVIGATION > IDLE가 된다. 이것이 D-399 §7 후속 5 가운데 Pinky 우선순위 표다. 구현 때 D-399 §1(50행)과 CORE SRS §8.1의 FLEET 행을 함께 고친다. Motion Intent 공통 schema와 OMX 표는 후속 5의 나머지로 남는다.
- **`SpeedLimits.fleet_linear`/`fleet_angular`는 지우지 않는다.** SRS SAF-004의 "Fleet Velocity Limit"을 "Fleet이 하달한 Device Action으로 CORE가 실행하는 움직임의 상한"으로 정의한다. 상관된 Nav2 goal, 차선 실행, 도킹 동작의 출력에 `clip(scope="fleet")`를 적용한다(`min(fleet, profile)`). 그러려면 `CommandManager`가 지금 출력이 상관된 동작에서 나온 것인지 알아야 한다. 기본값(0.20/0.80)은 Pinky 프로필 최대와 같아 설정하지 않은 로봇의 동작은 바뀌지 않는다. D-400 리졸버와 `test_sim_safety_configs.py` `_caps()`의 상한 목록에 계속 들어간다.
- **주의:** 상한을 낮추면 NAV-006 막힘 판정(`stuck_timeout_s` 30 s, 최소 진척)에 더 쉽게 걸린다. 상한을 낮출 때 함께 조정한다.
- 이 항목(R7)은 Step 결과·증거에 필요하지 않으므로 R1–R6·R8–R11과 따로 진행한다.
- **검토한 다른 선택.** 둘 다 지우기(SAF-004와 D-400 리졸버 입력이 사라짐), 둘 다 그대로 두기(생산자 없는 우선순위가 "Fleet이 바퀴를 몬다"는 오해와 우회 입구를 남김), `fleet` 출처를 Fleet Action용 하위 출처로 되살리기(같은 Nav2 슬롯에 두 출처 이름이 생김) — 모두 채택하지 않는다.

#### 5.2 CORE 종료 출처 → Step HOLD 사유

| CORE 종료(상관됨) | Fleet Step |
|---|---|
| `nav.completed`, 차선 실행 `stop_line`, `docking.docked`, `docking.undocked` | `ACTION_SUCCEEDED` → §1.2 |
| `nav.failed`, `docking.failed`, 차선 실행 `lane_lost`·`obstacle`·`obstacle_sensor_stale`·`stop_line_evidence_stale`·`max_distance`·`timeout`·`error` | HOLD(`action_failed:<사유>`) |
| 출처 `fleet_loss` | HOLD(`fleet_loss`) |
| 출처 `estop` | HOLD(`estop`) |
| 출처 `localization`(`LOCALIZED` 이탈 정지) | HOLD(`not_localized`) |
| 출처 `battery_policy`(SAF-005 복귀) | HOLD(`core_preempted:battery`) |
| 출처 `stuck`(NAV-006) | HOLD(`core_preempted:stuck`) |
| 출처 `manual`(운영자가 Step 도중 MANUAL로 바꿔 teleop으로 가져감) | HOLD(`operator_manual`) |
| 출처 `line_follow_off`(상관 없는 `line-follow/mode OFF`, D-421 전체 취소 포함) | HOLD(`operator_cancel` 또는 D-421 창이면 `site_cancel`) |
| 상관 없는 운영자 취소(대시보드, D-421 전체 취소) | HOLD(`operator_cancel` 또는 `site_cancel`) |
| 상관된 Fleet 취소의 최종 결과 | HOLD(`cancel_pending` → 결과로 대조) |

정확한 `source` 값은 R5 구현에서 API Reference와 함께 정한다. 표에 없는 출처는 HOLD(`core_ended:<source>`)다.

### 6. 빠진 조각

**로봇(CORE) — 모두 additive, D-18 절차**

| ID | 내용 | 이유 |
|---|---|---|
| R1 | `docking/dock`·`undock`에 선택 `correlation_id`, `docking.*` 시작·종료 이벤트에 되돌림. 도킹 세대에 묶음(D-316 보강과 같은 방식) | `DOCK`/`UNDOCK` 결과 상관 |
| R2 | 상관된 취소. `navigation/cancel`은 D-419의 `NavigationManager.cancel(correlation_id=…)`를 그대로 쓰고, 그 함수가 `False`(그 상관 동작이 진행 중이 아님)를 돌려주면 REST는 **409 `CORRELATION_NOT_ACTIVE`**를 낸다(조용한 성공으로 바꾸지 않는다). 본문에 R8의 그 상관 최종 기록이 있으면 싣는다. `docking/cancel`과 R3 취소도 같다. 상관 없는 취소는 지금처럼 동작 | Fleet이 남의 동작을 끄지 않음, 이미 끝난 시도를 구별 |
| R3 | 끝 조건 있는 차선 실행 `POST /line-follow/run {until: "stop_line", max_distance_m, max_time_s, correlation_id}`와 `POST /line-follow/run/cancel {correlation_id}`. `CAMERA_LINE`. 성공 종료는 `stop_line` 하나다: 정지선 관측이 신선하고 거리 ≤ 끝 문턱. 정지선 관측(road evidence)의 CORE 수신 시각이 traffic policy의 기존 `stale_after_s`(0.4 s, `traffic_policy/manager.py`)보다 오래되면 `stop_line_evidence_stale`로 끝난다. 새 문턱을 만들지 않는다. 상관 없는 `line-follow/mode OFF`도 실행을 끝내며 출처 `line_follow_off`를 싣는다. 거리·시간 상한은 실패 사유(`max_distance`, `timeout`)다. 그 밖에 `lane_lost`, `obstacle`, `obstacle_sensor_stale`, e-stop, 취소, `fleet_loss`. 상관된 시작·종료 이벤트. D-395 `lane_to_stopline`의 끝 판정을 재사용하되, 거기서도 같은 나이 검사를 더하고 거리 상한 = 성공 규칙은 이 실행에 쓰지 않는다. D-407 막힘은 그대로 콘솔 판단으로 간다 | `FOLLOW_LANE_TO_STOPLINE`, Fleet 원격 정지 판정 금지 |
| R4 | 장치 쪽 세대 울타리. 사이트 정지 요청이 `(site_epoch, generation)`을 싣고 CORE가 사전식으로 가장 큰 값을 영속 래치한다. 상관된 시작 요청은 같은 쌍을 싣고, 래치보다 작으면 거절한다. `site_epoch`는 Fleet `authority_epoch`(재시작 때 증가)다 | D-330 §2의 생산자/소비자 계약, §2의 송신 경합 |
| R5 | CORE가 스스로 또는 다른 출처 때문에 끝낸 상관 동작(e-stop, `fleet_loss`, `LOCALIZED` 이탈, SAF-005 복귀, NAV-006 막힘, 도킹의 모드 선점, 운영자의 MANUAL 전환, 상관 없는 차선 OFF)은 상관된 종료 이벤트에 `source`·사유를 싣는다. D-419의 `nav.canceled {source: "fleet_loss"}`와 같은 형태 | §5.2 |
| R6 | 최근 상관 ID 재사용 거절(크기 제한 링, R8과 공유) | 응답 유실 뒤 중복 제출, D-419 `HOLD` 재개 금지 |
| R7 | 출처 `fleet` 은퇴, 상관 동작에 `scope="fleet"` 상한(§5.1) | 별도 진행 |
| R8 | 상태에 `correlation` 블록: `current`(진행 중 상관 동작 하나: correlation_id, kind, 시작 CORE 시각)와 `last_terminal[]`(correlation_id, kind, outcome, reason, source, CORE 시각; 최근 128개, D-316 보강의 128과 같은 상한, R6과 같은 링). 메모리 기록이며 CORE 재시작 뒤 비어 있다 | 재연결·재시작 뒤 대조 |
| R9 | 상관된 시작 요청을 MANUAL 모드에서 409 `MODE_CONFLICT`로, `DOCKED`·`CHARGING`에서 409 `DOCKED_STATE`로 거절(`UNDOCK`은 예외). 상관 없는 요청의 동작은 바꾸지 않는다 | 지금 CORE는 MANUAL → NAVIGATION을 허용하고 도킹 완료 상태를 막지 않는다 |
| R10 | 상관 동작 진행 중 도킹이 모드를 가져가면(SAF-005 복귀 포함) R5 종료를 낸다 | §5.2 |
| R11 | FleetAgent가 설정된 로봇은 링크가 끊긴 동안 상관된 시작 요청을 409 `FLEET_LINK_DOWN`으로 거절. 상관 없는 요청은 그대로 | 결과를 받을 수 없는 시작 금지(§4.3) |

**D-330 §4(영속 의도)를 Pinky에서 읽는 방식.** CORE는 driver 호출 전에 발행 의도를 영속하지 않고, 이 ADR도 그것을 요구하지 않는다. 대신 다음을 대체 규칙으로 둔다. CORE 프로세스가 재시작되면 진행 중 동작은 사라지고(모터 쪽 명령 watchdog이 바퀴를 세운다), R8 기록도 비어 있다. Fleet은 그 시도를 확인할 수 없으므로 `UNKNOWN` → HOLD(`result_unknown`)로 두고, 운영자가 로봇 상태를 보고 대조한다. 자동 재발행은 없다. "CORE 재시작이 움직임을 멈춘다"는 전제는 DEVICE 단계에서 실제 측정해야 한다.

**Fleet**

| ID | 내용 |
|---|---|
| F1 | `RobotClient`/`HttpRobotClient`에 `dock`, `undock`, 상관된 `navigation_cancel`·`docking_cancel`, 차선 실행 시작·취소, R8 조회 |
| F2 | `PinkyCoreTransport`와 하달기의 장치별 어댑터 선택 |
| F3 | `CoreEventStore` → Step 투영(`nav.*`, `docking.*`, 차선 실행 이벤트, `safety.fleet_lost`). 기존 task 투영 유지 |
| F4 | 증거 경로 확장(§1.2, 실제 작업): 등록부에 "Fleet 내부 출처"(`robot_state`, 토큰 없음)와 `overhead_pose` 구별, predicate·증거 기록의 조건별 필드 집합(그리퍼 필드는 조작 조건에만), 생산자 범위 "workcell 또는 robot", 새 조건 넷은 Fleet 판정(`camera_observation`은 생산자 판정 유지), 증거 서비스를 Step 키로 조회(레거시 `MissionService` 경로 유지). `goal_evidence.py`·`goal_evidence_registry.py`·`goal_evidence_service.py`·`goal_evidence_store.py`를 함께 바꾸고 기존 PICK_PLACE 시험이 그대로 통과해야 한다 |
| F5 | claim 자원 종류 `dock`, §4.5 claim 단계 규칙, 콘솔 교통의 Mission claim 존중 |
| F6 | 종류 등록부와 Pinky 본문 검증을 C4 Step 표의 hook(S11)에 꽂기 |
| F7 | Mission 이동·차선 경로를 콘솔 교통 정리에 등록 |
| F8 | D-421 전체 취소에 §4.2 요구 반영(그 ADR 담당과 합의) |
| F9 | `localization_service.py` 사다리에 Mission claim 검사(§4.6) |
| F10 | Fleet 쪽 증거 링크 신선도 감시와 Step 도중 실효 SAF-003 정책 재확인(§4.3, §4.7) |

### 7. 단계와 소유

| 단계 | 내용 | 조건 |
|---|---|---|
| 0 (지금) | 이 ADR과 [조정 메모](../plans/2026-10-02-d420-pinky-device-actions-coordination.md). rosy-0d 답으로 §3 요구 표 확정. D-419·D-421 담당에게 §4.2·§4.3 전달 | — |
| 1a SOURCE/LOCAL, 원장 무관 | CORE R1–R6·R8–R11과 호스트 시험, Fleet F1·F5·F7·F9·F10, F4 가운데 Step 표와 무관한 부분(등록부 출처 구별, 조건별 필드 집합, 생산자 범위) | 지금 시작할 수 있다. R2·R5·R11은 D-419 착지 뒤 그 코드 위에 |
| 1b SOURCE/LOCAL, 원장 의존 | F2·F3·F6·F8, F4의 Step 키 증거 서비스, 호스트 시험(상관 투영, 중복·오래된 이벤트, 상관된 취소 409, 세대 울타리, 불명 결과 HOLD, 재시작 뒤 자동 재하달 없음, 콘솔 교통 vs claim, §4.5 claim 단계, 전체 취소의 Mission HOLD). 하달기는 시험 안에서만 `simulation`으로 생성 | **C4가 재개(D-413 Task 5 착지 뒤)되어 Step 표를 확정하고 main에 착지한 뒤** |
| 1c R7 | `fleet` 출처 은퇴와 상한 | 별도, 언제든 |
| 2a-prep 시뮬레이션 준비 (소유: 이 ADR의 구현 세션, Gazebo 구성 검토는 sim 담당) | 지금 `semantic_road_dashboard.launch.py`는 2a에 쓸 수 없다: Nav2·map server·위치 추정이 없어서 `NAVIGATE_TO_POSE`가 `LOCALIZED`·Nav2 준비를 얻지 못하고 R3도 `NOT_LOCALIZED`로 거절한다. 시작 자세(-0.20, -0.15)는 `stop_line_main`(x = -0.01)보다 0.19 m 앞이라 이동 Step을 둘 여유가 없다(차선 약 1.6 m). 카메라 기울기 25°가 두 곳(`cam_tilt_deg` launch 인자, `gazebo_camera_pitch_rad`)에 박혀 있다. 준비 작업: `map_260905_traffic.world` + `semantic/road_scene.yaml` + `road_observer_node` + `maps/map_260905.yaml` map server + Nav2 + 위치 추정(`LOCALIZED`까지) + CORE FleetAgent를 함께 띄우는 새 launch, 이동 Step과 정지선 접근 구간을 둘 수 있는 시작 자세(같은 차선에서 정지선 1 m 이상 앞), 두 곳의 카메라 기울기를 실측 11.8°로 | 단계 1a와 함께 시작할 수 있다. 2a의 선행 조건 |
| 2 ROS-SIM | **월드:** `map_v2_fleet`에는 정지선이 없고 road scene·`road_observer_node` 구성도 없다. 그래서 둘로 나눈다. (2a) 단계 2a-prep의 launch에서 `NAVIGATE_TO_POSE` → `FOLLOW_LANE_TO_STOPLINE`. (2b) `map_v2_fleet` 차선 월드에서 `UNDOCK` → `NAVIGATE_TO_POSE` → `NAVIGATE_TO_POSE`(주차 접근) → `DOCK`(도킹이 켜진 프로필, 월드에 도크 모델이 있어야 함 — 없으면 별도 준비 작업). `map_v2_fleet`에 정지선과 road scene을 더하는 일은 별도 계획으로 둔다. F7 전에는 움직이는 로봇 한 대. **정지 세대 시험**은 D-403 §7을 Pinky에 맞춘 것: Step 사이 정지, Action 도중 정지, 정지 뒤 늦은 수락, rearm 뒤 옛 세대 거절, Fleet 재시작, CORE 재시작(UNKNOWN/HOLD), 감사 DB 쓰기 불능 중 정지 fanout, WS 단절(SAF-003 `STOP`/`HOLD`), 전체 주행 취소 중 Step 사이 Mission, 운영자 goal에 대한 상관된 취소 거절 | 고정 이미지·커밋. 시뮬레이션 결과는 물리 정지 증거가 아니다 |
| 3 DEVICE | 로봇별 별도 결정. 로봇은 공유·관문 자원이라 움직이기 전에 사용자에게 묻는다. D-400 게이트, 실제 정지 readback, 정지 시간, CORE 재시작 시 정지 측정, 실물 카메라의 근거리 정지선 관측(열린 질문) | 이 ADR로 열지 않는다 |

- **소유.** Pinky 몫(F1–F10, R1–R11, 종류 등록부와 증거 판정)은 이 ADR의 구현 세션이 맡는다. Step 표와 그 이관은 C4 담당 rosy-0d가 소유한다. 기존 `cell_job_store.py`를 넓히는 경우 그 저자 pl3의 검토를 받는다. Pinky 세션은 Step 표를 직접 바꾸지 않는다. R2·R5의 navigate 부분은 D-419 코드 위에 쌓고, F8은 D-421 담당과 합의한다.

## 빠져 있던 것과 이 ADR의 답

- **CORE가 먼저 끝내는 경우.** 배터리 자동 복귀(SAF-005, `nav.home`·`docking.return_started`), NAV-006 막힘(`nav.stuck`은 상관이 없고 뒤따르는 `nav.canceled`에 상관이 있다), D-395 `LOCALIZED` 이탈 정지, 도킹이 모드를 가져감. 답: R5·R10으로 상관된 종료와 출처를 내고, §5.2 표대로 HOLD한다. Fleet은 다음 Step으로 가지 않고, 같은 시도를 다시 보내지 않는다.
- **D-407 막힘과 R3 `max_time_s`.** 막힘이 열린 동안에도 `max_time_s` 시계는 흐른다. 시간이 다 되면 실행은 `timeout`(실패)으로 끝나고 막힘은 D-407 규칙(`mode_off`)으로 닫힌다. Step 본문의 `max_time_s`는 관제 판단 시간을 포함해 잡는다. 막힘 동안 시계를 멈추는 선택은 끝이 없는 실행을 만들 수 있어 채택하지 않는다.
- **차선 실행 취소 경로:** 새 `POST /line-follow/run/cancel`(R3). `PUT /line-follow/mode OFF`는 상관 없는 취소로 남는다.
- **HTTP 송신과 claim 트랜잭션:** 송신은 트랜잭션 밖(§2), 경합은 R4가 닫는다.
- **운영자 재개:** Mission 전체 재승인(§4.4). Step 단위 재송신은 두지 않는다.

## 열린 질문

1. **근거리 정지선 관측.** 끝 문턱(0.12 m) 안에서 실물 Pinky 카메라(pitch ≈11.8°)가 정지선을 계속 볼 수 있는가? 근거리 사각이 문턱보다 크면 `stop_line_visible`이 먼저 꺼져 R3가 `stop_line`에 닿지 못하고 `stop_line_evidence_stale`로 끝난다. 시뮬레이션의 카메라 각도도 실측값으로 맞춘 뒤 확인한다. 문턱 조정이나 "마지막 관측 뒤 추정 거리" 규칙이 필요하면 R3 구현 전에 정한다.
2. §1.2의 `settle_s`·ε·`max_age_s`의 기본값은 ROS-SIM 측정으로 정한다.
3. **상태에 정지선 관측 신선도가 있는가.** §4 조건 5(정지선 관측 신선)를 Fleet이 사전 확인하려면 `GET /robot/state`(또는 FleetAgent 상태)에 road 관측의 나이가 있어야 한다. API Reference의 상태 예시(`/ws/state`)는 `traffic_policy.age_s`·`stop_line_visible`·`stop_line_distance_m`을 보인다. 이 `age_s`가 CORE 수신 기준 road 관측 나이인지, `GET /robot/state`와 FleetAgent 하트비트에도 같은 값이 실리는지 R3 구현 전에 확인한다. 없으면 R8과 같은 변경에서 더한다. CORE 쪽 R3 거절은 이 질문과 무관하게 동작한다.

## 검토한 대안

| 대안 | 판단 |
|---|---|
| Pinky 전용 Step 표를 따로 둔다(C4를 기다리지 않으려고) | D-330 §1의 단일 발행 권한과 D-413의 사이트 원장 하나에 어긋나고, 인계 Mission이 두 원장에 걸친다. 채택하지 않는다. 기다리는 동안은 §7 단계 1a만 한다. |
| C4의 현재 초안 schema를 가정하고 Pinky를 먼저 구현 | C4가 멈춰 있고 schema가 바뀔 수 있다(첫 계획판과 재계획이 이미 다르다). 요구 표(§3)만 고정한다. |
| Fleet이 `line-follow/mode`를 켜고 상태를 보다가 정지선에서 `OFF`로 끈다 | 정지 결정이 Wi-Fi·relay 지연을 탄다. Fleet이 장치 제어 루프를 닫는 셈이다(D-399). 채택하지 않는다. |
| D-395 `lane_to_stopline`을 `LOCALIZED` 로봇에도 연다 | D-395의 의미(위치 확정 보조, 0.04 m/s, ≤ 1 m, 거리 상한 = 성공)와 Mission 주행이 한 API에 섞인다. 끝 판정 코드만 재사용한다. |
| 상관된 `nav.completed`를 곧 `GOAL_CONFIRMED`로 본다 | Nav2 성공 허용오차와 위치 추정 오류를 그대로 믿는다. D-328/D-333의 결과·목표 분리와 어긋난다. 채택하지 않는다. |
| 결과를 상태 폴링으로 판정 | 짧은 동작의 끝을 놓치고 어느 시도의 결과인지 증명하지 못한다(D-316 맥락). 대조에만 쓴다. |
| `FleetActionGrant`를 Pinky에도 쓴다 | `workcell_id`, 조작 증거 등 OMX 전용 필드가 섞이고 CORE는 grant를 영속하지 않는다. 공통 포트만 공유한다. |
| CORE에 영속 발행 의도 원장을 둔다 | D-330 §4의 문자 그대로지만 Pinky CORE에 새 영속 저장소와 재시작 복구를 더한다. 재시작이 움직임을 멈춘다는 전제를 측정하고 UNKNOWN/HOLD로 대조하는 쪽이 작다. DEVICE 측정이 전제를 깨면 다시 연다. |
| D-395 사다리가 `direct_action` claim을 잡는다 | Mission claim과 충돌해 HOLD 중인 Mission의 로봇에 사다리가 못 들어간다. 조건부 단일 예외(§4.6)를 택한다. |
| `PARK`, `LOCALIZE`를 Device Action으로 둔다 | `PARK`는 기존 두 동작의 합이고 bay와 이름이 겹친다. `LOCALIZE`는 D-395 발행자와 겹친다. 채택하지 않는다. |
| 출처 `fleet` 처리의 다른 선택 | §5.1 참고. |

## 결과

- Fleet 다단계 Mission이 Pinky에서 쓸 수 있는 동작이 넷으로 고정되고, 각 동작의 수락·결과·목표 증거·취소가 상관 ID로 이어진다.
- Step 원장(C4가 확정하는 표)과 Task Executor는 OMX와 Pinky가 하나씩 공유한다. 장치 차이는 전송 어댑터와 종류 등록부에 있다. Pinky의 원장 의존 구현은 C4 착지를 기다린다.
- CORE에서 생산자 없는 `fleet` 출처가 사라지고, `fleet_linear`는 Fleet Action 상한이라는 실제 의미를 갖는다.
- D-419(SAF-003 범위와 `HOLD` 재개), D-421(전체 취소 범위), D-313 시연의 Fleet 차선 모드 제한에 대한 개정을 제안한다. D-316의 상관은 docking·차선 실행·취소로 넓어지며, 그 확장은 구현 변경에서 API Reference와 함께 기록한다.

## 수용 기준과 증거 경계

- **SOURCE:** §7 단계 1a·1b·1c의 호스트 시험. C4 Step 표가 §3 S1–S12를 만족함을 보이는 시험(Pinky 종류 Step 생성, Pinky·OMX Step이 섞인 Mission). Pinky 종류 추가가 기존 Cell Job 행과 `PICK_PLACE`/`CELL_TRANSFER` digest를 바꾸지 않음. 비시뮬레이션 프로필에서 Pinky 하달기 거절. 실효 SAF-003 정책이 `RETURN_HOME`·`CONTINUE`인 로봇에 Step 제출 거절.
- **ROS-SIM:** §7 단계 2.
- **DEVICE / FIELD:** 이 결정으로 승격하지 않는다.

**관련 결정:** [D-12](D-12-mission-fleet.md), [D-18](D-18-rosy-core.md), [D-28](D-28-nav2.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-257](D-257-site-lane-map-and-overhead-sightings.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-313](D-313-supervised-camera-fault-demo.md), [D-316](D-316-pinky-site-fleet-navigation-result-correlation.md), [D-328](D-328-model-proposed-missions-and-independent-goal-evidence.md), [D-330](D-330-fleet-action-admission-stop-and-recovery.md), [D-333](D-333-er2-mission-device-action-contract-closure.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-395](D-395-fleet-assisted-localization.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-400](D-400-core-safety-policy-off-shadow-enforce.md), [D-401](D-401-rosy-cell-application.md), [D-403](D-403-fleet-cell-job-route-cell-transfer.md), [D-407](D-407-lane-stuck-recovery-console-then-local.md), [D-413](D-413-platform-modules-integrations-apps-profiles.md). main 미착지: D-419(`feat/d415-saf003-fleet-loss`), D-421(`feat/d414-fleet-cancel-all`).
