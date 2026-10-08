## D-520 곡률을 아는 차로 구간(회전교차로 ring)에서는 CORE가 지도의 호(ω = v·κ)를 주 명령으로 달리고, 카메라는 바깥선을 원으로 맞춰 옆 보정만 준다 — 구간 기하는 D-507 교차로 지시에 실어 보내고, IR 가드와 D-422가 지킨다

**Status:** Accepted (2026-10-08, 사용자 확정, 독립 비평 2회 반영. 구현·SIM·DEVICE 수용은 별도). **개정 2026-10-09**(사용자 결정 "둘 다"): ring은 호 주행이 기본이고, 호는 odom에 놓은 지도 원을 따른다. 장치는 SIM 합격과 DEVICE 체크리스트 뒤다(맨 끝 「개정 2026-10-09」). 사용자 결정(2026-10-08, D-507 SIM 3–4c차 원인 분석 뒤):
- 곡률을 아는 구간(ring)에서는 CORE가 지도 호를 주 명령으로 달린다(angular = v·κ, feed-forward).
- 카메라는 바깥선을 호로 맞춰 옆 보정을 준다.
- IR 가드와 D-422 몸체 정지가 지킨다.
- 단계 1은 feed-forward만(SIM에서 흐름 측정), 단계 2가 호 맞춤 보정이다.

사용자 답(2026-10-08, 초안의 물음 1–4):
- 1항 계약은 교차로 지시의 `exit_segment`로 **결정**한다.
- 구간 끝에 `armed` 지시가 없으면 오늘의 추종으로 돌아가는 것으로 **결정**한다(2항).
- 호 주행 중 IR `left`·`right`는 곧바로 멈추지 않고 **한 번 반대쪽으로 보정**한다(2항 「IR 한 번 보정」).
- 단계 1·2 합격선은 초안대로 **결정**한다(7항).

구간 중간(ring 위) 시작은 아직 답이 없어 범위 밖으로 둔다. 상태 이름, 기본값과 「SIM으로 정할 값」은 구현·SIM에서 정한다. Status는 Proposed 그대로다.

잇는 결정: [D-507](D-507-lane-trip-leg-structure-and-site-floor.md)(구간 상태 기계, 교차로 지시 필드, `motion_admitted`, 현장 바닥 선언) · [D-476](D-476-lane-loss-expected-road-bridge.md) 개정 2(명령 곡률로 잇는 호 bridge, 가장 가까운 친척) · [D-468](D-468-local-lane-departure-return.md)(이탈 복귀) · [D-491](D-491-ir-guard-crosswalk-zone.md)(IR 가드) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md)(몸체 기준 정지) · [D-18](D-18-rosy-core.md)(CORE가 유일한 최종 `cmd_vel` 발행자) · [D-489](D-489-fleet-route-planning-concept-and-algorithm.md)/[D-490](D-490-fleet-route-planner-implementation.md)/[D-494](D-494-fleet-trip-execution-m2-contracts.md)(Fleet 경로·trip) · [D-500](D-500-measured-motion-response-and-clearance-budget.md)(측정한 운동 응답, 카펫 odom yaw) · [D-400](D-400-core-safety-policy-off-shadow-enforce.md)(plan 3 전 enforce 금지, 그대로) · [D-517](D-517-multi-robot-lane-traffic.md)(통행권 끝에서 정지)

### Context

1. **ring 기하.** 260919 회전교차로(`map_v2_fleet/lane_graph.yaml`)의 차로 중심선 반지름은 약 0.2514 m(κ ≈ 3.98 1/m, 반시계 일방)다. 섬 쪽 선은 r 0.155 m, 바깥선은 r 0.345 m이고 두 선 중심 사이는 0.19 m다. spoke 입구 네 곳(장소 SW·SE·NE·NW)에서 바깥선이 끊긴다. 장소 사이 호는 `ring_s`·`ring_w` 0.3739 m, `ring_n` 0.3722 m(약 85°), `ring_e` 0.4595 m(약 105°)다.
2. **카메라는 섬 쪽 선을 차로 안에서 보지 못한다.** ring 위 keep 프레임(`X:\DevTemp\ring-diag`, `runs_r3`·`r4`·`r4c`의 `keepgeo.jsonl`을 참값 자세로 다시 본 것)에서 섬 쪽 선은 시야 밖이다. SIM 기울기 8°에서도, 실기 pitch 11.8°에서도 그렇다. 바깥선은 호 약 52°(base_link x 0.14–0.335 m)에서 보이고 로봇 진로를 가로지른다.
3. **직선 현 keeper는 ring을 따라가지 못한다.** `lane_keep.py`의 `extract_lines`는 선을 직선 조각으로 뽑고 30° 안에서 평행한 둘을 짝짓는다. ring에서 keeper는 바깥선의 가파른 현 하나를 얻는데 그 현이 차로 어느 쪽인지가 모호하다. 그 현을 네 입구로 보이는 spoke 선과 짝지어 바깥으로 흐르고, `no_boundary`·`flipping`·교차로 사유로 끝난다. D-507 SIM 4c차에서 회전각을 −9…+15°로 쓸어도 재획득 뒤 10 s 유지는 0/54였고, ring을 따라 간 거리는 0.014–0.151 m였다. 끝 자리는 ring 중심선보다 0.026–0.070 m 바깥이었다(`docs/validation/d507-lane-trip-sim-2026-10-08/result.md` 4c차, R3-3, R4-1, R4-2).
4. **문턱값으로는 고치지 못한다.** 보이는 선이 하나뿐이고 그 선은 진로를 가로지르는 곡선이다. 짝 각도·경계 거리 문턱을 바꿔도 직선 현 모형이 원의 한쪽 경계를 차로 경계로 바꾸지 못한다. IR(몸 아래 ±0.020 m)은 0.0925 m 떨어진 경계를 몸이 경계에 걸친 뒤에야 보므로 지킬 수만 있다.
5. **Fleet은 그 구간의 곡률을 안다. CORE는 모른다.** Fleet 지도 차로는 polyline이고 `width_m`, `drive_mode`, 장소를 갖는다. D-507 교차로 지시는 이미 장소마다 `map_id`, 기대 창, 회전각, `advance_m`을 실어 CORE에 간다(`POST /api/v1/line-follow/junction`, API Ref v1.141). D-476 개정 2의 호 bridge는 κ를 측정이 아니라 직전 추종의 명령 곡률에서 얻고, 0.23 m까지만 잇는다. ring에서는 그 직전 추종이 없다.
6. **ring 진입의 끝 자세가 ring 접선과 어긋난다.** D-507 4항의 직진 `advance_m` 0.10 m 동안 ring 접선이 약 23° 돈다. 그래서 현 각이든 접선 각이든 전진 끝 진행 방향은 접선과 −7…−36° 어긋났다(4c차). 같은 반지름의 원을 따를 때 처음 방향 오차 ε는 원 중심을 약 r·ε 옮긴다. 20°면 약 0.088 m로 차로 여유를 넘는다. 호 주행은 접선 방향에서 시작해야 한다.
7. **odom의 한계.** 실기 카펫에서 제자리 회전 odom yaw가 몇 배 틀린 관찰이 있다(D-500 Context, 9dfk). Gazebo 회전 응답은 명령보다 약 2.4 % 모자랐다(110° 회전에 +1.8…+3.0°).
8. **크기 한도.** `control` 패키지는 2026-10-08 기준 45251줄로 한도 45254까지 3줄 남았다. perception 쪽 추가는 P1a 단계(`docs/plans/2026-10-08-control-p1a-sensing-perception-split.md`)가 착지해 `sensing/perception`이 따로 세어진 뒤에만 들어갈 수 있다.

### Decision

