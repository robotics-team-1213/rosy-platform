## D-495 차선 로봇은 교차로에서 멈춘 뒤 Fleet이 지도에서 정한 각도만큼 제한된 회전 동작을 하고 새 가지에서 차선 추종을 다시 잡는다 — 교차로 감지와 bridge는 로봇 기본값으로 켠다

**번호:** 처음 D-492로 적었으나 다른 브랜치가 D-492를 쓰고 main에 D-491(IR 가드)이 먼저 착지해 2026-10-07 착지 전에 D-495로 옮겼다(M2 계약 D-491 → D-494).

**Status:** Proposed (2026-10-07, 사용자 결정 2건: "회전 동작 먼저, 분기 인식 출력은 후속" · "로봇 기본값을 켜기"). [D-494](D-494-fleet-trip-execution-m2-contracts.md) 4항과 그 구현 부록(2026-10-07)의 한계를 메운다. 실차 이동·릴리스 승격은 아래 수용 절차를 따른다.

잇는 결정: [D-494](D-494-fleet-trip-execution-m2-contracts.md)(교차로 지시 API) · [D-476](D-476-lane-loss-expected-road-bridge.md)(예상 도로 bridge, 기본 꺼짐) · [D-468](D-468-local-lane-departure-return.md)(이탈 복귀) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md)(몸체 기준 근접 정지) · [D-489](D-489-fleet-route-planning-concept-and-algorithm.md)(교차로 동작 각도 θ) · [D-18](D-18-rosy-core.md)(CORE가 유일한 최종 `cmd_vel` 발행자)

### Context

1. D-494 구현 조사(2026-10-07)에서 확인한 것: CORE가 받는 차선 관측(`line/observation`)에는 분기 후보·방향이 없다. 교차로 신호는 keep 모드 keeper의 `junction_transverse`/`junction_fork`뿐이고, 이것도 `lane_corner_turning`이 켜졌을 때만 나온다. 로봇 기본값(`middleware/perception/config/line_follow.yaml`)은 꺼져 있다. 그래서 `left`/`right` 지시는 `junction_unresolved`로 멈추고, "지시가 없으면 교차로에서 멈춤"도 기본 설정의 로봇에서는 작동하지 않는다.
2. 교차로를 `straight`로 지나가려면 D-476 bridge가 필요한데, 이것도 기본값이 꺼져 있다(`rosy_default.yaml` `bridge_enabled: false`). D-476은 "리플레이 → 모델 PC 시뮬레이션 → 장치를 통과할 때까지 꺼 둔다"고 정했다. `docs/validation/d476-gazebo-model-pc-2026-10-06/`이 시뮬레이션 증거다.
3. Fleet은 지도에서 각 교차 장소의 들어오는 차로와 나가는 차로를 알고, 그 사이 각도 θ를 이미 계산한다(D-489 교차로 동작).

### Decision

1. **제한된 회전 동작(CORE).** `POST /api/v1/line-follow/junction`의 `left`/`right`가 선택 필드 `turn_deg`(부호 있는 각도, |θ| ≤ 150°)와 `advance_m`(0–0.30 m, 기본 0.10)을 받는다. Fleet은 지도의 θ를 `turn_deg`로 보낸다. 교차로가 감지돼 로봇이 멈춘 뒤 CORE line-follow 매니저가 순서대로 실행한다.
   - (a) **제자리 회전**: odom yaw로 닫힌 고리를 돌려 `turn_deg`만큼 돈다. 각속도는 수동 한도 이하로 하고, 목표 ±5°에서 멈춘다.
   - (b) **짧은 전진**: `advance_m`만큼 직진한다. 속도는 trip 최고 속도의 절반 이하다.
   - (c) **차선 다시 잡기**: 차선 추종을 다시 켜고, `reacquire_m`(기본 0.20 m)을 가는 동안 차선을 `visible`·신뢰도 기준 이상으로 다시 잡아야 한다. 못 잡으면 멈추고 `junction_unresolved`다.

   동작마다 시간 한도(회전 `|θ|/ω_min + 2 s`, 전진·재획득 각 5 s)가 있다. 다음 경우 즉시 멈추고 상태를 `aborted`로 둔다: odom 낡음·점프, E-stop, 모드 변경, D-422 몸체 기준 근접 정지, 시간 초과, 새 지시. 이 동작은 모두 CORE 매니저의 명령 경로 안에서만 이루어지며 최종 `cmd_vel` 발행자는 CORE 하나다. `turn_deg`가 없는 `left`/`right`는 지금처럼 `junction_unresolved`다(옛 Fleet 호환). 상태 `line_follow.junction.state`에 `turning`·`advancing`·`reacquiring`·`aborted`를 더한다.
