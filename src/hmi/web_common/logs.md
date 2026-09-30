# web_common logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-22 이전 이력은 `git log -- src/core/web_common`를 본다.

## 2026-09-22 · uncommitted · docs(harness): register web_common under D-168
- 변경: `AGENTS.md`(없던 경우), `progress.md`, `logs.md` 추가, `harness.yaml` 등록
- 증거: `PYTHONPATH=src/core:src python -m pytest src/core/core/test/test_ui_token_contracts.py src/core/core/test/test_palette_gates.py -q` — checked from core suite (1056 passed, 12 skipped, 2026-09-22 Windows); no own test/ yet (D-168 KNOWN_WITHOUT_OWN_TESTS)
- gate 변화: 없음(신규 기록). SOURCE HOLD(자체 시험 없음), LOCAL GO(core 스위트), 나머지 N/A
- 결정: D-168
- 교훈: 없음

## 2026-09-24 · uncommitted · test(core): 토큰·팔레트·헤드리스 시험을 자체 `test/`로 이전

- 변경: `src/core/core/test/{test_ui_token_contracts,test_palette_gates,test_headless_state}.py` → `src/core/web_common/test/`(`git mv`) + `test/conftest.py`(`core_api_web`·`core_features`·`core_common` sys.path — ui_token은 실제 FastAPI app을 세운다). D-168 `KNOWN_WITHOUT_OWN_TESTS`에서 `web_common` 제거, `harness.yaml` 경로 갱신(헤드리스를 `tests`에 추가), AGENTS·progress 동기화, SOURCE gate HOLD→GO. ament_cmake라 colcon test 배선은 없고 CI 4경로·직접 pytest로 실행한다.
- 증거: `python -m pytest src/core/web_common/test -q` 41 passed (2026-09-24 Windows); 전체 게이트는 커밋 직전 실행.
- gate 변화: SOURCE HOLD→GO(자체 `test/` 확보), LOCAL GO 유지.
- 결정: module-coupling-scorecard §6 과제 2.
- 교훈: 없음

## 2026-09-24 · uncommitted · feat(web): 브라우저 조작 부품을 web_common 한 벌로 모은다

- 변경: `components.css`·`ui.js` 추가(ui-button, ui-field, ui-tag, ui-text). 글자 계단 바닥을 0.75rem으로 올리고 `--text-display`를 둠. 콘솔·Fleet·게임 호스트·control 진단 페이지가 `/common/`으로 이 파일을 링크하고 버튼을 `ui-button`으로 쓴다. D-194.
- 증거: `python -m pytest src/core/web_common/test src/core/core_api_web/test src/site/fleet/test/test_grammar_separation.py src/site/fleet/test/test_server_app.py src/site/fleet/test/test_console_palette.py src/apps/games/test/test_preview.py src/apps/control/test/test_map_raster_color_contract.py src/apps/control/test/test_calibration_buttons.py src/core/core/test/test_dashboard.py src/core/core/test/test_console_layout.py -q` — 120 passed (2026-09-24 Windows).
- gate 변화: SOURCE GO, LOCAL GO 유지.
- 결정: D-194
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(web): 버튼 종류와 색 사본을 시험으로 잠근다

- 변경: `ui-button`은 `kind`를 표시에 적고 부모 클래스에서 짐작하지 않는다. 표면 시트가 `ui-button`·`ui-field`·`ui-tag`·`ui-text`의 면·글자·테두리를 다시 칠하면 실패한다. 얼굴 LCD 튜플은 `tokens.css` hex와 같아야 하고, 경기 피치의 원시 색은 `:root` 한 블록만 허용한다.
- 증거: `python -m pytest src/core/web_common/test src/core/core/test/test_dashboard.py src/core/core/test/test_console_layout.py src/site/fleet/test/test_server_app.py src/site/fleet/test/test_console_palette.py -q` — 101 passed (2026-09-24 Windows). 공유 관문·얼굴 팔레트·경기 프리뷰·진단 색 계약은 그 전에 32 passed.
- gate 변화: SOURCE GO, LOCAL GO 유지.
- 결정: D-194
- 교훈: 없음