1. **계약: D-507 교차로 지시에 나가는 구간의 기하를 싣는다(사용자 결정 2026-10-08).** 새 엔드포인트 `POST /api/v1/line-follow/route-segment`는 만들지 않는다. `POST /api/v1/line-follow/junction`에 선택 객체 `exit_segment` 하나를 더한다.
   - 필드:
     - `curvature_1pm`: 부호 있는 1/m, 왼쪽(반시계) +, 0.5 ≤ |κ| ≤ 5.0.
     - `length_m`: 이 장소에서 다음 장소까지 차로를 따른 길이, (0, 1.0].
     - `outer_line_offset_m`: 차로 중심선에서 곡선 바깥쪽 칠한 선 중심까지의 거리, [0.05, 0.20].
     - `end_place_id`: 다음 장소.
   - 지시의 `map_id`가 반드시 같이 와야 한다. 없으면 CORE는 지시 전체를 400으로 거절한다.
   - `outer_line_offset_m`은 `width_m`에서 오지 않는다. 지도의 칠한 선 간격에서 온다. 260919 ring의 선 반지름은 0.155 m와 0.345 m이고(STL 도색, `X:\DevTemp\ring-diag\ring_paint.py`), 간격 0.19 m의 절반 0.095 m를 보낸다. `width_m`은 0.185 m다.
   - 뜻: "이 장소의 회전을 마친 뒤 로봇이 들어갈 차로는 반지름 1/|κ|의 원호이고, 다음 장소까지 `length_m`이다." Fleet은 다음을 모두 만족할 때만 보낸다. 아니면 보내지 않고 오늘처럼 동작한다.
     - 그 차로 polyline이 한 원호에서 옆으로 허용치(「SIM으로 정할 값」) 안에 있다.
     - `drive_mode: lane`이다.
     - D-491 횡단보도 구역을 지나지 않는다.
       - 이 검사는 CORE가 한다(`_arc_on_crosswalk`). Fleet 지도에는 횡단보도 구역이 없어서 Fleet은 이 조건을 보지 않는다(2026-10-08 Fleet 구현 검토).
   - 260919의 네 호는 `ring_s` 0.3739 m, `ring_w` 0.3739 m, `ring_n` 0.3722 m(각 약 85°), `ring_e` 0.4595 m(약 105°)다(`lane_graph.yaml`, 반지름 0.2514 m).
   - 능력 `lane_arc: true`(CORE가 이 객체를 받고 5항의 선언이 있음)가 있는 로봇에만 Fleet이 보낸다. 없으면 필드를 빼고 오늘처럼 보낸다.
   - **회전각과 `advance_m`(D-507 4항 개정).** `exit_segment`가 있으면 Fleet은 `turn_deg`를 접선 그대로 보낸다. 들어오는 차로의 `end_tangent`에서 나가는 차로의 `start_tangent`까지의 `theta`이고, `TURN_OVERTURN_DEG` 6°를 더하지 않는다. `advance_m`은 보내지 않는다. CORE는 `exit_segment`가 있으면 `advance_m`을 무시한다. 지금 `set_junction`은 `advance_m`이 없을 때 `DEFAULT_ADVANCE_M` 0.10 m를 쓰는데, 이 경우에는 그 값도 쓰지 않는다. `exit_segment`가 없으면 D-507 4항의 잠정 규칙(접선 + 6°, `advance_m` 0.10)이 그대로다. D-507 4항에 이 문장을 가리키는 줄을 더했다.
   - 왜 이 계약인가:
     - 교차로 지시는 이미 `place_id`·`seq`·만료·`map_id`·능력 확인·Fleet 포트(`LaneJunctionPort.send_junction`)를 갖는다.
     - 호 구간은 늘 장소의 회전에서 시작해 다음 장소에서 끝난다.
     - 따로 엔드포인트를 두면 "어디서부터 길이를 재는가"를 교차로 상태 기계와 다시 맞춰야 한다.
     - D-476의 경로 힌트(`set_bridge_route_hint`)는 방향만 담고 공개 API가 아니며 배선도 없어서 기하를 실을 수 없다.
   - 구간 중간(ring 위)에서 시작하는 trip은 이 ADR 범위 밖이다. 호 주행은 교차로 지시로만 들어간다.

