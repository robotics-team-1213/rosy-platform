## D-494 관제 trip 실행(D-488 M2)의 계약 — 로봇 능력 필드, 시각 있는 odom 자세, Rosy Cam 주 지도 자세, 교차로 동작 API, 서버 trip 루프, 주행 가르치기

**번호:** 처음 D-491로 적었으나 main에 다른 D-491(IR 가드 횡단보도)이 먼저 착지해 2026-10-07 착지 전에 D-494로 옮겼다.

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

### 구현 부록 (2026-10-07)

1·2항 구현(`feat/d491-robot-trip-contracts`)과 독립 검토에서 정한 것이다. 결정 본문은 바꾸지 않는다.

1. **`odom_pose.stamp`는 CORE가 odom 메시지를 받은 시각이다.** ROS 헤더 시각이 아니다(sim에서는 sim time이라 UTC가 아니다). 값은 UTC epoch 초(실수)로 sighting `captured_at`과 같은 형식이다. 유한하지 않은 odom 표본은 버리고 이전 값을 둔다.
2. **`robot_kind`는 `robot.model`이 로봇 패키지 이름(`[a-z][a-z0-9_]*`, 64자 이하)일 때만 싣는다.** 아니면 빼고 로그를 한 번 남긴다. 그런 로봇은 능력 미상(`TRIP_ROBOT_CAPS_UNKNOWN`)으로 읽힌다.
3. **`trip_max_linear`**는 safety `max_linear`·`fleet_linear`와 line-follow `max_linear` 중 최솟값이다. Fleet은 0 m/s를 "갈 수 있는 간선 없음"(`TRIP_NO_ROUTE`)으로 계획한다. Fleet은 모르는 `drive_modes` 값을 버리고 아는 값만 쓴다.
4. **`junction_turn`**(D-495)은 line-follow 매니저의 `supports_junction_turn` 훅이 참일 때만 true다.

### 구현 부록 (2026-10-07) — 3항 map pose

브랜치 `feat/d491-fleet-map-pose`. 3항을 `operations/fleet/fleet/localization/map_pose.py`(순수, 표준 라이브러리만)와 `server/map_pose_service.py`(`arbitrated_pose`, `GET /api/fleet/robots/{robot_id}/map-pose`, viewer 이상)로 구현했다. 독립 검토 두 차례(REQUEST CHANGES) 반영 뒤의 규칙이다. 설정은 사이트 YAML `fleet.map_pose`다.