## 2026-09-24 · uncommitted · feat(web): 치수 계단과 진단 팔레트를 토큰에 잠근다

- 변경: 브라우저 표면의 padding·margin·gap·border-radius는 `--space-*`·`--radius-*`만 통과한다. 진단 페이지의 바탕·잉크·상태·경로색 hex를 `tokens.css`와 같게 맞추고, `--muted`가 토큰을 다른 값으로 덮지 않게 한다. concept 16에 법이 어느 시험에 매이는지 적었다. D-195.
- 증거: `python -m pytest src/core/web_common/test/test_shared_controls.py src/core/web_common/test/test_ui_token_contracts.py src/apps/control/test/test_map_raster_color_contract.py src/core/core/test/test_console_layout.py -q` — 48 passed (2026-09-24 Windows).
- gate 변화: SOURCE GO, LOCAL GO 유지.
- 결정: D-195
- 교훈: 없음

## 2026-09-24 · uncommitted · feat(web): 어휘 표의 나머지 다섯 부품을 만든다

- 변경: `ui-head`, `ui-grid`, `ui-chip`, `ui-triage`, `ui-evidence`를 `web_common`에 두고 스타일가이드가 그 요소로 어휘를 렌더한다. 라벨·값·필드·태그 예시도 `ui-text`, `ui-field`, `ui-tag`로 바꿨다. D-92가 미룬 넷은 그대로다.
- 증거: `python -m pytest src/core/web_common/test/test_shared_controls.py src/core/core_api_web/test/test_ui_route.py -q` — 15 passed (2026-09-24 Windows).
- gate 변화: SOURCE GO, LOCAL GO 유지.
- 결정: D-194
- 교훈: 없음

## 2026-09-24 · uncommitted · feat(web): 화면 틀을 공용 UI로 둔다

- 변경: `ui-shell`, `ui-topbar`, `ui-brand`, `ui-section`, `ui-empty`와 `template.html`. 콘솔·Fleet·경기 보드·진단 페이지가 그 껍질을 쓴다. 제품 `index.html`·`dashboard.html`에 껍질이 없으면 시험이 실패한다.
- 증거: `python -m pytest src/core/web_common/test/test_shared_controls.py src/core/core_api_web/test/test_ui_route.py src/apps/games/test/test_preview.py src/site/fleet/test/test_grammar_separation.py src/core/core/test/test_dashboard.py -q` — 45 passed (2026-09-24 Windows).
- gate 변화: SOURCE GO, LOCAL GO 유지.
- 결정: D-194
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(web): 빈 목록과 증거 색을 공용 부품에 맞춘다

- 변경: 빈 목록 행은 `ui-empty`가 있는 칸을 데이터 행으로 그리지 않는다. 지연·끊김·없음은 상태색이 아니라 흐린 글자다. Fleet 연결 알약과 지도 태그는 `ui-tag`다. 증거 네 이름은 `core_ui_logic.js`와 `ui.js`가 같아야 한다.
- 증거: `python -m pytest src/core/web_common/test/test_shared_controls.py src/core/core/test/test_evidence_margin.py src/site/fleet/test/test_grammar_separation.py src/core/core/test/test_dashboard.py -q` — 39 passed (2026-09-24 Windows).
- gate 변화: SOURCE GO, LOCAL GO 유지.
- 결정: D-194
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(web_common): ui-button small 기본 척급 규칙 (D-203)

