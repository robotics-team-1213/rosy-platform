## D-491 관제 trip 실행(D-488 M2)의 계약 — 로봇 능력 필드, 시각 있는 odom 자세, Rosy Cam 주 지도 자세, 교차로 동작 API, 서버 trip 루프, 주행 가르치기

**Status:** Proposed (2026-10-07, 사용자 지시 "M2 처리해"). [D-488](D-488-fleet-site-map-address-routes.md) 7항 M2의 구현 계약이다. 실차 이동·G4/G5·DEVICE 수용을 뜻하지 않는다.

잇는 결정: [D-488](D-488-fleet-site-map-address-routes.md)·[D-489](D-489-fleet-route-planning-concept-and-algorithm.md)·[D-490](D-490-fleet-route-planner-implementation.md)(현장 지도·계획기) · [D-463](D-463-fleet-lane-route.md)(다음 짧은 점) · [D-476](D-476-lane-loss-expected-road-bridge.md)(차선 bridge와 route hint 확정점) · [D-468](D-468-local-lane-departure-return.md)·[D-407](D-407-lane-stuck-recovery-console-then-local.md)(이탈·막힘) · [D-395](D-395-fleet-assisted-localization.md)(Fleet 보조 위치) · [D-257](D-257-site-lane-map-and-overhead-sightings.md)(sighting) · [D-18](D-18-rosy-core.md)(외부 API는 CORE)

### Context

2026-10-07 코드 조사(main `838c74349`)에서 확인한 것:

1. **로봇 능력.** `GET /api/v1/system/capabilities`의 `rosy.controls/1` `base_velocity`에는 수동 한도 `max_linear`·`max_angular`와 `autonomy: ["line"]`만 있다. 로봇 종류, `lane`/`free` 주행 방식, trip용 최고 속도 필드는 없다. Fleet hub는 HELLO의 `model`을 버린다. 계획기 `PlanRequest(robot_kind, drive_modes, max_speed_mps)`는 자리만 있고 비어서 호출된다.
2. **교차로 동작.** CORE에는 차선 주행 로봇에게 "다음 교차로에서 직진·좌·우·정지"를 알리는 API가 없다. `LineFollowManager.set_bridge_route_hint`는 내부 메서드이고 "Nothing feeds this yet"이며, D-476 구현 노트대로 차선을 잃은 동안의 직선 bridge에만 쓰인다. 실제로 좌우로 꺾는 동작은 없다.
3. **odom.** 전용 odom 채널이 없다. 상태 스냅숏의 `pose`는 프레임이 `localization.pose_frame`에 따라 map 또는 odom이고, hub heartbeat는 1 Hz다.
4. **D-395 중재기**는 로봇이 낸 180° 거울 후보 중 하나를 고르는 순수 함수다. 자세를 섞지 않는다. LOCALIZED는 로봇이 소유한다.
5. **`/route`(D-463)**에는 서버 루프가 없다. 호출 한 번이 한 걸음이고, 반복 호출자는 저장소에 없다. 진행 상태는 프로세스 메모리에만 있다. `record_plan`은 요약만 저장한다.
6. Fleet·콘솔에는 주행 궤적을 기록하는 도구가 없다.

### Decision

1. **로봇 능력 필드(CORE, API Ref additive).** `rosy.controls/1` `base_velocity`에 선택 필드 셋을 더한다.
   - `robot_kind`(로봇 패키지 설정, 예 `pinky_pro`)
   - `drive_modes`(`["lane"]`, `["free"]`, `["lane","free"]`): `lane`은 line-follow 서비스가 있을 때, `free`는 capabilities의 `navigation.goal_navigation`이 참일 때
   - `trip_max_linear`(m/s): 로봇이 trip에 허용하는 최고 속도. 기본은 `line_follow.max_linear`와 안전 한도 중 작은 값

   Fleet은 capabilities 캐시에서 이 값을 읽어 `PlanRequest`를 채운다. **필드가 없는 로봇(옛 이미지)에는 trip 실행을 열지 않는다**(`TRIP_ROBOT_CAPS_UNKNOWN`). 계획 미리보기는 지금처럼 허용한다.
