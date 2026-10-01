## D-405 반복 크롬 컨트롤은 아이콘이 얼굴이고(표준 trio), 아이콘 크기는 글자 척도를 재사용하며, 높이 함수는 dvh다

**Status:** Accepted (2026-10-02, 사용자 지시 — 공간 절약을 위해 아이콘을 최대한 쓰고 표준 패턴을 따르라). D-292 §2·D-359 §5·D-398을 좁힌다.

이는 결정: [D-75](D-75-d-7-react.md) · [D-280](D-280-calm-intelligence-product-design-philosophy.md) · [D-292](D-292-design-tokens-and-component-layout-contract.md) · [D-359](D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md) · [D-398](D-398-evidence-words-single-source-and-scope-gates.md).

### Context

2026-10-02 관제 콘솔 회차(사용자 감상: "글자가 너무 많다, 아이콘으로 해라, 예제를 찾아봐"). 반복 크롬 컨트롤 — 테마 trio(어둡게·밝게·시스템), 설정 토글, 영상 새로고침, 로봇 카드 측정 라벨(위치·방향·배터리·안전) — 이 한국어 글자로 폭을 쓰고 관제 밀도를 높였다.

표준 패턴 조사: shadcn/ui `mode-toggle`(트리거 Sun/Moon + Light/Dark/System 드롭다운), shadcn Theme Selector(Light=Sun, Dark=Moon, System=Monitor — Lucide trio), GitHub·Linear(아이콘 전용 태막 토글). 합의: **Sun/Moon/Monitor trio가 업계 표준**이고, **동사(액션) 버튼은 글자를 유지**한다.

같은 회차 토큰 감사: 간격(--space-1..6)·모서리(--radius-*)·글자(6단)는 이미 닫힌 척도(D-292·D-359)다. 빈틈은 ①아이콘·글리프 크기에 척도가 없다 ②Fleet 표면 높이 함수 4곳이 `vh`다(D-359 "높이는 `dvh`" 위반 — 모바일 동적 브라우저 크롬 아래에서 무대가 넘친다) ③폭 값(6rem·11rem·12rem…)은 무규칙해 보이지만 폭·격자·위치는 원래 표면 소유다(D-292 — 위반이 아니다).

### Decision

1. **반복 크롬 컨트롤의 얼굴은 아이콘이다.** 테마 trio(어둡게=달, 밝게=해, 시스템=모니터), 설정 토글(슬라이더), 영상 새로고침(회전 화살표), 카드 측정 라벨(위치=십자선, 방향=나침반, 배터리=배터리, 안전=방패).
2. **한국어 이름은 사라지지 않는다.** 아이콘 옆 `<span class="sr-only">이름</span>` + `title`. 운용자 말 한국어 평문 계약(D-398)과 `test_theme_choices.py`의 대조 원리(버튼 텍스트 콘텐츠 = 선택지 이름)를 그대로 지킨다. aria-label을 새로 만들지 않고 기존 텍스트를 sr-only로 감싼다 — 시험과 계약이 읽던 자리를 그대로 둔다.
3. **아이콘 크기는 새 척도를 만들지 않는다.** 공용 클래스 `.ui-icon`(components.css)이 글자 척도 value 단계(`--text-value` 1.125rem)를 쓴다. 색은 `currentColor` — 자리의 역할 토큰(예: `.facts span`의 `--ink-quiet`)을 상속한다. 아이콘 폰트·외부 에셋·웹폰트 금지(D-75 정신) — 인라인 SVG만.
4. **동사 버튼은 글자를 유지한다.** 무장·목표 지정·삭제…·전체 정지. 조사한 예제 전부가 동사는 글자로 남긴다(아이콘 추측이 안 되는 조작을 아이콘만으로 두면 초보 운용자가 못 쓴다).
5. **높이 함수는 `dvh`다(D-359 재확인).** Fleet 표면의 남은 `vh` 4곳(`min(42vh,30rem)` ×2, `min(30vh,18rem)`, `min(54vh,40rem)`)은 이번 회차에 교정했다. 대시보드 잔존(`console-detail.css` `31vh`, `shell.css` `24vh`, `1000px`류)은 이 회차 목록으로 남기고 다음 화면 회차에 옮긴다.
6. **폭·격자·위치는 표면 소유다(D-292).** 원시 폭 값은 위반이 아니다. 글리프 크기(범례 `0.7rem`, 점 `0.85rem`)는 `.ui-icon`으로 통합하는 방향으로 다음 회차에 마이그레이션한다.

### Alternatives

- **전면 아이콘화(동사까지):** 조사한 예제에 없고 운용자가 뜻을 추측해야 한다. 거절.
- **아이콘 전용 + aria-label 새로 만들기:** 접근성은 같지만 기존 시험·계약이 읽던 텍스트 자리가 사라진다. 거절 — sr-only가 같은 효과를 낸다.
- **새 `--size-*` 척도 추가:** 척도 닫힘 원칙(D-359)을 하나 더 만들 필요가 없다 — 글자 척도 재사용으로 충분하다. 거절.

### Consequences

테마 그룹·상단바·카드가 좁아지고 스크린리더 이름은 그대로다. 새 아이콘이 필요하면 인라인 SVG(`.ui-icon`, currentColor)로 표면 또는 theme.js가 그린다. DESIGN.md 부품 장에 `.ui-icon`을 올린다(별도 회차).

### Validation

- 계약 시험: `test_theme_choices.py`(대조 원리 보존 — regex가 icon 필드를 허용), web_common 209 passed, fleet 1213 passed.
- 브라우저: 재캡처에서 테마 3종·설정·새로고침·카드 4종 SVG 렌더, 페이지 오류 0.
- SOURCE/LOCAL 증거뿐, 사람 G3 관측은 별도.
