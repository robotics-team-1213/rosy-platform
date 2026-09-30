## D-344 Pilot 의 자동 주행은 누르고 있는 동안만 진행하는 보조 자율이며, 스틱을 건드리면 즉시 수동이다

**Status:** Accepted (2026-09-29, 설계 결정). 가제보 검증 전에는 실기에서 켜지 않는다.

### Context

- 로봇 CORE 에는 이미 차선 추종(`PUT /api/v1/line-follow/mode` `CAMERA_LINE`, D-143), 교통 정책
  (정지선·횡단보도·신호), 내비게이션 목표·경유점 API 가 있다. 실물 카메라에도 도로 인식
  오버레이(`semantic-road-v1`)가 돈다.
- 2026-09-29 실물 rosy-pinky-8kcn 은 `runtime.navigation: absent`, `goal_navigation: false`,
  지도 없음이다. 차선 추종은 `NAVIGATE` 능력을 요구하므로 지금은 409 로 거절된다.
- 사용자는 도로·경로를 따라 자동으로 가는 모드를 원한다. 무인으로 멀리 보내는 것과 운전자가 보면서
  맡기는 것은 안전 요구가 다르다.

### Decision

1. pilot 은 모드 셋을 둔다.

   | 모드 | 무엇 | CORE 경로 | 켜지는 조건 |
   |---|---|---|---|
   | 수동 | 지금의 스틱·페달 | `POST /teleop` | teleop 능력 |
   | 차선 따라가기 | 로봇이 조향·속도를 정하고 사람은 "진행"을 누르고 있음 | line-follow `CAMERA_LINE` | `NAVIGATE` 능력 + 차선 증거 신선 |
   | 목표 지점 | 지도에서 탭한 곳으로 | `POST /navigation/goal` | 지도·로컬라이즈 준비 |

2. **누르고 있는 동안만 진행(dead-man).** 자동 모드에서도 화면의 "진행" 버튼(또는 게임패드 트리거)을
   누르고 있을 때만 자동 주행이 유지된다. 떼면 pilot 이 즉시 자동을 끄고(`mode OFF`·`navigation/cancel`)
   정지를 확인한다. 운전자가 화면을 보고 있다는 증거가 곧 진행 허가다.
3. **스틱·페달을 건드리면 즉시 수동으로 넘어간다**(자동 해제 → MANUAL → 입력 반영). 되돌리기는
   명시적으로 다시 누를 때만 한다.
4. **HUD 는 자동의 근거를 보인다**: 차선 신뢰도·오차, 교통 상태(정지선 거리·신호색), 거절 이유
   (예: "내비게이션 능력 없음 — 차선 따라가기를 쓸 수 없습니다"). 켤 수 없는 모드는 이유와 함께 흐리게.
5. **최종 명령은 CORE 가 소유**한다(D-2). pilot 은 모드를 고르고 진행 신호를 줄 뿐 조향을 계산하지 않는다.
6. **검증 순서**: 가제보 차선 월드(map_v2 lane) → 실물(한도 L1 이상, D-342) 순서다. 실물은
   `NAVIGATE` 능력이 켜지는 런타임 구성 결정이 따로 필요하다.

### 보강 (2026-09-29, 실물 rosy-pinky-8kcn 조사)

7. **차선 추종의 권한은 구동(`MOVE`)이다.** 지금까지 `PUT /line-follow/mode` 는 `NAVIGATE`
   (`navigation.goal_navigation`)를 요구했는데, 실물 런타임 `motor` 는 Nav2 가 없어 이 권한을 늘 끈다
   (`runtime_capability_data`). 카메라 차선 추종은 Nav2·지도가 필요 없다 — 필요한 것은 구동 준비와
   신선한 차선 증거이고, 증거 검사(신선도·신뢰도·출처)는 이미 `LineFollowManager` 가 한다. 그래서
   요구 권한을 `MOVE` 로 바꾼다. `navigation.goal_navigation` 은 목표 지점 모드에만 남는다.
