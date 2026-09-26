## D-248 AuthBar — 공유 규칙은 못박고, headless는 뽑지 않고, 잠금 폴링만 멈춘다

**Status:** Accepted (2026-09-25). 잠금 플래그 + pill 덮기 방지 + G2 잠금 셀 + 변이 증명으로 착지. (번호: D-247·D-253을 거쳐 D-248로 확정. 롤아웃 계획의 실행 순서와 맞춘다. 내용은 동일.)

잇는 결정: [D-193](D-193-login-code-and-credential-lifecycle.md)(자격 수명) · [D-233](D-233-design-system-component-token-draft.md)(L2 후보 AuthState) · [D-245](D-245-estop-pilot-kind-question-role-note.md)(파일럿 선례) · D-130.2.

**Context (실측):**

| 항목 | CORE `src/hmi/dashboard/client.js` | Fleet `src/site/fleet/fleet/server/web/console.js` + `server/app.py:135-140` |
|---|---|---|
| 토큰 종류 | 만료·역할 포함 (paired/card/manual) | 정적 공용 1개 — `Bearer` 문자열 비교, 만료·신원 없음 |
| 저장 | sessionStorage 기본. paired + 유지 체크 + 7일 이내만 localStorage | sessionStorage만 (`rosy-console-token`) |
| 신원·만료 표시 | whoami 뱃지 (role/source/expiry) | 없음 — 서버에 whoami/만료 계약이 없음 |
| 401 | WS 4403은 재시도 중단, 4401은 whoami 재확인 | `markLocked()` + pill `토큰 필요` |
| 입력 | 코드 8자 + 토큰 2탭 + 유지 체크 | 토큰 1칸, Enter·버튼 저장 (`console.js:881-896`) |

간극 1개: `console.js:70` 주석은 "폴링이 계속 401을 두드리기 전에"라고 쓰지만 코드는 잠긴 뒤에도 `refreshState`(1s)·`refreshMap`·`refreshFormation`(5s)을 계속 돌린다. CORE 규칙(거부된 자격으로 두드리지 않는다)에 어긋난다.

**Decision (초안):**

1. **공유 규칙(AuthBar 규격)을 못박는다.** sessionStorage 기본 · persist는 만료+명시 옵트인만 · 잠금은 pill 언어로 · 401은 이유 표시 + 두드림 중단. CORE는 전부, Fleet은 끝 1항(두드림 중단)만 미달이다.
2. **L2 AuthState headless는 뽑지 않는다.** 공유할 로직이 sessionStorage 래퍼 3줄뿐이고, Fleet 서버에 whoami/만료 계약이 없어 D-130.2 자격(로직 + 2표면)에 못 미친다. Fleet 서버에 신원 계약이 생기면 그때 API-ref 사이클에서 심사한다.
3. **파일럿 커밋은 잠금 플래그다.** `markLocked`/`markUnlocked`가 `auth.locked`를 세우고/내리고, 세 폴링 진입점에서 잠기면 조용히 건너뛴다(토큰 저장·수동 새로고침은 그대로). 문구·간격·API는 그대로라 PINNED·적합 게이트에 손대지 않는다.
4. **바꾸지 않는 것.** Fleet 정적 토큰을 만료형으로 바꾸지 않는다(서버 계약, 별도 ADR). CORE 2탭 로그인을 Fleet에 이식하지 않는다(관제PC 단일 토큰이 계약이다).

**Alternatives:** headless AuthState를 지금 뽑는 안 — 공유 로직이 없어 D-130.2 위반. Fleet에 whoami를 신설하는 안 — 서버 계약 신설이라 파일럿 크기 초과. 폴링을 그대로 두는 안 — 주석과 코드가 어긋난 채로 남고, 잠긴 관제PC가 401을 1초마다 두드린다.

**Consequences (Accepted되고 파일럿이 끝나면):** AuthBar 규격 4항이 D-248 이후의 선례가 된다. Fleet 토큰 저장은 이미 규격이라 손대지 않는다.

**Validation / Transition:** (1) `test_web_dialog_contract.py` + `src/hmi/web/test` + `src/site/fleet/test`(D-242 잔재 1건 제외) 녹색, (2) `ROSY_RUN_BROWSER_TESTS=1 test_fleet_console_browser.py` 녹색 + 잠금 셀 캡처(`docs/validation/uiux-surfaces-2026-09-25/`에 1셀 추가), (3) 변이 증명: 플래그 제거 → 401 폴링 지속(기존 행위). `ROSY ADR Log.md`에 `D-248 | AuthBar — 잠금 폴링 중단 | Accepted` 1행 추가가 이 초안의 착지다.

**References:** D-130, D-193, D-218, D-233, D-245, `src/site/fleet/fleet/server/app.py`, `test/test_web_dialog_contract.py`.

---
