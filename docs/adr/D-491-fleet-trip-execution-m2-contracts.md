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

### 구현 부록 (2026-10-07)

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
