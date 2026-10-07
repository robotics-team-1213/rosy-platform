## D-476 차선을 잃으면 곧바로 멈추지 않고, 알던 차로의 연장선을 짧게 잇는다(예상 도로 bridge)

**Status:** Proposed (2026-10-06; 문서만, 코드 변경 없음. 기본 꺼짐, SOURCE/SIM/DEVICE/FIELD 수용 별도). D-468 결정 6의 "근거가 없는 reverse·spin·forward를 폴백으로 넣지 않는다" 가운데 forward 부분에 "근거"의 정의를 더한다(결정 4). D-384 개정 1 §1의 "COAST·SLOW는 CORE에 `visible = true`와 낮춘 신뢰도로만 전달된다"는 bridge가 켜진 동안 쓰지 않는다(결정 6). 기존 ADR 본문은 고치지 않는다. 고침 관계는 이 Status와 「기존 결정과 관계」에만 둔다. 개정 1(2026-10-07, 아래)이 진입 조건을 D-468 차로 안 증명에서 차선 추종 자신의 확신으로 바꾼다.

### Context

- **선을 잃으면 그 프레임에 멈춘다.** CORE `LineFollowManager`는 `FOLLOW`가 아니면 관측 없음·stale·`line_not_visible`·`low_confidence`마다 HOLD(영 twist)를 낸다(`middleware/core/services/core_features/line_follow/manager.py:493-507`). `lost_after_s`(3.0 s, `model.py:84`)가 지나면 `LOST` `reselection_required`로 잠그고 `nav.lane_lost`를 낸다(`manager.py:582-595`). 자동 재탐색은 없다.
- **CORE는 어디로 가던 중인지 모른다.** `LineFollowManager`는 경로, lane_graph 간선, 목표를 받지 않는다. 도색이 끊긴 곳(마모, 이음매, 반사, 교차로 안)에서도 로봇은 방금까지 따라온 차로를 잊은 것처럼 선다.
- **예상 도로는 섀도에만 있다.** D-384 `road_state`(`middleware/perception/control/sensing/perception/road_state.py`)는 주행기록계로 차로를 이어 COAST(`1.08·s_lost < 0.10 m`)·SLOW(`< 0.25 m`) 단계를 두고 시계 상한 2.5 s를 지킨다(`road_state.py:55-58`). `route_hint`(`left`/`straight`/`right`, `road_state.py:137-143`)로 교차로 동점을 깬다. 그러나 `road_state_node`는 명령을 내지 않고 제어 경로가 읽지 않는 섀도다(`road_state_node.py:2`, `:25`).
- **D-468은 뒤로 돌아가는 길만 있다.** `ReturnController`는 정상 차로 checkpoint `(pose, Corridor)`를 odom에 고정하고(`lane_return.py:266`, `:302`) 역추적·교대 재탐색·Fleet 순으로 간다(`lane_return.py:161`). 앞으로 가는 후보는 "근거 없음"으로 금지된다. 생산 연결(`bind_return_motion`)은 미병합 브랜치 `feat/lane-return-motion` 커밋 `6d39e52f4`에 있다.
- **D-463 Fleet 차선 경로는 지도에 정착한 로봇 전용이다.** `LOCALIZED`·지도 `pose_frame`일 때만 Nav2 목표를 보낸다. 차선 추종 로봇은 대개 정착하지 않았고, 이 경로는 line follow에 아무것도 주지 않는다.

### Decision

1. **기억은 D-468 checkpoint를 다시 쓴다.** 차선이 보이는 동안 마지막으로 확인한 차로 자세와 방향을 odom frame으로 유지한다. 새 저장소를 만들지 않는다. D-468 `ReturnController.checkpoint`와 `PoseTrail`을 그대로 쓰고, 무효화 규칙(frame 변경, 시각 역행, 큰 위치 점프, stale pose; D-468 결정 3)도 그대로 따른다.
2. **목표는 그 차로의 짧은 연장선 위 한 점이다.** 선을 잃으면 checkpoint 차로의 중심선을 odom에서 `bridge_lookahead_m`(d)만큼 늘린 점과 그 접선 방향을 국소 목표로 둔다. 지도 자세는 필요 없다.
   - **교차로:** 방향 힌트가 있을 때만 그 쪽으로 굽힌다. 힌트 출처는 (a) D-384 `route_hint`, (b) 진행 중인 임무·Fleet 경로가 내려 준 다음 lane_graph 간선의 방향(`left`/`straight`/`right`)이다. 힌트는 방향만이고 좌표가 아니다. 힌트가 없으면 교차로에서는 bridge를 하지 않고 기존대로 HOLD한다(D-384 개정 1 §3 `junction_logic_enabled = False`와 같다). D-384 결정 2의 "모르면 오른쪽"은 bridge의 근거가 되지 않는다.