2. **교차로 감지와 bridge를 로봇 기본값으로 켠다.** `line_follow.yaml` `lane_corner_turning: true`, `rosy_default.yaml` `bridge_enabled: true`.
   - 효과: 모든 차선 주행에서 교차로 앞 정지(D-494 "지시 없으면 멈춤")와 짧은 차선 소실 bridge가 작동한다.
   - D-476의 "꺼 둔다"를 이 ADR이 개정한다. 다만 **릴리스 수용 절차는 남긴다**: 이 기본값이 들어간 페이로드는 모델 PC Gazebo `map_v2_fleet_real`(교차로·bridge·회전 동작 포함 한 바퀴)과 실기 차선 한 바퀴를 통과해야 robots에 승격한다. 이 노트북에서는 Gazebo를 돌리지 않는다.
   - 되돌리기는 카드 설정(`/boot/firmware/rosy-config.yaml`) 또는 로봇 패키지 설정으로 두 값을 끈다. 코드 변경은 필요 없다.
3. **Fleet trip 루프(D-494 5항)는 `lane` 간선의 좌·우 교차로에 `turn_deg`를 보낸다.** 직진은 `straight`, 마지막은 `stop`이다. 로봇 능력(D-494 1항)에 `junction_turn: true`가 없으면 좌·우가 있는 `lane` 계획의 실행을 열지 않는다(`TRIP_MODE_UNSUPPORTED`).
4. **분기 인식 출력은 후속 ADR이다.** 차선 인식이 `branches [{direction, heading_deg, confidence}]`를 내고, 회전 동작 대신 그 가지를 따라 꺾는 방식은 별도 ADR로 정한다. 그때 교차로 판정도 표시 토픽(`line/keep_debug`)이 아니라 `line/observation`으로 옮기는 것을 같이 정한다. 이 ADR의 회전 동작은 그 뒤에도 분기를 인식하지 못할 때의 대체 경로로 남는다.

### 범위 밖

- 분기 인식 출력과 가지 추종(4항 후속). `free`(Nav2) 로봇의 교차로. 여러 로봇 교차로 예약.

### 검토한 대안

- **분기 인식 먼저.** 인식·제어 양쪽에 큰 작업이고 Gazebo 검증이 길다. 사용자는 회전 동작을 먼저 고르고 분기 인식을 후속으로 두었다.
- **trip 중에만 교차로 감지를 켜기.** 일반 차선 주행과 trip 사이에 동작이 달라져 현장에서 설명하기 어렵다. 사용자는 기본값으로 켜기를 골랐다.
- **Fleet이 회전 속도를 직접 낸다.** D-18 위반이다. Fleet은 각도와 거리만 정하고 CORE가 실행한다.

### Consequences

- 9dfk 같은 차선 전용 로봇이 지도 경로의 좌·우 교차로를 지날 수 있다. 이것은 회전 동작이 실차에서 통과한 뒤의 이야기다.
- 차선 주행 전체에서 교차로 앞 정지와 bridge가 기본으로 켜진다. 현장에서 교차로마다 멈추는 것이 기본 동작이 된다. trip이 아니면 운영자가 Pilot이나 지시로 이어 간다.
- 수용 기준:
  - SOURCE: 회전·전진·재획득 상태 전이, 각 중단 조건, 각도 오차 ±5°, `turn_deg` 없는 옛 요청, 기본값 변경과 되돌리기 설정, Fleet의 `turn_deg` 전송과 능력 거절
  - SIM(모델 PC): `map_v2_fleet_real` 좌·우·직진 교차로가 포함된 trip 한 바퀴
  - DEVICE: 9dfk 차선 한 바퀴와 교차로 회전 한 번(사용자 승인, 마커·Rosy Cam 맞춤 뒤)

### 구현 메모 (2026-10-07, feat/d491-core-junction-action)

결정 본문은 바꾸지 않는다. 구현에서 정한 것과 확인한 것이다.

