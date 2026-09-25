## D-251 절차 카드 — 크롬 규칙만 못박는다. 헬퍼는 이미 dom.js에 있다

**Status:** Accepted (2026-09-26). 코드 변경 0줄이 결과인 파일럿으로 착지.

잇는 결정: [D-201](D-201-fixed-grammar-surfaces-fit-contract.md)(편집은 절차로) ·
[D-130](D-130-l2-headless.md) 2항 · [D-249](D-249-fieldmap-spec-no-extraction.md)(뽑지 않음의 선례).

**Context (실측):**

점검뷰의 11종 카드(host 3 + 설정 8)는 같은 크롬을 반복한다: `header(h3 +
mode-chip)` → `host-note` → `form(type="button" 저장)` → `*-message`. 공유
로직으로 보이는 것(`fillNumberInput`·`fillSelect`·`fillTextInput`·
`setFieldMessage`·`setEnabled`·`bindFormSave`)은 이미 `src/hmi/dashboard/dom.js:120-153`에
있고 대시보드 안에서만 쓰인다. Fleet 폼(대형 select·신호 버튼·토큰 칸)은 소박해서
공유할 로직이 없다. 즉 D-130.2 자격(로직 + 2표면)에 못 미친다.

**Decision (초안):**

1. **카드 크롬 규칙을 못박는다.** 절차 카드의 순서는 고정이다:
   제목행(역할 chip 포함) → 안내문(로컬 저장 위치를 말함) → 폼(저장은
   `type="button"` + `bindFormSave`, Enter 내비게이션 금지) → 결과 메시지
   (`role="status"`). 새 절차 카드는 이 순서를 따른다.
2. **코드는 뽑지 않는다.** dom.js 헬퍼는 이미 공유 위치에 있고, 크롬은 장식이라
   뽑는 순간 표면 문법을 오염시킨다.
3. **파일럿 커밋은 이 ADR + 로그뿐이다.** 11종 카드가 규칙을 어기는 곳이 있으면
   그때 개별 수정으로 다룬다(이번 실측에서는 없음).

**Alternatives:** 크롬을 `ui-settings-card`로 뽑는 안 — 단일 표면의 장식이라
D-92 제5항 위반. Fleet 폼을 dom.js로 합치는 안 — 소비자가 둘이 아니라
합치기가 목적이 된다. 11종 카드Rewrite안 — 동작 동결 중인 점검뷰를 흔든다.

**Consequences (Accepted되면):** 절차 카드 인벤토리는 닫힌다. 새 카드는 크롬
순서를 따르는지로 리뷰한다.

**Validation / Transition:** (1) `hmi/dashboard/test` + `gateway` 대시보드 시험
녹색(변경 없음 확인), (2) 11종 카드의 DOM 순서 대조(리뷰). `ROSY ADR Log.md`에
`D-251 | 절차 카드 — 크롬 규칙 고정 | Proposed` 1행 추가가 이 초안의 착지다.

**References:** D-92, D-130, D-201, D-233, D-249, `src/hmi/dashboard/dom.js`,
`src/hmi/dashboard/settings.js`.

---
