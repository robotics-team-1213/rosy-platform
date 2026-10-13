## D-531 CORE가 지금 받아 둔 교차로·굽이·호 지시에서 경로 문맥을 만들어 `line/route_context`로 인식 keeper에 준다 — 문맥은 거부(HOLD 쪽)로만 쓰고, 없거나 낡으면 keeper는 main과 같다; B9 `bend_expected`는 이 통로로만 켜진다

**Status:** Proposed (2026-10-09). 사용자 결정(2026-10-09, "둘 다"): 지도 호 주행(D-520 단계 2, 다른 세션 진행 중)을 먼저 하고, 경로 문맥을 인식에 주는 일을 그 다음 단계로 한다. 방향은 사용자가 정했고 이 문안은 아직 승인되지 않았다. 구현·SIM·DEVICE 수용은 별도다.

잇는 결정: [D-507](D-507-lane-trip-leg-structure-and-site-floor.md)(교차로 지시 필드, 기대 창, 3항이 미룬 경로 문맥 통로, B9 구현 메모, 굽이 odom 통과 보충) · [D-520](D-520-map-guided-ring-arc-following.md)(ring 호 주행, `exit_segment`, 3항 "문맥 통로 필요 없음"의 범위) · [D-495](D-495-lane-junction-bounded-turn-and-junction-defaults.md)(재획득) · [D-494](D-494-fleet-trip-execution-m2-contracts.md)(교차로 지시 API) · [D-476](D-476-lane-loss-expected-road-bridge.md)(bridge 경로 힌트) · [D-364](D-364-lane-keeping-perception-and-replay-bench.md)(keeper, `line/keep_debug`) · [D-18](D-18-rosy-core.md)/D-143(CORE가 유일한 최종 `cmd_vel` 발행자) · [D-459](D-459-pinky-persistent-label-review-application.md)(사람 검수) · [D-400](D-400-core-safety-policy-off-shadow-enforce.md)(plan 3 전 enforce 금지, 그대로)

### Context