1. **시계와 sighting 신선도.** `odom_pose.stamp`는 UTC epoch 초(float)이고 `captured_at`과 같은 형식이다. CORE가 odom을 받을 때 벽시계로 찍는다(ISO 문자열도 읽는다). 로봇 시계와 사이트 시계의 차이는 0.1 s 이하여야 한다(chrony). 짝짓기는 `captured_at` 시각의 odom으로 하므로 전달 지연은 자세 정확도를 바꾸지 않는다. 그래서 lease는 1 s(`sighting_lease_s`)로 두고, D-488 3항·D-257 5항의 300 ms보다 길다. 이 값은 sighting 섭취 lease보다 클 수 없고, 크면 기동을 거절한다. odom `stamp`가 `now`보다 `max_odom_future_s`(0.5 s) 넘게 앞서면 버리고, 버린 수와 마지막 이유(`future`, `out_of_order`, `malformed`)를 출력 `odom_refused`·`odom_refused_reason`으로 보인다.
2. **품질 통과.** `min_quality` 기본 0.5다. `quality`가 없는 sighting은 통과한다.
3. **지도 프레임.** sighting의 `map_id`가 활성 현장 지도의 `map_id`와 같을 때만 받는다. 활성 지도가 없으면 모두 받는다. 걸러낸 수는 출력 `sightings_filtered_map_id`로 보인다. 활성 지도 `map_id`를 어떤 sighting 출처도 보고하지 않으면 기동 때와 그 지도가 활성화된 뒤 처음 읽을 때 경고 로그를 한 번 남긴다. 그래서 sighting 출처 설정의 `map_id`가 현장 지도 `map_id`와 같아야 한다. 앵커는 자기 `map_id`를 갖는다. 다른 `map_id`의 sighting이 오면 처음부터 다시 앵커하고, 앵커의 `map_id`가 활성 지도와 다르면 `DEGRADED`다.
4. **짝짓기.** odom은 보통 카메라보다 늦게 도착한다(hub 스냅숏은 최대 약 1 s 낡음). 그래서 sighting은 `captured_at` 순서의 대기열(최대 32건, 넘치면 가장 오래된 것부터 버림)에서 그 시각 이후의 odom 표본이 올 때까지 기다린다. 새 sighting이 기다리는 sighting을 밀어내지 않는다. 표본이 오면 순서대로 처리한다. 감싸는 두 표본의 간격이 `max_interp_gap_s`(1.2 s) 안이면 보간한다(yaw는 ±π를 넘어 보간). 그렇지 않으면 0.25 s 안의 가장 가까운 표본을 쓰고, 없으면 버린다. `max_odom_age_s`(3 s)보다 오래 기다린 sighting은 버린다. odom이 재설정되면(7항) 그 전에 찍힌 대기 sighting도 버린다.
5. **첫 앵커와 회복.** 첫 sighting은 `DEGRADED`로 앵커하고, 연속 2회 일치해야 `LOCALIZED`다. 회복도 같다. trip 시작에는 sighting 3건이 필요하다. 점프한 sighting은 0회로 세고 다시 앵커한다. 아래 6항의 한도를 넘긴 뒤 일치한 sighting은 1회로 센다. 횟수는 2에서 멈춘다.
6. **DEGRADED 한도.** 다리 길이 `dead_reckon_m` > 1.5 m, 앵커 뒤 누적 회전 > `max_bridge_turn_deg`(270°, sighting 없이 계획된 U턴 한 번은 견딘다), 앵커 나이 `anchor_age_s` > `max_anchor_age_s`(10 s), 점프(0.15 m 또는 20°, 방향은 ±π를 감아서 잰다) 중 하나면 `DEGRADED`다.
7. **odom 끊김과 재설정.** 다음 중 하나면 앵커를 버린다. 앞 표본과의 간격이 `max_odom_age_s`(3 s)를 넘을 때, odom이 낡아 `UNKNOWN`이 된 뒤 다시 올 때, 한 걸음이 `max_speed_mps`(1.0 m/s) × 간격 + 0.05 m보다 길 때, 방향 변화가 `max_turn_rate_dps`(360°/s) × 간격 + 0.1 rad보다 클 때다. 뒤의 둘은 CORE 재시작으로 odom이 0으로 돌아간 경우다. 다음 sighting으로 다시 앵커할 때까지 `UNKNOWN`이다.
8. **odom 주기.** 길이와 회전은 받은 표본 사이의 직선 길이와 |Δyaw|를 더한 값이다. 그래서 실제보다 작게 잰 하한이고, odom을 드물게 읽으면 더 작아진다. trip 루프(5항)는 실행 중인 로봇의 odom을 `refresh(robot_id, force_rest=True)`로 2 Hz 이상 읽는다. 이 호출은 hub 캐시를 건너뛰고 REST 상태를 읽는다. 같은 로봇의 동시 읽기는 하나로 합친다.
9. **hub 경로의 odom.** `StateSnapshot`에 `odom_pose`가 없는 동안 hub heartbeat는 그 필드를 버린다. 1·2항 브랜치(`feat/d491-robot-trip-contracts`)가 필드를 넣으면 hub 경로로도 들어온다. REST 스냅숏은 그대로 전달된다.
10. **API Ref 버전.** 작성 시점에 v1.112를 썼다. 7항 착지 순서에 따라 착지 때 다음 빈 번호로 다시 매긴다.
11. **읽기 엔드포인트.** 기본 `refresh`로 로봇 상태를 새로 읽는다(신선한 hub 스냅숏, 아니면 REST). 같은 로봇의 동시 읽기는 한 번으로 합치고, 마지막 odom이 0.2 s보다 새로우면 읽지 않는다. 읽기 실패는 기다리던 쪽이 취소돼도 회수해 기록한다. 로봇에 닿지 못하면(HTTP 오류 포함) 마지막 odom으로 답하고 3 s 뒤 `UNKNOWN`이 된다. `UNKNOWN`이면 `x`·`y`·`yaw`는 null이다. 모르는 로봇, 또는 읽는 사이 로스터에서 빠진 로봇은 404 `UNKNOWN_ROBOT`이다. 로스터에서 빠진 로봇의 상태는 버린다.