8. **운전자 확인 만료는 CORE 가 소유한다.** `PUT /line-follow/mode` 에 `hold_s`(0 < hold_s ≤ 2)를 주면
   그 세션은 `POST /api/v1/line-follow/hold` 로 계속 갱신되어야 한다. 갱신이 `hold_s` 를 넘겨 끊기면
   CORE 의 차선 추종 틱이 스스로 OFF 로 내리고(`driver_released`), 바퀴 명령은 0 이 된다. pilot 은
   "진행"을 누르는 동안 100 ms 마다 갱신하고 `hold_s = 0.5` 를 쓴다(teleop 워치독과 같은 크기).
   탭 이탈·네트워크 끊김·앱 종료 모두 같은 경로로 멈춘다. `hold_s` 없는 호출(기존 관제 화면)은
   지금처럼 동작한다.
9. **실물 로봇은 카메라 서비스에서 차선 관측(`line_observer_node`)도 띄운다.** 관측 전용 노드이고
   바퀴 명령을 내지 않는다(D-2). 도로 관측(`road_observer_node`)과 같은 `camera/front` 를 구독한다.
10. 실물 첫 자동 주행의 순항 속도는 설정 `line_follow.cruise_speed` 를 **0.04 m/s** 로 낮춰 시작하고,
    D-342 과 같이 녹화 증거로 올린다.

11. **앞 물체 정지는 차선 추종이 소유한다(LiDAR).** CORE 가 받은 스캔에서 로봇 정면 ±20° 부채꼴의
    최소 거리를 구해, 0.20 m 보다 가까우면 `HOLD`(`obstacle_ahead`), 0.28 m 보다 멀어지면 다시 간다.
    이 정지는 차선 상실이 아니라 LOST 로 굳지 않는다. 주행 중 LiDAR 가 0.5 s 넘게 끊기면
    `obstacle_sensor_stale` 로 멈춘다(한 번도 안 온 벤치에서는 판정하지 않음). LiDAR 장착 방향은
    `line_follow.lidar_forward_deg` 로 준다 — Pinky Pro 실물은 LiDAR 0° 가 로봇 뒤라 180 이다
    (2026-09-29 실측: 정면 2.6 m·오른쪽 벽 0.14 m 가 카메라 화면과 일치). 상태에 `clearance_m` 을 싣고
    pilot HUD 가 보인다. 이것은 "물체 인식"의 첫 단계(거리 기반)이고, 종류를 가리는 학습 검출기는
    D-199 의 교체 가능한 백엔드로 뒤에 붙는다.
