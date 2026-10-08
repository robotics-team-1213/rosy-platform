## D-520 곡률을 아는 차로 구간(회전교차로 ring)에서는 CORE가 지도의 호(ω = v·κ)를 주 명령으로 달리고, 카메라는 바깥선을 원으로 맞춰 옆 보정만 준다 — 구간 기하는 D-507 교차로 지시에 실어 보내고, IR 가드와 D-422가 지킨다

**Status:** Proposed (2026-10-08, 문서만. 코드·API 변경 없음. 구현·SIM·DEVICE 수용은 별도). 사용자 결정(2026-10-08, D-507 SIM 3–4c차 원인 분석 뒤):
- 곡률을 아는 구간(ring)에서는 CORE가 지도 호를 주 명령으로 달린다(angular = v·κ, feed-forward).
- 카메라는 바깥선을 호로 맞춰 옆 보정을 준다.
- IR 가드와 D-422 몸체 정지가 지킨다.
- 단계 1은 feed-forward만(SIM에서 흐름 측정), 단계 2가 호 맞춤 보정이다.

이 문서의 계약 모양(1항), 상태 이름, 기본값, 합격선은 초안이다. 「사용자에게 묻는 것」의 답을 받아 Accepted로 올린다.

잇는 결정: [D-507](D-507-lane-trip-leg-structure-and-site-floor.md)(구간 상태 기계, 교차로 지시 필드, `motion_admitted`, 현장 바닥 선언) · [D-476](D-476-lane-loss-expected-road-bridge.md) 개정 2(명령 곡률로 잇는 호 bridge, 가장 가까운 친척) · [D-468](D-468-local-lane-departure-return.md)(이탈 복귀) · [D-491](D-491-ir-guard-crosswalk-zone.md)(IR 가드) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md)(몸체 기준 정지) · [D-18](D-18-rosy-core.md)(CORE가 유일한 최종 `cmd_vel` 발행자) · [D-489](D-489-fleet-route-planning-concept-and-algorithm.md)/[D-490](D-490-fleet-route-planner-implementation.md)/[D-494](D-494-fleet-trip-execution-m2-contracts.md)(Fleet 경로·trip) · [D-500](D-500-measured-motion-response-and-clearance-budget.md)(측정한 운동 응답, 카펫 odom yaw) · [D-400](D-400-core-safety-policy-off-shadow-enforce.md)(plan 3 전 enforce 금지, 그대로) · [D-517](D-517-multi-robot-lane-traffic.md)(통행권 끝에서 정지)

### Context