3. **BRIDGE는 FOLLOW와 STOP 사이의 느린 단계다.**
   - **진입 조건:** 직전이 자신 있는 차로 내부 추종이었을 때만이다. 곧 D-468 정상 checkpoint가 유효하고, 직전 프레임까지 `FOLLOW`였으며, 소실 사유가 `line_not_visible`·`observation_stale`·`no_observation`(짧은 끊김)일 때다. `low_light`·`overexposed` 같은 영상 품질 실패, 장애물 정지(D-422), 차선 침범(`departure_stop`, D-468), 이미 진행 중인 stuck/YIELD에서는 들어가지 않는다.
   - **거리 상한:** 소실 시점부터 실제 odom 이동 거리로 잰다. 시작값은 D-384 사다리다: 0.10 m까지 순항 상한, 0.25 m까지 50 %, 그 뒤 STOP. 거리는 D-384와 같이 1.08배 해서 쓴다. 명령 적분을 이동 거리로 쓰지 않는다(D-468 결정 3).
   - **시간 상한:** `lost_after_s − 0.5 s`(D-384 개정 1 §1) 안이다. bridge는 손실 시계(`_loss_started_at`)를 되돌리거나 늘리지 않는다.
   - **안전:** 의도한 bridge 호를 따라 D-422 몸 기준 쓸기 판정이 비어 있어야 한다(전방 LiDAR + 기억 점 + 초음파, LiDAR 사각 하한 포함). IR 이탈 가드(D-344 §12)는 계속 적용된다. live 속도 상한, E-stop, 제어 권한은 그대로다. 출력은 기존 generation/evidence_revision으로 같은 CommandManager 경로에 제출한다(D-2, D-468 Consequences).
4. **D-468 결정 6에 대한 근거 정의.** 다음 셋이 모두 성립하면 forward bridge는 "근거 있는 forward"다: (a) 최근 확인된 차로의 연장선(결정 1·3의 진입 조건), (b) 결정 3의 거리·시간 상한, (c) 그 호를 따른 신선한 전방 여유(D-422). 하나라도 없으면 forward 금지는 그대로다. D-468의 나머지(reverse·spin 금지, 역추적, 재탐색, 복구 성공 판정)는 바꾸지 않는다.
5. **끝.** 재획득하면 `FOLLOW`로 돌아간다. 재획득은 D-468 결정 5와 같이 같은 저장 차로의 경계 위치·방향·차체 여유로 확인하며, 선이 보임만으로 끝내지 않는다. 상한 안에 재획득하지 못하면 그 자리에서 멈추고 기존 D-468 역추적·재탐색으로 넘긴다. 그 뒤 D-407/D-438 Fleet stuck 사건, 그리고 `LOST` 잠금 의미는 바뀌지 않는다.
6. **도색 공백과 도로 끝을 구별하는 것은 거리 상한이다.** 짧은 도색 공백은 상한 안에서 다시 잡힌다. 실제 도로 끝·막다른 곳은 상한에서 멈추므로 밖으로 달려 나가지 않는다. 벽이나 물체가 있는 도로 끝은 D-422가 먼저 멈춘다. bridge가 켜진 동안 D-384 COAST·SLOW를 `visible = true`로 CORE에 넣지 않는다. 같은 공백을 perception과 CORE가 두 번 잇지 않기 위해서다. D-384 출력은 bridge의 목표·힌트·비교 증거로만 쓴다.
7. **기본 꺼짐과 승격 순서.** 새 파라미터 `line_follow.bridge_enabled`(기본 `false`)와 `bridge_lookahead_m`, 거리·시간 상한을 둔다. 켜는 순서는 다음과 같다.
   1. 기록된 실주행(D-378/D-379 데이터 파이프라인)에 D-384 섀도 COAST 판정과 bridge 판정을 재생해 비교한다. 지표는 상한 안 재획득률, 재획득 시 `|Δd|`·`|Δφ|`, 도로 끝에서 상한을 넘긴 0건이다.
   2. 모델 PC 또는 사이트 PC의 시뮬레이션이다. 이 노트북에서 Gazebo를 돌리지 않는다.
   3. 사용자 승인 뒤 장치에서 녹화와 함께 시험한다.

   각 단계 통과 전에는 다음 단계로 가지 않는다. Proposed·구현은 지원 가능 표시가 아니다(D-468 결정 8).