`trusted_map_pose`·`/route`·교통정리·D-395는 바꾸지 않았다. D-457 tracking은 입력이 아니다. 콘솔이 읽은 스냅숏을 map pose에 넘기다 실패해도 스냅숏 수집은 계속되고, 로그는 로봇마다 한 번 남긴다.

### 구현 부록 (2026-10-07) — 4항 교차로 동작
4항(CORE 교차로 동작 API)을 `feat/d491-core-junction-action`에서 구현하기 전에 오늘의 인식이 무엇을 주는지 조사했다. 결정 본문은 바꾸지 않는다.

**인식 조사 결과**

1. **CORE가 받는 차선 관측에는 분기 정보가 없다.** CORE line-follow의 입력 `line/observation`은 `{source, stamp, visible, error, confidence, ground?, quality?, containment?}`뿐이다(`middleware/perception/control/sensing/perception/lane.py` `line_observation_payload`, `middleware/core/gateway/core/bridge/observation.py`). 가지 후보, 가지 방향, 교차로 표시가 없다.
2. **교차로 판정은 keep 모드 keeper 안에만 있다.** `lane_keep_junction.py`는 `lane_corner_turning`이 켜졌을 때만 두 가지를 HOLD로 판정한다. 하나는 교차로 입구 `junction_transverse`다. 따르는 경계가 차로 밖으로 15° 넘게 꺾이고 가로선이 앞 0.45 m(`JUNCTION_AHEAD_M`) 안에서 진로를 가로지를 때다. 다른 하나는 갈래 `junction_fork`다. 같은 쪽 경계 둘이 30° 넘게 벌어질 때다. 이 판정은 CORE에 `visible=false`로만 간다. 이유 문자열은 `line/keep_debug`의 `reason`에만 있고, CORE는 그 토픽을 표시 전용 `LanePerceptionStore`로 받는다. 실기 기본값은 `lane_corner_turning: false`이므로 이 판정이 나오지 않는다.
3. **어느 가지가 왼쪽·직진·오른쪽인지는 아무도 내지 않는다.** `lane_topology.lane_hypotheses`의 `relation: left|right`는 나란한 옆 차로(표시용)이지 분기가 아니다. D-384 `road_state`의 가설과 `route_hint` 동점 깨기는 제어 경로가 읽지 않는 섀도다. `core_features.road_behaviour.choose_branch`는 `JunctionAhead.branches`를 받는 순수 함수지만 그 값을 채우는 생산 코드가 없다. sim의 `route_a`·`route_b`·`route_ab`는 launch 때 정한 lane_graph 경로와 odom으로 인식 노드 안에서 가지를 고르는 시제품이다. 읽기 전용 파라미터라 CORE가 실행 중에 바꿀 수 없고, 운영자 모드 목록(`OPERATOR_LANE_MODES`)에도 없다.
4. **결론.** 오늘의 인식은 CORE에 분기 후보를 하나도 주지 않는다. "교차로를 봤다"는 신호는 corner turning을 켠 keep 모드에서 표시 토픽의 `reason`으로만 있다.

**제어 설계(이 브랜치)**