1. **ring 기하.** 260919 회전교차로(`map_v2_fleet/lane_graph.yaml`)의 차로 중심선 반지름은 약 0.2514 m(κ ≈ 3.98 1/m, 반시계 일방)다. 섬 쪽 선은 r 0.155 m, 바깥선은 r 0.345 m이고 두 선 중심 사이는 0.19 m다. spoke 입구 네 곳(장소 SW·SE·NE·NW)에서 바깥선이 끊긴다. 장소 사이 호는 4분의 1 바퀴, 약 0.39 m다.
2. **카메라는 섬 쪽 선을 차로 안에서 보지 못한다.** ring 위 keep 프레임(`X:\DevTemp\ring-diag`, `runs_r3`·`r4`·`r4c`의 `keepgeo.jsonl`을 참값 자세로 다시 본 것)에서 섬 쪽 선은 시야 밖이다. SIM 기울기 8°에서도, 실기 pitch 11.8°에서도 그렇다. 바깥선은 호 약 52°(base_link x 0.14–0.335 m)에서 보이고 로봇 진로를 가로지른다.
3. **직선 현 keeper는 ring을 따라가지 못한다.** `lane_keep.py`의 `extract_lines`는 선을 직선 조각으로 뽑고 30° 안에서 평행한 둘을 짝짓는다. ring에서 keeper는 바깥선의 가파른 현 하나를 얻는데 그 현이 차로 어느 쪽인지가 모호하다. 그 현을 네 입구로 보이는 spoke 선과 짝지어 바깥으로 흐르고, `no_boundary`·`flipping`·교차로 사유로 끝난다. D-507 SIM 4c차에서 회전각을 −9…+15°로 쓸어도 재획득 뒤 10 s 유지는 0/54였고, ring을 따라 간 거리는 0.014–0.151 m였다. 끝 자리는 ring 중심선보다 0.026–0.070 m 바깥이었다(`docs/validation/d507-lane-trip-sim-2026-10-08/result.md` 4c차, R3-3, R4-1, R4-2).
4. **문턱값으로는 고치지 못한다.** 보이는 선이 하나뿐이고 그 선은 진로를 가로지르는 곡선이다. 짝 각도·경계 거리 문턱을 바꿔도 직선 현 모형이 원의 한쪽 경계를 차로 경계로 바꾸지 못한다. IR(몸 아래 ±0.020 m)은 0.0925 m 떨어진 경계를 몸이 경계에 걸친 뒤에야 보므로 지킬 수만 있다.
5. **Fleet은 그 구간의 곡률을 안다. CORE는 모른다.** Fleet 지도 차로는 polyline이고 `width_m`, `drive_mode`, 장소를 갖는다. D-507 교차로 지시는 이미 장소마다 `map_id`, 기대 창, 회전각, `advance_m`을 실어 CORE에 간다(`POST /api/v1/line-follow/junction`, API Ref v1.141). D-476 개정 2의 호 bridge는 κ를 측정이 아니라 직전 추종의 명령 곡률에서 얻고, 0.23 m까지만 잇는다. ring에서는 그 직전 추종이 없다.
6. **ring 진입의 끝 자세가 ring 접선과 어긋난다.** D-507 4항의 직진 `advance_m` 0.10 m 동안 ring 접선이 약 23° 돈다. 그래서 현 각이든 접선 각이든 전진 끝 진행 방향은 접선과 −7…−36° 어긋났다(4c차). 같은 반지름의 원을 따를 때 처음 방향 오차 ε는 원 중심을 약 r·ε 옮긴다. 20°면 약 0.088 m로 차로 여유를 넘는다. 호 주행은 접선 방향에서 시작해야 한다.
7. **odom의 한계.** 실기 카펫에서 제자리 회전 odom yaw가 몇 배 틀린 관찰이 있다(D-500 Context, 9dfk). Gazebo 회전 응답은 명령보다 약 2.4 % 모자랐다(110° 회전에 +1.8…+3.0°).
8. **크기 한도.** `control` 패키지는 2026-10-08 기준 45251줄로 한도 45254까지 3줄 남았다. perception 쪽 추가는 P1a 단계(`docs/plans/2026-10-08-control-p1a-sensing-perception-split.md`)가 착지해 `sensing/perception`이 따로 세어진 뒤에만 들어갈 수 있다.

### Decision

