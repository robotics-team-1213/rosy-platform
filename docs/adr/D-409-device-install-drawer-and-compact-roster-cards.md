## D-409 기기 등록·연결 도구도 설치 서랍으로 접히고, 컴팩트 카드는 요약만 말한다

**Status:** Accepted (2026-10-02, 사용자 지시 — 남은 설치 요소도 분리하고 역할을 명확히 하라). D-359 §5·D-405·D-406을 이어 확장한다.

이는 결정: [D-359](D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md) · [D-405](D-405-icon-first-controls-and-measured-size-discipline.md) · [D-406](D-406-console-camera-operate-install-split-and-goal-toggle.md).

### Context

2026-10-02 회차 3. D-406으로 카메라 설치·보정 도구는 접혔지만, 기기 연결 묶음(로봇 등록 `#robot-enrollment` + 카메라 연결 승인 `#camera-link`)이 여전히 운용 화면 ops 블록에 펼쳐져 있었다 — 원래 주석도 이들을 "설정 일"로 불렀다. 폰(390×844)에서 로스터 카드가 측정 4칸을 모두 펼쳐 문서가 3,172px로 길었다. 대시보드에도 D-359 높이 계약(vh 금지)의 잔존이 있었다(`console-detail.css` 31vh·60vh, `shell.css` 24vh 2곳).

### Decision

1. **기기 연결 묶음은 `details#device-install-tools`(기기 등록·연결 도구, 기본 접힘) 안으로 간다.** `#robot-enrollment`·`#camera-link` 아이디와 조상 구조는 그대로라 기존 시험(`test_console_camera_pairing.py`)과 JS가 그대로 붙는다. 알림 문장(`role=alert`·`aria-live`)은 접혀도 소리 난다.
2. **컴팩트(<30rem) 카드는 요약이다.** 측정 칸에 `data-fact`(pose/yaw/battery/safety)을 달고, 컴팩트에서 위치·방향은 숨긴다 — 위치는 지도가 말한다. 카드 안쪽 여백도 한 단 줄인다(`--space-3/4` → `--space-2/3`). 폭이 넓어지면 전체 측정이 돌아온다.
3. **대시보드 잔존 높이 함수를 dvh로 교정한다**(`console-detail.css` clamp 31vh·min-height 60vh, `shell.css` clamp·max-height 24vh). D-405 결정 5의 잔존 목록을 소진했다.

### Alternatives

- **별도 설치 뷰로 완전 이동:** 다음 단계. 이번 회차는 접기로 역할 경계를 먼저 만든다(D-406과 같은 원리).
- **컴팩트에서 카드 전체 숨김:** "어느 로봇에 주의가 필요한가"가 폰에서 답히지 않는다. 거절.

### Consequences

운용 화면의 ops 블록은 대형·신호등·기록만 남는다. 설치 일은 두 서랍(카메라 설치·보정, 기기 등록·연결)로 접힌다 — 나중에 설치 뷰가 생기면 이 서랍들이 옮겨간다. 폰 카드가 짧아져 스크롤 예산이 줄고, 위치·방향 값은 넓은 창과 지도에서 본다.

### Validation

- 계약 시험: fleet 전체(`test_console_camera_pairing.py` 조상·순서·헤딩 보존 포함), web_common(dvh·반응형 계층 게이트), dashboard 회귀.
- 브라우저: 재캡처에서 서랍 접힘·컴팩트 카드 요약 확인, 페이지 오류 0.
- SOURCE/LOCAL 증거뿐, 사람 G3 관측은 별도.
