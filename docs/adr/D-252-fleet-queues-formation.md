## D-252 Fleet 큐·대형 — 머리만 triage로, 대기는 문장으로 미리 말한다

**Status:** Accepted (2026-09-26). 큐 머리 triage + 대기 요약 + 계약·브라우저 녹색 + 변이 증명 + G2 2셀로 착지.

잇는 결정: [D-92](D-92-l2.md) 제5항 · [D-218](D-218-web-dialogs-name-the-action.md)(F-20) ·
D-219(운용 요약 어휘) · concept 16 §7.3(예외 문법).

**Context (실측):**

큐 패널(`index.html:51-64`, `console.js:515-547`)은 평범한 `h3 + ul` 2벌이다.
행 내용은 계약으로 고정돼 있다(`test_console_queues_contract.py`,
브라우저 큐 시험: `#critical-list li` 1건·`#warning-list li` 1건, 문구 단언,
빈 큐 숨김). 대형 폼(`index.html:71-101`)은 무장 전 요약이 없다 — 비활성 때
안내문 1줄뿐이다(`console.js:702-704`). 대기 슬롯 좌표는 서버 기하
(`fleet.formation.geometry`)가 쥐고 있어 클라이언트가 미리 그릴 수 없다.

**Decision (초안):**

1. **큐 머리를 `ui-triage`로 바꾼다.** `h3` 자리에 상태 머리(`<b>주의 N</b>` +
   `<small>로봇 이름들</small>`, status warn/crit)가 들어가고, `ul` 행·id·
   빈 숨김·grid 배치는 그대로 둔다. 계약 선택자(`#warning-list` 등)를
   깨뜨리지 않는다.
2. **대기 요약은 문장으로 미리 말한다.** 비활성 때 안내문을 폼 현재값으로
   채운다(`리더 rosy_01 · COLUMN 0.6m · 3대`). 지도 고스트 미리보기는 하지
   않는다 — 서버 기하를 JS에 복제하는 순간 단일 출처가 깨진다.
3. **파일럿 커밋 범위.** 큐 머리 교체 + 대기 요약 바인딩. 행 문구·API·배치
   불변이라 PINNED·적합 게이트에 손대지 않는다.
4. **바꾸지 않는 것.** HITL 행의 정직한 경로 문구(D-218 F-20), 빈 큐 숨김
   (Law 1), 대형 단일 세션 규칙.

**Alternatives:** 지도 고스트 미리보기안 — 기하 복제로 기각. 큐 행까지
triage 행으로 바꾸는 안 — 계약 문구와 선택자를 둘 다 흔들어 파일럿 초과.
아무것도 하지 않는 안 — 무장 전 확인 수단 없이 대형을 여는 상태가 남는다.

**Consequences (Accepted되고 파일럿이 끝나면):** Fleet 예외 패널의 머리 어휘가
`ui-triage`로 닫힌다. 대기 요약이 무장 전 마지막 확인이 된다.

**Validation / Transition:** (1) 큐·대형 계약 + `ROSY_RUN_BROWSER_TESTS=1`
Fleet 12종 녹색, (2) G2 셀 2개(큐 triage 렌더·대기 요약), (3) 변이 증명(triage
제거 → 머리 소실 적색). `ROSY ADR Log.md`에 `D-252 | Fleet 큐·대형 | Proposed`
1행 추가가 이 초안의 착지다.

**References:** D-92, D-130, D-201, D-218, D-219, D-233, concept 16 §7.3,
`src/site/fleet/fleet/server/web/index.html`,
`src/site/fleet/fleet/server/web/console.js`.

---