1. **계약: D-507 교차로 지시에 나가는 구간의 기하를 싣는다.** 새 엔드포인트 `POST /api/v1/line-follow/route-segment`는 만들지 않는다. `POST /api/v1/line-follow/junction`에 선택 객체 `exit_segment` 하나를 더한다.
   - 필드: `curvature_1pm`(부호 있는 1/m, 왼쪽(반시계) +, 0.5 ≤ |κ| ≤ 5.0), `length_m`(이 장소에서 다음 장소까지 차로를 따른 길이, (0, 1.0]), `width_m`(그 차로 폭, [0.10, 0.40]), `end_place_id`(다음 장소). 지시의 `map_id`가 반드시 같이 와야 한다. 없으면 CORE는 지시 전체를 400으로 거절한다.
   - 뜻: "이 장소의 동작을 마친 뒤 로봇이 들어갈 차로는 반지름 1/|κ|의 원호이고, 다음 장소까지 `length_m`이다." Fleet은 그 차로 polyline이 한 원호에서 옆으로 0.005 m 안에 있고, `drive_mode: lane`이며, D-491 횡단보도 구역을 지나지 않을 때만 보낸다. 아니면 보내지 않고 오늘처럼 동작한다.
   - 능력 `lane_arc: true`(CORE가 이 객체를 받고 5항의 선언이 있음)가 있는 로봇에만 Fleet이 보낸다. 없으면 필드를 빼고 오늘처럼 보낸다.
   - 왜 이 계약인가: 교차로 지시는 이미 `place_id`·`seq`·만료·`map_id`·능력 확인·Fleet 포트(`LaneJunctionPort.send_junction`)·`armed` 상태를 갖는다. 호 구간은 늘 장소에서 시작해 장소에서 끝난다. 따로 엔드포인트를 두면 "어디서부터 길이를 재는가"를 교차로 상태 기계와 다시 맞춰야 한다. D-476의 경로 힌트(`set_bridge_route_hint`)는 방향만 담고 공개 API가 아니며 배선도 없어서 기하를 실을 수 없다.
   - 지시가 `exit_segment`를 실으면 Fleet은 `turn_deg`를 현(chord)이 아니라 장소에서의 **접선** 차이로 보내고 `advance_m`은 보내지 않는다(Context 6). `straight` 지시도 `exit_segment`를 실을 수 있다(ring 위 장소를 지나 계속 ring).
   - 구간 중간(ring 위)에서 시작하는 trip은 이 ADR 범위 밖이다. 호 주행은 교차로 지시로만 들어간다.