1. **회전 동작 위치.** `core_features/line_follow/junction.py`가 매니저 틱 안에서 결정의 twist만 바꾼다. 같은 generation·evidence revision으로 CommandManager에 간다. 최종 `cmd_vel` 발행자는 그대로 CORE다.
2. **수치.** 회전 각속도는 `clip(2·|오차|, min(0.3, 한도), 한도)` rad/s이고, 한도는 수동 각속도 한도와 `max_angular` 중 작은 값이다. 시간 한도의 ω_min은 `min(0.3, 한도)`다. 전진 속도는 `0.5·min(line_follow.max_linear, 수동 선속도 한도)`이다. CORE 매니저는 Fleet용 `trip_max_linear`를 모르므로 이 값으로 trip 최고 속도의 절반 이하를 지킨다. `left`는 `turn_deg > 0`, `right`는 `< 0`이어야 한다. 아니면 400이다.
3. **재획득.** 전진이 끝난 틱은 0을 내고, 다음 틱부터 기존 차선 추종이 움직인다. 그 뒤 받은 신선한 visible 프레임(신뢰도 `min_confidence` 이상) 하나로 끝난다. odom 0.20 m 또는 5 s 안에 못 잡으면 `unresolved`다. 끝나면 직전 교차로 감지 기록을 지운다. 그래야 방금 지난 교차로로 `waiting`에 다시 걸리지 않는다.
4. **중단.** odom이 0.3 s보다 낡았거나 PoseTrail이 끊긴 경우, 모드 변경(E-Stop 포함), D-422 몸체 간격(회전·전진 twist 기준), D-468 동작 확인 실패, 각속도·선속도 한도 0, 열린 stuck, 시간 초과, 새 지시가 중단 이유다. 운전자 확인 만료·IR 이탈 감시처럼 차선 시야와 무관한 기존 HOLD 사유도 중단으로 친다. 모드 변경으로 생긴 `aborted`는 다음 모드 변경에서 지운다. 그 밖의 `aborted`는 다음 지시까지 HOLD다. 새 지시는 진행 중인 동작을 멈추고 자신은 받지 않는다(`accepted: false`).
5. **동작 중 손실 시계.** keeper의 교차로 HOLD가 시작한 차선 손실 시계는 회전 시작과 전진 중에 지운다. 지시가 운영자의 재선택 역할을 한다. 그러지 않으면 회전 중 `LOST`가 잠긴다. D-468 복귀 제어기도 동작 중에 지워서, 끝난 뒤 옛 차로로 되돌아가지 않게 한다.
6. **되돌리기 경로 확인.** 카드 설정 `/boot/firmware/rosy-config.yaml`(`rosy_config.py`)은 정해진 최상위 키만 받는다. 그래서 이 두 값을 끌 수 없다. `bridge_enabled`는 CORE 설정 겹(`~/.rosy/rosy.yaml` 또는 `ROSY_CONFIG`, `line_follow.bridge_enabled: false`)으로 코드 변경 없이 끈다. `lane_corner_turning`은 운영자 겹(`/etc/rosy/line_observer_overrides.yaml`)의 허용 키가 아니다. 그래서 지금은 페이로드의 `line_follow.yaml`을 바꾸는 릴리스로만 끌 수 있다. 결정 2의 "카드 설정으로 끈다"를 지키려면 허용 키를 넓히는 별도 변경이 필요하다.
7. **bridge 전제.** D-476 bridge는 D-468 안에서만 돌고 `recovery_local_enabled`가 켜져야 한다. 이 값의 기본값은 꺼짐이다(`rosy_default.yaml`). 따라서 `bridge_enabled: true`만으로는 그 값을 켠 로봇에서만 bridge가 작동한다.
8. **차선 모드.** `lane_corner_turning`의 교차로 HOLD는 keep 모드에서만 나온다. 기본 `camera_lane_mode`는 `line`이므로, 교차로 정지와 회전 시작은 keep 모드 로봇에서만 일어난다. `lane` 모드에서는 같은 값이 odom 기반 모서리 회전기를 켠다.
9. **능력 필드.** `junction_turn: true`는 이 브랜치에 넣지 않았다. `feat/d491-robot-trip-contracts`가 같은 `controls.py`·`api/v1/system.py` 줄을 고치기 때문이다. 착지 순서를 정할 때 그 브랜치에서 더한다.

### 결정 개정 (2026-10-07, 사용자 결정, 구현 메모 6·7·9항을 대신한다)