2. **CORE 호 주행은 교차로 지시와 따로인 `line_follow.arc` 기록이다.** 오늘 CORE에는 지시 칸이 하나뿐이다. `set_junction`은 동작(`MANEUVER`) 중에 다른 지시가 오면 그 동작을 `aborted`로 끝낸다. Fleet은 `MANOEUVRE` 상태 동안 다음 지시를 보내지 않는다(`trip_runner._step_lane`). 그래서 호는 교차로 상태가 아니다.
   - **들어감.** 다음 가운데 하나다.
     - (a) `exit_segment`가 있는 `left`·`right` 지시가 `turning`을 마쳤고 `pivot_basis`가 `map` 또는 `segment_end`다. 그 지시는 `advancing`·`reacquiring` 없이 그 자리에서 `done`이 된다(`_mark_done`). CORE는 새 호 기록을 연다.
     - (b) 앞 호가 끝난 자리에서, `end_place_id`의 `straight` 지시가 `exit_segment`를 실었다. 그 지시도 `done`이 되고 다음 호 기록이 곧바로 열린다.
   - `pivot_basis: stop_point`면 호를 열지 않고 오늘처럼 전진·재획득한다. `stop_point` 폴백은 오늘처럼 기본 전진이다. `exit_segment`가 있어도 `DEFAULT_ADVANCE_M` 0.10 m를 쓰고, 1항의 `advance_m` 무시는 호가 열릴 때만이다(구현 리뷰 2026-10-08).
   - **기록.** 호 기록은 자기 번호 `arc_seq`를 갖는다. `line_follow.arc`는 `{arc_seq, from_place_id, end_place_id, curvature_1pm, length_m, travelled_m, state: running|ended|stopped, reason, ...}`이다. 매니저 잠금 안의 한 상태이고, 새 스레드·저장소·발행자는 없다. twist는 매니저 틱에서 같은 generation·evidence revision으로 CommandManager에 간다(D-18).
   - **호 주행 중의 지시 칸.** 칸은 비어 있다. 호는 `MANEUVER`도 Fleet `MANOEUVRE`도 아니다.
     - Fleet의 의무: 호가 도는 동안 `end_place_id`의 지시를 보낸다. 앞 지시가 `done`이 되면 바로 보낸다. 260919 호 길이 0.37–0.46 m는 `arm_distance_m` 0.6 m보다 짧아서 오늘의 무장 규칙으로도 곧 보내진다.
     - CORE는 그 지시를 `armed`로 받는다. 받은 지시가 호를 끊지 않는다. 호가 끝날 때까지 그 지시는 실행되지 않고, keeper 교차로 감지로 쓰이지도 않는다.
     - Fleet의 `carried` 판정: 이어지는 `straight`(b)는 `MANOEUVRE`나 `executing`을 거치지 않고 호 끝에서 곧바로 `done`이 된다. 그래서 오늘의 판정(`trip_runner.py` 349–352, `_completed`)으로는 그 지시가 `carried`로 보이지 않는다. Fleet은 `line_follow.arc.from_place_id`가 보낸 장소와 같고 `arc_seq`가 새로우면 그 지시를 `carried`로 본다. `left`·`right` 뒤의 호도 같은 규칙으로 본다.
     - 다른 장소의 지시는 호가 도는 동안 `armed`로 남는다. 호 끝에서는 그 지시를 `aborted`(`reason: arc_mismatch`)로 버리고, 지시가 없는 경우와 같이 처리한다.
   - **명령.**
     - v = 그 trip의 차선 주행 속도(`min(cruise_speed, 수동 선속도 한도)`, 기본 0.08 m/s).
     - ω = g·v·κ + v·(k_y·e_y + k_θ·e_θ).
       - κ는 `curvature_1pm`이다.
       - g는 로봇별 `line_follow.arc_curvature_gain`(기본 1.0)이고, D-500 측정 운동 응답이나 보정 저장소에서 온다.
       - e_y·e_θ는 3항의 카메라 호 맞춤이 신선하고 확신 있을 때만 쓰고, 아니면 0이다.
     - 보정 항은 |v·(k_y·e_y + k_θ·e_θ)| ≤ v·`arc_max_correction_1pm`(기본 1.5 1/m)으로 자른다.
     - 전체 |ω|는 live 각속도 한도 안이다. 한도에 걸리면 같은 곡률로 v를 줄인다(D-344 §13, D-476과 같음).
   - **거리와 끝.** odom 경로 길이가 `length_m`에 닿으면 끝난다. 길이는 매 걸음을 앞 자세 진행 방향에 투영한 부호 있는 합이다(D-507 3항과 같은 셈). 시간 한도는 `length_m / v + STEP_MARGIN_S`다. 끝에서:
     - `end_place_id`의 지시가 `armed`면, 그 지시의 축은 이 끝 자리다(`pivot_basis: segment_end`). keeper 감지도, D-507 3항 기대 창도, D-507 4항 접근도 쓰지 않는다. 축은 로봇이 있는 자리다.
       - `left`·`right`: 정지 확인(D-495 L1) 뒤 회전한다. 나가는 차로가 직선이면 오늘의 전진·재획득이고, 또 호면 (a)다.
       - `straight`: `exit_segment`가 있으면 (b)다. 없으면 그 지시는 `done`이 되고 오늘의 추종으로 간다.
       - `stop`: 선다.
     - 지시가 없으면 오늘의 추종(`follow`)으로 돌아간다(사용자 결정 2026-10-08). 이벤트 `nav.lane_arc_end_unarmed`(warning, `end_place_id`, `travelled_m`)를 낸다.
       - 알려진 위험은 LOST만이 아니다. ring 위에서 keeper는 바깥선의 현을 spoke 선과 짝지어 ring 중심선보다 0.026–0.070 m 바깥으로 흐른 뒤에야 `camera_line_not_visible`로 선다(D-507 SIM 4c차).
       - 그래서 위 Fleet의 의무가 이 경우를 막는 주 장치다. 그래도 남는 경우는 오늘의 손실 경로(손실 시계 → LOST)와 IR 가드(`lane_edge_*`), D-422가 맡는다.
     - 끝 자리의 odom 오차는 진행 방향 m당 0.05다(D-507 2항 `ODOM_DRIFT_PER_M`). ring 호에서 약 0.02 m다.
   - **운동 허가.** 매 틱 `motion_admitted(now, v, ω, kind='arc', map_id)`(D-507 6항)를 거친다.
     - `IR_ALLOWED`(`motion_admit.py`)에 새 kind 둘을 더한다. `arc`는 {`clear`}, `arc_edge`는 {`clear`, `left`, `right`}다. `arc_edge`에서는 새 인자 `ir_side`로 한쪽만 받는다(아래 보정).
     - ring 위에서는 차로 안에 IR 밑을 지나는 선이 없다. 그래서 `left`·`right`·`centre`는 몸이 경계에 걸쳤다는 뜻이다.
     - **입구 유예.** 호 시작 뒤 odom 0.03 m(`ARC_START_IR_GRACE_M`) 안에서는 `left`·`right`를 허가하고, 보정도 열지 않는다. 회전 축은 spoke 입구 위의 장소이고, IR 줄(x 0.0295 m)이 입구의 끊긴 선 끝 위에 있을 수 있다. SIM 기록에서 이 자리의 IR 판정을 찾지 못해서 증거 대신 이 유예를 둔다. `centre`는 유예 중에도 멈춘다. 유예가 끝난 뒤 처음 판정이 유예 중에 본 판정과 같은 쪽이면 보정을 열지 않고 `lane_arc_edge`로 선다. 입구 선이 아니라 몸이 그쪽 경계에 걸쳐 있다는 뜻이기 때문이다.
     - `stale`은 언제나 거절이다. 후진은 없다.
   - **D-422 sweep.** 그 틱의 (v, ω) 호를 `_sweep_clear`가 그대로 쓴다. 직선 연장이 아니라 호를 쓴다. 그래서 섬이나 ring 바깥 벽이 직선 앞에 있다는 이유로는 서지 않고, 호 위의 물체에는 선다. 틱 단위 D-422(`obstacle_ahead`)도 그대로다.
   - **IR 한 번 보정(사용자 결정 2026-10-08, 곧바로 멈추는 대신).** 한 호에서 한 번만 한다.
     - **시작.** 유예 뒤 `arc` 중 처음 나온 `left`·`right` 판정이 보정을 연다. 판정은 신선하고 교정된 것이다(D-344 §12). 그 쪽을 s(`left` = +1, `right` = −1)로 기억하고, 이때의 호 기준 방향을 적어 둔다. 기준 방향은 ψ(s) = ψ₀ + κ·s다. ψ₀는 호 시작의 odom yaw이고, s는 호 시작부터의 odom 길이다. `centre`는 보정을 열지 않고 곧바로 멈춘다(몸이 선을 밟고 있음).
     - **명령.**
       - 앞으로만 간다(v > 0, 후진 없음).
       - 속도는 v_c = v × `ir_guard_speed_scale`이다. 0.5는 오늘 IR 가드와 같은 값이고, v_c는 0.04 m/s다.
       - 각속도는 ω = g·v_c·κ − σ·v_c·b다. σ는 단계마다 정한다.
       - b는 `line_follow.bridge_arm_max_curvature`를 그대로 쓴다. 4.0 1/m는 지도에서 가장 좁은 차로 호다(D-476 개정 2).
       - 선이 왼쪽 IR 밑이면 오른쪽(음의 각속도, REP-103)으로 비킨다. 오늘 추종의 IR 가드와 같다.
       - 보정 동안 3항의 카메라 보정 항은 0이다. 전체 |ω|는 live 한도 안이다.
     - **`away`.** σ = +s로, 정해진 odom 거리 `ARC_IR_AWAY_M` = 0.12 m를 간다.
       - 유도: b만으로 IR 줄이 테이프 폭 0.025 m만큼 옆으로 옮겨 가는 거리는 √(2 × 0.025 / 4.0) ≈ 0.112 m이고, 이것을 올림했다.
       - 끝 자리에서 IR가 **확신 있는 `clear`**여야 한다. 신선하고 교정됐으며, 관측이 `visible: false`인 경우다. `_ir_guard`는 `visible`이지만 신뢰도가 `min_confidence` 아래인 관측도 `clear`로 돌려준다. 그런 `clear`는 여기서 `clear`로 치지 않는다.
       - 끝에 확신 있는 `clear`가 아니면 멈춘다.
       - 이 단계에서 진행 방향은 호 기준에서 선 반대쪽으로 b × 0.12 = 0.48 rad만큼 벌어진다.
     - **`level`.** σ = −s(반대 편향)로 간다. odom yaw가 그 순간의 호 기준 ψ(s) = ψ₀ + κ·s에 닿으면 끝난다.
       - 상한은 odom 거리 1.5 × `ARC_IR_AWAY_M` = 0.18 m다. 상한 안에 닿지 않으면 멈춘다.
       - 거울 거리 대신 기준 방향으로 끝내는 이유: 거울 거리로 끝내면 호 자체가 그동안 κ만큼 돌아서 진행 방향이 다시 바깥을 향한다.
       - 몸은 약 b·d²(d = 0.12 m, 약 0.058 m)만큼 차로 안쪽으로 옮겨 간다. 처음 어긋남(0.06–0.075 m)이 그만큼 줄어 중심 근처로 온다.
     - **허용하는 IR 판정.** `clear`만으로는 보정을 할 수 없다. 보정을 연 판정 자체가 경계를 보고 있기 때문이다. 그래서 보정 동안의 허가는 `motion_admitted(..., kind='arc_edge', ir_side=s)`다. 단계별로 받는 판정은 다음과 같다.
       - `away`: s 쪽 또는 `clear`.
       - `level`: `clear`만.
       - 보정이 끝난 뒤의 `arc`: 다시 `clear`만.
       - D-422 sweep은 보정 twist (v_c, ω) 그대로를 쓴다.
     - **멈춤(`lane_arc_edge`, 다시 보정하지 않음).** 다음 가운데 하나면 멈춘다.
       - 보정 중 반대쪽 판정이나 `centre`.
       - `away` 끝에 확신 있는 `clear`가 아님.
       - `level` 중 다시 s 쪽 판정.
       - `level` 상한 초과.
       - 보정이 끝난 뒤 같은 호에서 두 번째 `left`·`right`.
       - 보정 중에 구간 길이에 닿음. 흔들린 자세에서 다음 교차로 지시를 실행하지 않는다.
       - 보정 중 시간 한도(`(0.12 + 0.18) / v_c + STEP_MARGIN_S`) 초과.
     - **상태.** `line_follow.arc.ir_correction`에 `{side, phase, away_m, level_m, used}`를 보인다. 구간 odom 길이에는 보정 경로도 들어간다. S자는 호보다 몇 mm 길다.
   - **멈춤(HOLD, `line_follow.reason`).** 멈춘 뒤 다시 호를 열지 않는다. 호 기록은 `stopped`이고 Fleet은 trip을 `stopped`로 끝낸다.
     - `lane_arc_edge`: 「IR 한 번 보정」의 멈춤 조건이나 `centre`.
     - `lane_arc_entry`: 6항의 진입 방향 검사.
     - `obstacle_ahead`: D-422 몸체 sweep 미달.
     - `lane_arc_pose_lost`: odom이 `stale_after_s`보다 낡음·끊김·frame/epoch 변경(D-468 7항 (2)의 불연속).
     - `lane_arc_motion_unconfirmed`: 스캔이 `clearance_stale_s`보다 낡음.
     - 모드 변경·E-stop·운전자 hold: 오늘과 같은 사유.
     - `lane_arc_timeout`: 시간 한도 초과.
     - `lane_arc_blind`: 3항의 보정 없이 간 거리가 `arc_blind_max_m`을 넘음.
   - **호 주행 중 keeper 사유.** `no_boundary`, `flipping`, `junction_*`, `camera_line_not_visible`, `low_confidence`, 영상 품질 사유는 멈춤이 아니다. 3항 보정의 입력이 없다는 뜻일 뿐이다. 손실 시계(`_loss_started_at`)는 호 주행 동안 돌지 않고, 끝나면 그 자리에서 새로 시작한다.
   - **다른 복구와의 관계.** 호 주행 중에는 D-476 bridge와 D-468 이탈 판정 (1)·(3)이 열리지 않는다. 둘 다 카메라 corridor에 기대는데, ring에서는 그 corridor가 직선 현 모형이라 틀린다. (2) 자세 불연속은 위 `lane_arc_pose_lost`로 멈춘다. 호에서 멈춘 뒤 D-468 복귀·역추적도 하지 않는다.
   - **D-507 상태 기계와의 관계.**
     - 호는 D-507 1항 표의 `turning`과 `follow` 사이에 들어간다. `exit_segment`가 있으면 `advancing`·`reacquiring` 자리를 대신한다.
     - 지시는 `turning`이 끝날 때 `done`이다.
     - 호 끝의 장소는 D-507 3항 창과 4항 접근 대신 `segment_end`를 쓴다.
     - `exit_segment`가 없는 지시와 ring 밖의 모든 교차로는 D-507 그대로다.
   - **D-491·D-517.** 횡단보도가 있는 구간에는 1항에 따라 호 기하가 오지 않는다. D-517 통행권 끝(`until_m`, `ttl_s`)은 호 주행에서도 추종과 같이 선다.
   - **설정**(`rosy_default.yaml`, 기본 꺼짐):
     - `line_follow.arc_enabled`(false).
     - `arc_curvature_gain`(1.0, [0.8, 1.25]).
     - `arc_max_correction_1pm`(1.5).
     - `arc_blind_max_m`.
     - `arc_gain_lateral_1pm2`(36), `arc_gain_heading_1pm`(12). 값은 「SIM으로 정할 값」에서 정한다.
     - IR 한 번 보정은 새 설정 없이 기존 값 `ir_guard_speed_scale`·`bridge_arm_max_curvature`와 코드 상수 `ARC_IR_AWAY_M`(0.12 m), `ARC_START_IR_GRACE_M`(0.03 m)을 쓴다.
     - `arc_enabled: true`는 5항의 선언, `ir_guard_enabled`, `obstacle_mode: path`, URDF 몸을 요구한다. 없으면 CORE 시작 거부.
   - **출력(API reference 판 올림).**
     - 지시 필드 `exit_segment`.
     - 능력 `lane_arc`.
     - `line_follow.arc` 상태(위 기록, 3항 맞춤 값, `ir_correction`).
     - `line_follow.junction.pivot_basis` 값 `segment_end`(`core_common/protocol/schemas.py`의 `pivot_basis` 주석 `map | stop_point`에 더함).
     - 사유 `lane_arc_*`.
     - 이벤트 `nav.lane_arc_end_unarmed`.
     - 지시 `aborted` 사유 `arc_mismatch`.
     - Fleet: `line_follow.arc`의 `from_place_id`·`arc_seq`로 `carried` 판정.
     - 내부: `IR_ALLOWED`의 `arc`·`arc_edge`, `motion_admitted(..., ir_side=None)` 인자.
     - 단계 2에서 keep_debug `paint_points_m`·`paint_points_v`.
   - **코드 위치와 크기.**
     - `line_follow/recovery` 크기 단위는 2026-10-08 판정 2713줄이고, 다음 재판정은 +150(2863)이다. 지금 그 디렉터리 파일의 원시 줄 수 합은 2803이다. 판정의 셈법이 다르면 조금 다를 수 있다. 남은 약 60줄에 호 상태 기계와 맞춤(합쳐 약 300줄 예상)이 들어가지 않는다.
     - 그래서 새 하위 패키지 `core_features/line_follow/arc/`(`lane_arc.py`, `lane_arc_fit.py`)를 별도 크기 단위로 둔다. 매니저 mixin 방식과 한 잠금은 같다.
     - 구현 전에 `docs/plans/`에 날짜 붙은 분리 계획이 있어야 한다(`test_size_units_are_real_subpackages_with_a_split_plan`, 선례 `docs/plans/2026-10-07-line-follow-recovery-subpackage.md`).
     - `motion_admit.py`의 kind 추가(몇 줄)는 recovery 안에 둔다.