2. **CORE 호 주행(`arc`).** `line_follow.junction.state`에 새 단계 `arc`를 둔다. 코드는 `core_features/line_follow/recovery/lane_arc.py`(같은 매니저 잠금·generation·evidence revision, 새 스레드·저장소·발행자 없음, D-18)다.
   - **들어감.** (a) `exit_segment`가 있는 `left`·`right` 지시가 `turning`을 마쳤고 `pivot_basis`가 `map` 또는 `segment_end`일 때, `advancing`·`reacquiring` 대신 `arc`로 간다. (b) `exit_segment`가 있는 `straight` 지시가 장소를 지날 때(2항 끝남의 `segment_end`, 또는 오늘의 창 안 감지). `pivot_basis: stop_point`(축 근거 없음)면 호에 들어가지 않고 오늘처럼 전진·재획득한다.
   - **명령.** v = 그 trip의 차선 주행 속도(`min(cruise_speed, 수동 선속도 한도)`, 기본 0.08 m/s). ω = g·v·κ_c + v·(k_y·e_y + k_θ·e_θ). κ_c는 `curvature_1pm`, g는 로봇별 `line_follow.arc_curvature_gain`(기본 1.0, D-500 측정 운동 응답이나 보정 저장소에서 온 값), e_y·e_θ는 3항의 카메라 호 맞춤이 신선하고 확신 있을 때만이고 아니면 0이다. 보정 항은 |v·(k_y·e_y + k_θ·e_θ)| ≤ v·`arc_max_correction_1pm`(기본 1.5 1/m)으로 자르고, 전체 |ω|는 live 각속도 한도 안이다. 한도에 걸리면 같은 곡률로 v를 줄인다(D-344 §13, D-476과 같음).
   - **거리와 끝.** odom 경로 길이(매 걸음을 앞 자세 진행 방향에 투영한 부호 있는 합, D-507 3항과 같은 셈)가 `length_m`에 닿으면 끝난다. 시간 한도는 `length_m / v + STEP_MARGIN_S`다. 끝에서:
     - 다음 장소(`end_place_id`)의 지시가 이미 `armed`면, 그 지시의 축은 이 끝 자리다(`pivot_basis: segment_end`). keeper의 교차로 감지를 기다리지 않는다. 그 지시가 `left`·`right`면 정지 확인 뒤 회전하고, 다음 차로가 직선이면 오늘의 전진·재획득, 또 호면 다시 `arc`다. `straight`면 위 (b), `stop`이면 선다.
     - 지시가 없으면 오늘의 추종(`follow`)으로 돌아간다. ring 위라면 keeper가 다시 실패할 수 있고 그때는 오늘의 손실 경로(LOST)다.
     - 끝 자리의 odom 오차(진행 방향 m당 0.05, D-507 2항 `ODOM_DRIFT_PER_M`)는 Fleet이 다음 지시의 `expect_tol_m`에 이미 넣는다.
   - **운동 허가.** 매 틱 `motion_admitted(now, v, ω, kind='arc', map_id)`(D-507 6항)를 거친다. 새 kind `arc`의 IR 허용 값은 `clear`뿐이다(D-476 bridge와 같다). ring 위에서는 차로 안에 IR 밑을 지나는 선이 없으므로 `left`·`right`·`centre`는 몸이 경계에 걸쳤다는 뜻이다. `stale`은 언제나 거절이다. 후진은 없다.
   - **D-422 sweep.** 그 틱의 (v, ω) 호를 `_sweep_clear`가 그대로 쓴다. 직선 연장이 아니라 호를 쓸므로 섬 안이나 ring 바깥 벽이 직선 앞에 있다는 이유로 서지 않고, 호 위의 물체에는 선다. 틱 단위 D-422(`obstacle_ahead`)도 그대로다.
   - **멈춤(HOLD, `line_follow.reason`).** IR가 `clear`가 아님 → `lane_arc_edge`. D-422 몸체 sweep 미달 → `obstacle_ahead`. odom이 `stale_after_s`보다 낡음·끊김·frame/epoch 변경(D-468 7항 (2)의 불연속) → `lane_arc_pose_lost`. 스캔이 `clearance_stale_s`보다 낡음 → `lane_arc_motion_unconfirmed`. 모드 변경·E-stop·운전자 hold·새 지시 거절·지시 만료 → 오늘과 같은 사유. 시간 한도 초과 → `lane_arc_timeout`. 3항의 보정 없이 간 거리가 `arc_blind_max_m`을 넘음 → `lane_arc_blind`. 멈춘 뒤 다시 호로 들어가지 않는다. 지시는 `done`이 아니라 `aborted`로 기록되고 Fleet은 trip을 `stopped`로 끝낸다.
   - **호 주행 중 keeper 사유.** `no_boundary`, `flipping`, `junction_*`, `camera_line_not_visible`, `low_confidence`, 영상 품질 사유는 멈춤이 아니다. 3항 보정의 입력이 없다는 뜻일 뿐이다. 손실 시계(`_loss_started_at`)는 호 주행 동안 돌지 않고, 끝나면 그 자리에서 새로 시작한다. 교차로 감지는 지시를 쓰지 않는다(장소는 odom 끝이 정한다).
   - **다른 복구와의 관계.** 호 주행 중에는 D-476 bridge와 D-468 이탈 판정 (1)·(3)이 열리지 않는다. 둘 다 카메라 corridor에 기대는데, ring에서는 그 corridor가 직선 현 모형이라 틀린다. (2) 자세 불연속은 위 `lane_arc_pose_lost`로 멈춘다. 호에서 멈춘 뒤 D-468 복귀·역추적도 하지 않는다(HOLD, Fleet이 trip을 끝냄).
   - **D-491·D-517.** 횡단보도가 있는 구간에는 1항에 따라 호 기하가 오지 않는다. D-517 통행권 끝(`until_m`, `ttl_s`)은 호 주행에서도 추종과 같이 선다.
   - **설정**(`rosy_default.yaml`, 모두 기본 꺼짐): `line_follow.arc_enabled`(false), `arc_curvature_gain`(1.0, [0.8, 1.25]), `arc_max_correction_1pm`(1.5), `arc_blind_max_m`(아래 단계별), `arc_gain_lateral_1pm2`(36), `arc_gain_heading_1pm`(12). 이득 시작값은 거리 영역 임계 감쇠(k_θ = 2√k_y, 시정수 약 0.17 m)이며 단계 2 SIM에서 정한다. `arc_enabled: true`는 5항의 선언, `ir_guard_enabled`, `obstacle_mode: path`, URDF 몸을 요구한다. 없으면 CORE 시작 거부.