1. **trip 로봇은 keep 모드로 달린다.** 교차로 감지(`lane_corner_turning`)는 keep 모드에서만 작동한다. 따라서 `lane` trip은 keep 모드 로봇에서만 연다. 9dfk는 배포할 때 운영자 겹에서 `camera_lane_mode: keep`으로 바꾼다. 배포 뒤 장치 확인(차선 한 바퀴, 교차로 정지 한 번)을 해야 trip을 연다.
2. **`recovery_local_enabled` 로봇 기본값을 켠다**(`rosy_default.yaml`). 이 값은 D-468 로컬 차선 복귀, D-476 bridge, D-407 로컬 후진의 전제다. D-407 로컬 후진은 로봇 패키지의 URDF 몸 기하가 있을 때만 움직인다. 승격 규칙은 2항과 같다. 모델 PC Gazebo `map_v2_fleet_real` 한 바퀴와 실기 차선 한 바퀴를 통과한 페이로드만 robots에 간다. 이 결정은 D-407 결정의 "로컬 복구 기본 꺼짐"과 D-468 확인 문단의 "장치 기본 false"를 개정한다.
3. **되돌리기.** `bridge_enabled`와 `recovery_local_enabled`는 CORE 설정 겹(`~/.rosy/rosy.yaml` 또는 `ROSY_CONFIG`, `line_follow.<키>: false`)으로 코드 변경 없이 끈다. `lane_corner_turning`은 운영자 겹과 카드 설정에 넣지 않는다(사용자 결정). 끄려면 페이로드 `line_follow.yaml`을 바꾸는 릴리스가 필요하다. 2항의 "카드 설정으로 끈다"는 이렇게 고친다.
4. **능력 `junction_turn`의 뜻.** CORE `LineFollowManager.supports_junction_turn`이 참일 때만 `true`다. 참이 되려면 세 조건이 모두 맞아야 한다. 최근 2 s 안에 받은 신선한 `line/keep_debug` 프레임이 `corner_turning: true`를 실어야 한다. 이 토픽은 keep 모드에서만 나오므로 keep 모드라는 증거가 된다. 그리고 이 매니저에 제한 회전이 있어야 한다. 관측 노드의 lane mode와 flag는 인식 파라미터라서 CORE 설정에 없다. 그래서 이 근거로 판정하고, 프레임이 없으면(카메라 정지, `line` 모드, flag 꺼짐) `false`다. 필드는 `feat/d491-robot-trip-contracts`가 `getattr(svc.line_follow, "supports_junction_turn", False) is True`로 읽는다. Fleet은 `junction_turn`이 없거나 거짓인 로봇에서 좌·우가 있는 `lane` 계획을 `TRIP_MODE_UNSUPPORTED`로 거절한다(결정 3).
5. **D-407 로컬 후진 포함(사용자 결정, 2026-10-07).** 기본값을 켜면 D-407 자율 로컬 후진도 같이 켜진다. 대상은 로봇 패키지에 URDF 몸 기하가 있는 모든 로봇이다. 사용자는 이것을 알고 2항을 그대로 두었다. D-407의 "로봇 self-mask 측정이 끝났어야 켠다" 조건은 이 결정의 승격 규칙으로 바뀐다. 승격 규칙은 모델 PC SIM 한 바퀴와 실기 차선 한 바퀴를 통과한 페이로드만 robots에 가는 것이다. 시험 `test_line_follow_stuck_api.py::test_packaged_default_backs_off_on_a_body_geometry_robot`이 포장 기본값과 Pinky 설정에서 후진이 나오는 것을 고정한다.

### 독립 안전 검토 반영 (2026-10-07, REQUEST CHANGES 대응)

검토 지적(H1, M1–M8, L1–L6)을 이렇게 고쳤다. 결정 본문과 앞 절의 번호는 바꾸지 않는다.

1. **H1 카메라 앞 오프셋.**
   - 페이로드 `middleware/perception/config/line_follow.yaml`의 `camera_x_offset_m`은 `0.03317`이다. 출처는 `middleware/apps/device/pinky/profile/config/camera_nominal.yaml` `x_offset_m`이다. 이 값은 URDF 공칭 값이다(`geometry.yaml` camera.*, `cam_tilt_deg` 8). 로봇별 보정이 이 값을 다듬는다.
   - 이전 값 0.0은 모서리·교차로 기하를 33 mm 짧게 쟀다. 이 값은 D-468 containment의 기하도 바꾼다.
   - `map_v2_fleet_real.launch.py`는 이제 `lane_corner_turning`·`camera_x_offset_m`을 덮어쓰지 않는다. 그래서 SIM 수용 바퀴는 페이로드 값으로 돈다. 시험 `test_acceptance_lap_runs_the_payload_corner_and_offset_values`가 이것을 고정한다.
   - `map_v2_fleet_lane.launch.py`는 25° 시뮬 카메라용 별도 값(0.028481)을 그대로 쓴다. 이 launch는 수용 바퀴가 아니다.
   - `lane_corner_turning`은 keep 모드의 교차로 HOLD 말고도 두 가지를 켠다. `lane` 모드의 모서리 회전기와 `edge_left`의 모서리 넘김이다.
