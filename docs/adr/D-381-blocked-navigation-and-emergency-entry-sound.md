## D-381 막힌 내비게이션은 같은 청록을 깜빡이고, 비상정지 진입은 한 번만 소리로 말한다

**Status:** Accepted (2026-10-01, 사용자 위임·승인). D-380의 운용 모드 축을 두 세부로 채운다.

잇는 결정: [D-380](D-380-lamp-mode-patterns-from-core-status-inputs.md) · [D-260](D-260-robot-shows-its-state-by-sound-light-screen-and-summary.md) · [D-82](D-82-oklch.md).

### Context

D-380 뒤에 남은 두 갭. (1) NAVIGATION 모드에서 목표가 BLOCKED/FAILED로 끝나도 로봇은 "움직이는 중"의 청록 호흡을 그대로 보였다 — 근처 사람에게 "가고 있다"고 거짓말을 한 셈이다. (2) EMERGENCY(e-stop)는 램프 빨강 4 Hz만 있고 소리가 없었다. 사람이 누른 정지야 알지만, SAF-002 감시 정지처럼 로봇 스스로 멈춘 경우 근처 사람이 알 길이 없었다.

### Decision

1. **`nav_state`도 같은 핸드오버를 탄다.** status-inputs에 `nav_state`(NavigationState)를 더하고, 검증 규칙은 `robot_mode`와 같다(모르는 값은 나머지를 버리지 않고 없음).
2. **BLOCKED/FAILED는 `blocked` 패턴**: NAVIGATION 안에서만, 같은 청록을 2 Hz로 깜빡인다("시도 중이지만 못 간다"). PLANNING·ARRIVED·CANCELED는 한 목표의 지나가는 끝이라 무늬를 바꾸지 않는다. `blocked`는 DOCKING보다 아래, navigating보다 위 — 모드 축 안의 세부일 뿐 건강 상태를 넘지 않는다.
3. **EMERGENCY 진입음**: 부저가 2.5 kHz 네 번을 울린다(실패=2 kHz 세 번과 음높이·횟수가 다르다). 진입 시 한 번, 유지 중 무음, 해제 시 ready 차임 한 번. 건강 상태와 무관하게 패턴 기반으로 판정한다 — e-stop은 로봇이 스스로 멈췄을 수도 있는 소식이기 때문이다. 반복 제한 없음(드물고, 기다리는 소리다).

### Alternatives

- **BLOCKED마다 경보음:** 차단은 회복 시도가 이어지는 운용 상태다. 소리는 경보 예산(D-82)을 소모한다. 거부.
- **ARRIVED에 별도 무늬:** 모드는 여전히 NAVIGATION이고 다음 목표가 올 수 있다. 지나가는 상태에 무늬를 낭비하지 않는다. 거부.
- **EMERGENCY를 caution 저음으로 재사용:** 저음은 "살펴봐 달라"고 말하고 e-stop은 "멈췄다"고 말해야 한다. 거부.

### Consequences

핸드오버에 필드가 하나 더 늘었다(구 소프트웨어가 읽지 못하는 값이 아니라, 없음으로 소급 안전하다). 비상 해제 직후 ready 차임이 한 번 더 울린다 — 해제 확인음으로 의도한 동작이다. LCD 상태줄은 바꾸지 않았다: 막힘은 대시보드 이벤트가 이미 말한다.

### Validation

- 계약 시험(호스트): `lamp_pattern`의 nav 우선순위 전 표, status_inputs 키 셋, 핸드오버 검증, 부팅 표시의 blocked 행·EMERGENCY 진입/유지/해제 소리. 변이 증명 3종(blocked 규칙 제거·진입음 제거·C 이름 제거 → 각각 빨강).
- 기기(DEVICE 증거는 별도): NAVIGATION 중 목표 차단 유도로 blocked 점멸 확인, e-stop 투입·해제로 4회 고음·차임 확인.