1. **교차로 감지.** `line/keep_debug`의 `reason`이 `junction_transverse` 또는 `junction_fork`이고 카메라 시각이 `stale_after_s` 안이면 감지로 본다. CORE는 이 값을 멈추는 쪽으로만 쓴다. 움직임의 근거로는 쓰지 않는다. IR_LINE, keep이 아닌 카메라 모드, corner turning이 꺼진 keep 모드에서는 감지하지 못한다.
2. **교차로 앞 정지 거리.** 따로 설정을 두지 않는다. 감지가 곧 정지 근거이고, keeper가 감지하는 때는 가로선이 앞 0.45 m 안에 들어올 때다. CORE는 그 다음 틱(20 Hz)에 0을 낸다. keeper도 그 프레임부터 목표를 버리므로 기본 경로도 멈춘다.
3. **`straight`.** 받으면 `armed`이고 D-476 bridge route hint를 `straight`로 둔다. 감지되면 `executing`이 되고 기존 주행(keeper, D-476 bridge)을 그대로 둔다. 감지가 사라지면 지시를 다 쓴 것으로 보고 `idle`로 돌아가며 hint를 지운다. keeper가 교차로에서 목표를 버리므로 실제로 지나가려면 D-476 bridge(기본 꺼짐)가 켜져 있어야 한다. 꺼져 있으면 기존 손실 규칙(`lost_after_s` 뒤 LOST)을 따른다.
4. **`left`·`right`.** 가를 분기 후보가 없으므로 받는 즉시 `unresolved`로 두고 line-follow를 HOLD `junction_unresolved`로 멈춘다. 교차로까지 가지 않는다. corner turning이 꺼진 실기는 교차로를 보지 못하고 한쪽 경계를 따라 아무 가지로나 들어갈 수 있기 때문이다. 추측해서 꺾지 않는다. hint는 지시 방향으로 두며, D-476 bridge는 이 값에서 원래 움직이지 않는다.
5. **`stop`.** 받으면 `executing`이다. odom 이동 거리(D-468 PoseTrail, 0.3 s 안에 신선한 표본)가 `stop_after_m`에 닿으면 HOLD `junction_stop`이다. odom이 없거나 낡았거나 끊기면 거리를 증명할 수 없으므로 바로 멈춘다. HOLD는 다음 지시나 모드 변경까지 이어진다. `stop_after_m`은 0~2.0 m이고 `stop`에만 쓴다. 다른 동작과 함께 오면 400이다.
6. **지시 없음·만료.** 지시가 없거나 `armed` 지시가 만료된 채 교차로가 감지되면 `waiting`이고 HOLD `junction_waiting`이다. 감지가 깜빡여도 다음 지시나 모드 변경까지 풀지 않는다. 만료는 `armed` 지시에만 적용한다. 실행 중이거나 멈춘 지시는 만료로 풀리지 않는다.
7. **`junction_unresolved`의 뜻.** 지시는 받았지만 CORE가 지시한 가지를 인식으로 가려낼 수 없어서 멈췄다는 뜻이다. 오늘은 `left`·`right`가 항상 이 상태다.
8. **덮어쓰기와 수명.** 새 지시는 보관 중인 지시를 바꾸고 `junction_seq`를 하나 올린다. seq는 CORE 프로세스가 살아 있는 동안 계속 커진다. line-follow 모드가 바뀌면(OFF 포함) 지시와 감지 기록을 지운다.
9. **상태 표시.** `line_follow.junction {pending_action, place_id, state, seq}`이다. 교차로 정지는 `line_follow.state=HOLD`이고, 사유는 `junction_waiting`·`junction_unresolved`·`junction_stop` 중 하나다. 이미 `LOST`·`OFF`인 상태는 덮지 않는다. 응답은 `{accepted, junction_seq, state}`이다. `state`는 4항에 더한 필드다.
10. **seat.** D-460에 따라 CORE에는 seat 임대가 없다. 이 API의 "seat 보유자"는 `POST /api/v1/line-follow/hold`와 같은 기존 검사를 뜻한다. operator 토큰이어야 하고, 보정 lease(`require_calibration_owner`)를 넘어야 하며, 수동 조종이 풀려 있어야 한다.
11. **CORE 경계.** 지시는 기존 결정을 0으로 만들거나 그대로 둘 뿐이다. 새 움직임을 만들지 않고 모드를 바꾸지 않는다. 최종 `cmd_vel` 발행자는 그대로 CORE CommandManager다.

**한계**

- 실기 기본값(corner turning 꺼짐)에서는 교차로를 감지하지 못한다. 따라서 "지시 없는 교차로에서 멈춤"이 작동하지 않는다. 5항 trip 루프의 `lane` 간선은 이 한계가 풀리기 전에는 그 기본 안전 동작에 기댈 수 없다.
- 좌·우 회전 주행은 없다. 인식이 가지별 방향과 각도를 내는 계약(예 `branches [{direction, heading_deg, confidence}]`)을 새 ADR로 만들어야 한다. 그 전에는 4항의 "분기 후보 중 지시 방향과 가장 가까운 것"이 뜻을 갖지 못하며, Consequences의 SIM `lane` trip 완주는 좌·우 지시가 있는 경로에서 통과할 수 없다.
- 감지 입력은 표시 토픽 `line/keep_debug`를 정지 쪽으로만 다시 쓴 것이다. 감지 계약을 `line/observation`으로 옮길지는 위 분기 계약 ADR에서 함께 정한다.

### 구현 부록 (2026-10-07) — 5항 trip 루프

브랜치 `feat/d491-fleet-trip-loop`의 구현과 두 번의 검토(조정자 검토, 독립 검토)에서 정한 것이다. 결정 본문은 바꾸지 않는다. API Reference 행은 착지 순서대로 v1.116다(v1.112–v1.114는 1·2항, 3항, 4항이 먼저 썼다). CORE 쪽 동작은 4항 구현(`feat/d491-core-junction-action`의 `line_follow/junction.py`)을 기준으로 한다.