12. **차선 경계는 두 겹으로 지킨다(카메라 + IR).** 2026-09-29 실물 녹화에서 로봇이 흰 경계선을 밟고
    넘었다. 원인은 실물 `camera_lane_mode: line` 이 하단 밝은 화소 전체의 무게중심을 목표로 삼는
    것이라, 경계선이 한쪽만 보이면 그 선 위가 목표가 된다. 지면 투영(homography)이 필요한
    `lane`·`edge_left`·`centre` 는 실물에 교정이 없어 쓸 수 없다.
    - **카메라(1차)**: 영상 공간에서 중앙 기준 좌·우 가장 가까운 경계를 찾아 그 사이 가운데를
      목표로 하는 `camera_lane_mode: between` 을 둔다. 한쪽만 보이면 두 쪽이 보일 때 익힌 차로 폭만큼
      안쪽을 목표로 한다. 관측 계약(`error/confidence/visible`)은 그대로다.
    - **IR(최후 방어선)**: 바닥을 보는 좌·중·우 IR 은 이미 IR_LINE 관측으로 CORE 에 온다(D-143).
      CAMERA_LINE 중 `line_follow.ir_guard_enabled` 이면 CORE 가 그 관측을 감시로 쓴다. 경계선이
      옆 센서 밑(|error| ≥ `ir_guard_edge_error`)이면 카메라 조향을 덮어 반대로 `ir_guard_turn` 만큼
      돌고 속도를 `ir_guard_speed_scale` 배로 줄인다(`lane_edge_left/right`). 가운데 센서 밑이면 선을
      밟고 넘는 중이라 멈춘다(`lane_departure`). 셋 다 흰색(정지선·횡단보도)은 대비가 없어 관측이
      비가시라 감시가 걸리지 않는다. 감시가 켜졌는데 IR 이 끊기거나 미교정·교정 해시 불일치면
      멈춘다(`lane_guard_stale`). 어느 것도 LOST 로 굳지 않는다.
    - IR 은 rosy-io 그래프(`motor`)에서 `bringup_robot.launch.py enable_ir:=true` 로 control
      `ir_adc_node` 를 띄운다. 내비게이션 그래프는 line_follow 가 띄우므로 끄고, 두 유닛은
      `Conflicts=` 로 동시에 돌지 않는다 — ir_sensor/range 발행자는 버스당 하나다.
    - 켜는 순서: IR 발행 확인 → 카펫(검정 끝점)·흰 테이프(흰 끝점) 실측으로 `/etc/rosy/line_follow.yaml`
      교정 → 교정 해시를 `line_follow.ir_calibration_revision` 에 → 좌·우 부호를 손으로 확인 →
      `ir_guard_enabled: true`. 기본값은 꺼짐이다.
    - 검증은 녹화 루프로 한다: 자동 주행 녹화 → 프레임 격자 → 경계 안에 있었는지 판정 → 조정 → 반복.

### 보강 (2026-09-30, 실물 준비 — 로봇 부재 중 SOURCE 만)

- **§11 보강 — 앞 물체 정지는 조향을 안다(`line_follow.obstacle_mode: path`, 기본).** 실물 L 모서리에서
  둘레 벽이 로봇 앞 약 0.2 m 라, 정면 ±20° 부채꼴 판정(0.20 m)은 모든 모서리에서 로봇을 세운다
  (가제보는 0.10/0.14 m 로 낮춰야 돌았다). 이제 CORE 는 스캔을 로봇 좌표 점으로 받아, 틱마다
  **의도 조향**(지금 차선 관측이 시킬 선·각속도, IR 감시의 비킴 포함)의 짧은 호를 그리고 그 호 둘레
  ±`obstacle_corridor_half_width_m`(0.09 = 발자국 반폭 0.06 + 여유 0.03) 띠 안 점까지의 호 길이를
  여유 거리로 쓴다. 호는 `obstacle_path_horizon_m`(0.40, resume 이상) 와 90° 회전 중 짧은 쪽까지다.
  출력이 아니라 의도를 쓰는 까닭은, 멈춘 뒤 출력은 0 이라 직진 호가 되어 모서리 벽에 영영 막히기
  때문이다. 쓸 관측이 없으면 마지막 의도를 쓴다. 지키는 것: 정지 0.20·재출발 0.28 떨림 방지, LiDAR
  0.5 s 끊김이면 `obstacle_sensor_stale`, 경로 위 진짜 물체면 `obstacle_ahead`, LOST 로 굳지 않음.
  직진일 때 띠는 부채꼴보다 좁지 않다(부채꼴 0.2 m 에서 ±0.068 m, 띠 ±0.09 m). 선속도 0 인 제자리
  회전은 로봇 둘레 띠 안 점을 0 거리로 본다. `obstacle_mode: sector` 는 옛 판정 그대로다.
  **실물 확인 필요:** path 는 좌·우를 가른다 — LiDAR 가 뒤집혀(거울) 달렸으면 왼쪽 회전에 오른쪽을
  본다. 켜기 전에 로봇 왼쪽에 물체를 두고 점이 +y 에 오는지(스캔 +90° 가 180° 장착에서 로봇 오른쪽)
  확인한다.
