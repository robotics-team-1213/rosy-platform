## D-428 웹 표면의 얼굴 하드코딩을 지운다 — 재도색은 게이트가 막고, 없는 얼굴만 공용에 더하고, 중복은 부품으로 흡수한다

**Status:** Accepted (2026-10-03, 사용자 지시 — 하드코딩 제거 스윕으로 공용컴포넌트·책임 분리·토큰 사용을 완성). D-292·D-359·D-398·D-405의 집행 회차이고 role-surfaces S2(`../plans/2026-09-24-role-surfaces-s1-foundation-plan.md`)의 경계를 존중한다.

이는 결정: [D-75](D-75-d-7-react.md) · [D-280](D-280-calm-intelligence-product-design-philosophy.md) · [D-292](D-292-design-tokens-and-component-layout-contract.md) · [D-359](D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md) · [D-371](D-371-list-row-irreversible-actions-confirm-before-danger-fill.md) · [D-398](D-398-evidence-words-single-source-and-scope-gates.md) · [D-405](D-405-icon-first-controls-and-measured-size-discipline.md).

### Context

2026-10-03 전 웹 표면 감사(robot·console·game-board·pilot·web-common; lane-live-view·control-diagnostic은 등록부 예외 확인만). 계약 시험은 213 passed — 시험이 이미 지키는 것(팔레트·반응형 3단·글자 6단·간격 척도)이 아니라 시험이 못 잡는 위반만 모았다. 남은 것은 셋이다.

1. **재도색** — 표면 시트가 ui-* 요소를 다시 그린다. 대시보드 `.view-tab`(`styles.css:240-250`, 눌림 채움까지 공용 segment와 다르다)·`.drawer-close`(277-289)·`.mode-control ui-button` 구분 테(`console-detail.css:335-336`·349-350)·`#safety-mode-status`(`shell/shell.css:62-70`), Fleet `.field-size input`(`styles.css:69`)·`.enroll-address input, #enroll-code`(704 — 둘 다 `.ui-field` 재도색), Pilot 그리퍼 range(`styles.css:671-672` — components.css에 range 얼굴이 없어 굴러듦). `test_shared_controls`의 FACE 검사는 선택자에 `ui-` 토큰이 있을 때만 작동해, ui-* 요소에 붙은 클래스·id 선택자 경로가 빠져나간다.
2. **중복 얼굴** — 공용 부품이 있는데 표면이 다시 만든다. 상태 알약=ui-tag(대시보드 `.summary-state`·이벤트 심각도 2벌·Pilot HUD 알약 2종·games `.lost`), 사실 격자=`.ui-readout`(Fleet 4벌·대시보드 3벌 — 공용 ui-grid는 제품에서 한 번도 안 쓰임), 머리=ui-head(Fleet `.robot-head` 8곳), 빈 상태=ui-empty(Fleet 어휘 3벌), 확인=confirmIrreversible(Fleet `window.confirm` 4곳 — 문서 전체를 막는 모달이라 정지 컨트롤까지 죽는다, D-371의 정반대), 증거=ui-evidence(games 3곳), 글자 척도=ui-text(Pilot HUD·games `.kicker`), 점=ui-triage 점(대시보드 연결 점), 브랜드=ui-brand(대시보드 `index.html` 손브랜드 — `surface.html`은 올바르다), 링크 버튼 얼굴 5벌(`a.docs-link` 재구현), 무대 위 가운데 안내 4벌, 지도·카메라 무대가 dashboard↔Fleet에 같은 클래스명으로 복사.
3. **값 하드코딩** — `vh` 3곳(dashboard `panels/surface-panels.css:38`·48, Fleet `styles.css:56` — D-405 "높이는 dvh" 잔존), 정의되지 않은 `ui-tag status="good"` 3곳(Fleet `console.js:409`·`install.js:229`·`vision-view.js:355` — 조용히 neutral로 그려짐), 죽은 CSS 3벌(대시보드 `.topbar` 2벌, Fleet `.signal-empty`). 대시보드는 `setOff` 10파일·`el()/node()` 헬퍼 13파일 복붙(`dom.js`가 이미 수출한다), Fleet은 공용 칸 질의(22rem 접힘)가 `container-type` 없어 죽어 있다.

### Decision