1. **trip id.** trip id는 `plan_id`다. 한 계획은 한 번만 출발한다(409 `TRIP_ALREADY_STARTED`). 상태 코드는 없는 계획·trip 404, `TRIP_BUSY`·`TRIP_ALREADY_STARTED`·`TRIP_NOT_RUNNING` 409, 나머지 시작 거절 422다. `/trip`의 `execute: true`는 계속 501이다. 출발은 언제나 이름 있는 운영자의 별도 호출이다.
2. **차선 로봇이 갈 수 없는 계획.** `TRIP_MODE_UNSUPPORTED`로 거절한다. 차로 중간에서 끝나는 `lane` trip(`LANE_END_NOT_A_PLACE`), `lane` U턴(`LANE_UTURN`), 150°를 넘는 회전(`LANE_TURN_TOO_SHARP`)이다. `lane` 간선이 하나라도 있으면 능력 `junction_turn: true`가 있어야 한다(`JUNCTION_TURN_UNSUPPORTED`). CORE의 교차로 판정은 keep 모드 증거가 살아 있을 때만 작동해서, 없으면 교차로에서 멈추지도 꺾지도 않는다(D-495). 실행 가능 규칙은 순수 모듈 `fleet/routing/execute.py`에 둔다.
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

### 구현 부록 (2026-10-07) — 6항 가르치기

브랜치 `feat/d494-fleet-teach-drive`. 6항을 순수 모듈 `operations/fleet/fleet/routing/teach.py`, 서비스 `server/teach_service.py`, 경로 `server/teach_routes.py`(`GET /api/fleet/teach`, `POST /api/fleet/teach/start`·`/stop`·`/confirm`·`/place`), 콘솔 `web/site-map-teach.js`(현장 지도 화면의 "지도 가르치기" 칸)로 구현했다. 결정 본문은 바꾸지 않는다. API Reference 행은 v1.119다(착지 때 다음 빈 번호로 다시 매긴다). 안전 파일 `console.py`는 고치지 않았다.