1. **D-507 3항이 미룬 일.** D-507은 "keeper에 경로 맥락(예 `line/route_context`)을 주는 계약은 굽이 오감지 수정 뒤에도 HOLD가 남을 때 따로 정한다"고 했다. 「검토한 대안」은 새 노드 간 계약이 필요하다는 이유로 이를 미뤘다. 그 조건이 이제 찼다.
2. **B9 게이트는 입력만 있고 켜는 통로가 없다.** `LaneKeeper.update(..., bend_expected=False)`(`lane_keep.py` 275행)가 B9 규칙 전부를 막고 있다. 기본값(거짓)에서 실물 라벨 434프레임(124745Z·133221Z, 픽스처 `b9_real_label_frames_main.json`)의 결정은 main과 0프레임 다르다. 게이트 켬(4cb87d467)은 90프레임이 다르고 HOLD → 주행 0, 주행 → HOLD 13이다. corner turning만으로 켠 B9는 장치 검토에서 HOLD → 주행 29프레임 중 맞은 것이 0이라 반려됐다(`docs/validation/lane-keep-bend-sim-2026-10-08/result.md`). 그래서 게이트는 "경로가 여기서 굽이를 기대한다"는 근거로만 켤 수 있다. D-507 B9 구현 메모가 빠진 것 다섯을 적었다: 굽이 장소 종류, CORE 지시 필드, CORE → 인식 통로, `line_observer_node` 배선, 굽이 앞 경계 공백. 앞의 둘은 D-507 굽이 보충(`bend` 지시, `bend_in_m`·`bend_tol_m`·`bend_radius_m`, 능력 `lane_bend`)이 채웠다. 남은 것이 통로와 배선이다.
3. **게이트 켬 SIM은 굽이 앞 공백을 넘지 못했다(0/6).** 그 공백은 D-507 굽이 보충의 CORE odom 통과가 넘겨받는다(남서 굽이 18/18 통과). 그래서 keeper의 B9는 굽이 자체를 달리는 수단이 아니다. 넘겨받기 앞 lead 창에서 굽이 사선을 L-모서리나 교차로로 오독하지 않는 것(`junction_fork` 0, `corner_*` 0)과, 호 끝 재획득에서 굽이 선을 차로 경계로 바르게 읽는 것이 B9의 몫이다.
4. **ring 실패(lap SIM 3, `docs/validation/lane-trip-lap-sim3-2026-10-09/result.md` 원인 4).** 출하 기본에서 12/12가 `ring_s`에서 차선을 잃었다. 섬 쪽 선은 ring 위 어느 프레임에서도 시야에 들어오지 않는다. 화면에 보이는 것은 끊긴 바깥선 현과 SE spoke의 나란한 두 경계(간격 0.185 m, 절대 방향 약 −70°)다. keeper는 그 spoke를 `both` 쌍으로 잡고 그쪽으로 갔다. 중심선 바깥 +0.059…+0.070 m(반폭 0.0925 m)까지 나간 뒤 IR `lane_edge_right` → `no_boundary` → D-407 후진으로 끝났다. 재생에서 같은 판단이 재현됐다. 일시 오류가 아니라 기하의 한계다. 지도 없이는 keeper가 "보이는 온전한 차로가 내 차로가 아니다"를 알 수 없다.
5. **D-520이 ring 위를 맡는다. 그러나 앞뒤 경계가 남는다.** D-520 호 주행 중에는 keeper 사유가 명령에 쓰이지 않는다(2항). 단계 2는 `paint_points_m`을 받아 CORE가 선을 고른다. 그래서 D-520 3항은 "문맥 통로가 필요 없다"고 했고, 그 범위에서는 맞다. 남는 곳은 셋이다. (a) 호를 열지 않는 경우: `arc_enabled: false`, `lane_arc` 능력 없음, `pivot_basis: stop_point`. (b) 호 끝에 `armed` 지시가 없어 오늘의 추종으로 돌아가는 경우(`nav.lane_arc_end_unarmed`). D-520은 이 경우의 바깥 흐름 0.026–0.070 m를 알려진 위험으로 남겼다. (c) 진출 spoke 재획득.
6. **CORE는 이미 필요한 값을 다 안다.** CORE에는 지금 받아 둔 지시(`armed`)가 있다. 그 지시는 `map_id`, 기대 창(`expect_in_m`·`expect_tol_m`·`pivot_past_line_m`), `lane_turn_deg`, `bend_in_m`·`bend_tol_m`·`bend_radius_m`·`turn_deg`, `exit_segment.curvature_1pm`을 담는다. CORE는 지시를 받은 뒤의 odom 전진 거리도 잰다(D-507 3항 주행 거리 창). 인식은 이 가운데 아무것도 모른다. 지금 CORE ↔ 인식 사이에는 인식 → CORE 방향(`line/observation`, `line/keep_debug`, `ros_bridge._on_lane_perception`)만 있다. CORE의 ROS 발행 가운데 `power/mode`는 이미 TRANSIENT_LOCAL로 latch된 String 토픽이다(`_LATCHED`).
7. **크기.** `control` 패키지는 한도 바로 아래다(D-520 Context 8). keeper·노드 쪽 추가는 P1a 분리(`docs/plans/2026-10-08-control-p1a-sensing-perception-split.md`)가 착지한 뒤의 크기 단위에서만 들어간다.

### Decision

