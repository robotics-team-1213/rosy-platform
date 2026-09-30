# 도로 주행 행동 전이표 (D-384 결정 2·4)

**상태:** 제안(2026-10-01). 코드는 `src/runtime/services/core_features/road_behaviour/`, 시험은 `src/runtime/services/test/test_road_behaviour.py`다.

## 무엇인가

- CORE `traffic_policy`·`line_follow`가 가져다 쓰는 ROS-free 라이브러리다. CORE 안의 fail-closed 교통 정책은 하나이고 Command Manager 앞에 있다(D-151 §3–4, D-2).
- **명령을 만들지 않는다.** 출력은 `state`, `speed_cap_mps`, `path_choice`, `reason`, `events`뿐이다. CORE는 `speed_cap_mps`를 자기 상한들과 `min()` 한다.
- `step_behaviour(memory, inputs, params)`는 순수 함수다. 같은 기억과 입력이면 같은 결과가 나오므로 재생과 섀도에서 그대로 돈다.
- 필요한 입력이 `t_stale`(0.3 s)보다 오래됐거나 없으면 `FAULT`, 속도 0이다. 경계값 0.3 s는 신선하다. 미래 시각 입력은 오래된 것으로 본다.

## 운용 값

- 동작점은 0.03–0.08 m/s다(L1 0.30 rad/s 미만에서는 차선 자동을 거절한다). `v_cruise = 0.08`이고, 입력 `core_speed_cap_mps`가 있으면 그보다 크지 않다.
- 복도 길이는 `d0 + tau*v_cruise` = 0.25 + 1.5 × 0.08 = 0.37 m다. `HOLD`는 0.42 m를 넘어야 풀린다.
- 앞 로봇 추종 상한은 `(gap - d0) / tau`다(ISO 15622, `tau` 최소 0.8 s). 가까워지는 속도가 `v_cruise`보다 큰 이동 물체(마주 오는 것)는 따르지 않고 `HOLD`한다.
- **추월하지 않는다.** 장애물이 있을 때 경로 선택은 늘 `None`이고 속도만 줄거나 0이 된다.
- 정지 장애물 멈춤이 `obstacle_escalate_s`(5.0 s, `LineFollowConfig`와 같은 값) 이어지면 `nav.line_obstacle_hold`를 한 번 낸다. 멈춤이 풀리면 다시 무장한다. 보행자·양보 대기는 이 사건을 내지 않는다.
- `road_state` 단계: `TRACK`·`COAST`는 정상 상한, `SLOW`는 50 %, `STOP`은 0이다. `CROSS` 안에서는 차선이 안 보이는 것이 정상이라 단계를 보지 않는다.

## 교차로 (기본은 꺼짐)

- 교차로 상태는 지도 위치와 정지선 거리가 필요하다(D-378 §3.3–3.4). 그 입력이 아직 없으므로 `junction_logic_enabled = False`가 기본이다.
- 꺼져 있으면 `d_jn`(0.6 m) 안의 교차로는 `HOLD`, 이유 `junction_unsupported`다. 켜져 있어도 정지선 거리가 신선하지 않으면 같다.
- 켜져 있으면 모든 교차로가 일단정지다: `APPROACH`(0.05 m/s) → 선 앞 0.15–0.22 m에서 `STOP_AT_LINE` 1.0 s → `YIELD_CHECK` → `CREEP`(0.03 m/s, 1.0 s) → `CROSS`.
- 갈래 선택(켜져 있을 때만): 경로 > 오른쪽 > 직진 > 왼쪽. 오른쪽이 없으면 직진, 그다음 왼쪽이고, 갈래가 없으면 선에서 기다린다(`no_branch`). 경로가 가리킨 갈래가 없으면 추측하지 않고 기다린다(`route_branch_unavailable`). 경로 입력이 오래됐으면 오른쪽으로 대신하지 않고 기다린다(`route_stale`).
- 양보(도로교통법 제26조) 순서: 이미 교차로 안 → 넓은 도로(둘 다 알 때) → 먼저 도착(`t_tie` 0.5 s 넘게 앞섬) → 동시 도착이면 오른쪽 로봇 → 좌회전은 마주 오는 직진·우회전(의도 모름 포함)에 양보.
- 횡단보도(제27조): 보행자가 있으면 어느 상태든 0이다. 시간 초과로 풀지 않고, Fleet 허가로도 풀지 않는다.
- Fleet 허가(`fleet_grant`)가 있으면 로컬 선착순·오른쪽 규칙 대신 쓴다. 참이어도 장애물·보행자·교차로 안 로봇은 이기지 못한다. 거짓이거나 오래됐으면 기다린다.
- `CROSS`는 호 길이 × 1.3 안에 목표 차로를 잡지 못하면 `FAULT`(`nav.road_turn_timeout`)다.