### 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-468 | checkpoint·PoseTrail·무효화·재획득 판정을 재사용. 결정 6의 forward 금지에 근거 정의를 더함(결정 4). 생산 연결은 `feat/lane-return-motion` `6d39e52f4`에 의존하며 다시 구현하지 않음 |
| D-384 | COAST/SLOW 거리 사다리, 1.08 배율, `lost_after_s − 0.5 s` 상한, `route_hint`를 시작값과 힌트로 씀. bridge 켜짐 동안 개정 1 §1의 visible 전달은 쓰지 않음 |
| D-422 / D-344 §12 | 몸 기준 쓸기 정지와 IR 가드는 BRIDGE에서도 그대로 적용 |
| D-463 | 지도 목표는 쓰지 않음. 임무가 고른 다음 간선의 방향만 힌트로 내려 받음 |
| D-407 / D-438 | bridge 실패 뒤의 Fleet stuck 경로와 답변 계약 유지 |
| D-2 / D-369 | 최종 명령은 CommandManager 하나 |

### Alternatives

- **현상 유지(즉시 정지):** 안전하지만 도색 공백마다 서고, 3 s 뒤 LOST로 잠겨 사람이 다시 골라야 한다. D-407 배경의 2026-10-01 실주행 LOST 원인에도 차선 부재가 있다.
- **D-463 지도 Nav2 목표로 잇기:** 지도에 정착한 로봇만 가능하다. 차선 추종 로봇은 대개 정착하지 않았으므로 기각한다.
- **Fleet이 국소 목표를 내려 줌:** 왕복 지연과 단절 때문에 1 s 안팎의 공백에 맞지 않는다. Fleet 단절이 로컬 동작을 막으면 안 된다(D-468 결정 7). 기각한다.
- **D-384 COAST를 perception에서 `visible = true`로 넘김(개정 1 §1):** CORE가 bridge 중임을 모르고, D-422 판정과 거리 상한을 CORE가 소유하지 못한다. bridge가 켜진 동안은 쓰지 않는다.

### Open questions

- 값: `bridge_lookahead_m`, 거리 사다리(0.10/0.25 m 유지 여부), 속도 배율, 연속 bridge 사이 최소 재추종 거리. 운용 속도 0.03–0.08 m/s에서 0.10 m는 시계 상한 2.5 s보다 길 수 있다(D-384 개정 3).
- 교차로 힌트 배선: 임무·Fleet 경로의 다음 간선 방향을 CORE까지 어떤 기존 계약으로 내릴지. 공개 API·모드·필드를 새로 둘지는 D-18에 따라 구현 변경에서 정한다.
- 상태 노출: `GET /api/v1/line-follow`에 BRIDGE 상태를 새 state로 둘지, 기존 HOLD 사유로 둘지.
- 고침 표시: D-468과 D-384 본문에 "D-476이 고침" 줄을 둘지. 이 저장소는 고치는 쪽 ADR의 Status에 적는 관례(D-438)라 지금은 두지 않았다.
- `LOST` 시계: bridge와 D-468 역추적이 같은 3 s 손실 시계 안에 다 들어가는지, D-468이 이미 잠금을 늦추는지 구현 시 확인한다.
- **해결 (프로젝트 소유자 결정, 2026-10-06): 이중 bridge.** 결정 6을 그대로 둔다. bridge가 켜진 동안 D-384의 perception 쪽 COAST·`visible = true` 경로는 쓰지 않고, D-384 출력은 목표·힌트·비교 증거로만 쓴다. 이 질문은 닫혔다.
- **해결 (구현 확인, 2026-10-06): `LOST` 시계.** bridge는 `_loss_started_at`을 읽기만 한다. 잠금은 bridge가 있든 없든 첫 손실 틱에서 `lost_after_s` 뒤에 걸린다. D-468은 잠금을 늦추지 않는다. 대신 `reselection_required`가 D-468의 로컬 사유라서 역추적·재탐색은 `LOST` 잠금 뒤에도 자기 상한(이탈 뒤 12 s, checkpoint 뒤 5 s 역추적)으로 계속되고, 확인된 복귀(`corridor_verified`)가 `_release_stuck`으로 잠금을 푼다. 곧 D-468은 3 s 안에 다 들어갈 필요가 없다. 시험: `test_lane_bridge.py::test_lost_latches_on_the_same_clock_with_or_without_bridge_and_d468_continues`.
- **해결 (구현, 2026-10-06): 상태 노출.** 새 state나 필드를 두지 않는다. bridge 중에는 기존 `RECOVERING`(D-407·D-468이 이미 쓰는 값)에 사유 `lane_bridge`, 막힘은 `HOLD`에 `lane_bridge_blocked`·`lane_bridge_motion_unconfirmed`다.