- **§12 보강 — IR 교정 절차와 도구.** `src/runtime/sensing/tools/device/ir_line_calibrate.py`(읽기 전용,
  `ir_sensor/range` 구독만) 가 카펫·왼쪽·가운데·오른쪽 테이프 네 자리 표본에서 채널별 중앙값으로
  끝점을 내고, `min_span`·잡음 6 배 분리·채널 순서·되읽기 부호(왼쪽 ≤ −0.3, 오른쪽 ≥ +0.3)를
  모두 통과할 때만 관측 노드 YAML 과 CORE `ir_calibration_revision` 을 찍는다. 절차는
  `docs/deployment/pinky-pro-ir-line-calibration-runbook.md`. 실물 관측 노드는 `rosy-camera` 의
  `camera_preview.launch.py` 에서 돌므로, 기기 교정 파일 `/etc/rosy/line_follow.yaml` 이 있으면 그
  노드가 패키지 기본 뒤에 덧읽는다(없으면 IR 교정 꺼짐 = IR_LINE fail-closed, 이전과 같다).
- **§13 — 차선 추종 각속도는 수동 한도 계단을 따른다.** 실물 자동 주행이 0.66 rad/s 까지 돌았는데
  수동은 D-342 L0 0.10 rad/s 다. 이제 차선 추종의 유효 각속도 상한은
  `min(line_follow.max_angular, safety.manual_angular)` 이고(`max_angular_follows_manual: true`, 기본),
  관리자 API 로 계단을 바꾸면 다음 틱부터 따른다. 상한이 조향을 자르면 선속도도 같은 비율로 줄여
  **같은 호를 더 천천히** 돈다(자르기만 하면 굽이에서 차로 밖으로 밀린다). IR 감시의 비킴도 같은
  상한을 넘지 않는다. 한도를 읽을 수 없거나 0 이면 조향 없이 직진하지 않도록 `angular_limit_zero`
  로 멈춘다. `max_angular_follows_manual: false` 는 명시적 덮어쓰기(= `max_angular` 만)다. 선속도는
  계단에 묶지 않았다 — 실물 순항은 §10 의 `cruise_speed` 가 따로 정한다.

### Alternatives

- **자동 모드를 켜 두고 손을 떼도 계속 간다.** 거부. 원격 화면은 지연·끊김이 있고(D-368) 무인 주행의
  안전 사례는 미션 계층(D-12)이 따로 소유한다.
- **pilot 이 차선 오차로 조향을 계산해 teleop 으로 보낸다.** 거부. CORE 의 차선 추종 정책(신뢰도·신선도·
  교통 게이트)을 우회한다.

### Consequences

- 운전자 한 명이 보면서 맡기는 보조 자율만 pilot 에 들어온다. 무인 미션은 Fleet 미션(D-12) 쪽이다.
- 진행 버튼 신호가 끊기면(탭 이탈·네트워크) 자동이 꺼져야 하므로, CORE 쪽에도 진행 신호 만료가
  필요하다 — line-follow 에 teleop 워치독 같은 "운전자 확인 만료"를 둘지 구현 회차에서 정한다.

### Validation

- SOURCE: 모드 전환 상태기계 시험(떼면 OFF, 스틱이면 수동, 거절 이유 표시).
- ROS-SIM: 가제보 차선 월드에서 차선 따라가기 한 바퀴 + 진행 해제 시 정지 거리 녹화.
- DEVICE: `NAVIGATE` 능력 구성 뒤 실물 녹화.

**Related:** [D-2](D-2-cmd-vel.md), [D-12](D-12-mission-fleet.md), [D-143](D-143-ir-navigation-evidence.md),
[D-323](D-323-rosy-pilot-teleop-app.md), [D-368](D-368-pilot-live-driver-video.md), [D-342](D-342-manual-limit-commissioning-ladder.md).
