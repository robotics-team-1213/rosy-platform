## D-266 진단 PARKED 해제 조건 — 계약 편입이 먼저다

**Status:** Proposed (2026-09-26). D-255의 B3를 여는 초안. 해제 자체가 아니라
해제 조건이다. sensing 주인의 판단이 필요하다.

잇는 결정: [D-77](D-77-core-dashboard.md) · [D-150](D-150-web-node-control-navigation-map.md) ·
[D-153](D-153-ui-ux.md) · [D-201](D-201-fixed-grammar-surfaces-fit-contract.md) ·
[D-218](D-218-web-dialogs-name-the-action.md).

**Context:**

진단은 PARKED라서 대화상자 계약(`SURFACES`는 `*.js`만 본다)과 G2 행렬 밖에
있다. 무확인 E-Stop·해제 버튼(`data-post`)이 계약 없이 살아 있다. 해제하려면
먼저 계약에 들어와야 하고, 계약에 들어오려면 단일 파일 1IIFE 구조를 깨지
않아야 한다(D-150).

**Decision (초안 — 해제 조건 4항):**

1. **대화상자 계약 편입.** `test_web_dialog_contract.py`의 SURFACES가
   `dashboard.html` 내 인라인 스크립트를 읽는다. alert/prompt 금지 +
   confirm 핀 현황을 고정한다(현재: confirm 0 — 무확인 E-Stop이 핀으로
   박힌다).
2. **무확인 E-Stop 처분.** 핀에 박힌 무확인을 용인(디버그 표면의 즉시성)하거나
   네이티브 confirm을 단다. 둘 중 하나를 고르고 핀에 적는다. Helm 없음.
3. **G2 셀 3개.** 감지(라이다 다이얼)·관측(지도+경로)·조작(수동 조종) 최소
   1셀씩. IIFE stub harness(`tools/test_dashboard_*.cjs`)가 있으면 재사용.
4. **위 3항이 끝나면 PARKED를 뗀다.** D-153 카드가 PARKED→HOLD/GO로 바뀐다.
   그 전까지 진단은 PARKED로 남는다.

**Alternatives:** 계약 없이 해제하는 안 — 무확인 E-Stop이 영원히 감시 밖이다.
1IIFE를 깨고 모듈화하는 안 — D-150 위반. 현상 유지안 — B3가 영원히 열린다.

**Consequences (Accepted되면):** sensing 주인이 1~3항을 실행한다. 프론트
레인은 핀 현황 리뷰로 돕는다.

**Validation / Transition:** (1) 계약 시험 녹색(핀 포함), (2) G2 3셀, (3)
PARKED 해제 amendment. `ROSY ADR Log.md`에 `D-266 | 진단 PARKED 해제 조건 |
Proposed` 1행 추가가 이 초안의 착지다.

**References:** D-77, D-150, D-153, D-201, D-218, concept 16 §7.

---