2. **M1 전진 시간 한도.** `advance_m / 전진 속도 + 2 s`다. 0.30 m 전진이 끝나는 것을 시험한다.
3. **M2 보정 lease.** 회전 시작과 동작 중 매 틱에 `calibration_active`가 False가 아니면 `aborted`(`calibration_active`)다. D-468·D-476과 같은 규칙이다.
4. **M3 같은 지시 재전송.** 동작 중에 같은 지시가 다시 오면 아무것도 바꾸지 않는다. 같다는 것은 `place_id`, `action`, `turn_deg`가 같고 `advance_m`이 기본값을 채운 값으로 같다는 뜻이다. 응답은 `{accepted: true, junction_seq: 지금 seq, state: 지금 상태}`다. 다른 지시는 지금처럼 동작을 멈추고 받지 않는다.
5. **M4 CAMERA_LINE 전용.**
   - 교차로 감지, `waiting`, 회전은 CAMERA_LINE에서만 일어난다. IR_LINE에서는 게이트가 결정을 바꾸지 않는다.
   - IR_LINE에서 오는 지시는 모두 409 `JUNCTION_CAMERA_ONLY`다. IR에는 교차로 감지가 없어서 `straight`·`stop`도 뜻을 갖지 못하기 때문이다.
   - 이것은 D-494 4항과 구현 부록의 "CAMERA_LINE/IR_LINE에서 받는다"를 개정한다. OFF는 그대로 409 `LINE_FOLLOW_NOT_ACTIVE`다.
6. **M5 재획득.** 손을 넘긴 뒤 받은 신선한 프레임이 연속 `junction_reacquire_frames`장(기본 3) 있어야 재획득이다. 각 프레임은 visible이고 신뢰도가 `min_confidence` 이상이어야 한다. containment가 차선 방향을 주면 그 방향이 돌린 방향의 ±30° 안이어야 한다. 차선이 `lost_after_s`를 넘게 보이지 않아 D-407 stuck이 열리면 `unresolved`다(`aborted`가 아니다).
7. **M6 지연 보정.** 회전은 `|오차| ≤ max(5°, |ω|·junction_turn_lead_s)`에서 멈춘다. `junction_turn_lead_s` 기본값은 0.15 s다. 그 뒤 ±5° 안에 0.3 s 머물러야 끝난다. 그동안 벗어나면 최저 각속도로 작게 고친다. 회전 시간 한도는 이 머무름까지 포함한다.
   - 시험: odom 지연 150 ms에 바퀴 1차 지연 0.15 s를 넣었을 때 90°, −150°, 30°에서 모두 ±5° 안이다.
   - 검토 탐침(지연 250 ms, τ 0.3 s)은 시작부터 차선을 본 적이 없는 설정이다. 그래서 M8 규칙에 따라 `lane_lost_before_junction`으로 멈춘다.
8. **M7 `stop`.** 거리에 닿거나 교차로를 보면 둘 중 먼저 오는 쪽에서 HOLD `junction_stop`이다.
9. **M8 LOST 해제.**
   - 회전 시작은 손실 시계가 교차로 감지가 시작된 때(신선도 0.3 s 여유)보다 앞서 있으면 `aborted`(`lane_lost_before_junction`)다. 이때 LOST는 그대로 둔다.
   - 감지가 시작한 손실 시계만 지운다.
   - 교차로에서 `lost_after_s`(기본 3 s)를 넘겨 기다리면 LOST가 걸리고 D-407 stuck이 열린다. 그 뒤 온 회전 지시는 `aborted`(`stuck`)다. **Fleet은 로봇이 교차로에 닿기 전에 지시를 무장해야 한다.** D-494 5항의 `arm_distance_m` 0.6 m가 그 장치다.