3. **카메라 호 맞춤(단계 2).** 반지름을 지도에서 알고 있으므로 원 전체를 맞추지 않고, 반지름을 고정한 원의 자리(옆 오프셋과 방향) 두 값만 맞춘다.
   - **입력(perception).** keep 모드 `line/keep_debug`에 `paint_points_m`을 더한다. 이미 계산한 BEV 도색 마스크(`lane_bev.py`)에서 base_footprint x 0.10–0.40 m 안의 도색 점을 최대 48개(고른 간격, mm 반올림)로 줄여 싣고, 영상 시각을 함께 둔다. 지원 표시는 `paint_points_v: 1`이다(`junction_ahead_v`와 같은 방식). perception은 선을 고르거나 맞추지 않는다. 어느 점이 바깥선인지는 지도를 아는 CORE가 정한다. 그래서 CORE → perception 경로 문맥 통로(D-507 「검토한 대안」이 미룬 `line/route_context`)가 필요 없다.
   - **맞춤(CORE, ROS 없는 함수, `recovery/lane_arc_fit.py`).** 지금 odom 자세와 호 시작 자세로 로봇 좌표의 예상 차로 중심원(중심 (0, 1/κ) 쪽, 반지름 1/|κ|)을 놓는다. 곡선 바깥쪽 선의 예상 반지름 R_o = 1/|κ| + `width_m`/2다. 영상 시각의 자세로 점을 옮긴 뒤, 예상 바깥원에서 반지름 방향으로 `arc_fit_gate_m`(0.03 m) 안의 점만 남긴다. spoke 선은 반지름 방향으로 뻗으므로 대부분 이 띠 밖에서 버려진다. 남은 점으로 R_o 고정 원의 중심 두 좌표를 가우스-뉴턴 두세 번으로 맞추고, 그 중심에서 e_y(x = 0에서 차로 중심원까지의 옆 오차, 바깥 +)와 e_θ(접선 대비 방향 오차)를 낸다.
   - **입구 공백.** 입구에서 바깥선이 끊기면 점이 적어질 뿐이다. 각 범위가 15° 이상이고 남은 점이 8개 이상이면 맞춘다. 공백 양쪽의 점도 같은 원 위이므로 함께 쓴다.
   - **확신.** 남은 점의 반지름 잔차 RMS ≤ 0.010 m, 각 범위 ≥ 15°, 점 ≥ 8개, 영상 나이 ≤ `stale_after_s`(0.3 s), 맞춘 e_y가 예상(0)에서 0.04 m 안. 넷을 다 만족하면 확신 있음이다. 0.04 m를 넘으면 틀린 선을 잡았을 수 있으므로 보정하지 않고 보정 없는 거리에 더한다. 엉뚱한 선 쪽으로 끌려가지 않는다.
   - **출력.** `line_follow.arc` 상태에 `e_y_m`, `e_theta_deg`, `fit_points`, `fit_span_deg`, `fit_rms_m`, `blind_m`(보정 없이 간 거리), `travelled_m`, `length_m`을 보인다. API reference는 구현 때 판 올림한다.
   - **크기.** CORE 쪽 맞춤은 `line_follow/recovery` 크기 단위 안이다. perception 쪽 추가(약 20–30줄)는 P1a 단계가 착지해 `sensing/perception`이 따로 세어진 뒤에만 넣는다. 그래서 단계 2는 P1a 뒤다. 단계 1은 perception을 바꾸지 않는다.