1. **문맥의 내용(`rosy.route_context/1`).** keeper가 받는 것은 "앞에 무엇이 어디쯤 있고, 차로가 어느 쪽으로 얼마나 휘는가"다. Fleet 지도 좌표나 기하를 그대로 주지 않는다. CORE가 지금 자세 기준으로 풀어서 준다.

   | 필드 | 뜻 | 출처(지시) |
   |---|---|---|
   | `v` | 1 | — |
   | `seq`, `place_id`, `map_id` | 이 문맥을 만든 지시 | 지시 |
   | `stamp_s`, `valid_until_s` | CORE ROS 시계(sim 시간 포함) 기준 만든 시각과 만료 | CORE |
   | `kind` | 현재 구간의 종류: `junction`, `bend`, `ring` | `left`·`right`·`straight`(창 있음) → `junction`; `bend` → `bend`; 실제 D-520 호가 `running`인 동안만 `ring`. `exit_segment`가 있어도 호 시작 전 접근 차로는 `junction` |
   | `ahead_m` | `[lo, hi]`: 지금 자세에서 그 장소의 기대 가로선(`junction`) 또는 호 시작점(`bend`)까지 차로를 따른 거리의 창 | `expect_in_m − pivot_past_line_m − 전진 거리 ± expect_tol_m`, `bend_in_m − 전진 거리 ± bend_tol_m`. 창이 없는 지시는 이 필드 없음 |
   | `bend_phase` | 굽이 진입 뒤 `bending` 또는 차선 재획득 중 `reacquiring`. 이때 접근 거리 `ahead_m` 대신 보낸다 | CORE 굽이 상태. `kind: bend`일 때만 |
   | `lane_turn_deg` | 장소까지 차로의 방향 변화(왼쪽 +) | `lane_turn_deg`(straight), `turn_deg`(bend) |
   | `curvature_1pm` | 지금 달리는 차로의 부호 있는 곡률(왼쪽 +). `ring`일 때만 | `exit_segment.curvature_1pm` |

   - **spoke를 이름으로 지우지 않는다.** "무시할 차로"를 방향 목록으로 보내지 않는다. 그 목록은 map → odom 방향 변환과 그 오차를 keeper가 지게 한다. 대신 keeper가 `curvature_1pm`이나 `lane_turn_deg`에서 기대 접선을 만들고, 그 접선과 맞지 않는 경계 쌍을 버린다(4항). spoke는 ring에서 반지름 방향으로 나가므로 기대 접선의 반대쪽으로 꺾인다. lap SIM 3 rec_01의 SE spoke 두 경계는 로봇 진행 방향에서 오른쪽 −14°·−20°였다. 같은 자리의 기대 접선은 왼쪽 +κ·x이고, x 0.15 m에서 약 +34°다. D-520 3항 spoke 거르기와 같은 근거다. 30° 문턱은 SIM에서 다시 정한다.
   - **새 Fleet 필드는 없다.** 문맥은 모두 지금 지시 필드에서 나온다. API reference는 지시 쪽이 아니라 상태 쪽(5항)만 판 올림한다.

2. **통로: ROS 토픽 `line/route_context`, CORE가 발행.** 파라미터가 아니다. 값은 지시와 odom 전진 거리에 따라 매 틱 바뀌고, 파라미터 서비스는 시각과 만료를 실을 수 없다.
   - 메시지는 `std_msgs/String` JSON이다. `line/keep_debug`와 같은 방식이고, 스키마는 `core_common/protocol`에 둔다.
   - QoS는 RELIABLE, KEEP_LAST 1, **VOLATILE**이다. 문맥은 latch하지 않는다. 다시 뜬 `line_observer_node`가 이미 끝난 지시의 문맥을 받는 일을 통로 수준에서 없앤다. 만료가 있어도 그렇게 한다. `power/mode`의 `_LATCHED`는 쓰지 않는다.
   - 발행 주기: 문맥이 있는 동안 5 Hz(`ROUTE_CONTEXT_PERIOD_S` 0.2 s), 그리고 지시 상태가 바뀌는 틱마다 한 번. 문맥이 없어지는 틱(지시 `done`·`aborted`·만료, 모드 변경, odom 끊김·epoch 변경, E-stop)에는 `{"v": 1, "seq": null}`을 한 번 보낸다. 받은 쪽은 그때 바로 버린다. 그 메시지를 놓쳐도 아래 만료가 같은 일을 한다.
   - 발행자는 CORE gateway(`ros_bridge`)다. 인식은 이 토픽을 읽기만 한다. 이 토픽은 정보이고 명령이 아니다. CORE는 그대로 유일한 최종 `cmd_vel` 발행자다(D-18, D-143). 인식은 `cmd_vel`을 계속 읽기만 한다.
   - 설정 `line_follow.route_context_enabled`(기본 false). 꺼져 있으면 CORE는 이 토픽을 만들지 않는다.

