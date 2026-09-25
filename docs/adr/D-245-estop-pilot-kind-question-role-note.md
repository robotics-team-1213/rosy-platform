## D-245 E-Stop 파일럿 — 4벌 실측, 통일할 것은 종류·물음형·권한 병기뿐이다

**Status:** Proposed (2026-09-25). 롤아웃 계획(`docs/plans/2026-09-25-design-system-rollout-design.md`) §3-1의 파일럿. 네 표면을 다시 설계하지 않는다. 코드 변경은 Fleet 전체 정지 버튼의 범위 병기 한 줄이다.

잇는 결정: [D-218](D-218-web-dialogs-name-the-action.md)(확인=네이티브, PINNED 표) · [D-233](D-233-design-system-component-token-draft.md)(인벤토리 P0) · D-92 제5항 · concept 16 Law 3·Law 4.

**Context (실측):**

| 표면 | 호출 버튼 | kind | 확인 문장 | 해제 |
|---|---|---|---|---|
| 운용 대시보드 `src/hmi/dashboard/index.html:245-250` | 즉시 정지 + `모든 역할에서 실행 가능` | irreversible | `Rosy를 즉시 정지할까요?` (`app.js:1389`) | 정지 해제 + `관리자 권한 필요`, `주변 안전을 확인했고 정지를 해제할까요?` (`app.js:1401`) |
| Fleet `src/site/fleet/fleet/server/web/index.html:24` | 전체 정지 (병기 없음) | irreversible | `등록된 모든 로봇을 정지시킵니다. 계속할까요?` (`console.js:641`) | 없음 (대형 해제는 별도) |
| 게임 `src/site/games/games/web/index.html:37-40` | 정지 + `스페이스도 양쪽을 세운다` | irreversible | 없음 — D-218이 확인 없는 표면으로 둠 | 없음 |
| 진단 `src/runtime/sensing/web/dashboard.html:415-425` | 정지 / 해제 (병기 없음) | irreversible danger / quiet, `data-post` | 없음 | 해제 (권한 병기 없음) |

핀 현황: `test/test_web_dialog_contract.py:26` — app.js 9, settings.js 11, map.js 1, console.js 1. 실측과 일치한다(대시보드 9곳, Fleet 1곳). 진단은 인라인 스크립트라 `SURFACES`의 `*.js` glob에 잡히지 않는다 — 계약 밖이다.

**Decision (초안):**

1. **통일하는 것은 세 가지뿐이다.** (a) 호출 버튼은 `kind="irreversible"` 채움으로 나른다(Law 3 시각 범주). (b) 확인 문장은 결과를 묻는 물음형(`~할까요?`)이며 대상을 이름으로 부른다(D-218 결정 2). (c) 해제 버튼에는 권한을 병기한다. 네 표면 중 (a)(b)는 이미 전부, (c)는 대시보드만 만족한다.
2. **버튼 라벨 자체는 통일하지 않는다.** `즉시 정지` / `전체 정지` / `정지`는 각 표면 청중의 평문이다(Law 4). `전체 정지`를 `즉시 정지`로 고르면 Fleet 청중이 잃는 정보(범위: 등록된 모든 로봇)가 있다. 라벨 통일은 이 파일럿의 비목표다.
3. **파일럿 커밋은 Fleet 한 줄이다.** `전체 정지` 버튼에 범위 병기를 단다 — 확인 문장에 이미 있는 말(`등록된 모든 로봇`)을 버튼으로 올린다. 마크업·배치는 Fleet 표면 소유로 둔다. PINNED 횟수는 불변(새 확인 없음)이라 계약 시험 수정은 없다.
4. **진단은 손대지 않는다.** PARKED 표면(D-153 결정 4, D-201 대상 제외)이며 계약 glob 밖이다. 진단의 무확인 E-Stop은 이 ADR의 허용이 아니라 미결로 남기고, 다음 회차에서 다룬다. 게임의 무확인은 D-218이 둔 것이므로 유지한다.

**Alternatives:** 네 표면 라벨 강제 통일안 — Law 4 위반이라 기각. 진단까지 계약 편입안 — 인라인 스크립트를 `*.js`로 뽑는 구조 변경이 따라와 파일럿 크기를 넘는다. 아무것도 하지 않는 안 — (c) Fleet 병기 부재가 남아 D-248(AuthBar)의 전제(역할×표면 행렬)가 빈칸으로 간다.

**Consequences (초안이 Accepted되고 파일럿이 끝나면):** E-Stop 규격(채움·물음형·권한 병기)이 D-245 이후의 선례가 된다. PINNED 표는 그대로다. 진단 제외는 미결로 기록된다.

**Validation / Transition:** (1) `python -m pytest test/test_web_dialog_contract.py src/hmi/web/test -q` 녹색 (핀 불변), (2) `ROSY_RUN_BROWSER_TESTS=1` Fleet 전체 정지 거부 경로 녹색이면 Accepted, (3) `docs/validation/uiux-surfaces-<date>/`에 Fleet 캡처 1셀. `ROSY ADR Log.md`에 `D-245 | E-Stop 파일럿 — 종류·물음형·권한 병기 | Proposed` 1행 추가가 이 초안의 착지다.

**References:** D-92, D-153, D-201, D-218, D-233, `test/test_web_dialog_contract.py`, `test/test_fleet_console_browser.py`.

---