3. **카메라 호 맞춤(단계 2).** 반지름은 지도에서 알고 있다. 그래서 원 전체를 맞추지 않고, 반지름을 고정한 원의 자리 두 값(옆 오프셋과 방향)만 맞춘다.
   - **입력(perception).** keep 모드 `line/keep_debug`에 `paint_points_m`을 더한다.
     - 이미 계산한 BEV 도색 마스크(`lane_bev.py`)에서 base_footprint x 0.10–0.40 m 안의 도색 점을 최대 48개(고른 간격, mm 반올림)로 줄여 싣고, 영상 시각을 함께 둔다.
     - 지원 표시는 `paint_points_v: 1`이다(`junction_ahead_v`와 같은 방식).
     - perception은 선을 고르지 않는다. 어느 점이 바깥선인지는 지도를 아는 CORE가 정한다. 그래서 CORE → perception 경로 문맥 통로(`line/route_context`)가 필요 없다.
   - **맞춤(CORE, ROS 없는 함수, `arc/lane_arc_fit.py`).** 바깥선 반지름은 R_o = 1/|κ| + `outer_line_offset_m`이다. 영상 시각의 odom 자세로 점을 로봇 좌표로 옮긴다. 남은 점으로 R_o 고정 원의 중심 두 좌표를 가우스-뉴턴 두세 번으로 맞춘다. 그 중심에서 e_y(x = 0에서 차로 중심원까지의 옆 오차, 바깥 +)와 e_θ(접선 대비 방향 오차)를 낸다.
   - **문(gate).**
     - **첫 맞춤:** 호에서 아직 받아들인 맞춤이 없을 때다. 호 시작 자세와 odom으로 놓은 예상 바깥원에서 반지름 방향 ±0.06 m(`ARC_FIT_GATE_FIRST_M`) 안의 점을 남긴다. 축의 옆 오차(SIM 최대 0.032 m)와 회전 오차가 만드는 예상원 어긋남이 0.03 m를 넘을 수 있어서 넓게 둔다.
     - **spoke 거르기:** 띠가 넓으면 spoke 선 조각이 들어온다. 각 점의 국소 방향(이웃 점들의 주성분)이 예상원의 그 자리 접선과 30° 넘게 다르면 버린다. spoke 선은 반지름 방향이라 약 90° 다르다.
     - **이후:** 마지막으로 받아들인 맞춤을 odom으로 옮긴 원 둘레 ±0.03 m(`ARC_FIT_GATE_M`)와 같은 방향 거르기를 쓴다.
     - 맞춤 하나가 앞 맞춤에서 옆으로 0.02 m 넘게 뛰면 쓰지 않고 보정 없는 거리에 더한다.
   - **입구 공백.** 입구에서 바깥선이 끊기면 점이 적어질 뿐이다. 각 범위가 15° 이상이고 남은 점이 8개 이상이면 맞춘다. 공백 양쪽의 점도 같은 원 위이므로 함께 쓴다.
   - **확신.** 다음을 모두 만족하면 확신 있음이다.
     - 남은 점의 반지름 잔차 RMS ≤ 0.010 m.
     - 각 범위 ≥ 15°, 점 ≥ 8개.
     - 영상 나이 ≤ `stale_after_s`(0.3 s).
     - 위 문을 통과했다.
     - 첫 맞춤이면 |e_y| ≤ 0.06 m. 그 밖이면 틀린 선을 잡았을 수 있다. 그때는 보정하지 않고 보정 없는 거리에 더한다.
   - **크기.** CORE 쪽은 2항의 새 하위 패키지에 둔다. perception 쪽 추가(약 20–30줄)는 P1a 단계가 착지해 `sensing/perception`이 따로 세어진 뒤에만 넣는다. 그래서 단계 2는 P1a 뒤다. 단계 1은 perception을 바꾸지 않는다.