2. **시각 있는 odom 자세(CORE, API Ref additive).** 상태 스냅숏에 선택 필드 `odom_pose {x, y, yaw, stamp}`를 더한다. 로봇 odom 프레임의 자세와 그 측정 시각(로봇 단조 시각이 아니라 UTC, `captured_at`과 같은 형식)이다. map 자세가 있어도 같이 싣는다. heartbeat 주기는 1 Hz 그대로 두고, trip 루프는 필요할 때 REST 스냅숏을 읽는다(4항).
3. **Rosy Cam 주 지도 자세(Fleet 순수 모듈).** 새 `operations/fleet/fleet/localization/map_pose.py`가 로봇마다 다음 순서로 자세를 정한다.
   - **앵커**: 신선한 sighting(lease 1 s 안, 출처 토큰이 그 로봇 id에 묶임, 품질 통과)의 `(x, y, yaw, captured_at)`를 지도 자세 앵커로 둔다. 그때의 `odom_pose`(가장 가까운 시각)를 짝으로 기억한다.
   - **다리**: 다음 sighting까지는 앵커 이후의 odom 증분(앵커 odom → 최신 odom의 강체 변환)을 앵커에 합성한다. 누적 이동 거리를 `dead_reckon_m`으로 센다.
   - **판정**: `dead_reckon_m > max_dead_reckon_m`(기본 1.5 m)이면 `DEGRADED`다. 새 sighting과 그 시각의 odom 예측 자세 차이가 `max_jump_m`(기본 0.15 m) 또는 `max_jump_deg`(기본 20°)를 넘으면 `DEGRADED`로 두고 새 sighting으로 다시 앵커한다. 연속 2회 일치하면 `LOCALIZED`로 돌아온다. sighting을 한 번도 못 받았거나 odom이 3 s 넘게 낡았으면 `UNKNOWN`이다.
   - **출력**: `MapPose{x, y, yaw, state, source: sighting|bridged, dead_reckon_m, age_s}`.
   - **사용처**: 이 자세는 **trip 실행(5항)의 위치 판정에만** 쓴다(D-488 3항의 범위 개정). D-463 `/route`·D-395 경로·교통정리는 지금 판정(`trusted_map_pose`)을 그대로 쓴다. sighting은 여전히 로봇 `cmd_vel`·안전 정지·로봇 AMCL에 들어가지 않는다. D-457 markerless tracking은 입력이 아니다(표시 전용 유지).
4. **교차로 동작 API(CORE, API Ref 한 행).** `POST /api/v1/line-follow/junction`(operator, seat 보유자만). 본문은 `{action: straight|left|right|stop, place_id, stop_after_m?, expires_s}`다.
   - CORE는 다음 교차로 하나에 대한 지시를 보관한다. `expires_s`는 최대 30 s이고, 지나면 버린다.
   - 차선 주행 매니저는 교차로를 감지하면 보관된 지시대로 가지를 고른다. **지시가 없거나 만료됐으면 교차로 앞에서 멈추고** `junction_waiting` 상태를 알린다. 이것이 기본 안전 동작이다.
   - `stop`이면 `stop_after_m`(기본 0) 뒤 멈추고 line-follow를 `hold` 상태로 둔다.
   - 가지 고르기는 기존 차선 인식이 낸 분기 후보 중 지시 방향과 가장 가까운 것을 따른다. 분기를 인식하지 못하면 멈추고 `junction_unresolved`를 알린다. 추측해서 꺾지 않는다.
   - 기존 D-476 bridge route hint는 이 지시에서 채운다(`left`/`right`/`straight`).
   - 응답은 `{accepted, junction_seq}`이고, 상태 스냅숏의 `line_follow.junction {pending_action, place_id, state: idle|armed|executing|waiting|unresolved, seq}`로 진행을 읽는다.
   - 이 API는 모드를 바꾸지 않는다. line-follow가 `CAMERA_LINE`/`IR_LINE`이고 seat가 있을 때만 받고, 그렇지 않으면 409 `LINE_FOLLOW_NOT_ACTIVE`다.