3. **신선도와 만료. 문맥이 없으면 keeper는 main과 같다.** keeper는 프레임마다 다음을 모두 만족하는 문맥만 쓴다. 하나라도 어기면 그 프레임은 문맥 없음이다.
   - 영상 원본 시각이 `stamp_s` 뒤 0.5 s(`ROUTE_CONTEXT_STALE_S`, 발행 주기 2.5배) 안이고 `valid_until_s` 앞이다. D-507 8항 `SOURCE_FUTURE_TOLERANCE_S`(0.1 s)보다 미래인 `stamp_s`는 버린다.
   - `valid_until_s − stamp_s ≤ 1.0 s`. CORE는 지시의 만료(`expires_s`)보다 늦은 값을 쓰지 않는다.
   - `seq`가 null이 아니고, 스키마 검사(범위: `ahead_m` 각 값 [−0.5, 2.0], lo ≤ hi; |`lane_turn_deg`| ≤ 360; 0.5 ≤ |`curvature_1pm`| ≤ 5.0)를 통과한다. 어기면 그 메시지 전체를 버리고 마지막 문맥도 지운다.
   - **문맥 없음 = main.** 결정·사유·목표·`junction_ahead_m`이 main keeper와 비트 단위로 같다. 달라지는 것은 `line/keep_debug`에 붙는 진단 필드 `route_context_seq`(null)와 `route_context_v: 1`뿐이다. 이것이 실패 방식이다. 통로가 끊기거나 CORE가 꺼지거나 노드가 다시 떠도 keeper는 오늘의 keeper다.
   - **CORE 쪽 되맞춤.** keeper는 그 프레임에 쓴 문맥의 `route_context_seq`를 `line/keep_debug`와 `line/observation`에 싣는다. CORE는 마지막 발행 seq가 아니라 콜백 시점 현재 지시 또는 실제 달리는 호의 seq와 비교한다. null이 아닌 값이 다르면 카메라 관측을 `invalid_observation`으로 무효화해 즉시 HOLD하고 그 프레임의 교차로 감지는 받지 않는다. 끝난 지시의 문맥으로 내린 판단으로는 움직이지 않는다.

4. **keeper에서의 쓰임: 거부로만.** 문맥은 keeper가 이미 할 수 있는 판단을 좁힌다. 새 주행을 만들지 않는다.
   - (a) **B9 게이트.** `bend_expected = (kind == 'bend' and ahead_m이 [0, JUNCTION_AHEAD_M + BEND_LEAD_M]과 겹침) or (CORE 굽이 상태가 bending·reacquiring임을 문맥이 실음)`. 상수는 keeper `JUNCTION_AHEAD_M` 0.45 m와 D-507 굽이 보충 `BEND_LEAD_M` 0.25 m다. corner turning이 꺼져 있으면 지금처럼 게이트도 꺼진다. 이것이 D-507 B9 구현 메모 (3)·(4)의 배선이다. 굽이 앞 공백((5))은 D-507 굽이 보충의 CORE 넘겨받기가 맡는다. 이 ADR은 keeper가 공백에서 달리게 하지 않는다. `bend_ahead`의 "차로 쪽 경계가 없으면 HOLD"는 그대로다.
   - (b) **곡률 맞지 않는 경계 쌍 버리기(`ring`, 그리고 `lane_turn_deg`가 있는 `junction` 창 안).** 기대 접선은 x만큼 앞에서 `curvature_1pm·x`(ring) 또는 창 안의 `lane_turn_deg` 방향 쪽(junction)이다. keeper의 경계 후보 가운데 방향이 기대 접선과 30°(`ROUTE_TANGENT_GATE_DEG`) 넘게 다른 것은 차로 경계 후보에서 뺀다. 남은 후보로 오늘 규칙을 그대로 돌린다. 남은 것이 없으면 오늘과 같은 `no_boundary`다. 결과는 둘뿐이다. 같은 결정이거나, 주행이 HOLD로 바뀌는 것이다. ring에서 SE spoke 쌍(`both`)은 이 규칙으로 빠지고, 그 프레임은 바깥으로 가는 대신 HOLD → 손실 경로로 간다.
   - (c) **교차로 사유는 창 밖에서 바꾸지 않는다.** `junction_*` 판정은 문맥이 있어도 그대로 낸다. 창 안·밖 판정은 지금처럼 CORE가 한다(D-507 3항). keeper가 창 밖이라고 교차로를 지우지 않는다.
   - 문맥이 바꾼 프레임은 `line/keep_debug`에 `route_context_effect`(`bend_rules`, `boundary_vetoed` 수)를 싣는다. 재생과 SIM 분석이 이 값으로 바뀐 프레임을 센다.