4. **보정 없는 거리 `arc_blind_max_m`.** 단계 1 빌드(SIM 전용)에서는 구간 길이 전체(보정 없음)를 허용해 흐름을 잰다. 장치 기본값은 단계 1 SIM의 흐름 측정에서 정한다. 그 전까지 장치에서는 `arc_enabled`를 켜지 않는다(6항 DEVICE는 단계 2 SIM 통과 뒤).

5. **현장 근거.** 호 주행은 D-507 6항 (a) enforce 또는 (b) site 근거가 있어야 한다. (b)의 바닥 근거는 D-507 9항 `line_follow.site_floor_map_id` 선언이고, 지시의 `map_id`가 그 값과 같아야 한다. 선언이 덮는 범위(차로와 그 바깥 0.30 m)는 호 주행이 벗어날 수 있는 거리(아래 6항 경계 + 정지 거리)보다 넓다. D-400 enforce는 바꾸지 않는다.

6. **안전 근거와 실패 방식.**
   - **feed-forward 흐름의 크기(계산, SIM으로 확인).** 같은 반지름의 원을 따를 때 처음 옆 오차는 그대로 남고, 처음 방향 오차 ε는 원 중심을 약 r·ε 옮긴다. 곡률 오차 δ(비율)는 반지름을 r·δ 바꾸고, 호 각 θ 뒤 옆 오차는 r·δ·(1 − cos θ)다. 4분의 1 바퀴(θ = 90°)에서 Gazebo 회전 부족 2.4 %는 약 0.006 m, 회전 오차 ±3°는 약 0.013 m, D-507 4차의 축 옆 오차는 0.005(SW)–0.032 m(NE)다. 합하면 0.02–0.05 m이고, 0.05 m 차로 여유 안이지만 NE에서는 여유가 거의 없다. 단계 2 보정이 필요한 이유다.
   - **카펫 odom·미끄럼.** 호 주행의 회전은 명령이 하고 odom은 거리와 끝만 잰다. 실제 곡률이 명령과 10 % 다르면 4분의 1 바퀴에서 약 0.025 m, 반 바퀴에서 약 0.05 m 벗어난다. 대응: 한 구간은 장소 사이 한 호(≤ 1.0 m, ring에서 약 0.39 m)뿐이다. 로봇별 `arc_curvature_gain`은 D-500 측정 운동 응답에서 정한다. 단계 2 보정이 붙는다. IR `clear`가 아니면 선다. DEVICE 판정은 odom이 아니라 독립 기준(LiDAR 벽 정합 또는 천장 카메라)으로 한다. odom 거리 오차(진행 방향)는 끝 자리를 m당 0.05 옮기고, 그것은 다음 지시의 기대 창이 덮는다.
   - **틀린 κ.** 지도와 바닥이 다르거나 Fleet 결함이면 로봇은 틀린 원을 돈다. 막는 것: `map_id`가 현장 선언과 같아야 함, 범위 확인(0.5 ≤ |κ| ≤ 5.0, 길이 ≤ 1.0 m), 단계 2에서 예상 바깥원에 점이 맞지 않으면 보정 없는 거리가 늘어 `lane_arc_blind`로 섬, IR 가드, D-422. 틀린 κ가 만드는 옆 오차는 IR 경계 정지 전까지 약 0.06–0.07 m(바깥선 안쪽 가장자리 0.0825 m − IR 0.020 m)다. 이 범위는 5항 선언의 0.30 m 안이다.
   - **구간 끝을 놓침.** 끝은 odom 길이로만 정한다. 시간 한도와 길이 한도가 둘 다 있어서 호 주행은 `length_m`을 넘어 계속되지 않는다. 다음 지시가 없으면 오늘의 추종으로 돌아가고, 그 추종이 실패하면 오늘의 LOST다.
   - **틀린 보정(단계 2).** 보정 항은 1.5 1/m로 잘려서 한 틱에 원을 크게 바꾸지 못한다. 예상에서 0.04 m 넘게 떨어진 맞춤은 쓰지 않는다. 보정이 없는 동안은 feed-forward만 남는다.
   - **진입 방향.** 호는 `turning` 직후 접선 방향에서 시작한다(1항의 접선 `turn_deg`, 직진 전진 없음). `pivot_basis: stop_point`이면 호에 들어가지 않는다.