5. **서버 trip 루프(Fleet).**
   - **계획 저장**: 계획 본문(segments·actions·places·map_version)을 `plan_id`로 저장한다(보존 규칙은 D-490 그대로).
   - **실행 시작**: `POST /api/fleet/trips/{plan_id}/start`(named operator)는 다음을 확인한다. 계획 뒤 30 s 안인지(`TRIP_PLAN_EXPIRED`), 활성 지도 버전이 같은지(`TRIP_MAP_CHANGED`), 로봇 능력이 있는지(`TRIP_ROBOT_CAPS_UNKNOWN`), 계획의 간선이 모두 그 로봇의 주행 방식으로 갈 수 있는지(`TRIP_MODE_UNSUPPORTED`), 다른 trip이 진행 중인지(`TRIP_BUSY`, 사이트 전체 한 대), `MapPose`가 `LOCALIZED`인지(`TRIP_POSE_UNTRUSTED`).
   - **상태기계**: `started → running → (arrived | stopped | failed | canceled)`다. 상태는 저장소에 남겨 재시작 뒤에도 "진행 중이었던 trip"을 알고, 재시작 뒤에는 `stopped(restart)`로 둔다. 자동으로 다시 출발하지 않는다.
   - **루프**: 0.5 s마다 실행 중인 trip 하나를 다룬다. `MapPose`를 계획 차로에 투영해 진행 s를 구한다.
     - `lane` 간선: 다음 교차 장소까지 남은 거리가 `arm_distance_m`(기본 0.6 m) 안이면 그 장소의 동작을 4항 API로 보낸다. 마지막 장소는 `stop`이다.
     - `free` 간선: D-463 `next_step`(0.20 m 앞 점) goal을 보낸다.
   - **멈춤**: `MapPose`가 `DEGRADED`/`UNKNOWN`이 되거나 로봇이 차로 폭 절반보다 벗어나면 새 지시를 보내지 않는다. `lane` 간선이면 다음 교차로에서 로봇의 기본 안전 동작(지시 없으면 멈춤)이 작동한다. `free` 간선이면 goal 전송을 멈추고 로봇의 deadman에 맡긴다. 그다음 trip을 `stopped(pose)`로 둔다.
   - **재계획(D-489 9항)**: 다음 장소에서만 한다. 경로가 바뀌면 운영자 확인을 받기 전까지 그 장소에 서 있는다.
   - **취소**: `POST /api/fleet/trips/{id}/cancel`은 `lane`이면 `stop`, `free`이면 goal 취소를 보낸다.
   - **가드 교체**: `route_active()` 30 s 가드는 "running trip이 있음"으로 바꾼다.
   - **표시**: 콘솔 지도 화면이 진행 중인 trip(현재 차로·다음 장소·상태·자세 출처)을 보인다.
6. **주행 가르치기(Fleet·콘솔).** `POST /api/fleet/teach/start {robot_id}`·`/stop`(named operator)으로 시작하고 멈춘다.
   - 기록하는 동안 3항 `MapPose`가 `LOCALIZED`이거나 다리 길이 0.5 m 이하인 점만 0.1 m 간격으로 남긴다.
   - 멈추면 Ramer–Douglas–Peucker(허용 0.02 m)로 단순화한 폴리라인과 양 끝에 가장 가까운 기존 장소(0.15 m 안) 후보를 돌려준다.
   - 운영자는 콘솔에서 시작·끝 장소(기존 장소 또는 새 주소 이름), 통행 방향, 주행 방식, 속도 상한을 정해 **초안에 간선으로 확정**한다. 기존 초안 PUT과 활성화 규칙(D-488)을 그대로 탄다.
   - 가르치기는 로봇을 움직이지 않는다. 운전자가 Pilot으로 몬다. 한 번에 한 대만 기록한다.
7. **브랜치와 착지 순서.** (a) CORE 계약(1·2항), (b) CORE 교차로 동작(4항), (c) Fleet `map_pose`(3항), (d) Fleet trip 루프(5항), (e) 가르치기(6항). (d)는 (a)·(b)·(c)의 인터페이스를 주입받아 병행하고, 착지는 (a)·(b)·(c) 다음이다. (e)는 (c) 다음이다. API Ref 버전은 착지 순서대로 다음 빈 번호를 쓴다.

### 범위 밖

- 여러 로봇 동시 trip(교통 층 ADR). `free` 방식의 실차(G4/G5 봉인 뒤). sighting 없는 구역의 장거리 주행. 교차로 기하를 CORE가 아는 일(지시는 Fleet이 지도에서 정한다).

### 검토한 대안

- **D-395 중재기를 확장해 자세를 섞기.** 중재기는 후보 선택용이고 로봇이 LOCALIZED를 소유한다. trip 전용 순수 모듈로 분리해, 기존 경로의 신뢰 판정을 바꾸지 않는다.
- **heartbeat를 5 Hz로 올리기.** 모든 로봇·Fleet 경로의 부하를 바꾼다. 시각 있는 `odom_pose`와 필요할 때 REST로 읽기로 충분하다.
- **교차로에서 지시가 없으면 직진.** 지시 지연·Fleet 끊김에서 잘못된 가지로 갈 수 있다. 멈춤이 안전하다.
- **Fleet이 교차로에서 속도 명령을 직접 낸다.** CORE가 최종 `cmd_vel`의 유일한 발행자라는 규칙(D-18)에 어긋난다.

