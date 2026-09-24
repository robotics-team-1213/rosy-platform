## D-224 표면의 키보드 어휘 — 약속한 키는 동작한다

**Status:** Accepted (2026-09-25)

**Context:** concept 16 §7.3은 Fleet 문법을 "keyboard-first: 예외를 순회하고
로봇 콘솔로 진입"이라 선언했고, 게임 보드 힌트는 "스페이스도 양쪽을
세운다"고 약속한다. 2026-09-25 실측(console.js·board.js 소스 점검):

- Fleet에는 키보드 경로가 없었다 — 토큰 입력의 Enter 저장(keydown 1곳)이
  전부다. ↑/↓ 순회도, 카드 선택도, Escape 해소도 없다. 선언은 있고 실현이
  없었다.
- 게임 보드에는 키보드 처리가 없었다 — "스페이스도 양쪽을 세운다"는
  글자뿐이었다. Law 0 위반이다: 없는 동작을 있다고 말한다.

**Decision:**

1. **Fleet 로스터 키보드 어휘.** ↑/↓ 로 로스터 카드를 순회하고, Enter 로 그
   카드의 목표 지정을 누르고, Escape 으로 선택을 해소한다. 카드(`article`)는
   `tabindex="-1"` 착지점이다 — 프로그램 포커스만 허용하고 탭 순서는
   더럽히지 않는다. 입력 컨트롤(input·select·textarea·button·a)에 있을 땐
   간섭하지 않는다. 포커스 링은 표면 전역 `:focus-visible` 규약이 그린다.
2. **게임 스페이스바 약속의 실현.** 몸(body)에 포커스가 있을 때 Space 는
   halt 클릭과 같은 `/stop` POST 를 친다. 포커스가 컨트롤에 있으면
   브라우저가 이미 Space 를 click 으로 바꾸므로 몸에서만 잡아 이중 발사를
   막는다. `repeat` 은 무시한다(눌러붙은 키가 정지를 연타하지 않는다).
3. **계기: 브라우저 렌더 시험.** `test_fleet_console_browser.py` — ↓↓ 로
   rosy_02 에 착지 → Enter 로 선택 1건 → Escape 으로 해소 0건.
   `test_games_board_browser.py` — Space 1회에 `/stop` POST 정확히 1회.
   변이 증명 완료(핸들러 무력화 → 양쪽 적색 → 원복 → 녹색).

**Alternatives:** 로빙 tabindex(0) 안 — 탭 순서에 카드 N개가 끼어들어
관제자의 탭 이동이 길어진다. 카드 클릭으로 선택하는 기존 경로만 두는 안 —
§7.3의 선언을 문서로 남기는 셈이라 BENCH에서 반드시 재발한다. 게임에
Space 확인 다이얼로그를 끼우는 안 — 정지는 즉시 실행이 문법이다(D-101).

**Consequences:** Fleet 카드가 포커스를 받으므로 `:focus-visible` 링이
키보드 사용자에게 보인다 — 링 색은 상호작용(`--focus-ring`)이라 상태색이
아니다. 새 키보드 경로는 이 ADR 의 어휘(순회·목표·해소)에만 산다.

**Validation / Transition:** 구현 커밋에서 핸들러 2건 + 시험 2건 + 변이
증명. 같은 커밋의 시험 인프라 수정: `browser_harness.open_page` 기본 대기
5초 → 15초 — 경합 중인 호스트에서 `goto(networkidle)`·`wait_for_function`
이 계약과 무관하게 쓰러지는 플레이크 3건의 공통 원인이었다. 계약 자체의
타임아웃은 호출처 명시값을 그대로 쓴다.

**References:** concept 16 §7.3·§7.5, Law 0, D-101, D-153, D-201, D-218(F-20),
D-219.

---