- 변경: components.css에 `ui-button small` 기본 규칙 추가 ? kind가 크기를 지정하지 않아도 `--text-micro` 계단 안에 들어온다. UA 기본값(smaller)이 16px 맥락에서 13.33px, 14px 맥락에서 11.67px를 만드는 누수의 뿌리.
- 증거: `python -m pytest src/core/web_common/test -q` → 60 passed. 계산 척급 센서스 게이트(test_dashboard_browser.py) off-scale 0.
- gate 변화: 없음.
- 결정: D-203
- 교훈: 닫힌 척급은 선언이 아니라 계산값에서 닫혀야 한다.

## 2026-09-24 · uncommitted · fix(harness): 과거 로그 항목 원문 복원(append-only)

- 변경: a93d5188 경로 재편이 D-194·D-195 증거의 `src/apps/control/test/...` 경로를 `src/core/control/test/...`로 고쳐 쓴 것을 원문으로 복원했다. 로그는 append-only고 역사 항목은 당시 경로를 말해야 한다. 현재 경로는 이 시점 기준 `src/core/control`이다.
- 증거: `python tools/harness/rosy_harness.py lint` — 3a17a0aa 기준 append-only 오류 소멸(커밋 뒤 HEAD 기준도 통과).
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 경로 재편 커밋이 로그 원문을 같이 고쳐 쓰지 않는다. 하네스 lint가 잡는다.

## 2026-09-25 · uncommitted · refactor(hmi): move web_common under src/hmi (D-231)

- 변경: src/hmi/web_common로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 hmi 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음

## 2026-09-26 · uncommitted · feat(hmi): ROSY 장미 브랜드 토큰과 동적 버튼 kind (D-277)

- 변경: `--brand-rose`와 `--brand-rose-wash`를 토큰화하고 워드마크·선택 역할 메뉴에 한정했다. 브라우저 테마색을 중립 바탕과 맞추고, JS 헬퍼가 만든 버튼도 의미에 맞는 `kind`를 명시하게 했다.
- 증거: `src/hmi/web/test src/hmi/dashboard/test` 64 passed, `src/runtime/gateway/test/test_dashboard.py` 27 passed. 실제 CORE `/console`를 visible Playwright로 1440px·390px에서 확인: ROSY 워드마크와 현재 메뉴의 장미 토큰, 누락 kind 0, 가로 넘침 0, 페이지 오류 0. `rosy_harness.py lint`: 0 error, 21 pre-existing last-verified warnings.
- gate 변화: SOURCE GO, LOCAL GO; ROS-SIM~FIELD N/A (이 변경 범위에 장치 수용은 없음).
- 결정: D-277
- 교훈: 브랜드 강조와 안전 의미색은 별도 토큰 집합이어야 한다.

## 2026-09-26 · uncommitted · feat(hmi): shared button sizes, action groups, and status UI (D-284)

- 변경: map button kinds to the 44/48/58px size tokens; add responsive `ui-actions` and accessible `ui-status`; use existing neutral palette tokens for selected segments and scrollbars.
- 증거: shared-control and palette gates plus browser component contract passed; focused dashboard/shared/API/map/host/browser suite: 241 passed, 2 skipped.
- gate 변화: unchanged. No ROS-SIM/device/field acceptance claimed.
- Decision: D-284.
- Rule: surfaces compose shared controls and do not repaint them; ROSY rose stays brand identity.

## 2026-09-26 · uncommitted · test(hmi): verify role UI after current-main rebase

- 변경: re-run shared UI, API, role browser, and device browser coverage after rebasing on current main.
- 증거: 241 passed, 3 skipped; `rosy_harness.py lint` reported 0 errors and 21 unrelated last-verified evidence warnings.
- gate 변화: unchanged. No ROS-SIM, ARM64 image, device, or field acceptance claimed.
- Decision: D-279 and D-284 remain the role recovery and shared component contracts.