7. **단계와 수용.**
   - **SOURCE.** 지시 검증(`exit_segment` 범위, `map_id` 없으면 400, 능력 `lane_arc`), `turning` → `arc` 전이와 `stop_point`에서 호 없음, ω = g·v·κ + 보정과 보정·전체 한도, odom 길이·시간 끝, `segment_end` 축으로 다음 지시 실행, 지시 없는 끝 → `follow`, 멈춤 사유 전부, kind `arc`의 IR 허용 값(`clear`만), 호 주행 중 keeper 사유 무시와 손실 시계 정지, 호 주행 중 D-476·D-468 (1)(3) 꺼짐, 호 sweep(직선 앞 점은 막지 않고 호 위 점은 막음), 설정 검증과 시작 거부, Fleet의 `exit_segment` 계산(원호 적합 0.005 m, 횡단보도 구간 제외, 접선 `turn_deg`). 단계 2: 고정 반지름 맞춤(합성 바깥선 + spoke 선 + 입구 공백 + 잡음), spoke 점 버림, 확신 조건, 0.04 m 밖 맞춤 버림. `arc_enabled: false`일 때 오늘의 결정 순서와 틱마다 같음(골든).
   - **SIM 단계 1(모델 PC, 이 노트북 아님, feed-forward만).** 4c차 놓기 자세(SW (−0.655, −0.432, 64°), NE (−0.0711, 0.4774, −117.8°))에서 각 3회. 진입 회전 뒤 다음 장소까지 호 하나를 달리고, 참값 자세로 ring 중심선에서의 반지름 방향 거리 Δr을 기록한다. 합격: 6/6 run 모두 호 전체에서 |Δr| ≤ 0.05 m, 구간 흐름(끝 Δr − 시작 Δr)의 평균 절댓값 ≤ 0.03 m, 벽 `near_stop` 0, `lane_arc_edge` 0. 함께 기록: 구간마다 시작 Δr·방향 오차, 끝 자리와 장소 사이 거리. 이 측정으로 장치 `arc_blind_max_m`을 정한다.
   - **SIM 단계 2(P1a 뒤, 보정 켬).** 같은 놓기 6회에 더해, 한 바퀴(SW 진입 → SE·NE `straight` → NW 진출) 3회. 합격: 모든 run에서 |Δr| ≤ 0.03 m, `lane_arc_blind` 0, NW 진출 뒤 spoke 재획득 3/3, 벽 `near_stop` 0. 처음 Δr을 0.04 m로 놓은 run에서 0.25 m 안에 |Δr| ≤ 0.02 m로 돌아옴.
   - **DEVICE(단계 2 SIM 통과 뒤, 사용자 승인).** 9dfk 또는 8kcn, D-507 9항 선언과 걷기 기록, IR 보정, 운동 응답 측정으로 정한 `arc_curvature_gain`. SW 진입 한 번 → 호 하나부터. Δr과 끝 자리는 odom이 아니라 독립 기준으로 판정한다.

### 범위 밖

- 구간 중간에서 시작하는 trip, 곡률이 변하는 차로(나선·S자)와 원호 아닌 굽이의 호 주행. 굽이 오감지(D-507 B9)는 그대로 그쪽 결정이다.
- keeper 직선 현 모형 자체의 수정. ring 밖 차선 추종은 바뀌지 않는다.
- D-400 enforce, D-468 역추적 한도, D-476 bridge의 변경.

### 검토한 대안