### Consequences

- 수용 기준 SOURCE:
  - 능력 필드와 옛 로봇 거절
  - `odom_pose` 왕복
  - `map_pose` 앵커·다리·`DEGRADED`·회복(시각 순서, 점프, 1.5 m)
  - 교차로 API: 권한·seat·만료·지시 없음 멈춤·`unresolved` 멈춤·`stop_after_m`
  - trip 상태기계: 모든 오류 코드, 재시작 `stopped`, 다음 장소 재계획, 한 대 제한
  - 가르치기 RDP·장소 붙이기·확정
- SIM: Gazebo `map_v2_fleet` 차선 트랙에서 `lane` trip 완주(교차로 지시 포함)
- DEVICE: 9dfk(마커·Rosy Cam 맞춤 뒤, 사용자 승인)

CORE 변경 두 가지(1·2항, 4항)는 서명 릴리스가 있어야 로봇에 닿는다.

### 구현 부록 (2026-10-07) — 5항 trip 루프

브랜치 `feat/d491-fleet-trip-loop`의 구현과 두 번의 검토(조정자 검토, 독립 검토)에서 정한 것이다. 결정 본문은 바꾸지 않는다. API Reference 행은 v1.112로 썼고, 착지 순서에 따라 다음 빈 번호로 옮긴다. CORE 쪽 동작은 4항 구현(`feat/d491-core-junction-action`의 `line_follow/junction.py`)을 기준으로 한다.