## 2026-09-26 · uncommitted · feat(hmi): share role form layout and field labels (D-285)
- 변경: Added `.ui-form` and `.ui-field-label` to shared `components.css`, migrated repeated role-panel form and label classes, and kept all controls as native HTML. Added a form-layout contract and desktop/mobile browser coverage.
- 증거: `python -m pytest src/hmi/web/test src/hmi/dashboard/test -q` with `ROSY_RUN_BROWSER_TESTS=1` ? 73 passed (2026-09-26 Windows).
- gate 변화: SOURCE remains GO; no ROS-SIM, artifact, device, or field claim is added.
- 결정: D-285.

## 2026-09-26 · uncommitted · feat(hmi): share semantic role readout layout (D-286)
- 변경: Added `.ui-readout` to shared styles, migrated read-only fact lists across console/setup/host panels, and removed the dashboard-local duplicate layout.
- 증거: `python -m pytest src/hmi/web/test src/hmi/dashboard/test -q` with `ROSY_RUN_BROWSER_TESTS=1` ? 75 passed (2026-09-26 Windows).
- gate 변화: SOURCE remains GO; no ROS-SIM, artifact, device, or field claim is added.
- 결정: D-286.

## 2026-09-26 · uncommitted · feat(hmi): share role readback sections (D-287)
- 변경: Added `.ui-readback` for read-only section grouping and migrated host, setup, and system panels. Kept labels, values, headings, and actions panel-owned.
- 증거: `python -m pytest src/hmi/web/test src/hmi/dashboard/test -q` with `ROSY_RUN_BROWSER_TESTS=1` ? 77 passed (2026-09-26 Windows).
- gate 변화: SOURCE remains GO; no ROS-SIM, artifact, device, or field claim is added.
- 결정: D-287.

## 2026-09-26 · uncommitted · feat(hmi): complete shared live-status adoption

- 변경: Migrate remaining role-panel live announcements to `ui-status`; route selected action-tab paint through the shared segment palette and remove the shell override.
- 증거: `python -m pytest src/hmi/web/test src/hmi/dashboard/test -q` with `ROSY_RUN_BROWSER_TESTS=1` — 85 passed; action-group browser tests — 5 passed.
- gate 변화: SOURCE remains GO; no ROS-SIM, artifact, device, or field acceptance is claimed.
- 결정: D-284 governs the shared status contract; D-283 governs action-group tabs.

## 2026-09-26 · uncommitted · feat(hmi): name shared component spacing roles (D-292)
- 변경: 컴포넌트 의미 간격 역할을 닫힌 집합으로 추가하고 공용 컨트롤·셸에 적용했다. 새 계약 시험은 모든 역할 별칭의 기본 간격 참조, 공용 사용, 반복 원시 간격 금지를 확인한다.
- 증거: `src/hmi/web/test/test_ui_token_contracts.py`, `test_shared_controls.py`, `src/hmi/dashboard/test/test_camera_capture.py`; HMI 전체 `ROSY_RUN_BROWSER_TESTS=1` — 97 passed (2026-09-26 Windows).
- gate 변화: SOURCE/LOCAL remain GO. Visible CORE Chromium reviewed operator console/setup and administrator console/setup/device at desktop and mobile widths; zero page errors or missing button kinds. Captures are under `X:\DevTemp\rosy-design-system-review`. No robot or field acceptance is claimed.
- 결정: D-292.

## 2026-09-26 · uncommitted · feat(hmi): close typography and interaction tokens (D-294)
- 변경: 공용 글자 굵기·줄 높이·자간·포커스 링·컴포넌트 진단선·비활성 농도를 토큰화하고, 스타일가이드에 실제 공용 부품 예시를 추가했다. 렌더링 값은 이전과 같고 1px 실선 규칙은 유지한다.
- 증거: 토큰 계약 38 passed; HMI 전체 browser-enabled 100 passed; CORE route/manifest 29 passed. 실제 CORE API + visible Chromium으로 스타일가이드와 operator/admin console·setup·device를 확인했다. 화면 오류 0, 버튼 kind 누락 0, 모바일 가로 넘침 0; 포커스 링 파랑과 비활성 opacity 0.45를 확인했다. 캡처는 `X:\DevTemp\rosy-design-system-polish`.
- gate 변화: SOURCE/LOCAL remain GO. ROS-SIM·ARTIFACT·DEVICE·FIELD 증거는 이 UI 변경으로 주장하지 않는다.
- 결정: D-294.

