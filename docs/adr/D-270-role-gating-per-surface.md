## D-270 역할 게이팅은 표면이 정한다 — 조작은 말고 설정은 숨긴다

**Status:** Proposed (2026-09-26). 합동 검토(`docs/plans/2026-09-26-role-gating-model-joint.md`)의
제안안이다. role-menu 세션의 반례를 받는다.

잇는 결정: D-193(자격 수명) · D-247(AuthBar) · D-251(절차 카드 크롬) ·
concept 16 Law 0·Law 4.

**Context:**

두 모델이 공존한다. legacy `/dashboard`는 disabled+사유 병기(B),
새 role-menu 표면은 min_role 숨김(A)이다. 서버 강제는 둘 다 거울처럼
맞춘다(`safety/stop`=viewer·`release`=admin·조작계=operator). 고를 것은
보이는 방식뿐이다.

**Decision (초안):**

1. **조작 표면(운용 콘솔·Fleet 관제·게임)은 B다.** 존재를 말한다. E-Stop은
   전 역할 실행, 해제는 admin 병기 — 이미 구현된 모양이 계약이다.
2. **설정·정비 표면(setup·device 절차)은 A다.** 절차는 권한별로 다른 길이다.
   viewer에게 admin 절차를 보여줄 이유가 없다.
3. **경계는 표면 선언에 적는다.** `panels.yaml`의 `min_role`이 A의 자리,
   legacy 카드의 disabled+사유가 B의 자리다. 새 표면은 둘 중 하나를 선언한다.
4. **전부 A / 전부 B 안은 기각한다.** 전부 A는 운용자의 Law 0(존재 은폐),
   전부 B는 절차의 Law 4(청중이 아닌 말을 보여줌)를 깬다.

**Alternatives:** 합동 문서 현상 유지안 — 결정 없이 혼재가 굳는다. 전부
숨김안·전부 표시안 — 위 4항의 이유로 기각.

**Consequences (Accepted되면):** 합동 문서의 잠정 상태가 이 결정으로
대체된다. 어긋난 표면이 있으면 그 표면의 세션이 고친다.

**Validation / Transition:** (1) 표면별 모델 선언 대조, (2) role-menu
세션의 반례 없음. `ROSY ADR Log.md`에 `D-270 | 역할 게이팅은 표면이 정한다 |
Proposed` 1행 추가가 이 초안의 착지다.

**References:** D-193, D-247, D-251, D-258, concept 16 Law 0·Law 4,
`docs/plans/2026-09-26-role-gating-model-joint.md`.

---