### Consequences

- 짧은 도색 공백과 교차로 안에서 로봇이 알던 차로를 조금 더 가고, 다시 잡지 못하면 지금처럼 멈춘 뒤 D-468로 넘긴다.
- 기본 꺼짐이라 지금 동작은 바뀌지 않는다.
- forward 근거가 정의되므로, D-468의 다른 경로가 같은 정의 없이 forward를 쓰는 일은 여전히 금지다.

### Validation

- ROS-free 단위 시험: 진입 조건별 거부(영상 품질·장애물·침범·checkpoint 없음), 거리·시간 상한 정지, D-422 막힘 시 정지, 교차로 힌트 없음 HOLD, 재획득 → FOLLOW, 미재획득 → D-468 인계, `bridge_enabled = false`에서 기존 동작과 비트 동일.
- 재생 비교와 시뮬·장치는 결정 7의 순서를 따른다. 호스트 pytest 통과는 장치·현장 수용이 아니다.

## 구현 메모 (2026-10-06, CORE 쪽, feat/d476-lane-bridge)

Status 는 Proposed 그대로다. 기본 꺼짐(`line_follow.bridge_enabled: false`)이고 결정 7의 재생·시뮬·장치 단계는 하지 않았다. 호스트 pytest 통과는 장치·현장 수용이 아니다.

- 코드: `middleware/core/services/core_features/line_follow/lane_bridge.py`(mixin, 목표 기하). D-468 중재(`lane_return_decision.py`) 안에서 같은 잠금·generation·evidence_revision으로 돈다. `body_stop.py`·`clearance.py`(safety)는 고치지 않고 부르기만 한다.
- 진입: 직전 틱이 D-468 `tracking`이고 checkpoint가 있는 `TRACKING`이었고, 이번 사유가 `line_not_visible`·`observation_stale`·`no_observation`일 때만. 영상 품질, `obstacle_ahead`, IR 가드(`clear`가 아니면), `lane_departure`, 열린 stuck, `low_confidence`, `invalid_observation`에서는 들어가지 않는다. 한 손실에서 한 번 끝나면 다시 `TRACKING`을 거쳐야 재진입한다. D-468(`recovery_local_enabled`, containment 증거)과 path 모드 URDF 몸(`body_stop_known`, scan 점)이 없으면 bridge도 없다.
- 목표: checkpoint 차로 중심선을 odom에서 직선으로 늘리고, 로봇 투영점 + `bridge_lookahead_m`을 pure pursuit로 좇는다. 각속도가 live 상한을 넘으면 같은 호로 속도를 줄인다(D-344 §13).
- 상한: 실측 odom 경로 길이 × `bridge_distance_scale`(1.08)가 `bridge_coast_m`(0.10) 미만이면 `min(cruise_speed, 수동 선속도 한도)`, `bridge_slow_m`(0.25) 미만이면 × `bridge_slow_scale`(0.5), 그 뒤 끝. 시간은 `lost_after_s − bridge_time_margin_s`(2.5 s)에서 끝.
- 안전: bridge 호를 관리자 의도(`_intended`)로 두어 D-422 몸 쓸기(LiDAR + 기억 점 + 초음파 + 사각 하한)가 그 호를 잰다. bridge는 그 틱에 몸 간격이 재출발 간격 이하이면 멈추고, D-468 동작 증명(바닥 + 몸 쓸기)도 통과해야 한다. 제출 때(`apply_if_current`) D-468 `_return_submission_valid`가 bridge 중에도 늘 다시 검사한다(운전자 hold, 보정, 영상 품질, 자세 신선함, live 선속도·각속도 한도, 동작 증명). 열린 stuck에서는 bridge하지 않고, 손실 시계가 거꾸로 가면(`now < _loss_started_at`) 끝낸다. D-468 역추적 경로는 bridge가 끝나는 틱에 한 번만 다시 만든다.
- 끝: 재획득은 D-468 결정 5 검증(세 프레임, 같은 차로)을 거쳐 `TRACKING`으로 돌아간다. 상한에 닿거나 막히면 그 틱에 멈추고 D-468로 넘긴다. 넘길 때 D-468 역추적 경로를 bridge 이동을 포함한 실측 trail로 다시 만든다(`ReturnController.rebase_retrace`).
- 교차로 힌트: `LineFollowManager.set_bridge_route_hint(None|'left'|'straight'|'right')`, 기본 None. CORE에는 교차로 기하가 없어 None·`straight`만 직선으로 잇고 `left`·`right`는 bridge하지 않는다. 이 입력을 채우는 배선(D-384 `route_hint`, 임무 다음 간선 방향)은 없다. 공개 API·필드는 새로 두지 않았다.
- D-384: `road_state_node`는 `mode='shadow'`로 고정이고 제어 경로가 읽지 않으며, `core_features/road_behaviour`는 자기 시험 말고 import하는 곳이 없다. 지금 이중 bridge 경로는 없다.
- 남은 것: 값 조정, 힌트 배선, 연속 bridge 사이 최소 재추종 거리(지금은 `TRACKING` 한 틱으로 다시 무장), D-468 역추적은 checkpoint 뒤 5 s 안에서만 움직이므로(역추적 속도 0.03 m/s), 긴 bridge 뒤에는 역추적이 중간에 끝나고 재탐색으로 넘어간다.
- Context의 "생산 연결은 미병합 `feat/lane-return-motion`"은 지금 main과 다르다. `bind_lane_return_motion`이 이미 `middleware/core/gateway/core/node.py`에서 묶인다. 이 구현은 그 연결을 그대로 쓴다.

