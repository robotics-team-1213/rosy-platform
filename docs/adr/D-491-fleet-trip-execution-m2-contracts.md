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

### 구현 부록 (2026-10-07) — 3항 map pose

브랜치 `feat/d491-fleet-map-pose`. 3항을 `operations/fleet/fleet/localization/map_pose.py`(순수, 표준 라이브러리만)와 `server/map_pose_service.py`(`arbitrated_pose`, `GET /api/fleet/robots/{robot_id}/map-pose`, viewer 이상)로 구현했다. 독립 검토(REQUEST CHANGES) 반영 뒤의 규칙이다. 설정은 사이트 YAML `fleet.map_pose`다.

1. **시계와 sighting 신선도.** `odom_pose.stamp`는 UTC epoch 초(float)이고 `captured_at`과 같은 형식이다. CORE가 odom을 받을 때 벽시계로 찍는다(ISO 문자열도 읽는다). 로봇 시계와 사이트 시계의 차이는 0.1 s 이하여야 한다(chrony). 짝짓기는 `captured_at` 시각의 odom으로 하므로 전달 지연은 자세 정확도를 바꾸지 않는다. 그래서 lease는 1 s(`sighting_lease_s`)로 두고, D-488 3항·D-257 5항의 300 ms보다 길다. 이 값은 sighting 섭취 lease보다 클 수 없고, 크면 기동을 거절한다. odom `stamp`가 `now`보다 `max_odom_future_s`(0.5 s) 넘게 앞서면 버리고, 버린 수와 마지막 이유(`future`, `out_of_order`, `malformed`)를 출력 `odom_refused`·`odom_refused_reason`으로 보인다.
2. **품질 통과.** `min_quality` 기본 0.5다. `quality`가 없는 sighting은 통과한다.
3. **지도 프레임.** sighting의 `map_id`가 활성 현장 지도의 `map_id`와 같을 때만 받는다. 활성 지도가 없으면 모두 받는다. 그래서 sighting 출처 설정의 `map_id`가 현장 지도 `map_id`와 같아야 한다. 앵커는 자기 `map_id`를 갖고, 다른 `map_id`의 sighting이 오면 처음부터 다시 앵커한다.
4. **짝짓기.** 감싸는 두 odom 표본의 간격이 `max_interp_gap_s`(1.2 s, 1 Hz heartbeat 포함) 안이면 보간한다(yaw는 ±π를 넘어 보간). 감싸는 표본이 아직 올 수 있는 동안(`이전 표본 시각 + max_interp_gap_s` 전) sighting은 기다린다. 그 뒤에는 0.25 s 안의 가장 가까운 표본을 쓰고, 없으면 버린다. 기다리는 sighting은 `max_odom_age_s`(3 s)보다 낡으면 버린다.
5. **첫 앵커와 회복.** 첫 sighting은 `DEGRADED`로 앵커하고, 연속 2회 일치해야 `LOCALIZED`다. 회복도 같다. trip 시작에는 sighting 3건이 필요하다. 점프한 sighting은 0회로 세고 다시 앵커한다. 아래 6항의 한도를 넘긴 뒤 일치한 sighting은 1회로 센다. 횟수는 2에서 멈춘다.
6. **DEGRADED 한도.** 다리 길이 `dead_reckon_m` > 1.5 m, 앵커 뒤 누적 회전 > `max_bridge_turn_deg`(180°), 앵커 나이 `anchor_age_s` > `max_anchor_age_s`(10 s), 점프(0.15 m 또는 20°, 방향은 ±π를 감아서 잰다) 중 하나면 `DEGRADED`다.
7. **odom 끊김과 재설정.** 앞 표본과의 간격이 `max_odom_age_s`(3 s)를 넘거나, odom이 낡아 `UNKNOWN`이 된 뒤 다시 오거나, 한 걸음이 `max_speed_mps`(1.0 m/s) × 간격 + 0.05 m보다 길면(CORE 재시작으로 odom이 0으로 돌아간 경우) 앵커를 버린다. 다음 sighting으로 다시 앵커할 때까지 `UNKNOWN`이다.
8. **odom 주기.** 길이와 회전은 받은 표본 사이의 직선 길이와 |Δyaw|를 더한 값이다. 그래서 실제보다 작게 잰 하한이고, odom을 드물게 읽으면 더 작아진다. trip 루프(5항)는 실행 중인 로봇의 odom을 2 Hz 이상으로 읽어야 한다(`refresh` 또는 heartbeat).
9. **hub 경로의 odom.** `StateSnapshot`에 `odom_pose`가 없는 동안 hub heartbeat는 그 필드를 버린다. 1·2항 브랜치(`feat/d491-robot-trip-contracts`)가 필드를 넣으면 hub 경로로도 들어온다. REST 스냅숏은 그대로 전달된다.
10. **API Ref 버전.** 작성 시점에 v1.112를 썼다. 7항 착지 순서에 따라 착지 때 다음 빈 번호로 다시 매긴다.
11. **읽기 엔드포인트.** 읽을 때 로봇 상태를 새로 읽는다(신선한 hub 스냅숏, 아니면 REST). 같은 로봇의 동시 읽기는 한 번으로 합치고, 마지막 odom이 0.2 s보다 새로우면 읽지 않는다. 로봇에 닿지 못하면(HTTP 오류 포함) 마지막 odom으로 답하고 3 s 뒤 `UNKNOWN`이 된다. `UNKNOWN`이면 `x`·`y`·`yaw`는 null이다. 모르는 로봇, 또는 읽는 사이 로스터에서 빠진 로봇은 404 `UNKNOWN_ROBOT`이다. 로스터에서 빠진 로봇의 상태는 버린다.

`trusted_map_pose`·`/route`·교통정리·D-395는 바꾸지 않았다. D-457 tracking은 입력이 아니다. 콘솔이 읽은 스냅숏을 map pose에 넘기다 실패해도 스냅숏 수집은 계속되고, 로그는 로봇마다 한 번 남긴다.