4. **보정 없는 거리 `arc_blind_max_m`.** 단계 1 빌드(SIM 전용)에서는 구간 길이 전체(보정 없음)를 허용해 흐름을 잰다. 장치 기본값은 단계 1 SIM의 흐름 측정에서 정한다(「SIM으로 정할 값」). 그 전까지 장치에서는 `arc_enabled`를 켜지 않는다(7항 DEVICE는 단계 2 SIM 통과 뒤).

5. **현장 근거.** 호 주행은 D-507 6항 (a) enforce 또는 (b) site 근거가 있어야 한다. (b)의 바닥 근거는 D-507 9항 `line_follow.site_floor_map_id` 선언이고, 지시의 `map_id`가 그 값과 같아야 한다. 선언이 덮는 범위(차로와 그 바깥 0.30 m)는 호 주행이 벗어날 수 있는 거리(아래 6항 경계 + 정지 거리)보다 넓다. D-400 enforce는 바꾸지 않는다.

6. **안전 근거와 실패 방식.**
   - **feed-forward 흐름의 크기(계산, SIM으로 확인).** r = 0.2514 m이고, θ는 호 각(85° 또는 105°)이다.
     - 처음 옆 오차는 그대로 남는다. D-507 4차의 축 옆 오차는 0.005 m(SW)–0.032 m(NE)다.
     - 처음 방향 오차 ε는 같은 원을 시작점 둘레로 돌린 것이다. 반지름 방향 어긋남은 약 r·ε·sin θ이고 90°에서 가장 크다. 3°에서 0.013 m다(85°·105° 모두 약 0.013 m).
     - 곡률 오차 δ(비율)는 r·δ·(1 − cos θ)다. Gazebo 회전 부족 2.4 %에서 85°는 0.0055 m, 105°(`ring_e`)는 0.0076 m다.
     - 합: SW 진입(`ring_s`, 85°)은 약 0.024 m, NE 진입(`ring_n`, 85°)은 약 0.051 m다. NE는 0.05 m 합격선에 걸려 있다. 단계 1에서 NE가 떨어지면 단계 2가 필요하다는 증거다.
   - **진입 방향 오차.** 진입 회전은 odom yaw로 멈춘다. 카펫에서 제자리 회전 odom yaw는 몇 배 틀렸다(D-500, 9dfk: odom 111°가 실제 약 30°).
     - 장치: `arc_enabled`를 켜기 전에 카펫 yaw 비(odom ÷ 실제)를 같은 독립 기준(7항 DEVICE)으로 잰다. 두 가지를 잰다. 하나는 제자리 회전이다. 다른 하나는 곡선 주행으로, IR 보정과 같은 곡률(κ + b ≈ 8 1/m)과 속도 0.04 m/s, 그리고 호 주행 곡률(κ)과 0.08 m/s다. 곡선 주행의 비가 IR `level`의 기준 방향과 `arc_curvature_gain`의 근거다.
     - 단계 2: 호 시작 뒤 0.10 m(`ARC_ENTRY_CHECK_M`) 안의 첫 확신 맞춤에서 |e_θ| > 5°면 `lane_arc_entry`로 선다.
     - 5°의 근거: 방향 오차 하나에 0.05 m 여유의 절반 0.025 m를 준다. ε ≤ 0.025 / 0.2514 = 0.0994 rad = 5.7°이고, 이것을 내림했다. 5°에서 r·ε = 0.022 m다.
     - 그 거리 안에 확신 맞춤이 없으면 진입 검사 없이 보정 없는 거리에 더한다.
   - **카펫 odom·미끄럼.** 호 주행의 회전은 명령이 하고, odom은 거리·끝·IR 보정의 기준 방향만 잰다.
     - 실제 곡률이 명령과 10 % 다르면 85°에서 약 0.023 m, 105°에서 약 0.032 m 벗어난다.
     - 대응:
       - 한 구간은 장소 사이 한 호(≤ 1.0 m, 260919에서 0.37–0.46 m)뿐이다.
       - 로봇별 `arc_curvature_gain`은 D-500 측정 운동 응답에서 정한다.
       - 단계 2 보정이 붙는다.
       - IR 한 번 보정과 두 번째 판정 멈춤이 있다.
     - odom 거리 오차(진행 방향)는 끝 자리를 m당 0.05 옮긴다. `segment_end` 축이 그만큼 장소에서 어긋난다.
   - **틀린 κ.** 지도와 바닥이 다르거나 Fleet 결함이면 로봇은 틀린 원을 돈다.
     - 막는 것:
       - `map_id`가 현장 선언과 같아야 한다.
       - 범위 확인(0.5 ≤ |κ| ≤ 5.0, 길이 ≤ 1.0 m).
       - 단계 2에서 점이 문에 들어오지 않으면 보정 없는 거리가 늘어 `lane_arc_blind`로 선다.
       - IR 한 번 보정 뒤 두 번째 판정에서 선다.
       - D-422.
     - IR가 처음 볼 때까지의 옆 오차는 약 0.06–0.075 m다(바깥선 안쪽 가장자리 0.0825 m − IR 0.020 m 근처). 이 범위는 5항 선언의 0.30 m 안이다.
   - **구간 끝을 놓침.** 끝은 odom 길이로만 정하고, 시간 한도와 길이 한도가 둘 다 있다. 다음 지시가 없으면 2항의 이벤트를 내고 오늘의 추종으로 간다. 그 추종의 바깥 흐름(0.026–0.070 m)은 IR 가드와 손실 경로가 맡는다.
   - **틀린 보정(단계 2).** 보정 항은 1.5 1/m로 잘린다. 문(첫 0.06 m, 이후 0.03 m), 방향 거르기, 0.02 m 뜀 거절이 있다. 보정이 없는 동안은 feed-forward만 남는다.
   - **IR 한 번 보정(사용자 결정).**
     - 보정이 열리는 자리에서 몸 중심은 차로 중심에서 약 0.06–0.075 m다.
     - `away`(0.12 m) 동안 바깥으로 더 가는 거리는 처음 방향 오차 ε에서 약 ε²/(2b)다. ε = 0.1 rad이면 약 1.3 mm다. `away` 끝에는 확신 있는 `clear`가 필요하다.
     - `level`은 odom yaw가 호 기준에 닿을 때 끝난다. 0.18 m 상한이 있다.
     - 몸은 경계 테이프 근처에서 최대 0.30 m를 간다. 이 범위는 5항 선언 안이다.
     - 앞만 간다. `centre`와 반대쪽 판정에서 서고, 보정 twist도 D-422 sweep과 `motion_admitted`를 거친다.
     - 남는 위험:
       - IR은 몸 아래의 늦은 울타리다(D-476 개정 1).
       - `level`의 기준은 odom yaw라서 카펫 yaw 오차가 그대로 들어온다.
       - 원인(틀린 κ, 미끄럼)은 남는다. 그래서 두 번째 판정은 멈춤이다.
     - 보정은 trip을 살리는 장치이고, 합격의 근거가 아니다.
   - **진입 자세.** 호는 `turning` 직후 접선 방향에서 시작한다(1항의 접선 `turn_deg`, 직진 전진 없음). `pivot_basis: stop_point`이면 호를 열지 않는다.