- **문턱값 고치기(짝 각도, 경계 거리, flip 래치).** 원인은 문턱이 아니라 모형이다. 차로 안에서 보이는 선은 진로를 가로지르는 바깥 곡선 하나이고, 직선 현 모형은 그 선의 쪽을 정하지 못한다. 4c차 54 run에서 회전각을 바꿔도 10 s 유지 0이었다.
- **섬 쪽 선 따르기.** 카메라가 차로 안에서 섬 쪽 선을 보지 못한다(SIM 8°, 실기 11.8° 모두). 카메라 각을 바꾸면 직선 차로의 시야와 D-378 기록·보정 전부가 바뀐다.
- **IR 경계 따르기.** IR은 몸 아래 ±0.020 m에 있다. 경계(0.0925 m)를 보려면 몸이 이미 경계에 걸쳐 있어야 한다. 그러면 0.05 m 여유를 늘 넘긴 채 달리게 된다. IR은 울타리로만 쓴다.
- **카메라만으로 호 맞춤(지도 곡률 없이 원 전체 맞춤).** 보이는 호는 약 52°뿐이라 반지름 0.345 m의 처짐이 약 0.035 m다. 반지름까지 맞추면 잡음에 약하고, spoke 선과 입구 공백에서 반지름이 크게 흔들린다. 보이지 않는 동안(입구, 영상 품질)은 명령이 없다. 지도 곡률을 주 명령으로 두면 카메라는 두 값만 맞추면 되고 카메라가 없어도 짧게 달릴 수 있다.
- **새 엔드포인트 `POST /api/v1/line-follow/route-segment`.** 길이를 재기 시작하는 자리를 교차로 상태 기계와 따로 맞춰야 한다. 지시 사이의 공백(Fleet 2 Hz)에서 호가 비고, `map_id`·능력·만료·`seq`를 다시 만들어야 한다. 호 구간은 늘 장소에서 시작하므로 교차로 지시에 싣는 쪽이 작다.
- **D-476 호 bridge를 늘리기.** κ가 직전 추종의 명령에서 오는데 ring에서는 그 추종이 없다. 거리 상한 0.23 m는 4분의 1 바퀴(0.39 m)보다 짧다.
- **ring 진입을 직진 전진 + 재획득으로 두고 회전각만 고르기.** 4c차가 기각했다(회전각과 무관하게 ring 추종 0.15 m 이하).

### Consequences

- ring 진입·통과·진출이 keeper의 ring 추종 없이 가능한 구조가 된다. 장소 사이 한 호는 지도 곡률과 odom 길이로 달리고, 다음 장소의 축은 odom 끝이다. 실차 수용은 단계 2 SIM 뒤다.
- CORE가 처음으로 지도에서 온 곡률을 명령에 쓴다. 그 값은 `map_id`와 현장 선언에 묶이고, 한 구간·한도·IR·D-422 안에서만 쓴다.
- ring 위에서는 keeper의 교차로 감지를 쓰지 않는다. 장소 위치 오차는 odom 거리 오차와 Fleet 기대 창이 진다.
- 단계 2는 P1a 착지와 API reference 판 올림(지시 필드, `line_follow.arc` 상태, keep_debug `paint_points_m`)을 기다린다.
- 기본은 꺼짐이다. `arc_enabled: false`면 오늘과 같다. Fleet은 `lane_arc` 능력이 없는 로봇에 `exit_segment`를 보내지 않는다.

### 사용자에게 묻는 것

1. 계약을 교차로 지시의 `exit_segment`로 할지(권고), 별도 엔드포인트로 할지.
2. 호 끝에 다음 지시가 없을 때 오늘의 추종으로 돌아갈지(이 초안, ring 위에서는 곧 LOST가 될 수 있음), 그 자리에서 HOLD할지.
3. 단계 1 합격선(|Δr| ≤ 0.05 m 전체, 평균 흐름 ≤ 0.03 m)과 단계 2 합격선(≤ 0.03 m)이 맞는지.
4. 호 주행 중 IR `left`·`right`에서 바로 멈출지(이 초안), 한 번 반대쪽으로 보정을 줄지.
5. 구간 중간(ring 위) 시작을 나중 결정으로 미뤄도 되는지.
