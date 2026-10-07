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