## 개정 1 (2026-10-07, 선택지 A): 진입은 차선 추종 자신의 확신에서, D-468 차로 안 증명과 분리

프로젝트 소유자 결정(2026-10-07, 선택지 A만)이다. 결정 1과 결정 3의 진입 조건 가운데 "D-468 정상 checkpoint가 유효"와, 구현 메모의 "D-468(`recovery_local_enabled`, containment 증거)과 동작 증명이 없으면 bridge도 없다"를 아래로 바꾼다. 나머지 결정(거리·시간 상한, D-422, 교차로 힌트, 끝, 승격 순서)은 그대로다. Status는 Proposed 그대로이고 기본은 꺼짐이다. 이 개정은 호스트 단위 시험까지만 했다. 재생·시뮬·장치 단계(결정 7)는 하지 않았다.

**왜.** 260919 트랙에서 Pinky의 좌우 유격은 한쪽 약 5 mm이고 차로 폭은 바꿀 수 없다. 320×240 카메라의 투영 불확실도는 25–100 mm이고 D-468의 상한은 15 mm다(`LaneReturnEvidence.MAX_UNCERTAINTY_M`). 그래서 이 카메라로는 차로 안을 증명할 수 없고 D-468 checkpoint가 생기지 않는다. 또 D-468 동작 증명(`return_sensor_allowed`)은 `control.sensor_adapter.mode == enforce`가 아니면 언제나 거짓이고, 장치는 D-400 계획 3 전까지 enforce가 아니다. 장치 기본값 `recovery_local_enabled: false`에서는 D-468 중재 자체가 돌지 않는다. 셋 중 하나만으로도 장치에서 bridge는 한 번도 돌 수 없었다(`docs/validation/d476-gazebo-model-pc-2026-10-06/result.md`).