7. **단계와 수용.**
   - **SOURCE: 일반.**
     - 지시 검증: `exit_segment` 범위, `map_id` 없으면 400, 능력 `lane_arc`, `exit_segment`가 있으면 `advance_m` 무시.
     - 호 열기: `turning` 끝에서 지시가 `done`이 되고 `arc_seq`가 열림. `stop_point`에서는 호 없음.
     - 호 중의 지시 칸: 호 중 `end_place_id` 지시가 `armed`로 받아지고 호를 끊지 않음. 다른 장소 지시는 호 끝에서 `aborted`(`arc_mismatch`)가 되고, 지시 없는 끝과 같이 처리함.
     - 명령: ω = g·v·κ + 보정, 보정·전체 한도.
     - 끝: odom 길이·시간 끝, `segment_end` 축으로 `left`·`right`·`straight`(호 잇기)·`stop` 실행, 지시 없는 끝 → `follow` + `nav.lane_arc_end_unarmed`.
     - 멈춤 사유 전부.
     - IR 허가: kind `arc`의 IR 허용 값(`clear`만), 입구 유예 0.03 m(`left`·`right` 허가, `centre` 멈춤), 유예 끝 첫 판정이 유예 중과 같은 쪽 → `lane_arc_edge`(보정 없음).
     - 무시와 꺼짐: 호 주행 중 keeper 사유 무시와 손실 시계 정지, D-476·D-468 (1)(3) 꺼짐.
     - 호 sweep: 직선 앞 점은 막지 않고 호 위 점은 막음.
     - 설정 검증과 시작 거부.
     - Fleet:
       - `exit_segment` 계산: 원호 적합 허용치, 횡단보도 구간 제외, `outer_line_offset_m`은 선 간격에서 옴.
       - `exit_segment`가 있으면 `turn_deg`는 접선, 6° 없음, `advance_m` 없음.
       - 호 중 `end_place_id` 지시 송신. `MANOEUVRE`에 호가 없음.
       - 이어지는 `straight`: CORE가 곧바로 `done`으로 넘기고 새 `arc_seq`·`from_place_id`를 보이면 Fleet이 `carried`로 보고, 같은 지시를 다시 보내지 않으며, 다음 장소로 넘어감. `left`·`right` 뒤 호도 같음.
     - 골든: `arc_enabled: false`일 때 오늘의 결정 순서와 틱마다 같음.
   - **SOURCE: IR 한 번 보정.**
     - 편향 방향과 크기: 처음 `left` → 음의 각속도 편향, `right` → 양의 편향. 크기는 v_c·b, 속도는 v × `ir_guard_speed_scale`이고 v > 0이다.
     - `away` 끝:
       - `away`는 0.12 m를 정해진 대로 간다.
       - 끝에 확신 있는 `clear`면 `level`로 간다.
       - 끝에 같은 쪽 판정이면 멈춘다.
       - 끝에 신뢰도 미달 `visible` 관측(`_ir_guard`가 `clear`로 돌려주는 것)이면 멈춘다.
     - `level` 끝:
       - odom yaw가 ψ₀ + κ·s에 닿을 때 끝난다. 끝난 뒤 odom 진행 방향과 호 기준의 차가 한 틱 동안의 회전량 안이다.
       - 상한 0.18 m를 넘으면 멈춘다.
       - 닫힌 루프 모형(곡률 이득 0.9)에서 보정 뒤 진행 방향이 바깥을 향하지 않는다.
     - 멈춤:
       - 보정 중 반대쪽 판정.
       - 시작 때나 보정 중 `centre`.
       - `level` 중 같은 쪽 재등장.
       - 보정이 끝난 뒤 두 번째 `left`·`right`(한 호에 한 번). 새 호에서는 다시 한 번 할 수 있다.
     - `motion_admitted`:
       - `kind='arc_edge', ir_side=s`는 s 쪽과 `clear`만 받고, 반대쪽·`centre`·`stale`은 거절한다.
       - `ir_side` 없는 `arc_edge`는 `ValueError`다.
       - 보정 twist의 D-422 sweep 미달 → `obstacle_ahead`.
     - 그 밖:
       - 보정 중 구간 끝 → `lane_arc_edge`(다음 지시 실행 안 함).
       - 시간 한도.
       - 후진 명령 0.
       - 보정 중 카메라 보정 항 0.
   - **SOURCE: 단계 2 맞춤.**
     - 고정 반지름 맞춤: 합성 바깥선 + spoke 선 + 입구 공백 + 잡음.
     - 첫 맞춤 문 0.06 m: 축 옆 오차 0.04 m에서 출발해도 바깥선을 잡음.
     - spoke 점은 방향 거르기로 버림.
     - 이후 문 0.03 m, 0.02 m 뜀 거절.
     - 확신 조건.
     - 첫 맞춤 |e_θ| > 5° → `lane_arc_entry`.
   - **SIM 단계 1(모델 PC, 이 노트북 아님, feed-forward만).**
     - 4c차 놓기 자세에서 각 3회 돌린다. SW는 (−0.655, −0.432, 64°), NE는 (−0.0711, 0.4774, −117.8°)다.
     - 진입 회전 뒤 다음 장소까지 호 하나를 달린다(SW → `ring_s`, NE → `ring_n`). 참값 자세로 ring 중심선에서의 반지름 방향 거리 Δr을 기록한다.
     - 합격(사용자 결정 2026-10-08):
       - 6/6 run 모두 호 전체에서 |Δr| ≤ 0.05 m.
       - 구간 흐름(끝 Δr − 시작 Δr)의 평균 절댓값 ≤ 0.03 m.
       - 벽 `near_stop` 0, `lane_arc_edge` 0, IR 보정 0.
     - 함께 기록: 구간마다 시작 Δr·방향 오차, 끝 자리와 장소 사이 거리, SE `straight`로 이은 `ring_e`(105°) 한 번.
     - 이 측정으로 장치 `arc_blind_max_m`을 정한다.
     - **실패의 뜻.** 단계 1 합격선은 측정이다. NE만의 0.05 m 초과는 단계 2를 막지 않는다(6항 예산에서 NE는 합격선에 걸려 있다). SW 초과나 흐름 평균 0.03 m 초과면 단계 2 전에 원인을 본다. 어느 경우든 `arc_blind_max_m`은 측정한 최대 흐름에서 정한다.
   - **SIM 단계 1 보정 사례.** 보정을 실제로 돌리는 사례다. 위 합격선은 보정 0을 요구하므로 따로 둔다.
     - 설정: `arc_curvature_gain` 0.9로 SW → `ring_s` 3회, SE `straight` → `ring_e`(105°) 3회.
     - 예상 바깥 흐름은 r·δ·(1 − cos θ)다. 85°에서 0.0255 m, 105°에서 0.035 m이고, 축 옆 오차가 더해진다.
     - IR가 열리지 않으면 0.8(설정 하한, 85°에서 0.057 m)로 내린다.
     - 합격:
       - 보정이 열린 run마다 `away` 끝 확신 `clear`, `level`이 상한 안에 호 기준에 닿음.
       - 보정 뒤 0.10 m에서 |Δr| ≤ 0.03 m, 보정 뒤 진행 방향과 접선의 차 ≤ 5°.
       - `centre` 0, 벽 `near_stop` 0.
     - 두 번째 판정으로 멈추면 기록하고, 그 run은 실패로 센다.
   - **SIM 단계 2(P1a 뒤, 보정 켬).**
     - 같은 놓기 6회와 한 바퀴 3회를 돌린다. 한 바퀴는 SW 진입 → SE·NE `straight` → NW 진출이고, `segment_end` 축을 쓰며 지시는 호 중에 무장된다.
     - 합격(사용자 결정 2026-10-08):
       - 모든 run에서 |Δr| ≤ 0.03 m.
       - `lane_arc_blind` 0, `lane_arc_entry` 0, IR 보정 0.
       - `nav.lane_arc_end_unarmed` 0.
       - NW 진출 뒤 spoke 재획득 3/3, 벽 `near_stop` 0.
     - 처음 Δr을 0.04 m로 놓은 run(첫 맞춤 문 0.06 m 안)에서 0.25 m 안에 |Δr| ≤ 0.02 m로 돌아와야 한다.
   - **DEVICE(단계 2 SIM 통과 뒤, 사용자 승인).**
     - 로봇: 9dfk 또는 8kcn.
     - 준비:
       - D-507 9항 선언과 걷기 기록.
       - IR 보정.
       - 카펫 yaw 비 측정: 제자리 회전과 곡선 주행(6항).
       - 운동 응답 측정으로 정한 `arc_curvature_gain`.
     - 시작: SW 진입 한 번 → 호 하나부터.
     - 판정 기준: Δr과 끝 자리는 odom이 아니라 독립 기준으로 판정한다. 기준은 LiDAR-벽 정합(`docs/solutions/workflow-issues/field-scripts-driving-a-real-robot-need-clearance-identity-and-wall-pose-2026-10-07.md`) 또는 Rosy Cam 천장 자세이고, 오차 ≤ 0.01 m여야 한다.
     - 합격선: 단계 2 SIM과 같다.