5. **CORE 쪽 상태와 출력.**
   - `line_follow.route_context`에 지금 발행 중인 문맥(또는 null)과 마지막 발행 시각을 보인다. 능력 `route_context: true`는 설정이 켜져 있을 때만이다. Fleet은 이 능력으로 아무것도 바꾸지 않는다. 관제 화면과 기록용이다.
   - D-520 호 주행 중(`line_follow.arc.state: running`)에도 문맥은 `ring`으로 나간다. 그러나 호 주행 중 keeper 사유는 지금처럼 명령에 쓰이지 않는다(D-520 2항). 호가 끝나 오늘의 추종으로 돌아가는 경우(Context 5 (b))와 진출 재획득(c)에서 4항 (b)가 처음으로 일을 한다.
   - D-476 bridge 경로 힌트(`set_bridge_route_hint`)는 바꾸지 않는다. 문맥은 bridge에 들어가지 않는다.
   - API reference 판 올림: 상태 `line_follow.route_context`, 능력 `route_context`, 토픽 `line/route_context`, `line/keep_debug`·`line/observation`의 `route_context_seq`·`route_context_effect`.

6. **실물 프레임 안전 규칙.**
   - **게이트 끔 = main.** 실물 라벨 434프레임을 문맥 없이 재생하면 main과 0프레임 다르다. 지금 `test_real_frames_without_a_bend_expected_decide_as_main`이 지키는 것을 문맥 없음 경로 전체(노드의 문맥 수신·만료 포함)로 넓힌다.
   - **문맥 켬에서 HOLD → 주행은 독립 검증 없이 0.** 같은 434프레임에 합성 문맥(`bend` 창 전체, `ring` κ ±3.98, `junction` `lane_turn_deg` ±60)을 넣어 재생한다. 프레임마다 main과 비교해 넷으로 센다. 같음, 주행 → HOLD(허용, 닫힌 쪽 실패), HOLD → 주행, 주행 → 다른 주행(목표 차가 0.01 m 넘음). 뒤의 둘은 독립 검증자가 그 프레임을 따라가도 되는 차로라고 확인하기 전에는 0이어야 한다. 독립 검증자는 이 코드의 작성자가 아니다. 사람 검수(D-459 Pinky 검수 앱의 프레임 판정), SIM 참값 자세, 또는 Rosy Cam 천장 자세다. 검증 기록은 `docs/validation/`에 프레임 id와 판정자로 남긴다. B9 4cb87d467의 게이트 켬 결과(HOLD → 주행 0, 주행 → HOLD 13)가 지금의 기준선이다.
   - 이 규칙은 시험으로 고정한다. 문맥 규칙을 바꾸는 커밋이 434프레임 재생에서 HOLD → 주행이나 주행 → 다른 주행을 하나라도 만들면 시험이 실패한다. 독립 검증을 받은 프레임만 픽스처의 허용 목록에 이름으로 들어간다.

7. **단계와 브랜치.** 한 브랜치에 한 주제다(D-372). D-520 단계 2가 먼저 착지한다(사용자 결정). P2는 P1a 크기 분리 뒤다.

   | 단계 | 브랜치 | 무엇 | 끝난 기준 |
   |---|---|---|---|
   | P0 | `docs/route-context-lane-keeper` | 이 ADR | 사용자 승인 |
   | P1 | `feat/route-context-core-publish` | CORE: 스키마(`core_common/protocol`), 지시 → 문맥 계산, 발행(VOLATILE, 5 Hz, 비움 메시지), 설정, 상태·능력, `route_context_seq` 되맞춤 | SOURCE 1–3 |
   | P2 | `feat/route-context-keeper-input` | perception: 노드 구독·신선도·만료, `LaneKeeper.update(route_context=...)`, B9 `bend_expected` 배선(4 (a)), keep_debug 진단 | SOURCE 4–5, 434프레임 게이트 끔 = main |
   | P3 | `fix/keeper-route-tangent-veto` | keeper: 곡률 맞지 않는 경계 쌍 버리기(4 (b)) | SOURCE 6, 434프레임 HOLD → 주행 0 |
   | P4 | `docs/route-context-sim` | 모델 PC SIM 기록 | SIM 합격선 |
   | P5 | — | DEVICE(사용자 승인) | DEVICE 합격선 |

   P1은 keeper를 바꾸지 않으니 먼저 착지해도 동작이 같다. P2 착지 뒤에도 `route_context_enabled` 기본 false라 출하 동작은 같다.