## 2026-09-27 · 6ce05ff1 · test(hmi): verify D-294 after latest-main integration
- 변경: D-294 검증 결과를 기록했다.
- 증거: browser-enabled HMI suite 100 passed; dashboard route/manifest suite 29 passed. Visible CORE Chromium reviewed styleguide plus operator/admin pages at desktop/mobile; page errors 0, missing button kinds 0, horizontal overflow 0.
- gate 변화: SOURCE/LOCAL remain GO. Pi/image/device/field acceptance is not claimed.

## 2026-09-27 · uncommitted · shared keyboard skip style
- Change: added shared visually hidden heading and skip-link styles with a z-index token.
- Evidence: focused browser skip-link regressions passed; UI token and architecture checks passed (29 tests).
- Gate: SOURCE/LOCAL only; device display is unverified.

## 2026-09-27 · uncommitted · D-300 surface typography and focus tokens
- 변경: 정규 가중치·1.25 압축 행간·2px 외곽 포커스 간격 토큰을 추가하고 dashboard/Fleet/games 표면에서 반복되는 타이포그래피와 표준 키보드 링을 공유 토큰으로 이동했다. 고유 자간과 장문 행간은 보존했다.
- 증거: 토큰/표면 계약 40 passed; browser-enabled HMI 전체 102 passed.
- gate 변화: SOURCE/LOCAL 유지. 장치·필드 수용은 평가 범위 밖.
- 결정: D-300.

## 2026-09-27 · 9049bd37 · test(hmi): verify D-300 after latest-main integration
- 변경: 최신 main 통합 뒤 공유 타입/포커스 계약을 다시 검증했다.
- 증거: 표면 계약 40 passed, browser-enabled HMI 전체 102 passed.
- gate 변화: SOURCE/LOCAL 유지. 장치·필드 수용은 범위 밖.
- 결정: D-300.

## 2026-09-27 · f4f15776 · verify D-300 after latest main integration
- 변경: latest main에 D-300 surface typography/focus token contract를 반영했다.
- 증거: surface 40 passed, HMI web 77 passed; harness lint 0 errors and 17 existing warnings.
- Gate: SOURCE/LOCAL remain GO; no device or field acceptance claimed.
- Decision: D-300.

## 2026-09-27 · 9ca7bc26 · verify D-300 on latest main
- 변경: D-300 토큰 계약을 최신 HMI component와 dashboard CSS에 적용하고 skip-link 포커스 테두리도 공용 너비 토큰을 사용하게 했다.
- 증거: surface 계약 41 passed, HMI web 78 passed, visible Chromium에서 page error 0 및 가로 넘침 0.
- gate 변화: SOURCE/LOCAL 유지. 장치·현장 수용은 주장하지 않는다.
- 결정: D-300.

## 2026-09-29 · uncommitted · D-329 표면 레지스트리 착지 (T1–T4)