### 범위 밖

- 구간 중간에서 시작하는 trip, 곡률이 변하는 차로(나선·S자)와 원호 아닌 굽이의 호 주행. 굽이 오감지(D-507 B9)는 그대로 그쪽 결정이다.
- keeper 직선 현 모형 자체의 수정. ring 밖 차선 추종은 바뀌지 않는다.
- D-400 enforce, D-468 역추적 한도, D-476 bridge의 변경. `exit_segment`가 없는 교차로의 D-507 4항 잠정 회전 규칙.

### 검토한 대안

- **문턱값 고치기(짝 각도, 경계 거리, flip 래치).** 원인은 문턱이 아니라 모형이다. 차로 안에서 보이는 선은 진로를 가로지르는 바깥 곡선 하나이고, 직선 현 모형은 그 선의 쪽을 정하지 못한다. 4c차 54 run에서 회전각을 바꿔도 10 s 유지 0이었다.
- **섬 쪽 선 따르기.** 카메라가 차로 안에서 섬 쪽 선을 보지 못한다(SIM 8°, 실기 11.8° 모두). 카메라 각을 바꾸면 직선 차로의 시야와 D-378 기록·보정 전부가 바뀐다.
- **IR 경계 따르기.** IR은 몸 아래 ±0.020 m에 있다. 경계(0.0925 m)를 보려면 몸이 이미 경계에 걸쳐 있어야 한다. 그러면 0.05 m 여유를 늘 넘긴 채 달리게 된다. IR은 울타리로만 쓴다.
- **호 주행 중 IR `left`·`right`에서 곧바로 멈추기(초안).**
  - 장점: 코드와 시험이 가장 작다. 로봇은 차로 중심에서 약 0.065 m인 자리에 선다.
  - 사용자는 한 번 보정을 골랐다(2026-10-08). 작은 흐름(곡률 이득 오차, 미끄럼) 하나 때문에 trip 전체를 끝내지 않기 위해서다.
  - 대가:
    - 몸이 경계 테이프 근처에서 최대 약 0.30 m를 더 간다.
    - IR 허가 규칙이 한 단계 늘어난다(`arc_edge`, 쪽 기억, 확신 있는 `clear`).
    - `level`이 odom yaw에 기댄다.
    - 시험이 늘어난다.
    - 두 번째 판정에서는 결국 멈춘다.
- **IR 보정의 `level`을 `away`와 같은 거리로 끝내기(첫 개정).** `away`를 첫 `clear`에서 끊고 같은 거리만큼 되돌리면, 그동안 호가 κ만큼 돌아서 끝의 진행 방향이 다시 바깥을 향한다. 검토에서 기각했다.
- **호를 교차로 상태 `arc`로 두기(초안).** 지시 칸이 하나이고 동작 중 새 지시가 동작을 끊으며, Fleet은 동작 중 지시를 보내지 않는다. 그래서 호 끝에 다음 지시가 `armed`일 수 없다. 호를 따로인 기록으로 둔다.
- **카메라만으로 호 맞춤(지도 곡률 없이 원 전체 맞춤).** 보이는 호는 약 52°뿐이라 반지름 0.345 m의 처짐이 약 0.035 m다. 반지름까지 맞추면 잡음에 약하고, spoke 선과 입구 공백에서 반지름이 크게 흔들린다. 보이지 않는 동안(입구, 영상 품질)은 명령이 없다. 지도 곡률을 주 명령으로 두면 카메라는 두 값만 맞추면 되고, 카메라가 없어도 짧게 달릴 수 있다.
- **새 엔드포인트 `POST /api/v1/line-follow/route-segment`.** 길이를 재기 시작하는 자리를 교차로 상태 기계와 따로 맞춰야 한다. `map_id`·능력·만료·`seq`도 다시 만들어야 한다. 호 구간은 늘 장소의 회전에서 시작하므로 교차로 지시에 싣는 쪽이 작다.
- **D-476 호 bridge를 늘리기.** κ가 직전 추종의 명령에서 오는데 ring에서는 그 추종이 없다. 거리 상한 0.23 m는 장소 사이 호(0.37–0.46 m)보다 짧다.
- **ring 진입을 직진 전진 + 재획득으로 두고 회전각만 고르기.** 4c차가 기각했다(회전각과 무관하게 ring 추종 0.15 m 이하).

### Consequences

- ring 진입·통과·진출이 keeper의 ring 추종 없이 가능한 구조가 된다. 장소 사이 한 호는 지도 곡률과 odom 길이로 달리고, 다음 장소의 축은 odom 끝이다. 실차 수용은 단계 2 SIM 뒤다.
- CORE가 처음으로 지도에서 온 곡률을 명령에 쓴다. 그 값은 `map_id`와 현장 선언에 묶이고, 한 구간·한도·IR·D-422 안에서만 쓴다.
- 교차로 지시는 `exit_segment`가 있으면 `turning` 끝에서 `done`이 된다. 호는 따로인 기록이다. Fleet은 호 중에 다음 지시를 보내야 한다.
- ring 위에서는 keeper의 교차로 감지를 쓰지 않는다. 장소 위치 오차는 odom 거리 오차가 진다.
- 구현 전에 `line_follow/arc` 크기 단위의 분리 계획이 필요하다. 단계 2는 P1a 착지를 기다린다. API reference를 판 올림한다(2항 출력).
- 기본은 꺼짐이다. `arc_enabled: false`면 오늘과 같다. Fleet은 `lane_arc` 능력이 없는 로봇에 `exit_segment`를 보내지 않는다.

### 남은 물음

- 구간 중간(ring 위)에서 시작하는 trip을 나중 결정으로 미뤄도 되는지. 이 문서는 범위 밖으로 둔다.

### SIM으로 정할 값

- `arc_gain_lateral_1pm2`(k_y, 시작 36)와 `arc_gain_heading_1pm`(k_θ, 시작 12). 시작값은 임계 감쇠 k_θ = 2√k_y이고, 거리 영역 시정수는 약 0.17 m다. 단계 2 SIM에서 처음 Δr 0.04 m 회복(0.25 m 안 ≤ 0.02 m)과 넘침이 없는 값으로 정한다.
- 장치 `arc_blind_max_m`: 단계 1 SIM의 구간 흐름(평균과 최대)에서 정한다. 정하기 전에는 장치에서 `arc_enabled`를 켜지 않는다.
- Fleet 원호 적합 허용치(시작 0.005 m): 실제 260919 `lane_graph.yaml` ring polyline의 원 적합 잔차를 재고 정한다. ring 네 호가 모두 들어와야 하고, 원호 아닌 굽이는 들어오지 않아야 한다.

### 개정 2026-10-09: ring은 지도 호 주행이 기본이고, 호는 odom에 놓은 지도 원을 따른다

사용자 결정(2026-10-09, "둘 다"): 260919 회전교차로 ring은 이제 호 주행으로 지나는 것이 기본이다. 경로 문맥을 인식에 주는 일([D-531](D-531-route-context-to-lane-keeper.md))은 다음 작업이고, 따로 ADR로 다룬다. 이 개정은 lap SIM 2·3(`docs/validation/lane-trip-lap-sim2-2026-10-08/`, `lane-trip-lap-sim3-2026-10-09/`)과 단계 1 SIM(`d520-arc-stage1-sim-2026-10-08/`, FAIL)의 원인 세 가지를 고친다.

