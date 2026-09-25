## D-233 디자인 시스템 초안 — 토큰 동결, 컴포넌트 3층, 표면이 레이아웃을 가진다

**Status:** Proposed (2026-09-25, 초안). 이 ADR은 결정하지 않는다. D-92·D-130·D-157·D-194·D-195·D-201·D-218 위에 컴포넌트 인벤토리와 토큰 운용 규칙의 초안을 올리고, 첫 회차(D-153 G2) 전에 반례를 받는다.

잇는 결정: [D-92](D-92-l2.md)(어휘 표) · [D-129](D-129-l1-d-92-1.md)(토큰 단일 파일) · [D-130](D-130-l2-headless.md)(문법 게이트 + headless 조건) · [D-153](D-153-ui-ux.md)(표면 단위 평가) · [D-157](D-157-shared-headless-ui-package-monorepo-web-decoupling.md)(중립 패키지) · [D-194](D-194-shared-browser-controls.md)(조작 부품 한 벌) · [D-195](D-195-measure-and-shared-palette.md)(치수 닫힌 집합) · [D-201](D-201-fixed-grammar-surfaces-fit-contract.md)(적합 계약) · [D-218](D-218-web-dialogs-name-the-action.md)(확인=네이티브) · [D-241](D-241-core-package-directories-use-role-names.md) · [D-242](D-242-remaining-role-directories.md)(역할 디렉터리 — 패키지 이름 유지) · [D-243](D-243-operator-screens-live-in-hmi.md)(운용 화면은 `src/hmi/dashboard`).

**Context:**

1. 다섯 표면이 같은 개념을 다른 마크업으로 들고 있다. E-Stop은 운용뷰(`src/hmi/dashboard/index.html:245-250`)·Fleet(`src/site/fleet/fleet/server/web/index.html:24`)·게임(`src/site/games/games/web/index.html:38`)·control 진단(`src/runtime/sensing/web/dashboard.html:415-425`)에 4벌, 지도는 `map.js` vs `console.js:paintGrid` vs 진단 mapwrap으로 3벌, 텔레옵 hold-to-drive는 운용뷰와 진단 `.pad/.keys`로 2벌이다. (2026-09-25 재검증: D-241·D-242·D-243 역할 디렉터리 이동 반영. 운용 대시보드는 `src/runtime/api_web/core_api_web/web/`에서 `src/hmi/dashboard/`로(D-243 운용 화면 hmi), `web_common`은 `src/hmi/web/`으로·`control`은 `src/runtime/sensing/`으로(D-242) 이동. 패키지 이름·import는 유지. 내용 동일함을 같은 날 재확인.)
2. 역할 게이팅은 CORE에만 있다(`client.js:isAdmin`, `app.js:876-910`, `data-role="administrator"`). Fleet은 단일 관제 토큰(`server/web/console.js:22-24`), 게임·진단은 무인증이다. 컴포넌트를 뽑기 전에 역할×표면 행렬이 없었다.
3. 스킬 충돌을 미리 정리한다. `frontend-design` 스킬은 대담한 미학·모션·질감을 요구하지만, 이 트리의 법(표면 시트 주석: 그라디언트·글로우·드롭섀도·등장 애니메이션 금지, 깊이는 면과 실선으로만)이 이긴다. 스킬의 기여는 장식이 아니라 문법 약속(공간·예외·초점·절차)과 증거 상태·적합 계약의 엄격한 집행이다. `web-design-guidelines`는 리뷰 체크리스트로만 쓴다.
4. D-130은 headless 처소를 CORE 웹 패키지라 했고 D-157은 중립 패키지로 옮겼다. D-242가 그 디렉터리를 `src/hmi/web/`으로 개명했다(패키지 이름 유지). 이 초안은 그 처소를 따른다 — 새 패키지를 만들지 않는다.

**Decision (초안):**

