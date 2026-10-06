## D-476 차선을 잃으면 곧바로 멈추지 않고, 알던 차로의 연장선을 짧게 잇는다(예상 도로 bridge)

**Status:** Proposed (2026-10-06; 문서만, 코드 변경 없음. 기본 꺼짐, SOURCE/SIM/DEVICE/FIELD 수용 별도). D-468 결정 6의 "근거가 없는 reverse·spin·forward를 폴백으로 넣지 않는다" 가운데 forward 부분에 "근거"의 정의를 더한다(결정 4). D-384 개정 1 §1의 "COAST·SLOW는 CORE에 `visible = true`와 낮춘 신뢰도로만 전달된다"는 bridge가 켜진 동안 쓰지 않는다(결정 6). 기존 ADR 본문은 고치지 않는다. 고침 관계는 이 Status와 「기존 결정과 관계」에만 둔다.

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

### Consequences

- 짧은 도색 공백과 교차로 안에서 로봇이 알던 차로를 조금 더 가고, 다시 잡지 못하면 지금처럼 멈춘 뒤 D-468로 넘긴다.
- 기본 꺼짐이라 지금 동작은 바뀌지 않는다.
- forward 근거가 정의되므로, D-468의 다른 경로가 같은 정의 없이 forward를 쓰는 일은 여전히 금지다.

### Validation

- ROS-free 단위 시험: 진입 조건별 거부(영상 품질·장애물·침범·checkpoint 없음), 거리·시간 상한 정지, D-422 막힘 시 정지, 교차로 힌트 없음 HOLD, 재획득 → FOLLOW, 미재획득 → D-468 인계, `bridge_enabled = false`에서 기존 동작과 비트 동일.
- 재생 비교와 시뮬·장치는 결정 7의 순서를 따른다. 호스트 pytest 통과는 장치·현장 수용이 아니다.
