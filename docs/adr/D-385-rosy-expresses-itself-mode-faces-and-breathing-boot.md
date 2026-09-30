## D-385 Rosy가 스스로 표현한다 — 모드가 표정을 고르고, 기다리는 부팅 카드는 숨쉰다

**Status:** Accepted (2026-10-01, 사용자 요청·위임). 건강은 색·소리가 말하고(D-260), 운용은 램프가 밝히며(D-380), 기분은 이제 얼굴이 말한다.

잇는 결정: [D-280](D-280-calm-intelligence-product-design-philosophy.md) · [D-260](D-260-robot-shows-its-state-by-sound-light-screen-and-summary.md) · [D-380](D-380-lamp-mode-patterns-from-core-status-inputs.md) · [D-190](D-190-vendor-parity-boot-display.md).

### Context

로봇의 얼굴(emotion GIF 8종)은 부팅 후 한 번 `happy`로 시작해 그대로였다. 모드가 바뀌어도·막혀도·멈춰도 얼굴은 아무 말이 없었다. 부팅 카드는 정지 텍스트라 "죽었는지 살았는지"가 한눈에 안 들었다. 절전 중 배터리 경보로 깨우는 것(PWR-003 `WAKE_BATTERY`)은 이미 있었으므로, 이 결정은 표정과 생기를 채운다.

### Decision

1. **모드가 표정을 고른다** (`core_features.command.emotion_map`, ROS-free): IDLE→basic, MANUAL→interest, NAVIGATION→happy, DOCKING→fun, EMERGENCY→sad. 막힌 내비게이션(BLOCKED·FAILED)은 happy를 이기고 **bored** — 램프의 blocked와 같은 입력, 같은 우선순위 문법. 모르는 모드는 None(지금 표정 유지)이지 추측이 아니다.
2. **브리지가 얼굴에 전한다**: 5 Hz 상태 틱에서 `set_emotion` 서비스로, **LiDAR 문법**(서비스 없으면 latch 없이 재시도 — 감정 노드는 늦게 뜰 수 있다). 표정에는 깜빡임 같은 시간 축이 없다: 모드가 바뀔 때 한 번 갈아입는다.
3. **부팅 카드가 숨쉰다** (`info_screen.render_boot(frame)`): BOOTING·PROVISIONED 동안 무대 제목이 두 밝기로 0.5 Hz 숨쉰다(같은 글자·자리·색, 45 % 밝기 단계). CORE_READY·FAILED·SETUP는 꼼짝 않는다 — 도착한 로봇은 안절부절하지 않는다(D-280).
4. **절전은 이미 "꼭 필요한 것만"이다**: standby는 백라이트 0(완전 소등), 배터리 경보(WAKE_BATTERY)·근접·접촉만 깨운다. 새로 더하는 규칙 없음 — 이 결정은 그 지점을 확인하고 문서로 못박는다.

### Alternatives

- **EMERGENCY에 angry:** 화를 내는 표정은 누군가를 탓하는 뉘앙스다. 멈춘 로봇은 슬픈 것이 맞다. 거부.
- **표정 애니메이션(빠른 전환·깜빡임):** 얼굴은 분위기이지 경보가 아니다. 경보 예산은 소리·색에 있다(D-82). 거부.
- **부팅 카드에 스피너·진행바:** 진행률을 거짓으로 말하게 된다. "아직 살아 있다"만 말하는 두 단계 숨쉼이 정직하다. 거부.

### Consequences

감정 노드가 없는 벤치·시뮬에서도 조용하다(서비스 없으면 유지·재시도). `set_emotion`의 어휘(GIF 파일명)가 사실상 계약이 된다 — `emotion_map`은 이름을 하드코드하고 시험이 어휘를 지킨다. 표정 갱신은 상태 틱(최대 5 Hz) 안에서 모드 변화시 한 번이므로 LCD 부하는 무시할 수준.

### Validation

- 계약 시험(호스트): 정책 전표·막힘 우선순위·어휘 검증, reconcile 래치(LiDAR 문법), 카드 숨쉼/정지 프레임, 부팅 표시 프레임 키. 변이 증명 2종(막힘 표정 교체·밝기 단계 제거 → 빨강). 433 passed.
- 기기(다음 릴리스): 모드 전환마다 얼굴이 바뀌는 것, BOOTING 카드 숨쉼, CORE_READY에서 멈춤을 사람이 확인.