1. **진입(무장).** 손실 직전 틱이 차선 추종 자신의 확신 있는 추종이어야 한다. 곧 그 틱의 상태가 `TRACKING`이고 사유가 `tracking`(IR 경계 회피 `lane_edge_*`가 아님)이며, 직전 `bridge_arm_frames`(기본 3)개의 받아들인 카메라 프레임이 모두 보였고 신뢰도가 `bridge_arm_confidence`(기본 0.5) 이상이다. 무장은 한 틱만 산다. 다음 틱이 다시 확신 추종이면 새로 무장하고, 아니면 연속 수를 0으로 되돌린다. 잘못된 프레임(`invalidate`)도 0으로 되돌린다. bridge 뒤 재획득하면 다시 세 프레임이 필요하다.
   - 기본값 근거: 0.5는 추종 하한 `min_confidence` 0.35보다 높아 신뢰도 배율 1/4 미만으로 겨우 조향하는 프레임은 무장하지 않는다. 3프레임은 D-468 결정 5의 재획득 프레임 수와 같고, 7.7–10 Hz에서 약 `stale_after_s`(0.3 s) 하나에 해당한다. `bridge_enabled`이면 `bridge_arm_confidence ≥ min_confidence`여야 한다.
   - 그대로 두는 조건: `bridge_enabled`(기본 `false`), 손실 사유가 `BRIDGE_REASONS`(`line_not_visible`·`observation_stale`·`no_observation`), 영상 품질 실패(`low_light`·`overexposed`)·`obstacle_ahead`·`low_confidence`·`invalid_observation`·`lane_departure`에서 진입하지 않음, 열린 stuck에서 진입하지 않음, IR 가드가 켜져 있으면 `clear`여야 함, 자세가 신선하고(0.3 s) 무장 때와 같은 epoch·frame, 시계가 거꾸로 가면 끝, 손실 시계(`_loss_started_at`)를 되돌리거나 늘리지 않음, 경로 힌트 `left`/`right`면 bridge 없음, 제어 권한(보정 중 아님, 수동 한도 계단, NOMINAL 지면이면 운전자 hold).
   - D-468이 켜져 있고 그 제어기가 `tracking`이 아닌 단계(진행 중인 복귀)면 bridge는 들어가지 않는다. 진행 중인 D-468 복귀가 로봇을 가진다.
2. **목표.** 무장 틱의 D-468 증거 장부 odom 자세(`LaneReturnEvidence`의 PoseTrail 마지막 표본)를 닻으로 둔다. 새 저장소는 없다. 그 틱에 D-468이 차로를 증명했으면(불확실도 ≤ 15 mm) 그 차로 중심선과 방향을 쓰고, 아니면 몸이 방금 따라온 선(닻 자세의 위치와 방향)을 쓴다. 좁은 차로에서는 유격(약 5 mm)이 이 선과 중심선의 차이를 묶는다. 이것은 투영 불확실도(25–100 mm)보다 작다. 그 선을 odom에서 직선으로 늘리고 지금처럼 pure pursuit로 좇는다.
3. **안전 근거(워커 바닥 증명 없이).**
   - D-422 몸 쓸기: bridge 호를 관리자 의도(`_intended`)로 두고 `body_path_gap`(LiDAR + range_min 아래 기억 점 + 초음파, LiDAR 사각 하한 포함)이 그 호에서 재출발 간격보다 커야 한다. 아니면 `HOLD lane_bridge_blocked`. 스캔이 `clearance_stale_s`보다 오래됐으면 막힘으로 본다. 틱 단위 D-422(`obstacle_ahead`)도 그대로다.
   - 제출 때(`apply_if_current`) 다시 검사: D-468 제어기가 없어도 bridge 결정은 언제나 다시 검사한다(운전자 hold, 보정, 영상 품질, 자세 신선함, live 선속도·각속도 한도, 같은 D-422 몸 쓸기).
   - 거리 사다리(실측 odom × 1.08, 0.10 / 0.25 m), 시간 상한(`lost_after_s − 0.5 s`), 속도 ≤ min(cruise, 수동 선속도 한도)는 그대로다.
   - **D-468 워커 바닥 증명.** (a) 살아 있으면(sensor adapter `enforce`) 지금처럼 bridge 명령마다 필요하다. 거절하면 `HOLD lane_bridge_motion_unconfirmed`. (b) 살아 있지 않으면(`off`·`shadow`) 요구하지 않는다. 게이트웨이는 `bind_return_motion(..., floor_proof_live=lambda: mode == "enforce")`로 알린다. 이 값을 읽지 못하거나 묶지 않았으면 필요한 것으로 본다(닫힌 쪽).
   - (b)의 근거: bridge는 전진만 하고, 카메라가 직전 확신 프레임에서 차로로 보여 준 방향으로만 간다. 쓸고 갈 호는 LiDAR 몸 쓸기가 덮는다. 길이는 실측 최대 0.25/1.08 ≈ 0.23 m이고 시간은 2.5 s 안이다. 바닥 증명은 지금 장치 어디에도 없으므로, (b)는 오늘 bridge 없이 확신 추종이 이미 달리던 근거보다 약하지 않다. 추종도 같은 바닥 증명 없이 달린다.