8. **수용.**
   - **SOURCE.**
     1. 지시 → 문맥: 지시 종류별 `kind`, `ahead_m`(전진 거리 반영, D-468 역추적처럼 뒤로 간 거리는 빼서 창이 늘어남), `lane_turn_deg`, `curvature_1pm`. 창 없는 지시는 `ahead_m` 없음. 설정 꺼짐이면 토픽 없음.
     2. 비우기: `done`·`aborted`·만료·모드 변경·odom epoch 변경·E-stop 틱에 `seq: null` 한 번. QoS가 VOLATILE·RELIABLE·depth 1임을 `test_bridge_timers`처럼 고정.
     3. 되맞춤: 다른 `seq`를 실은 관측은 CORE가 `invalid_observation`으로 무효화한다. 마지막 발행 seq와 현재 지시 seq가 다른 전환 구간, 호 시작 전 `exit_segment`가 있는 지시, null 입력을 시험한다.
     4. keeper 신선도: 낡음(0.5 s), 만료, 미래 시각, 범위 밖, `seq` null, 스키마 위반 각각에서 결정이 main과 비트 단위로 같음.
     5. B9 배선: `bend` 창 안에서만 `bend_expected` 참, corner turning 끔이면 거짓, 창 밖·다른 kind에서 거짓.
     6. 곡률 거르기: 합성 ring 프레임(바깥선 현 + SE spoke 두 경계)에서 spoke 쌍이 빠지고 결정이 HOLD 또는 바깥선 기반이 됨. 곧은 차로 프레임에 `ring` 문맥을 주면 주행 → HOLD만 생기고 HOLD → 주행 0.
     7. 실물 434프레임: 6항 두 규칙.
     8. 구조: 인식 패키지에 `cmd_vel` 발행자 없음(기존 아키텍처 시험), `line/route_context` 발행자는 CORE gateway 하나.
   - **SIM(모델 PC, 이 노트북 아님).**
     - 남서 굽이 lap(D-507 굽이 보충 하네스)을 `route_context_enabled: true`로: 굽이 통과가 18/18 기준보다 나빠지지 않음, lead 창 안 `junction_fork`·`corner_*`·`flipping` 0, 넘겨받기 뒤 spoke `flipping` LOST가 기준(4/18)보다 늘지 않음. `sitecustomize.py`의 전역 `bend_expected` 대신 실제 통로를 쓴다.
     - ring lap(lap SIM 3 하네스, `arc_enabled: false`): ring 위에서 중심선 바깥 최대 Δr ≤ 0.05 m(오늘 0.059–0.070), SE spoke 쪽 `both` 추종 0, IR `lane_edge_right` 0. 차선을 잃는 것은 허용한다. 바깥으로 흐르는 대신 HOLD로 서는지가 합격선이다. ring 통과를 이 단계 합격으로 요구하지 않는다(ring 통과는 D-520의 몫).
     - ring lap(`arc_enabled: true`, D-520 단계 2 착지 뒤): D-520 단계 2 SIM 합격선이 문맥 켬에서도 그대로. 호 끝 지시 없는 run을 일부러 만들어 오늘의 추종으로 돌아갈 때 바깥 흐름이 문맥 끔보다 작음.
     - 문맥 통로를 run 중간에 끊는 run 3회: 끊긴 뒤 0.5 s 안에 keep_debug `route_context_seq`가 null이 되고 결정이 main 규칙으로 돌아옴.
   - **DEVICE(9dfk 또는 8kcn, 사용자 승인, P4 합격 뒤).**
     - 먼저 오프라인: 실기 기록 세션(260919 굽이·ring 구간)을 합성 문맥으로 재생해 6항 집계를 낸다. HOLD → 주행 프레임이 있으면 D-459 사람 검수 전에는 주행하지 않는다.
     - 그 다음 Fleet trip 주행: 남서 굽이와 ring 진입·진출. D-507 9항 선언, IR 가드, D-422 그대로. 판정은 odom이 아니라 LiDAR 벽 정합 또는 Rosy Cam 천장 자세로 한다. 합격선은 SIM과 같다.

### 범위 밖