1. **토큰은 동결이다.** `src/hmi/web/tokens.css`가 색·타입의 단일 출처(D-129). 간격·모서리·글자는 `--space-*`·`--radius-*`·`--text-*` 닫힌 집합(D-195). 진단 래스터(`--unk/--free/--wall`)와 게임 피치 `:root`만 예외로 남는다(D-194). 토큰 값·이름 변경은 전 표면 D-153 재평가 트리거다.
2. **컴포넌트는 3층이다.**
   - **L0 토큰** — `tokens.css`. 표면이 재선언 금지(`test_shared_controls.py`).
   - **L1 공유 조작 부품** — `components.css` + `ui.js` (`ui-button 5 kind`, `ui-tag`, `ui-text`, `ui-head/grid`, `ui-chip`, `ui-triage`, `ui-evidence`, `ui-empty`, `ui-field`, `ui-shell/topbar/brand`). 주인은 `src/hmi/web`, 배치는 표면. 새 L1은 어휘 표 개정과 같은 커밋에서만(Styleguide 동기 수정).
   - **L2 headless 로직** — `core_ui_logic.js`(HeadlessState/증거 판정) 패턴. 자격은 D-130.2 그대로: 로직이 있고 둘 이상의 표면이 필요할 때만, 스타일 0, `::part` 노출, 처소는 `src/hmi/web`. 지금 자격 충족 후보는 `AuthState`(만료·whoami)·`TeleopHold`(100ms hold)·`EvidenceAge`(fresh/delayed 단 하나의 시계)뿐이다. 확인 다이얼로그는 뽑지 않는다 — D-218이 네이티브 `confirm`으로 졸업시켰다.
   - **표면 소유** — 그 외 전부(히어로, 텔레메트리 그리드, 호스트 카드, 설정 카드 8종, 로스터, 대형 폼, 피치, LiDAR 다이얼)는 표면 시트에 남는다. 중복이 셋째 표면에 등장하면 그때 L2 자격을 심사하고, 그전에는 복제를 유지한다(D-92 제5항 "쓰이지 않는 컴포넌트는 결함을 숨긴다").
3. **역할×표면 행렬이 게이트 조건이다.** CORE 운용(viewer 읽기+E-Stop / operator 모드·teleop·목표 / admin 해제), CORE 점검(읽기 / 웨이포인트·SLAM·언도크 / 네트워크·릴리스·신원·토큰·정책), Fleet 단일 토큰(읽기·목표·대형·e-stop 동일 권한 — 확인 문구로 보완), 게임(전원 심판 — 관전 readonly 미구현), 진단(무인증 엔지니어 — 배포 제외로 격리). 새 조작 컴포넌트는 이 행렬의 셀을 명시하지 않으면 L1/L2에 들지 않는다.
4. **인벤토리(우선순위).** P0: `AuthBar`(CORE drawer + Fleet tokenbar 통합, 저장소는 sessionStorage/pair 규칙 유지) · `EStopBlock` · `FieldMap`(레이어·legend·empty — 래스터 팔레트는 파이프라인과 함께) · `TeleopPad`. P1: `HostCard`/`SettingsFormRow`(`bindFormSave` 포함) · `EventList` · `VisionStage` · `RosGraphMap`. P2: Fleet `QueuesPanel`을 `ui-triage` 위로, `FormationForm`에 슬롯 미리보기, `ConfirmIrreversible`은 만들지 않고 PINNED_CONFIRMS 표 유지. P3: 게임 `ScoreBoard` + readonly 관전 prop. P4 진단은 기능 동결, 토큰 합치만 허용.
5. **적합 계약은 그대로.** D-201의 문서 스크롤 금지·분쇄 검사·안전조작 가시성을 새 컴포넌트도 상속한다. 새 패널은 선언 뷰포트 캡처(D-153 G2) 없이 GO를 주장하지 않는다.

**Alternatives:** 전면 공용 라이브러리(D-92 기각 유지 — 근거 미달). 표면별 완전 중복 유지(4벌 E-Stop의 문구 drift를 방치 — F-20 선례가 반증). 커스텀 모달 확인 컴포넌트(D-218이 비용으로 기각). 새 `ui-*` 패키지 신설(D-157·D-231에 위배).

**Consequences (초안이 Accepted되면):** L1 추가는 어휘 표 + Styleguide + 게이트 시험을 같은 커밋에 동반한다. L2 추가는 두 표면의 사용처와 함께 온다. 토큰 변경은 전 표면 회차를 연다. 첫 회차 전까지 이 초안의 어떤 인벤토리도 GO가 아니다(D-153과 같은 논리).

**Validation / Transition:** `src/hmi/web/test/test_shared_controls.py` + `test_ui_token_contracts.py` + `test_palette_gates.py` 그대로(새 게이트 없음). 전이는 (1) 이 초안에 대한 반례 수집, (2) P0 중 `EStopBlock` 문구 통일 1건으로 파일럿, (3) `docs/validation/uiux-surfaces-<date>/` 회차에 캡처. `ROSY ADR Log.md`에 `D-233 | 디자인 시스템 초안 — 토큰 동결, 컴포넌트 3층 | Proposed` 1행 추가가 이 초안의 착지다.

**References:** concept 16 §2·§3·§4·§5·§7, D-72, D-75, D-77, D-82, D-88, D-101, D-129, D-203, D-214, `src/hmi/web/template.html`(문법 4종), `src/hmi/dashboard/styleguide.html`(어휘 실행 사본).

---
