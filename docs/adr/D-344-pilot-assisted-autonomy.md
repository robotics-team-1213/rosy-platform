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

### Alternatives

- **자동 모드를 켜 두고 손을 떼도 계속 간다.** 거부. 원격 화면은 지연·끊김이 있고(D-341) 무인 주행의
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
[D-323](D-323-rosy-pilot-teleop-app.md), [D-341](D-341-pilot-live-driver-video.md), [D-342](D-342-manual-limit-commissioning-ladder.md).
