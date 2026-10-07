## D-492 차선 로봇은 교차로에서 멈춘 뒤 Fleet이 지도에서 정한 각도만큼 제한된 회전 동작을 하고 새 가지에서 차선 추종을 다시 잡는다 — 교차로 감지와 bridge는 로봇 기본값으로 켠다

**Status:** Proposed (2026-10-07, 사용자 결정 2건: "회전 동작 먼저, 분기 인식 출력은 후속" · "로봇 기본값을 켜기"). [D-491](D-491-fleet-trip-execution-m2-contracts.md) 4항과 그 구현 부록(2026-10-07)의 한계를 메운다. 실차 이동·릴리스 승격은 아래 수용 절차를 따른다.

잇는 결정: [D-491](D-491-fleet-trip-execution-m2-contracts.md)(교차로 지시 API) · [D-476](D-476-lane-loss-expected-road-bridge.md)(예상 도로 bridge, 기본 꺼짐) · [D-468](D-468-local-lane-departure-return.md)(이탈 복귀) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md)(몸체 기준 근접 정지) · [D-489](D-489-fleet-route-planning-concept-and-algorithm.md)(교차로 동작 각도 θ) · [D-18](D-18-rosy-core.md)(CORE가 유일한 최종 `cmd_vel` 발행자)

### Context

1. D-491 구현 조사(2026-10-07)에서 확인한 것: CORE가 받는 차선 관측(`line/observation`)에는 분기 후보·방향이 없다. 교차로 신호는 keep 모드 keeper의 `junction_transverse`/`junction_fork`뿐이고, 이것도 `lane_corner_turning`이 켜졌을 때만 나온다. 로봇 기본값(`middleware/perception/config/line_follow.yaml`)은 꺼져 있다. 그래서 `left`/`right` 지시는 `junction_unresolved`로 멈추고, "지시가 없으면 교차로에서 멈춤"도 기본 설정의 로봇에서는 작동하지 않는다.
2. 교차로를 `straight`로 지나가려면 D-476 bridge가 필요한데, 이것도 기본값이 꺼져 있다(`rosy_default.yaml` `bridge_enabled: false`). D-476은 "리플레이 → 모델 PC 시뮬레이션 → 장치를 통과할 때까지 꺼 둔다"고 정했다. `docs/validation/d476-gazebo-model-pc-2026-10-06/`이 시뮬레이션 증거다.
3. Fleet은 지도에서 각 교차 장소의 들어오는 차로와 나가는 차로를 알고, 그 사이 각도 θ를 이미 계산한다(D-489 교차로 동작).

### Decision

1. **제한된 회전 동작(CORE).** `POST /api/v1/line-follow/junction`의 `left`/`right`가 선택 필드 `turn_deg`(부호 있는 각도, |θ| ≤ 150°)와 `advance_m`(0–0.30 m, 기본 0.10)을 받는다. Fleet은 지도의 θ를 `turn_deg`로 보낸다. 교차로가 감지돼 로봇이 멈춘 뒤 CORE line-follow 매니저가 순서대로 실행한다.
   - (a) **제자리 회전**: odom yaw로 닫힌 고리를 돌려 `turn_deg`만큼 돈다. 각속도는 수동 한도 이하로 하고, 목표 ±5°에서 멈춘다.
   - (b) **짧은 전진**: `advance_m`만큼 직진한다. 속도는 trip 최고 속도의 절반 이하다.
   - (c) **차선 다시 잡기**: 차선 추종을 다시 켜고, `reacquire_m`(기본 0.20 m)을 가는 동안 차선을 `visible`·신뢰도 기준 이상으로 다시 잡아야 한다. 못 잡으면 멈추고 `junction_unresolved`다.

   동작마다 시간 한도(회전 `|θ|/ω_min + 2 s`, 전진·재획득 각 5 s)가 있다. 다음 경우 즉시 멈추고 상태를 `aborted`로 둔다: odom 낡음·점프, E-stop, 모드 변경, D-422 몸체 기준 근접 정지, 시간 초과, 새 지시. 이 동작은 모두 CORE 매니저의 명령 경로 안에서만 이루어지며 최종 `cmd_vel` 발행자는 CORE 하나다. `turn_deg`가 없는 `left`/`right`는 지금처럼 `junction_unresolved`다(옛 Fleet 호환). 상태 `line_follow.junction.state`에 `turning`·`advancing`·`reacquiring`·`aborted`를 더한다.
2. **교차로 감지와 bridge를 로봇 기본값으로 켠다.** `line_follow.yaml` `lane_corner_turning: true`, `rosy_default.yaml` `bridge_enabled: true`.
   - 효과: 모든 차선 주행에서 교차로 앞 정지(D-491 "지시 없으면 멈춤")와 짧은 차선 소실 bridge가 작동한다.
   - D-476의 "꺼 둔다"를 이 ADR이 개정한다. 다만 **릴리스 수용 절차는 남긴다**: 이 기본값이 들어간 페이로드는 모델 PC Gazebo `map_v2_fleet_real`(교차로·bridge·회전 동작 포함 한 바퀴)과 실기 차선 한 바퀴를 통과해야 robots에 승격한다. 이 노트북에서는 Gazebo를 돌리지 않는다.
   - 되돌리기는 카드 설정(`/boot/firmware/rosy-config.yaml`) 또는 로봇 패키지 설정으로 두 값을 끈다. 코드 변경은 필요 없다.
3. **Fleet trip 루프(D-491 5항)는 `lane` 간선의 좌·우 교차로에 `turn_deg`를 보낸다.** 직진은 `straight`, 마지막은 `stop`이다. 로봇 능력(D-491 1항)에 `junction_turn: true`가 없으면 좌·우가 있는 `lane` 계획의 실행을 열지 않는다(`TRIP_MODE_UNSUPPORTED`).
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