## 전이표

아래 표는 `render_transition_table_markdown()`의 출력이다. 시험이 이 문서와 코드가 같은지 확인한다. 표를 고치려면 `table.py`를 고치고 다시 붙인다.

<!-- BEGIN generated: core_features.road_behaviour.render_transition_table_markdown() -->
| from | condition | to | speed cap |
|---|---|---|---|
| `LANE_FOLLOW`, `FOLLOW`, `HOLD` | static obstacle within d0 + tau*v_cruise (HOLD releases at + 0.05 m) | `HOLD` | 0 |
| `LANE_FOLLOW`, `FOLLOW`, `HOLD` | junction within d_jn, junction logic off or stop line unknown | `HOLD` | 0 (junction_unsupported) |
| `LANE_FOLLOW`, `FOLLOW`, `HOLD` | junction within d_jn, junction logic on, stop line fresh | `APPROACH` | v_app |
| `LANE_FOLLOW`, `FOLLOW`, `HOLD` | moving lead within corridor (not oncoming) | `FOLLOW` | (gap - d0) / tau |
| `LANE_FOLLOW`, `FOLLOW`, `HOLD` | corridor clear, no junction within d_jn | `LANE_FOLLOW` | v_cruise |
| `APPROACH` | junction known absent | `LANE_FOLLOW` | v_cruise |
| `APPROACH` | stop line <= d_stop_max (< d_stop_min adds overshoot event) | `STOP_AT_LINE` | 0 |
| `APPROACH` | stop line > d_stop_max | `APPROACH` | v_app |
| `STOP_AT_LINE` | stopped < t_stop | `STOP_AT_LINE` | 0 |
| `STOP_AT_LINE` | stopped >= t_stop | `YIELD_CHECK` | 0 |
| `YIELD_CHECK` | obstacle, pedestrian, no branch, robot in intersection, Fleet grant false/stale, or local right of way to another robot | `YIELD_CHECK` | 0 |
| `YIELD_CHECK` | all clear (Fleet grant true skips local ordering) | `CREEP` | v_creep |
| `CREEP` | static obstacle, pedestrian, robot in intersection, grant false/stale | `YIELD_CHECK` | 0 |
| `CREEP` | clear for < t_clear | `CREEP` | v_creep |
| `CREEP` | clear for >= t_clear | `CROSS` | v_cross |
| `CROSS` | target lane acquired | `LANE_FOLLOW` | v_cross |
| `CROSS` | travelled > 1.3 x arc length without target lane | `FAULT` | 0 |
| `CROSS` | turning (pedestrian or static obstacle: cap 0 in place) | `CROSS` | v_cross |
| `LANE_FOLLOW`, `FOLLOW`, `HOLD`, `APPROACH`, `STOP_AT_LINE`, `YIELD_CHECK`, `CREEP`, `CROSS` | a required input stale (> t_stale) or missing | `FAULT` | 0 |
| `FAULT` | lane inputs fresh and road_state TRACK | `LANE_FOLLOW` | v_cruise |
| `FAULT` | otherwise | `FAULT` | 0 |

| state | required inputs (junction logic on) |
|---|---|
| `LANE_FOLLOW` | `road_state`, `obstacles`, `junction` |
| `FOLLOW` | `road_state`, `obstacles`, `junction` |
| `HOLD` | `road_state`, `obstacles`, `junction` |
| `APPROACH` | `road_state`, `obstacles`, `junction`, `stop_line_distance` |
| `STOP_AT_LINE` | `obstacles`, `junction` |
| `YIELD_CHECK` | `obstacles`, `junction`, `pedestrian_at_crosswalk`, `other_robots` |
| `CREEP` | `road_state`, `obstacles`, `junction`, `pedestrian_at_crosswalk`, `other_robots` |
| `CROSS` | `obstacles`, `pedestrian_at_crosswalk`, `turn` |
| `FAULT` | - |
<!-- END generated -->

## CORE 통합 전 열린 질문(차선 유지 소유 세션)

1. CORE 어디서 부를지: `traffic_policy.gate()` 안인지 `line_follow` 틱의 상한인지.
2. `obstacles` 입력을 CORE `path_clearance` 결과에서 만들지, LiDAR 점에서 따로 만들지.
3. 0.03 m/s 미만 상한(추종 중 등)을 CORE가 0으로 볼지.
4. `STOP_AT_LINE` 1.0 s를 시간만으로 셀지, 측정 속도 0 확인을 더할지.
5. 로봇 도착 시각의 시계 기준(Fleet 시계와 로봇 시계).
6. 4방향 동점은 Fleet이 정한다. 허가 없이 동점이면 서로 기다릴 수 있다.