1. **진입 회전각.** 1항 「회전각과 `advance_m`」을 고쳤다. `exit_segment`가 있어도 `turn_deg`는 D-507 4항의 `turn_target`이다. lead 접선 `theta`는 SW 입구에서 12–17° 틀렸다.
2. **원 추종(odom feed-forward + 반지름 보정).** 호를 열 때 CORE는 odom에 지도 원 하나를 놓는다.
   - 원을 놓는 법:
     - (a) 회전 뒤에는 회전 목표 yaw(진입 yaw + `turn_deg`, 지도 접선)를 접선으로 하고 지금 자리를 지나는 원이다. 회전이 목표에서 몇 도 덜 돌거나 더 돌고 끝나도, 로봇은 그 방향을 따르지 않고 원으로 돌아온다.
     - (b) 이어지는 `straight`는 앞 호의 원을 그대로 쓴다. 같은 odom 궤적, 같은 세대(사이에 모드 변경 없음), 같은 κ이고 앞 호가 이 장소에서 끝났을 때만이다. 회전은 늘 (a)다(안전 검토 2026-10-09: 지난 바퀴의 원을 다시 쓰지 않는다).
     - IR `level`의 기준 ψ₀ + κ·s에서 ψ₀도 (a)의 목표 yaw다(회전 끝 자세와 최대 5° 다름).
   - 매 틱 두 오차를 잰다. e_r은 원 밖으로의 거리이고 바깥이 +다. e_θ는 진행 방향 − 원 접선이다.
   - 명령은 ω = g·v·κ + v·c다.
     - c = clamp(sign(κ)·(k_y·e_r + I) − k_θ·e_θ, ±`ARC_MAX_CORRECTION_1PM` 1.5 1/m). I는 k_i·∫e_r ds(odom 길이)이고 |I| ≤ 1.0 1/m로 자른다. 이어지는 `straight`는 원과 함께 I도 이어받는다.
     - k_y 64 1/m², k_θ 16 1/m, k_i 150 1/m³이다. 거리 영역 극점은 −11.5, −2.3 ± 2.8i이다(Routh k_i < k_θ·k_y). 비례만으로는(시작값 36·12) 명령보다 덜 도는 로봇에서 일정한 바깥 어긋남이 남았다(lap SIM 4 첫 묶음: Gazebo가 0.08 m/s 호에서 약 15 % 덜 돌아 +0.02–0.04 m). 지금은 코드 상수다. 로봇별 값이 필요해지면 2항의 설정 키로 옮긴다.
     - IR 보정의 `away`·`level` 동안 c는 0이고 I도 쌓지 않는다.
   - |e_r| > `ARC_MAX_RADIAL_M` 0.075 m면 `lane_arc_edge`로 선다. IR이 칠한 선을 보는 자리는 약 0.0625 m이고 차로 반폭은 0.0925 m다. IR 보정 중에는 이 한도를 쓰지 않는다. 보정에는 2항의 멈춤(반대쪽·`centre`·두 번째 판정·`level` 상한·시간)이 있다.
   - **IR은 경로가 아니라 측정과 안전이다.** 호에서 처음 나온 `left`·`right` 판정은 2항대로 한 번 보정을 연다. 그 순간 원을 반지름 방향으로 옮긴다. 옮긴 원에서 몸은 그 쪽 칠한 선 중심보다 0.0325 m(테이프 반폭 0.0125 m + IR 줄 옆 0.020 m, Pinky URDF) 안쪽에 있다. 보정이 끝나면 옮긴 원을 따른다. 두 번째 판정에서 서는 규칙은 그대로다.
   - 그대로 두는 것: 매 틱 `motion_admitted`(kind `arc`/`arc_edge`), 그 틱 twist의 D-422 sweep, odom 길이 끝, 시간 한도, 모든 멈춤은 HOLD(호 기록 `stopped`)다.
   - **반지름.** 지도 차로 중심 반지름은 0.2514 m(`lane_graph.yaml`)이고, 칠한 두 선의 가운데는 (0.155 + 0.345)/2 = 0.250 m다. 둘은 1.4 mm 다르므로 따로 고르지 않고 지도 차로 중심(κ)을 따른다. 바깥으로 흐른 원인은 반지름이 아니었다. 원인은 진입 방향 12–17°(lap SIM 2)와 명령보다 덜 도는 곡률이었다(단계 1 SW: 진입 오차 +1–2°에서도 흐름 33 mm, 이득 1.1에서 16 mm).
   - **남는 한계.** odom 원은 odom이 맞는 만큼만 맞다.
     - 회전 축의 옆 오차(D-507 SIM 0.005–0.032 m)는 odom에 보이지 않는다.
     - 회전 끝의 odom yaw와 실제 yaw의 차도 보이지 않는다.
     - 카펫에서 odom yaw가 틀리면(D-500) 원도 같이 틀린다.
     - 그래서 IR 측정·두 번째 판정 멈춤·D-422가 남고, 장치 조건에 카펫 yaw 비가 남는다.
   - 단계 2(카메라 맞춤, 3항)는 그대로 남는다. 확신 있는 맞춤이 오면 e_r·e_θ의 출처가 된다.
3. **기본 켬.**
   - `line_follow.arc_enabled`의 기본은 true다. 능력 `lane_arc`는 `arc_enabled`와 현장 바닥 선언 `site_floor_map_id`(5항)가 함께 있을 때만 참이다.
   - 선언이 없는 로봇은 오늘과 같다. Fleet은 `exit_segment`를 보내지 않고, CORE는 받으면 409 `LANE_ARC_UNAVAILABLE`이다.
   - 바뀐 시작 규칙: 선언 없는 `arc_enabled: true`는 이제 시작 거부가 아니다. 능력만 거짓이다. `ir_guard_speed_scale` 0도 거부 대신 능력 거짓이다(한 번 보정을 할 수 없다). 선언 자체는 `ir_guard_enabled`·`obstacle_mode: path`·URDF 몸을 요구한다(D-507 9).
   - 지도 쪽 조건은 1항 그대로다. Fleet은 원호 적합을 통과한 `lane` 호(260919의 ring 네 호)에만 `exit_segment`를 싣는다. 원호 기하가 없는 지도와 장소는 오늘의 추종이다.
   - 끄는 스위치는 `arc_enabled: false`다.
4. **장치 조건(4항·7항 DEVICE의 "켜지 않는다"를 바꾼다).** 장치에서 호 주행은 다음 순서를 모두 지난 뒤에만 한다.
   - (1) 이 개정의 SIM 합격([lap SIM 4](../validation/lane-trip-lap-sim4-2026-10-09/result.md)).
   - (2) 아래 DEVICE 체크리스트.
   - (3) 사용자 승인.
   - 그 전까지 현장 바닥을 선언하는 장치 계획은 `line_follow.arc_enabled: false`를 함께 둔다. `tools/device_test/plan_rules.py`는 이 키를 false로만 받고, `site_floor_map_id`를 선언하는 계획에 이 키가 없으면 거절한다.
   - **남는 위험(안전 검토 2026-10-09, 사용자 판단).** 이 규칙은 장치 시험 계획만 지킨다. 계획 밖에서 로봇 overlay(`/var/lib/rosy/core/.rosy/rosy.yaml`)가 `site_floor_map_id`를 선언하면, 그 로봇은 다음 payload(D-412 자동 갱신 포함)부터 `lane_arc`를 알린다. 손 데모 overlay나 복원 전에 끊긴 시험이 그런 경우다. 저장소에서 이 키를 선언하는 것은 `d476_bridge_9dfk.yaml` 하나이고, 그 계획은 끝나면 overlay를 바이트 단위로 되돌린다. 장치 overlay를 직접 쓰는 사람은 DEVICE 체크리스트 전까지 `arc_enabled: false`를 함께 써야 한다. 코드로 막으려면 장치에서만 켜지는 수용 표지가 필요한데, 이는 이번 결정("추가 opt-in 없이 기본")과 맞서므로 사용자가 정한다.
   - SIM 합격선:
     - lap 12회 이상에서 각 ring 호의 참값 |Δr| ≤ 0.05 m.
     - IR 보정 0, `lane_arc_edge` 0, 벽 `near_stop` 0.
     - NE 회전으로 ring에 드는 trip 3회 이상에서 같은 기준.
   - DEVICE 체크리스트(7항 DEVICE 준비 그대로에 원 추종 항목을 더함):
     - D-507 9항 선언과 걷기 기록.
     - IR 보정.
     - 카펫 yaw 비(odom ÷ 실제)를 제자리 회전과 곡선 주행(κ 3.98, 0.08 m/s)으로 잰다. 곡선 비가 1 ± 0.05 밖이면 `arc_curvature_gain`만으로는 원 추종 기준이 틀리므로 켜지 않는다.
     - D-500 운동 응답으로 `arc_curvature_gain`을 정한다.
     - 시작은 SW 진입 한 번 → 호 하나다.
     - Δr과 끝 자리는 독립 기준(LiDAR-벽 정합 또는 Rosy Cam 천장 자세, 오차 ≤ 0.01 m)으로 판정한다.
     - 합격선은 위 SIM 합격선과 같다.
