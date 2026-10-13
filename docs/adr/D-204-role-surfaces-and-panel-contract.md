## D-204 역할별 CORE 화면과 패널 계약

**Status:** Accepted (2026-09-24)

**Context:** CORE `/dashboard` 한 페이지가 현장 운용, 작업 준비, 설치·정비를 모두 싣는다.
concept 16 §2는 Robot console과 Device runtime을 다른 화면으로 정의했지만 Device runtime은
`/dashboard`의 `점검` 뷰로 살아 있다. 패널은 HTML에 항상 있고 capability 판단은 JS 곳곳에
흩어져 있어 §8의 "`not_provided`는 생략"이 구조로 보장되지 않는다. 자산 허용목록은 손으로
적는 목록이다. 설계: `docs/plans/2026-09-24-role-surfaces-panel-composition-design.md`.

**Decision:**

1. **조립 축은 역할→화면, capability→패널이다.** 기기는 renderer를 싣지 않는다(concept 16 §8).
2. **CORE 화면은 세 개다.** `/console`(운용, spatial), `/setup`(작업 준비, procedure),
   `/device`(설치·정비, procedure). e-stop은 패널이 아니라 셸이 세 화면 같은 자리에 하나만 둔다.
3. **패널 레지스트리 `middleware/ui/robot/panels.yaml`이 유일한 조립 규칙이다.** CORE는 기동 때 검증하고 틀리면
   기동을 거부한다.
4. **`GET /api/v1/ui/surfaces/{surface}`가 매니페스트다.** CAP-001(`withhold_hardware_flags` 적용 후)과
   inventory descriptors를 읽기만 한다(D-68). `requires`가 거짓이거나 descriptor가 `not_provided`면
   패널을 뺀다. 역할이 낮으면 뺀다. UI의 역할 판단은 표시용이며 권한의 정본은 API `require_role`이다.
5. **패널 계약:** `export function mount(el, ctx) → unmount`. `ctx = { api, store, role, panel }`.
   패널은 `/common/*` 외에는 import하지 않고, 서로 부르지 않으며, inline style을 쓰지 않는다.
   한 패널의 실패는 그 슬롯에만 머문다.
6. **자산 허용목록은 셸 파일과 레지스트리에서 기동 때 만든다.** 정확히 일치하는 집합이며 폴더 스캔이
   아니다. 새 접두 `/assets/*`로 서빙하고 `/dashboard/assets/*`는 이관이 끝날 때까지 같은 목록을 쓴다.
7. **파일 예산:** 패널 JS ≤ 400줄, 셸 JS ≤ 300줄.

**Consequences:** 로봇마다 다른 화면은 코드가 아니라 capability YAML이 만든다. 새 기기 기능은
패널 파일 하나와 레지스트리 한 줄로 붙는다. `/dashboard`는 S4에서 `/console`로 리다이렉트되고
`app.js`는 해체된다. Fleet 콘솔의 같은 계약 이관은 별도 결정이다.

**Note (2026-10-13):** 이 결정은 a49707919("feat(ui): add role-based base surfaces")로 구현되었고, 이 기록은 2026-10-13에 복원했다. 코드는 `middleware/core/api/core_api_web/api/`(레지스트리·매니페스트)와 `middleware/ui/robot/`(셸·패널)에 있다. 결정 내용은 바꾸지 않았다.