1. **기록.** 0.5 s마다 3항 `refresh(robot_id, force_rest=True)`로 로봇 상태를 REST로 한 번 읽고 `arbitrated_pose`를 본다. `LOCALIZED`이고 `dead_reckon_m` ≤ 0.5 m인 자세만, 마지막으로 남긴 점에서 0.1 m 이상 떨어졌을 때 남긴다. `DEGRADED`는 다리 길이와 상관없이 남기지 않는다(점프로 다시 앵커한 순간의 튐이 선에 들어가지 않게). 결정 본문의 "또는"을 이렇게 좁혔다(독립 검토). `UNKNOWN`과 좌표 없는 자세도 버린다. 한 기록은 최대 20000점(지도 전체 점 상한)이다.
2. **한 대.** 사이트에 기록은 하나다. 기록 중의 시작은 409 `TEACH_BUSY`다. 멈춘 기록은 확정을 기다리는 동안 여럿 있을 수 있고, 각각 `teach_id`로 확정한다. 확정 요청은 `robot_id`가 아니라 `teach_id`만 받는다(같은 로봇을 다시 가르칠 수 있어서다).
3. **시작과 주소 만들기의 위치 조건.** 시작과 "여기에 주소 만들기"는 자세가 `LOCALIZED`가 아니면 422 `TEACH_POSE_UNTRUSTED`(`detail.state`)다. 신뢰할 앵커 없이 시작한 기록은 첫 점부터 다리일 수 있어서다.
4. **멈춤.** RDP 허용 0.02 m, 거리는 현의 선분까지 잰다(시작과 끝이 같은 고리도 반대편을 남긴다). 반복형이라 긴 기록에서 재귀 한도에 걸리지 않는다. 점이 2개 미만이거나 길이가 0.10 m(`MIN_EDGE_M`) 이하면 422 `TEACH_TOO_SHORT`로 버린다. 끝마다 0.15 m 안의 기존 장소를 가까운 순으로 낸다. 비어 있으면 새 주소를 제안한다. 멈춤은 지도를 쓰지 않는다.
5. **확정.** 기준 지도는 초안, 없으면 활성 지도의 복사, 둘 다 없으면 빈 지도다. 끝 장소는 기존 장소 id 또는 `{name, kind}`(새 주소, 기본 `junction`)다. 기존 장소가 그 끝에서 0.15 m보다 멀면 422 `TEACH_PLACE_TOO_FAR`(선을 멀리 떨어진 장소로 잡아당기지 않는다), 없는 장소면 `TEACH_UNKNOWN_PLACE`다. 선의 양 끝은 장소 좌표로 고정하고, 그 장소에서 0.15 m 안에 있는 앞·뒤쪽 중간 점은 뺀다. 그래야 고정한 끝이 차로 끝 방향(접선)을 꺾지 않는다(독립 검토). 새 id는 `teach_eN`·`teach_pN`이다. 폭을 주지 않으면 0.185 m(가져오기 기본값)다. 저장은 `SiteMapStore.save_draft`를 그대로 탄다: 같은 `expected_revision` 규칙(409 `SITE_MAP_DRAFT_CHANGED`), 스키마 오류 422 `SITE_MAP_INVALID`(`detail.errors`), 2 MiB를 넘으면 413 `SITE_MAP_TOO_LARGE`. 거절된 확정은 기록을 남겨 다시 시도할 수 있다. 성공하면 그 기록을 지운다. 활성화는 기존 별도 단계다.
6. **수명.** 기록은 메모리에만 있고 재시작에서 사라진다. 멈춘 뒤 10분 안에 확정하지 않으면 버린다(404 `TEACH_UNKNOWN`). 기록 중인 세션은 10분 동안 새 점을 하나도 남기지 못했거나 20000점에 닿으면 스스로 멈춘다. 운영자 멈춤과 같은 길을 타며 이벤트의 주체는 `system:teach_idle`, `detail.reason`은 `idle`·`full`이다(운영자는 `operator`). 이렇게 멈춘 기록도 확정을 기다리고, 확정하지 않으면 멈춘 뒤 10분에 버린다. 0.1 m보다 짧으면 바로 버린다. 누구든 이름 있는 운영자가 멈출 수 있다(독립 검토).
7. **감사.** 시작·멈춤·확정·주소 만들기는 HTTP 감사와 함께 현장 지도 이벤트 `teach_started`·`teach_stopped`·`teach_confirmed`·`teach_place`로 남는다. 초안 저장은 기존 `draft_saved` 이벤트도 남긴다.
8. **콘솔.** 기록 중인 선과 마지막으로 멈춘 선을 지도 위에 점선(`series-secondary`)으로 1 s마다 그린다. 지도 범위는 지도의 장소·차로로 정하므로 지도 밖의 선은 잘린다. 활성 지도도 초안도 없으면 선이 보이지 않는다. 확정·주소 만들기는 초안에 저장되지 않은 수정이 있으면 막는다(먼저 저장). 새 끝 주소의 종류는 `junction`이고, 바꾸려면 기존 장소 편집 칸을 쓴다.
9. **로봇.** 가르치기는 로봇에 아무 명령도 보내지 않는다. 운전자는 Pilot으로 몬다. 운행(5항)과 섞이지 않는다.

### 개정 제안

- 2026-10-10 (fix/marker-loss-auto-relocalize, 적용): 6항 앵커 나이 한도와 회복(2회 일치)에서, 앵커 뒤 odom 길이 0.02 m 이하이고 회전이 2° 이하인 **서 있는 로봇**은 sighting 사이가 `max_anchor_age_s`보다 길어도 일치 횟수를 0으로 돌리지 않는다. 일치하는 sighting 두 번이면 `LOCALIZED`로 돌아온다. 현장 2026-10-10 `rosy_40`(주차, 마커가 8프레임에 1번 읽힘)은 그동안 `LOCALIZED`로 돌아오지 못했다. 움직인 로봇, 점프, odom 초기화(앵커를 버림) 규칙은 그대로다.
- [D-541](D-541-core-fleet-trip-lease.md) (2026-10-09, Proposed): 5항 trip 루프는 시작 전에 CORE trip lease를 열고 주기마다 늘리며, lease를 잃으면 명령 없이 `stopped(lease_lost)`로 끝나고 다시 열지 않는다. [D-540](D-540-fleet-console-structure-v2.md)(Proposed): 5항 "표시"의 자리는 관제 로봇 카드와 현장 지도 읽기 표시, 재계획 확인은 예외 큐 항목이다.