10. **L1 정지 확인.** 교차로에서 멈춘 뒤 odom이 0.2 s 동안 `|v| < 0.01 m/s`, `|ω| < 0.05 rad/s`를 보여야 회전을 시작한다. 지연된 odom은 자기 마지막 0.2 s로 판단한다. 2 s 안에 서지 않으면 `aborted`(`not_still`)다. 이동 중 상태 사유는 `junction_stopping`이다.
11. **L2 동작 확인.** D-468 동작 확인 함수가 묶여 있지 않으면 회전을 거절한다(`motion_unconfirmed`). 확인 함수의 부재는 허가가 아니다.
12. **L3 지연 요구.** 교차로 감지는 이제 정지만이 아니라 회전 시작도 가른다. `line/keep_debug` 프레임은 카메라 시각에서 `stale_after_s`(0.3 s) 안에 CORE에 닿아야 한다. 늦은 프레임은 버린다. 실기 수용에서 keep_debug 지연을 잰다(아래 DEVICE 4).
13. **L5 D-395 위치 미션.** D-395 위치 미션도 CAMERA_LINE 차선 추종을 쓰면 교차로 정지(`waiting`)를 받는다. 미션이 교차로 앞에서 멈추면 이것이 원인이다. 미션 쪽은 바꾸지 않았다.
14. **L6 권한.** `POST /line-follow/junction`은 이제 다른 구동 경로처럼 수동 조종이 풀려 있어야 한다(`require_manual_released`, 409 `MODE_CONFLICT`). 따라서 D-494 구현 부록 10항의 "operator·보정 lease·수동 조종 해제" 문구가 코드와 맞는다. 낡은 `rosy_default.yaml`·`model.py` 주석도 고쳤다.

**수용 점검표.** 승격 전에 모두 통과해야 한다.

- SIM(모델 PC, 이 노트북 아님):
  - S1: `map_v2_fleet_real.launch.py`를 `camera_lane_mode:=keep`과 페이로드 `line_follow.yaml` 그대로(덮어쓰기 없음)로 띄운다. CORE 겹은 `rosy_default.yaml`(bridge·recovery_local 켜짐)이다. 차선 한 바퀴에서 `junction_waiting` 정지와 Fleet 지시 없는 정지를 기록한다.
  - S2: 좌(`turn_deg` +)·우(−)·직진·마지막 `stop`이 들어간 trip 한 바퀴를 돈다. 회전 오차 ±5°, 재획득 3프레임, `aborted` 0건을 확인한다.
  - S3: 교차로 앞 0.6 m 전에 무장하지 않은 지시(늦은 지시)가 `stuck`/`aborted`로 멈추는지 확인한다.
  - S4: bridge·D-468·D-407 로컬 후진이 켜진 채 차선 한 바퀴를 돈다. 의도하지 않은 후진·복귀가 없어야 한다.
- DEVICE(9dfk, 사용자 승인, 마커·Rosy Cam 맞춤 뒤):
  - D1: 운영자 겹에서 `camera_lane_mode: keep`으로 바꾼다. `supports_junction_turn`이 참인지 확인한다.
  - D2: 실기 차선 한 바퀴를 돈다. 교차로 정지 위치(가로선 앞 거리)를 잰다.
  - D3: 교차로 좌·우 회전을 한 번씩 한다. 회전 오차와 재획득을 확인한다. 정지 확인 0.2 s가 지켜지는지도 본다.
  - D4: `line/keep_debug` 카메라 시각에서 CORE 수신까지의 지연을 잰다(0.3 s 미만이어야 함).
  - D5: 되돌리기를 확인한다. `~/.rosy/rosy.yaml`로 `bridge_enabled`·`recovery_local_enabled`를 끄는 겹을 적용한 뒤 동작이 사라지는지 본다.

### 안전 재검토 반영 (2026-10-07)

1. **N1 진입 방향.** 로봇이 교차로를 처음 본 순간의 odom yaw를 그 교차로 정지의 진입 방향으로 기억한다. 신선한 odom이 있을 때 기록한다. 같은 정지 중의 모든 회전 지시는 `진입 yaw + turn_deg`를 겨눈다. 그래서 회전 중간에 `aborted`된 뒤 다시 보낸 지시가 방향을 더하지 않는다. 탐침 `probe_resend.py`는 이전에 90° 지시로 133.9°까지 돌았다. 지금은 85.8°에서 멈춘다(±5° 안). 재획득 방향 검사도 같은 목표를 쓴다.
   - 진입 방향을 지우는 경우: 교차로를 떠나 `reacquiring`에 들어갈 때, `straight`로 지나갈 때, 교차로가 보이지 않고 처리 중인 지시가 없을 때, 모드가 바뀔 때.
   - 진입 뒤 odom이 끊겼다(epoch·frame이 바뀌었다)면 회전 시작은 `aborted`(`odom`)다.