4. **남는 위험(정직하게).**
   - **바닥 끝·구멍.** LiDAR 스캔 면은 바닥 위라 낭떠러지나 구멍을 보지 못한다. 초음파는 물체만 본다. CORE IR 가드는 낭떠러지 검출기가 아니다. Pinky IR 세 개는 URDF에서 x = 0.0295 m로 몸 앞끝(약 0.042 m)보다 뒤, 몸 아래에 있어 앞쪽을 전혀 보지 않는다. 또 IR 선이 안 보이면 가드는 `clear`다. 그래서 enforce가 아니면 bridge 거리(최대 약 0.23 m + 정지 거리) 안의 바닥 끝·구멍은 아무 센서도 보지 못한다. 카메라가 직전 프레임에서 그 바닥을 차로로 봤다는 것만이 근거이고, 차로가 바닥 끝 때문에 사라졌다면 그 근거도 없다. 바닥 끝이 있는 곳(탁자, 단, 계단 근처)에서는 enforce 없이 bridge를 켜지 않는다. 260919 트랙은 바닥 위 둘레 벽 안이다.
   - **옆으로 벗어남.** 닻 방향은 마지막 확신 틱의 odom yaw다. 조향 흔들림만큼 방향 오차가 있고, 0.23 m에서 1°는 약 4 mm로 유격과 같은 크기다. IR 가드가 켜져 있으면 경계선이 측면 IR 밑에 오는 틱에 bridge가 끝난다. 기본 `ir_guard_enabled: false`에서는 거리 상한 말고 옆 울타리가 없다. 장치 단계 전에 IR 가드를 보정하고 켤 것을 권한다.
   - **낮은 물체.** 스캔 면 아래이고 초음파 원뿔 밖인 낮은 물체는 추종 때와 같이 보이지 않는다.
   - **도로 끝.** 결정 6 그대로 거리 상한이 구별한다.
5. **D-468과의 관계.** bridge는 `recovery_local_enabled`와 무관하다. 상한에 닿거나 막혀 끝나면, D-468이 켜져 있으면 지금처럼 넘긴다(`ReturnController.rebase_retrace`로 bridge 이동을 포함한 역추적). 꺼져 있으면 오늘의 HOLD(`camera_line_not_visible` 등)와 같은 손실 시계의 `LOST`로 간다. D-468 자체는 엄격한 그대로다. 차로 안 증명, 동작 증명, reverse·rotate 금지와 결정 6의 forward 금지는 바뀌지 않는다. 결정 4의 "근거 있는 forward" 정의 가운데 (a)는 이 개정의 진입 조건으로 읽는다. 이 근거 정의는 bridge에만 쓰이고 D-468의 다른 경로에는 쓰지 않는다.
6. **외부에 보이는 것.** 새 상태·필드·사유는 없다. `RECOVERING lane_bridge`, `HOLD lane_bridge_blocked`·`lane_bridge_motion_unconfirmed` 그대로라 API reference는 바꾸지 않았다. 새 설정은 `line_follow.bridge_arm_confidence`, `line_follow.bridge_arm_frames`다(`rosy_default.yaml`).
7. **시험.** `middleware/core/services/test/test_lane_bridge.py`: 좁은 트랙(불확실도 0.05 m, D-468 차로 안 거짓, `recovery_local_enabled false`, 바닥 증명 살아 있지 않음)에서 무장·전진, 증명되지 않은 목표는 따라온 odom 선, 무장 거부(신뢰도 낮음, 프레임 부족, 연속 끊김, `low_light`, `obstacle_ahead`, IR 가드 not clear, 열린 stuck, 힌트 left/right), 몸 쓸기 막힘 → `HOLD lane_bridge_blocked`, 거리·시간 상한, 손실 시계 불변, D-468 꺼짐 소진 → HOLD 뒤 같은 시계의 LOST, enforce에서 바닥 증명 필요, 제출 때 재검사. 기존 OFF 비트 동일 시험과 D-468 인계 시험은 그대로 통과한다. `middleware/core/gateway/test/test_lane_return_sensors.py`: 바닥 증명 liveness는 enforce에서만 참.