- 변경: `src/hmi/web/surfaces.yaml`를 표면 계약 적용 범위의 단일 출처로 두었다. `test/surface_registry.py`(로더 + 필드 규칙 `problems()` + `git ls-files -c -o --exclude-standard` 발견 스캔)와 `test/test_surface_registry.py`(규칙별 검사 9개)를 새로 넣고, `test_shared_controls.py`·`test_surface_typography_focus_contracts.py`, 루트 `test/test_web_dialog_contract.py`의 `SURFACES` 상수를 지워 `for_contract`로 바꿨다. 셸 점검은 파일시스템 `rglob`을 추적 파일 발견 스캔으로 바꿨다.
- 증거: 레지스트리 6항목이 기존 하드코딩 셋과 일치함을 대조(`shared_controls` 4, `typography_focus` 4, `dialog` 3, 추적 HTML 8개), `problems()` 0. `src/hmi/web/test` 87 passed — 변경 전 1 failed/77 passed(`test_a_browser_page_starts_from_the_shell`이 `.gitignore`된 Android 빌드 산출물을 훑어 로컬만 빨갰음)가 0 failed가 되었다. 변이 확인 5건 전부 원하는 이유로 빨갛고 복구 초록: M1 항목 제거 → `test_every_html_under_src_is_registered`, M2 add 안 된 `src/hmi/pilot/index.html` → 같은 이유, M3 없는 path → `path:`, M4 `dialog` 제거에 `contract_reason` 삭제 → `reason:`, M5 `git add` 후에도 항목이 없으면 여전히 빨강 (`-o` 는 M2가, `-c` 는 M5가 증명). `src/site/fleet/test`·`src/site/games/test` 647 passed, `test/architecture/test_module_structure.py` 33 passed, harness `lint` 0 errors, 계약 시험 78 passed.
- gate 변화: SOURCE/LOCAL GO 유지. 라이브러리·계약 등급이라 ROS-SIM~FIELD는 그대로 N/A이며 장치·현장 수용은 주장하지 않는다.
- 결정: D-329 Decision 1–3을 실행했다. Decision 4의 `matrix.json` 스키마와 회차 파일명 규칙, 자동 픽셀 게이트, `src/hmi/pilot` 등록은 범위 밖이다.

## 2026-09-29 · uncommitted · D-335 ui-brand 홈 링크 공용 동작

- 변경: `ui.js`의 `ui-brand`가 `href`(와 `aria-label`)를 받으면 자식을 하나의 링크로 감싸게 했다. 링크의 hover 밑줄과 포커스 링은 `components.css`가 소유하고, `template.html`에 href 선언 예시를 남겼다. 소비자는 속성 선언만 하고 앵커를 따로 적지 않는다. `test_shared_controls.py`에 동작·스타일 소유를 고정하는 계약을 더했다. 배경과 대안은 [D-335](../../../docs/adr/D-335-brand-home-link-shared-component.md).
- 증거: `python -X utf8 -m pytest src/hmi/web/test src/hmi/dashboard/test/test_surface_home_link.py src/hmi/dashboard/test/test_dashboard_package.py src/hmi/dashboard/test/test_web_budgets.py -q` 97 passed 1 skipped(브라우저 클릭 1건은 게이트 변수). 게이트 실행에서 `ROSY_RUN_BROWSER_TESTS=1` 클릭 통과를 확인한다.
- gate 변화: 없음. web_common은 라이브러리 계층이라 ROS-SIM~FIELD는 N/A 유지.

## 2026-09-29 · uncommitted · web-surface-hardening: `/common` allowlist은 `manifest.json` 하나

- 변경: `manifest.json`(공유 자산 이름 → 미디어 타입, JS는 `text/javascript` 하나)을 새로 두고 `CMakeLists.txt`가 share로 설치한다. core_api_web·fleet·games·control 진단 페이지가 각자 적던 목록 넷을 이 파일 읽기로 바꿨고, 네 서버 모두 `hold-ticker.js`를 서빙한다. `test/test_asset_manifest.py`가 목록=설치 파일(manifest 자신 제외)과 파일 존재를 고정한다. `AGENTS.md`·`progress.md`의 토큰 링크 안내를 `/common/tokens.css`로 고쳤다(D-129 정정).
- 증거: `python -m pytest src/hmi/web/test -q` 92 passed.
- gate 변화: 없음. 라이브러리 계층이라 ROS-SIM~FIELD는 N/A.
- 결정: D-157(명시 allowlist) 유지, D-129 정정 2026-09-29.

## 2026-09-30 · uncommitted · test(roles): D-358 S2 역할 경계 시험과 표면 소유 목록