1. **재도색 금지를 게이트가 잡는다.** 표면 시트는 ui-* 요소에 face 선언(background·color·border·font·opacity·outline)을 두지 않는다 — 선택자가 ui-* 토큰을 직접 쓰든 ui-* 요소에 붙은 클래스·id·`[data-*]`를 거치든. 게이트는 HTML 정적 태그와 JS 빌더(`el()/node()/createElement`)에서 ui-* 요소가 가진 속성을 수집해 표면 시트의 face 선언과 대조한다. 새 게이트는 변이 증명으로 믿는다(`test/AGENTS.md`).
2. **공용에 더하는 얼굴은 넷뿐이다.** ① `input[type="range"].ui-field` 얼굴(테=선, 켜짐=focus-ring, 비활성=점선 — 체크와 같은 문법) ② 링크 버튼 얼굴(`a.docs-link` 일반화, 5벌 흡수) ③ `ui-note`(안내·주의 상자 — Fleet 4벌·대시보드 회수) ④ `ui-stage`(매질 무대: 테·바탕·가운데 안내 슬롯 — 지도·카메라 무대 3벌 흡수, 배치·높이는 표면 소유 유지). styleguide.html 견본과 DESIGN.md 부품 장을 같은 커밋에 고친다.
3. **있는 부품으로 흡수한다.** 상태 알약→ui-tag, 사실 격자→`.ui-readout`(이름–값)·ui-grid(라벨 격자), 머리→ui-head, 빈 상태→ui-empty, 확인→confirmIrreversible·openLiveDialog(표면 JS의 `window.confirm` 금지를 게이트에 더한다), 증거 네 상태→ui-evidence, 글자→ui-text 척도, 점→ui-triage, 브랜드→`<ui-brand href>`, 이벤트 심각도는 한 매커니즘으로. 죽은 CSS는 지운다.
4. **값을 바로잡는다.** `status="good"`은 정의된 어휘(neutral·active)로 고치고 good은 ui-tag 어휘에 두지 않는다(정상에 색이 없다, D-82). `vh` 3곳은 `dvh`로. Fleet은 공용 칸 질의가 살도록 조상에 `container-type: inline-size`를 단다(배치 — 표면 소유).
5. **이행 순서는 web_common → 대시보드 → Fleet → Pilot → games다.** web_common이 부품과 게이트를 먼저 놓는다. 대시보드는 shell·panels·두 셸이 함께 쓰는 잎(map·vision·client·dom)부터 고치고, role-surfaces S2가 지울 legacy 항목은 이 회차가 건드리지 않는다. Fleet은 `index.html`·`install.html`의 복사된 상단바·카메라 블록도 같이 접는다. 단계마다 계약 시험 + 두 테마 390×844·320×568 캡처.
6. **`app.js` 830줄(D-362 초과)은 이 회차가 분할하지 않는다.** S2·D-362 대기열이 소유한다. 대시보드 안의 헬퍼 복붙(`setOff`·`el()/node()`)은 dom.js 수출 import로 바로잡는다(panels는 이미 `/assets/client.js`를 싣는다 — 같은 층이다).

### Alternatives

- **표면별 회차로 분산 처리:** 느리고 게이트가 없으면 같은 위반이 다시 자란다. 거절.
- **재도색 허용 목록 운영:** 예외가 규칙을 이긴다(D-359 "한 블록 규칙" 정신). 거절.
- **공용 부품 대규모 확장(넷 밖):** 두 표면 근거 없는 부품은 만들지 않는다(D-292). 거절 — 필요해지면 그때 ADR 항목으로 더한다.

### Consequences

표면 시트에서 얼굴이 사라지고 자리만 남는다(파일 크기도 줄어든다). ui-chip·ui-grid가 처음으로 제품에서 쓰인다. Fleet의 `window.confirm` 4곳이 공용 대화상자로 바뀌며 정지 컨트롤이 대화상자 위에서 산다(D-371과 같은 이유). games 보드는 ui-tag·ui-chip·ui-evidence·ui-text를 얹고 경기장 팔레트 `:root` 예외는 그대로다.

### Validation

- 게이트: face 대조 확장·`window.confirm` 금지·ui-tag 어휘 대조 — 각각 변이 증명(빨강 확인 후 복원).
- 시험: web_common 전량 + 각 표면 시험(대시보드·Fleet·pilot·games)이 초록.
- 캡처: 두 테마(dark·light) 390×844·320×568에서 머리 높이·넘침 없음 확인(D-359 §8).
- SOURCE/LOCAL 증거뿐, 실물 화면 수용은 별도 회차.

**Note (2026-10-13):** 이 ADR은 2026-10-13에 복원했다. 스윕 자체는 main에 없다 — 브랜치 `feat/d428-web-face-sweep` 작업 트리의 미커밋 파일 10개로만 있다. 본문의 `styles.css`·`shell/`·`panels/` 등 경로는 이전 레이아웃(`src/hmi/...`, `src/site/fleet/...`) 기준이며 현재는 `shared/web`, `middleware/ui/...`, `operations/ui/...` 아래에 있다.