2. **R1 반복 거절.** 끝까지 실행된 지시는 같은 `place_id`·`action`으로 다시 오면 409 `JUNCTION_ALREADY_DONE`이다. 끝까지 실행된 지시는 셋이다. 재획득으로 끝난 회전, 지나간 `straight`, 회전 뒤 단계(`advancing`·`reacquiring`)에서 끊긴 회전이다. 다른 `place_id`의 지시가 받아지거나 모드가 바뀌면 풀린다. 회전 중(`turning`)에 끊긴 지시는 같은 교차로에서 다시 보낼 수 있다(N1이 방향을 맞춘다).
   - **trip 루프:** Fleet은 같은 장소에 지시를 한 번만 보낸다. 409 `JUNCTION_ALREADY_DONE`은 "이미 실행됨"으로 읽고 다음 장소로 넘어간다. 같은 장소를 연이어 두 번 지나는 계획(되돌아오는 고리)은 그 사이에 다른 장소 지시가 있어야 한다.
3. **R2 머무름과 정지.** 회전 완료에는 ±5° 안 0.3 s 머무름과 함께 odom 정지 확인(0.2 s 동안 `|v| < 0.01 m/s`, `|ω| < 0.05 rad/s`)이 둘 다 필요하다. 지연된 yaw만 보고 끝내지 않는다.
   - 탐침 `probe_lag2.py` 재실행 결과(최종 오차): 지연 0 ms·τ 0 s에서 90°/−150°/30°/8°가 4.2/−4.2/4.3/4.6°다.
   - 150 ms·0.15 s에서는 −0.8/0.9/−1.6/0.3°다.
   - 250 ms·0.3 s에서는 2.9/−2.8/2.8/−3.2°다.
   - 같은 250 ms 조건에 다른 설정을 넣으면 이렇다. `max_angular` 0.2에서 −1.1°, `junction_turn_lead_s` 0에서 2.9°, 0.5에서 2.3°다.
   - 교차로에서 2 s 기다린 뒤 지시하면 −0.8°다. 한 프레임 끊김(7·3프레임마다)에서도 −0.8°다.
   - 4 s 기다림(`lost_after_s` 초과)은 `aborted`(`stuck`)이다. 이것은 의도한 결과다.
   - 호스트 시험이 고정하는 것은 150 ms·0.15 s 모형의 ±5°뿐이다. 그 밖의 지연에서 ±5°는 실기 D3로 확인한다.
4. **R3 대기 중 끊김.** 교차로 정지 중(진입 방향이 기록됐거나 `waiting`)에는 감지가 0.3 s 넘게 끊겨도 첫 감지 시각을 새로 잡지 않는다. 그래서 M8의 "교차로가 시작한 손실" 판정이 같은 교차로를 기준으로 남는다.

**수용 점검표 보강.** 앞 절의 S1–S4와 D1–D5에 더한다.

- S2 보강: 회전이 끝나 `idle`이 된 뒤 같은 교차로를 다시 감지해 `junction_waiting`에 걸리지 않는지 기록한다.
- S5: 회전 중간에 끊고(예: 보정 lease 또는 장애물) 같은 지시를 다시 보낸다. 최종 방향이 진입 방향 + `turn_deg`의 ±5° 안이어야 한다.
- S6: 회전이 끝난 뒤 같은 지시를 다시 보낸다. 409 `JUNCTION_ALREADY_DONE`이어야 하고 다음 교차로에서 회전하지 않아야 한다.
- D6: 실기에서 odom 지연과 모터 응답 지연을 잰다. 그 값으로 `junction_turn_lead_s`를 정한다(기본 0.15 s). ±5°는 150 ms 모형에서만 증명됐으므로 D3에서 실제 오차를 기록한다.

### 최종 안전 검토 반영 (2026-10-07)

1. **N2 모드 재선택.** 교차로 정지 기록은 모드 변경 뒤에도 남는다. 남는 기록은 셋이다. 감지 시각, 진입 방향, 실행된 (`place_id`, `action`)이다.
   - 같은 교차로에서 CAMERA_LINE을 다시 고르거나(OFF→CAMERA_LINE 포함) 같은 지시를 보내면 409 `JUNCTION_ALREADY_DONE`이다. 탐침 `probe_final.py`는 이전에 171.5°까지 돌았다.
   - 같은 장소의 다른 회전 지시는 받는다. 그러나 재선택이 odom 궤적(D-468 PoseTrail epoch)을 새로 시작하므로 진입 방향과 비교할 수 없다. 그래서 회전 시작은 `aborted`(`odom`)이고 돌지 않는다.
   - 진입 방향은 감지가 `lost_after_s` 넘게 없으면 끝난다. 실행 기록은 다른 `place_id` 지시가 받아질 때만 끝난다. 모드 변경으로는 끝나지 않는다. 앞 절 R1의 "모드 변경으로 풀린다"는 이렇게 고친다.
   - 이것은 S6을 지키기 위한 것이다. 감지가 끊긴 시간으로 실행 기록을 풀면 늦게 온 같은 지시가 다음 교차로에서 다시 돈다.