1. **trip id.** trip id는 `plan_id`다. 한 계획은 한 번만 출발한다(409 `TRIP_ALREADY_STARTED`). 상태 코드는 없는 계획·trip 404, `TRIP_BUSY`·`TRIP_ALREADY_STARTED`·`TRIP_NOT_RUNNING` 409, 나머지 시작 거절 422다. `/trip`의 `execute: true`는 계속 501이다. 출발은 언제나 이름 있는 운영자의 별도 호출이다.
2. **차선 로봇이 갈 수 없는 계획.** `TRIP_MODE_UNSUPPORTED`로 거절한다. 차로 중간에서 끝나는 `lane` trip(`LANE_END_NOT_A_PLACE`), `lane` U턴(`LANE_UTURN`), 150°를 넘는 회전(`LANE_TURN_TOO_SHARP`)이다. `lane` 간선이 하나라도 있으면 능력 `junction_turn: true`가 있어야 한다(`JUNCTION_TURN_UNSUPPORTED`). CORE의 교차로 판정은 keep 모드 증거가 살아 있을 때만 작동해서, 없으면 교차로에서 멈추지도 꺾지도 않는다(D-492). 실행 가능 규칙은 순수 모듈 `fleet/routing/execute.py`에 둔다.
3. **CORE 교차로 상태를 먼저 읽는다.** `lane` 간선에서는 tick마다 보내기 전에 `line_follow.junction`을 읽는다. CORE는 지시를 하나만 보관하고, 회전 동작 중의 새 지시는 그 동작을 `aborted`로 만들고 받지 않는다. 그래서 CORE가 `executing`이거나 `turning`·`advancing`·`reacquiring`인 동안에는 보내지 않는다. 예외는 우리가 보낸 `stop`(재계획 대기)을 확인 뒤의 새 동작으로 바꿀 때다. `straight`와 회전은 CORE가 같은 seq·장소로 `armed`를 보일 때 만료(15 s)의 절반마다 다시 보낸다. 장소 앞에서 CORE가 `idle`·`waiting`이면(만료됨) 다시 보낸다. `stop`은 한 번만 보낸다. CORE가 우리 seq로 `executing`이나 회전 동작 상태를 한 번이라도 보인 지시는 수행된 것으로 보고 다시 보내지 않는다. 같은 장소·동작을 다시 보내 409 `JUNCTION_ALREADY_DONE`을 받으면 실패가 아니라 수행됨이다. CORE가 장소의 지시를 `aborted`로 보이거나 우리 지시가 동작을 abort시키면(`accepted: false`), 로봇이 다시 `CAMERA_LINE`이 돼도 그 지시를 자동으로 다시 보내지 않는다. trip은 `stopped(junction)`이고 운영자가 새 계획으로 다시 출발시킨다(CORE 안전 검토). CORE는 동작 중의 같은 지시를 무시하고(M3), 수동 조작이 잡혀 있으면 409 `MODE_CONFLICT`다.
4. **멈춤 거리.** `stop`(마지막 장소, 차선→좌표 넘김, 재계획 대기)의 `stop_after_m`은 장소까지 남은 거리를 [0, 2] m로 자른 값이다. CORE는 이 거리를 교차로가 아니라 받은 때부터의 odom으로 잰다. CORE는 이 거리와 교차로 감지 중 먼저 오는 쪽에서 선다(M7). 실제로 서는 위치는 모델 PC SIM에서 재야 한다(이 노트북에서 Gazebo를 돌리지 않는다). 차선 도착은 마지막 장소의 `stop`이 받아들여졌고 로봇이 장소 0.15 m 안이거나, CORE가 그 `stop`(우리 seq `executing`)을 붙잡고 있고 0.3 m 안일 때다.
5. **다음 구간으로 넘어가는 때.** CORE가 그 장소의 지시를 수행한 뒤 끝냈다고 알릴 때(수행됨 + `idle` 또는 더 새 seq, 장소 0.3 m 안, 또는 `JUNCTION_ALREADY_DONE`), 또는 자세가 다음 차로 위로 0.02 m 넘게 나아가고 지금 차로보다 다음 차로에 더 가까울 때다. 90°·90°를 넘는 회전과 0.37 m 고리 차로로 시험한다. 처음 구현의 "장소를 지난 투영"만으로는 제자리 회전과 짧은 차로에서 넘김을 놓치거나 CORE의 동작 중에 다음 지시를 보낼 수 있었다.
6. **지시 만료.** 교차로 지시 `expires_s`는 15 s다.
7. **차선→좌표 넘김.** 넘기는 장소에서 차선 로봇에 `stop`을 보낸다. 모드 전환 경로는 이 ADR에 없다.
8. **재계획.** 계기는 주입된 막힌 차로 집합(`blocked()`) 또는 지도 버전 변경이다. 막힌 차로를 내는 곳은 아직 없다. 로봇은 그 장소에서 `stop`(좌표면 장소 목표)으로 서 있고, 확인 뒤 마지막 지시 기록을 지우고 새 계획의 그 장소 동작이 보관된 `stop`(그 seq만)을 바꾼다. 확인 전에 지도가 바뀌면 409 `TRIP_MAP_CHANGED`이고 같은 장소에서 다시 계획한다.
9. **모든 끝에서 바로 멈추고, 모든 멈춤이 trip을 끝낸다.** 운영자의 멈춤은 거절되지 않고 먼저 로봇에 간 뒤 trip을 `canceled`로 끝낸다. 로봇별 취소·전체 취소·intent 취소(`console.cancel`)는 `operator_cancel`, Fleet 비상 정지(`estop_all`)는 `operator_estop`, `line-follow` `OFF`는 `operator_line_follow_off`다. 로봇 호출이 실패해도 trip은 끝난다. 그렇지 않으면 다음 tick이 멈춘 로봇에 다시 지시를 보낸다. trip 루프 자신의 정지는 감싸기 전의 콘솔 메서드를 써서 되돌아 들어가지 않는다. 취소, 위치 상실·차로 이탈, CORE `aborted`·`unresolved`·10 s 넘는 `waiting`(`stopped(junction)`), 멈춤 규칙, 로봇 오류(`failed`), 루프 오류(`failed(TRIP_LOOP_ERROR)`), 재시작 뒤의 열린 trip(tick과 따로 10 s마다 최대 30회 다시 시도, 로봇이 명단에서 빠지거나 새 trip이 그 로봇을 잡으면 그만, 다른 trip 중이면 건너뜀)은 모두 로봇을 바로 멈춘다. 콘솔이 보내지 않은 목표(교통 대기·양보·위치 불신으로 대기열에 들어감)도 trip 실패(`TRIP_GOAL_REFUSED`)로 멈추고, 좌표 trip이 끝날 때마다 그 로봇의 콘솔 대기열을 지운다. `lane`이면 장소가 있을 때 교차로 `stop`(`stop_after_m` 0)을 보내고 `PUT /api/v1/line-follow/mode {mode: OFF}`로 차선 주행을 끈다. `POST /api/v1/line-follow/hold`는 hold-to-run 세션을 늘리는 운전자 "진행" 신호(D-344 8항)라 멈춤으로 쓰지 않는다. `free`이면 목표를 취소한다. 다만 위치를 잃은 `free` 로봇은 지금처럼 목표 전송만 멈추고 로봇의 deadman에 맡긴다. 멈춤의 각 단계는 어떤 예외에도 다음 단계를 시도하고, 결과를 `detail.stop_sent`와 `detail.error`로 남긴다.
10. **취소는 기다리지 않는다.** 취소는 진행 중인 tick의 잠금을 기다리지 않고 바로 멈춘다. 그 tick이 이미 보내던 지시가 취소 뒤에 닿으면 그 tick이 다시 멈추고, 취소된 상태를 바꾸지 않는다. tick은 보낸 뒤 도착 판정 전에 trip이 아직 열려 있는지 다시 본다. 루프의 로봇 호출은 하나에 1.5 s를 넘지 않는다.
11. **멈춤 규칙과 시작 검사.** 계획을 따라간 거리가 `fleet.trip.stall_s`(기본 20 s) 동안 0.05 m 이상 늘지 않으면 `stopped(stall)`이다. CORE 교차로 동작 중과 재계획 확인 대기 중에는 세지 않는다. `lane` 간선이 있는 계획은 시작 때 `GET /api/v1/line-follow` `mode`가 `CAMERA_LINE`이 아니면 422 `TRIP_LINE_FOLLOW_NOT_ACTIVE`다. CORE는 `IR_LINE`에서 교차로를 감지하지 못해 지시를 409 `JUNCTION_CAMERA_ONLY`로 거절한다. 지도 버전은 로봇 호출이 끝난 뒤 trip을 열기 직전에 한 번 더 본다.
12. **위치 판정.** 시작은 sighting 앵커가 2 s 이내로 알려졌을 때만 연다(없거나 낡으면 `TRIP_POSE_UNTRUSTED`). 루프는 tick마다 trip 로봇의 상태를 REST로 한 번 읽어(`refresh(force_rest=True)`) odom을 2 Hz로 채운다. 이 읽기 실패 경고는 30 s에 한 번만 남긴다. 위치로 멈출 때 제공자의 `sightings_filtered_map_id`·`odom_refused`를 `detail`에 남긴다.
13. **루프는 죽지 않는다.** `run()`은 앱이 살아 있는 동안 돌아오지 않는다. tick 오류는 그 trip만 `failed(TRIP_LOOP_ERROR)`로 끝내고 로봇을 멈춘다. 저장소까지 실패하면 메모리의 trip만 닫는다.
14. **trip 중 다른 이동 거절.** trip이 도는 동안 그 로봇에 대한 Fleet의 다른 이동 명령은 409 `TRIP_ROBOT_BUSY`다. `/goal`·`/route`·작업 배차(그 로봇을 배차 대상에서 뺀다)·`formation/start`이다. `formation/reform`·`formation/resume`, 움직이는 줄 막힘 결정(`RESUME`·`BACK_AND_RETRY`·`YIELD`), `OFF`가 아닌 `line-follow` 모드 변경도 거절한다. 멈추는 결정 `WAIT`·`ABORT`·`MANUAL`은 로봇에 보내고, `ABORT`·`MANUAL`은 trip도 끝낸다(`operator_stuck_abort`·`operator_stuck_manual`). Fleet 쪽 자동 해결기(`stuck_resolver_loop`, D-438)는 trip 로봇에 답하지 않는다. 로봇 안의 D-407 해결기는 CORE 쪽 안전이라 그대로 둔다. 콘솔 목표는 보낸 지 2 s 안이면 로봇이 아직 `NAVIGATING`을 알리지 않았어도 진행 중으로 본다. 거꾸로 trip 시작은 로봇이 콘솔 목표(진행 중)·대기열·양보·대형 중이면 409 `TRIP_ROBOT_BUSY`(`detail.reason`)다. 콘솔 교통 정리는 trip 로봇에 비켜서기를 시키지 않고(움직일 수 없는 장애물), 능력 저하 재배정의 후보로 삼지 않는다. 이 가드는 안전 파일 `console.py`를 늘리지 않으려고 `trip_guard.py`가 콘솔 인스턴스의 `goal`·`formation_start`·`line_follow_mode`를 감싸서 하고, `console.py`는 `TripAware.trip_busy`를 쓰는 네 줄을 고칠 뿐 줄 수가 늘지 않는다. trip 루프만 `console.goal(..., trip=True)`로 보낸다.
15. **크기 예산.** Fleet 패키지 크기는 40110 줄로 독립 재판정됐다(검토자가 증가를 타당하다고 판단). `trip_runner.py`는 600 줄 안이고, 포트·설정은 `trip_ports.py`, 실행 가능 규칙은 `fleet/routing/execute.py`다.