- keeper가 spoke나 섬 선을 직접 추종하게 하는 모형 변경(직선 현 모형 자체의 교체). ring 위 주행은 D-520이다.
- 문맥으로 HOLD를 주행으로 바꾸는 규칙(예: 기대 창 안에서만 `bend_ahead` 직진 허락). 6항의 독립 검증을 거친 별도 결정으로만 더한다.
- Fleet 지시 API 필드 추가, 장소 종류 추가. D-476 bridge, D-468 복귀, D-400 enforce 변경.
- `line/observation`으로 교차로 판정 옮기기(D-495 4항 후속).

### 검토한 대안

- **파라미터(`bend_expected`를 노드 파라미터로 CORE가 set).** 시각·만료가 없고, 서비스 호출이 실패하면 마지막 값이 남는다. 실패가 열린 쪽이다.
- **TRANSIENT_LOCAL latch(D-507 B9 메모의 예).** 다시 뜬 노드가 끝난 지시의 문맥을 받을 수 있다. 만료로 막을 수 있지만 VOLATILE + 주기 발행이 더 단순하고 닫힌 쪽이다.
- **Fleet이 인식에 직접 주기.** Fleet은 ROS에 없고 로봇의 odom 전진 거리를 모른다. 지도 자세 오차가 그대로 들어온다. 지시를 받아 odom으로 푸는 CORE가 맞는 자리다.
- **무시할 spoke의 방향 목록을 보내기.** map → odom 방향 변환과 그 오차가 인식으로 간다. 곡률·방향 변화에서 기대 접선을 만들어 거르는 쪽이 같은 일을 지시 필드만으로 한다. 안쪽 갈래가 있는 지도에서 이것이 부족하면 그때 더한다.
- **keeper에 지도(lane graph)를 주기.** 인식이 지도 버전·`map_id`·자세를 모두 알아야 한다. CORE가 지도를 모르는 구조(D-507 Context 5)와 어긋난다.
- **D-520 단계 2의 `paint_points_m`만으로 충분하다고 보기.** 호 주행 중에는 그렇다. 호를 열지 않는 로봇, 호 끝 지시 없음, 진출 재획득, 굽이 lead 창은 keeper가 그대로 달리거나 판단한다. 그 자리의 오독은 남는다.
- **corner turning을 게이트로 쓰기.** 장치 기본으로 켜져 있어 게이트가 되지 않는다. 장치 검토가 반려했다(Context 2).
- **문맥을 keep 규칙에 섞지 않고 CORE가 keep_debug를 사후에 거르기.** CORE는 keeper의 후보 경계를 다시 계산할 수 없다. spoke 쌍을 뺀 뒤 남은 후보로 다시 고르는 일은 keeper 안에서만 된다.

### Consequences

- CORE → 인식 방향의 첫 통로가 생긴다. 정보 토픽이고 명령이 아니다. CORE는 그대로 유일한 최종 `cmd_vel` 발행자다.
- B9 `bend_expected`가 실제 경로 근거로만 켜진다. SIM의 `sitecustomize.py` 전역 켬은 이 통로가 대신한다.
- 문맥은 거부로만 쓰이므로, 문맥 켬의 새 실패는 HOLD가 늘어나는 쪽이다. ring에서는 바깥으로 흐르던 run이 일찍 서게 된다. trip 완료율은 그 자체로 오르지 않는다.
- 통로가 끊기거나 꺼져 있으면 오늘과 같다. 출하 기본은 꺼짐이다.
- keeper와 노드 크기가 늘어난다. P2·P3는 P1a 분리 뒤다.

### 남은 물음

- 문맥 통로 QoS를 VOLATILE로 둔 것(2항)에 동의하는지.
- spoke 방향 목록 대신 기대 접선 거르기(1항, 4 (b))로 시작해도 되는지.
- 6항의 독립 검증자로 D-459 사람 검수와 SIM 참값 가운데 무엇을 기본으로 할지. 실물 프레임은 사람 검수 말고는 참값이 없다.
- P3 곡률 거르기를 `junction` 창 안(`lane_turn_deg`)까지 넓힐지, ring(`curvature_1pm`)만으로 시작할지.
- DEVICE 뒤 `route_context_enabled`를 로봇 기본으로 켤 조건.