2. **L2 odom 재시작.** 교차로에서 기다리는 동안 odom이 재시작하거나 끊기면 그 교차로 정지의 회전 지시는 모두 `aborted`(`odom`)다. 모드를 바꿔도 같은 교차로를 계속 보고 있으면 풀리지 않는다(N2). 그 교차로는 `straight`·`stop` 지시나 Pilot 수동 조종으로 벗어난다. 벗어나 감지가 `lost_after_s` 넘게 없으면 다음 교차로는 정상이다.
3. **L3 정지 판정 설정.** 정지 판정 속도를 설정값으로 올렸다. `line_follow.junction_still_linear`는 0.01 m/s이고 범위는 (0, 0.05]다. `junction_still_angular`는 0.05 rad/s이고 범위는 (0, 0.2]다.
4. **L1.** HTTP 409 `JUNCTION_ALREADY_DONE` 시험을 더했다(`test_line_junction_api.py`).

**수용 점검표 보강.**

- S5 보강: `advancing` 중 중단 → CAMERA_LINE 재선택 → 같은 지시 재전송이 409 `JUNCTION_ALREADY_DONE`이어야 한다. 다른 방향 지시는 `aborted`(`odom`)이고 로봇은 돌지 않아야 한다.
- D3 보강: 실제 odom에서 회전이 시간 초과(`timeout`·`not_still`) 없이 머무름까지 끝나는지 기록한다. 끝나지 않으면 `junction_still_linear`·`junction_still_angular`를 실측 잡음 위로 맞춘다.

### main 병합 메모 (2026-10-07, D-476 rev 1과의 관계)

main에 D-476 rev 1이 먼저 들어왔다(`1e8c44aa2`, `a67879335`). 그래서 이 ADR 결정 2의 bridge 기본값을 이렇게 고친다.

1. **`bridge_enabled`의 로봇 기본값은 꺼짐으로 둔다.** rev 1에서 켜진 bridge는 두 가지가 있어야 한다. 하나는 `ir_guard_enabled`다(IR 교정 전에는 꺼짐). 다른 하나는 `control.sensor_adapter` enforce이거나 `bridge_site_no_dropoffs: true`(현장 수용)다. 둘이 없으면 CORE가 시작을 거부한다(`check_bridge_floor_basis`, `LineFollowConfig` 검증). 이 둘을 기본값으로 켜는 것은 현장마다 정할 안전 결정이다. 그래서 병합에서 켜지 않았다. 켜려면 로봇이나 현장 설정 겹에서 세 값을 함께 켠다. 무엇을 켤지는 사용자 결정이다.
2. **`recovery_local_enabled`는 그대로 켜짐이다.** rev 1의 bridge는 이제 D-468 containment 없이 확신 있는 추종에서 무장한다. 그래서 이 값은 bridge의 전제가 아니다. 이 값은 D-468 로컬 복귀와 D-407 로컬 후진만 켠다.
3. **교차로와 bridge의 관계는 바뀌지 않는다.**
   - 지시 없이 교차로가 감지되면 게이트가 bridge 결정까지 0으로 만든다(`junction_waiting`).
   - `straight` 지시는 route hint `straight`로 bridge를 허용한다.
   - `left`·`right`는 hint가 bridge를 막는다.
   - 회전 동작은 시작할 때 무장된 bridge(`_bridge`)를 지운다. 동작 뒤에는 rev 1 규칙대로 확신 있는 직선 추종 `bridge_arm_frames`장으로 다시 무장한다.
4. **수용 점검표.**
   - S1의 "bridge 켜짐"은 위 전제를 갖춘 SIM 설정에서만 뜻이 있다. 모델 PC SIM은 `bridge_site_no_dropoffs: true`와 `ir_guard_enabled: true`(sim IR)를 겹으로 켜고 돈다.
   - S4는 bridge 없이 D-468·D-407 로컬 동작만으로도 따로 돈다.