- 변경: `surfaces.yaml` 모든 표면에 `role`(D-358 1항 한 줄 요약)과 `owns`(4항 소유 조작) 목록을 더했다. 레지스트리 로더가 빈 `role`, 없는 `owns`, 중복 소유, 사유 없는 표 항목을 거절한다. 대시보드 `manual-drive`는 `transitional: "D-358 4항 1"`로 표시했다. 새 `test/architecture/test_app_roles.py`가 천장 카메라 앱(`/api/v1/`·`/api/fleet/`(pairing/v1 제외)·`cmd_vel`·`estop` 없음), Vision(`/api/v1/`·`cmd_vel` 없음, Fleet에는 sightings만), Fleet vision 라우트(lease만 발급, 바이트 없음), 소유 겹침(estop·transitional만 허용)을 검사한다.
- 증거: `test_app_roles.py` 6 passed, `src/hmi/web_common/test` 98 passed. 변이 증명 네 가지(카메라 앱에 `/api/v1/estop`, Vision에 `/api/fleet/missions`, lease 응답에 `jpeg` 키, Fleet에 `robot-detail` 소유 추가) 모두 적신 → 되돌림.
- gate 변화: 없음. SOURCE/LOCAL.
- 결정: D-358 1·4항. Pilot(`src/hmi/pilot`)은 main에 없어 대상이 아니다. `test_pilot_is_not_on_main_yet`이 착지 순간 적신이 되어 Pilot 검사 추가를 강제한다(skip 아님).
- 교훈: 없음.

## 2026-09-30 · uncommitted · feat(icons): D-358 S3 이름·아이콘·파비콘

- 변경: `icons/`에 SVG 네 개(`overhead-camera-app`·`pilot`·`fleet-console`·`robot-dashboard`)를 두었다. 108 격자, `--ground` 바탕, `--brand-rose` 점 하나, 표면마다 글리프 토큰 하나(`<path>`만). `surfaces.yaml`에 `app_name`·`app_name_en`·`short_name`·`icon`을 더했다. `manifest.json`이 아이콘을 한 개씩 `image/svg+xml`로 허용하고(폴더를 열지 않음) CMake가 `share/web_common/icons`로 설치한다. `test_asset_manifest.py`는 `icons/` 한 단계와 SVG 미디어 타입을 받도록 고쳤다. `tools/icons/render_png.py`(Pillow)가 SVG를 PNG로 그린다.
- 증거: `test_surface_icons.py` 8 passed(토큰 색만, `--status-*` 없음, 안전 영역, 48 px 흑백 IoU < 0.5, 이름표·Android `app_name` 대조). G2 캡처: `private/validation/2026-09-30-d358-icons/d358-icons-side-by-side.png`(색·흑백 × 48·192 px, 원형 마스크).
- gate 변화: 없음. G2 사용자 확인 대기, DEVICE(실제 런처)는 별도 회차.
- 결정: D-358 2·3항. Pilot 이름·아이콘 PNG·버튼 문구는 Pilot이 main에 없어 착지 회차로 미룬다(`pilot.svg`만 먼저 둠).
- 교훈: SVG·Android XML 주석에 `--`를 쓰면 파서가 거절한다(토큰 이름을 주석에 적지 말 것).


## 2026-09-30 · uncommitted · docs(adr): D-358 앱 역할 ADR을 D-370으로 재번호

- 변경: 이 모듈의 D-358 앱 역할·이름·아이콘 주석과 시험 문서 문자열을 D-370으로 바꿨다. 동작 변경 없음.
- 증거: 번호만 바꾼 diff. 시험은 병합 뒤 회차에서 다시 돌린다.
- gate 변화: 없음.
- 결정: 이 항목 앞의 "D-358 S1/S2/S3"·"D-358 N항"은 D-370을 가리킨다(main의 D-358 ER2 피드백 outbox와 다름). 옛 항목은 고치지 않는다.
- 교훈: 없음.
