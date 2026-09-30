## D-380 램프는 로봇 상태에 이어 운용 모드도 밝힌다 — CORE가 status-inputs에 RobotMode를 넘기고 같은 규칙표가 우선순위를 정한다

**Status:** Accepted (2026-09-30, 사용자 요청·승인). D-260 결정 1의 다섯 건강 상태는 그대로 두고, 그 옆에 운용 모드 축을 하나 더 얹는다. *(첫 기록 번호는 D-375였으나 main의 동시 예약과 충돌해 D-380으로 개명했다 — 선례 D-324→D-325.)*

잇는 결정: [D-260](D-260-robot-shows-its-state-by-sound-light-screen-and-summary.md) · [D-247](D-247-dashboard-shows-every-board-device.md) · [D-190](D-190-vendor-parity-boot-display.md) · [D-174](D-174-first-boot-defects-and-boot-indicator.md).

### Context

2026-09-30 코드 파악에서 확인된 갭: 램프는 `ready`(초록 3초 후 소등)에서 끝나고, 그 뒤 MANUAL 운전·NAVIGATION 주행·DOCKING·EMERGENCY(e-stop) 중에 로봇 몸에는 아무 표시가 없었다. `RobotMode`(IDLE/MANUAL/NAVIGATION/DOCKING/EMERGENCY)와 `NavigationState`는 대시보드에만 존재했다. 반면 부팅·건강 축(D-260)은 `core_common.robot_state` 하나의 규칙표로 LCD·램프·부저·대시보드가 같은 말을 하는 구조가 이미 잡혀 있다.

### Decision

1. **모드는 기존 핸드오버를 탄다.** CORE가 10초마다 쓰는 `/run/rosy/status-inputs.json`(D-260 M1)에 `robot_mode` 필드를 하나 더한다. `rosy-boot-status`가 검증해 `boot-status.json`으로 옮기고, `rosy-boot-display`가 읽는다. CORE가 죽으면 핸드오버가 끊기고(60초 유효) 모드 표시도 사라진다 — 죽은 CORE의 과거 모드를 램프가 배회하는 일이 없다.
2. **우선순위는 규칙표가 정한다**: `실패 > 비상정지(EMERGENCY) > 주의 > 부팅 > 도킹 > 내비게이션 > 수동 > 준비`. `core_common.robot_state.lamp_pattern(state, robot_mode)`이 이 순서를 소유하고, 부팅 표시는 그 답을 그대로 부른다.
3. **램프 패턴 4종 추가**(`lamp_pattern.c`): `manual` 흰색 호흡 3초, `navigating` 청록 호흡 4초(부팅 파랑 2초와 색·속도가 다르다), `docking` 마젠타 1 Hz(실패 빨강과 같은 주기, 다른 색), `emergency` 빨강 4 Hz(실패 1 Hz의 네 배 — 두 빨강은 속도로 구분된다).
4. **LCD 상태줄에 모드 접미**: `Ready - NAVIGATION`처럼 기존 LCD 한정 어휘(`Ready - cannot move`)의 하이픈을 따른다. 색으로만 모드를 말하면 색약 사용자에게 닿지 않는다. 대시보드는 이미 `state.mode`를 따로 보여주므로 바꾸지 않는다.
5. **모드 변경은 조용하다.** 부저는 D-260 결정 2 그대로 건강 상태 전환에만 울린다. 모드 전환은 빈번해서 소리가 되면 소음이 된다.
6. **다섯 상태는 건강 상태 그대로.** 모드는 `evaluate()`의 판정을 바꾸지 않고 `result["robot_mode"]`로 검증만 거쳐 함께 실린다. 상태 축과 모드 축을 섞지 않는다.

### Alternatives

- **CORE가 램프를 직접 구동:** `/dev/ws281x_pwm`은 rosy-display 유닛에만 허용됐다(D-260 3). 소유권을 옮기면 부팅 표시가 무너진다. 거부.
- **`SetLamp` 서비스로 수동 표시:** 표시 주체가 둘이 되어 판정이 어긋난다 — D-260이 없앤 바로 그 문제. 거부.
- **대시보드에만 두는 현행 유지:** 로봇을 직접 보는 사람(현장·전시)에게 모드가 안 보인다. 이 결정의 이유. 거부.

### Consequences

CORE가 살아 있고 hardware 모드일 때만 모드 패턴이 보인다(core/motor 모드는 애초에 움직일 수 없어 IDLE뿐이다). 핸드오버 검증에서 모드만은 규칙이 다르다: 경보 임계·장치 행과 달리, 모르는 모드는 **나머지를 버리지 않고** 없음(None)이 된다 — 그림 같은 모드 검증은 불가능하고, 경보와 장치는 독립적으로 쓸모 있기 때문이다. 램프 C 헬퍼와 파이썬 테이블의 패턴 이름 동기는 계약 시험이 지킨다.

### Validation

- 계약 시험(호스트): `robot_state.lamp_pattern` 우선순위 전 표, `status_inputs` 키 셋, `rosy-boot-status` 검증·레코드, 부팅 표시 패턴 선택·무음 전환·LCD 접미, C `known()` 이름 동기. 변이 증명 4종 완료.
- 기기(DEVICE 증거는 별도): hardware 모드에서 MANUAL/NAVIGATION/DOCKING 각 전환 시 램프 패턴 확인, CORE 정지 60초 후 모드 표시 소멸 확인.
