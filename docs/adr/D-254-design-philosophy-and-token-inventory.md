## D-254 디자인 철학과 토큰 전집 — concept 16을 읽는 법과 닫힌 집합의 목록

**Status:** Accepted (2026-09-26). 전집과 코드의 일치(51 passed) + 파일:행 대조로
착지. 흩어진 결정(철학·토큰·부품·게이트)을 한 문서에서 가리킨다. 어긋난 이름
1건(D-233의 층 번호)을 여기서 바로잡는다.

잇는 결정: concept 16 · [D-92](D-92-l2.md) · [D-130](D-130-l2-headless.md) ·
[D-194](D-194-shared-browser-controls.md) · [D-195](D-195-measure-and-shared-palette.md) ·
[D-201](D-201-fixed-grammar-surfaces-fit-contract.md) · [D-218](D-218-web-dialogs-name-the-action.md) ·
[D-233](D-233-design-system-component-token-draft.md).

**Context:**

철학은 concept 16에 이미 있다(5법칙·4문법·증거 4상태·어휘). 토큰은
`src/hmi/web/tokens.css`에 이미 닫혀 있다. 그런데 세 가지가 어긋나 있다.
첫째, D-233이 층을 L0/L1/L2라 불렀는데 concept 16 §4는 L1/L1.5/L2/L3라 부른다 —
같은 것을 가리키는 이름이 둘이다. 둘째, concept 16 §4의 부품 목록에
`ui-empty`·`ui-shell`·`ui-topbar`·`ui-brand`·`ui-section`이 빠져 있다(코드는
`src/hmi/web/ui.js:172-204`에 있다). 셋째, concept 16 §4·§6·§10이 옛 경로
(`web_common/`, `control/web/`)를 가리킨다(D-241·D-242·D-243 이동 전).

**Decision (초안):**

1. **층 번호는 concept 16을 따른다.** D-233의 L0/L1/L2 표기는 이 ADR 이후 쓰지
   않는다. 대응표: D-233 L0 = concept L1(법·토큰), D-233 L1 = concept L1의
   브라우저 크롬, D-233 L2 = concept L1.5(headless), 표면 소유 = concept
   L2(문법)+L3(내용). D-233 본문은 Proposed라 이 대응표로 읽는다.
2. **토큰 전집 (`tokens.css`, 닫힌 집합).** ground(바탕·글자·선, H258 무채도) ·
   status(임계 전용, 따뜻한 띠) · series(계열, 차가운 띠) · raster(무채색 단조,
   대시보드 파이프라인 전용) · space 6단계(4의 배수) · radius 4종 · target 3종
   (크기가 위험도를 말함) · topbar-height · surface(flat/raised/line/sheen) ·
   nominal(정상은 색이 아님) · component(주 명령은 가장 밝은 중립) · gauge(임계
   전 중립) · type 6단계 + body/mono 서체 · track-label. 추가는 닫힌 집합을
   여는 ADR과 함께만 온다.
3. **L1 크롬 전집 (`ui.js` + `components.css`, 13종).** `ui-button`(5 kind) ·
   `ui-field` · `ui-tag`(neutral/warn/crit) · `ui-text` · `ui-head` · `ui-grid` ·
   `ui-chip` · `ui-triage` · `ui-evidence`(4 state) · `ui-empty` · `ui-shell`(4
   grammar) · `ui-topbar` · `ui-brand` · `ui-section`. 배치는 표면, 재도색
   금지(`test_shared_controls.py`).
4. **L1.5 전집.** `HeadlessState`(증거 판정) · `hold-ticker.js`(홀드 운율+해제
   zero, D-250). 자격은 "로직 + 2표면 필요"(D-130.2), 처소는 `src/hmi/web/`.
5. **concept 16의 옛 경로는 이 ADR에서 고치지 않는다.** §4·§6·§10의
   `web_common/`·`control/web/` 표기는 D-241·D-242·D-243 이후 낡았다. 아키텍처
   문서의 주인이 고치는 것이고, 이 ADR은 대조표로만 남긴다:
   `web_common/` → `src/hmi/web/`, `control/web/dashboard.html` →
   `src/runtime/sensing/web/dashboard.html`, `src/runtime/core_api_web/.../web/` →
   `src/hmi/dashboard/`.

**Alternatives:** concept 16을 직접 고치는 안 — 아키텍처 문서의 소유 범위를
넘는다. D-233을 L0/L1/L2로 밀고 concept을 따르게 하는 안 — 상위 문서가 이미
Accepted인 이름을 쓰는 쪽이 이긴다. 토큰을 새로 여는 안 — 근거 미달.

**Consequences (Accepted되면):** 층을 말할 때는 concept 번호를 쓴다. 새 토큰·새
크롬·새 headless는 이 전집의 어느 칸에 드는지를 밝혀야 한다. concept 16의 경로
수정 자체는 별도 변경이다.

**Validation / Transition:** (1) `src/hmi/web/test` 녹색(전집과 코드의 일치),
(2) 이 문서의 파일:행이 실재와 일치(리뷰 대조). `ROSY ADR Log.md`에
`D-254 | 디자인 철학과 토큰 전집 | Proposed` 1행 추가가 이 초안의 착지다.

**References:** concept 16 §2·§3·§4·§5·§6·§7·§10, D-72, D-82, D-92, D-129,
D-130, D-194, D-195, D-201, D-218, D-233, `src/hmi/web/tokens.css`,
`src/hmi/web/ui.js`, `src/hmi/web/template.html`.

---
