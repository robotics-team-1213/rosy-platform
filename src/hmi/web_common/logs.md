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

## 2026-09-30 · 960a76f2 · D-359 US-001 토큰 세 층과 이름 정리

- 변경: `tokens.css`를 팔레트(원시 색은 여기에만, 닫힌 키 목록) → 파생(`color-mix(in oklab, …)`로 팔레트만 참조) → 역할 층으로 나눴다. 이름 paper→`--ink`, muted→`--ink-quiet`, muted-line→`--line-quiet`을 src 전체(CSS·JS·HTML·LCD/Kotlin 사본 주석·시험)에서 기계적으로 바꿨다. `--ink-on-crit`·`--shadow-base`를 팔레트에 두고, 쓰이지 않는 토큰(sheen 셋, status-good 알파 여섯, crit-a12, warn-a40, series-primary-a08, line-08, status-crit-ground, muted-cool)과 같은 값 별칭(`-2`, status-ok, route-dim → `--series-secondary`)을 지웠다. games의 경기장 잉크는 `--pitch-ink`로 이름을 옮겨 공용 `--ink`와 겹치지 않게 했다. oklch가 아니라 oklab으로 섞는 이유: Chromium이 채도 ~0 색의 oklch 색상각을 none으로 풀어 0°로 그린다(실측 ΔE_OK 최대 0.019).
- 증거: Chromium 계산 색 비교(옛 main 대 새 파일, 이름 변경 반영) 68개 전부 허용 범위, 최대 ΔE_OK×100 = 0.77(`--brand-rose-wash`, RGB 2.14/255), 나머지 ≤ 0.2. `python -m pytest src/hmi/web_common/test -q` 97 passed.
- gate 변화: 없음. 라이브러리 계층이라 ROS-SIM~FIELD는 N/A.
- 결정: D-359 §1.

## 2026-09-30 · faa60733 · D-359 US-002 밝은 팔레트·테마 선택 경로·테마별 게이트

- 변경: `tokens.css` 팔레트 선택자를 `:root, [data-theme="dark"]`로 바꾸고 같은 키 집합의 `[data-theme="light"]` 블록을 더했다(OKLCH 생성, 각 블록이 자기 `color-scheme`). 파생 공식은 두 테마에서 그대로 뜻이 맞아 고치지 않았다(선·장막은 잉크·바탕 알파, 그림자는 `--shadow-base` 알파). `theme.js`(외부 스크립트, tokens.css 바로 뒤 동기 로드)가 `rosy.theme` dark|light|system(기본·무효·저장소 실패 → dark)을 풀어 `html[data-theme]`과 `meta[name=theme-color]`(계산된 `--ground`)를 첫 그림 전에 정하고, `data-theme-pin`을 따르며, `window.RosyTheme {get,set,resolved}`와 `rosy:theme` 이벤트, `[data-theme-choice]` 버튼 배선을 준다. `manifest.json`·설치 목록에 등록. `surfaces.yaml`에 `themes`를 두고 레지스트리가 테마 표면의 theme.js, 고정 표면의 pin, 정적 theme-color = dark `--ground`, 표면 CSS의 `color-scheme` 부재를 본다. `test_palette_gates.py`는 `token_themes.py`로 테마별 팔레트를 읽어 모든 게이트를 테마마다 돌리고(브랜드 밝기 대역·래스터 단조는 바탕 극성 기준으로 일반화), 키 집합 동일·파생 블록 원시 색 없음·로봇 사다리·주 명령 ink 채움·위험 채움 위 글자 = on-crit 잉크를 더했다. LCD·진단·네이티브 사본 비교는 dark 블록으로 고정했다. 위험 채움 위 `--ink` 참조 10곳을 `--ink-on-crit`로 바꿨다(2297d11d).
- 증거: `python -m pytest src/hmi/web_common/test -q` 121 passed 9 skipped(브라우저 게이트 제외). 변이 6건 전부 빨강 후 복구: light 키 삭제 → `test_every_theme_defines_the_same_palette_keys` 외 3, 파생 블록 `#123456` → `test_the_derived_block_has_no_raw_colour`, light `--ink` 저대비 회색 → `test_text_tokens_meet_wcag_on_the_ground[light]` 외 2, 공용 위험 태그 `--ink` → `test_text_on_a_danger_fill_uses_the_on_crit_ink`, Fleet theme.js 제거·games pin 제거 → `test_every_surface_declares_its_themes_and_its_pages_follow_them`.
- 브라우저(`ROSY_RUN_BROWSER_TESTS=1`): `src/hmi/dashboard/test src/hmi/web_common/test` 181 passed 1 failed → 실패는 새 패널 순서(order 10)가 390×844 /device에서 운영 상태를 밀어낸 것이라 order 110으로 옮긴 뒤 해당 시험·`test_theme_browser.py` 10 passed. `test/test_role_surface_states_browser.py test/test_fleet_console_browser.py test/test_rosy_games_surface.py` 42 passed 3 failed: swarm_control(기존 알려진 실패), semantic_subheadings(기준 커밋 fdb428de에서도 실패), slow_initial_gather(부하 플레이크 — 단독 재실행 통과).
- gate 변화: 없음. 라이브러리 계층이라 ROS-SIM~FIELD는 N/A. 밝게는 제품 기본값이 아니고 사람 G3·현장 조명 관측 전이다.
- 결정: D-359 §2·§3·§7.1·§7.3.

## 2026-09-30 · 4d513a41 · D-359 US-003 캔버스 색·글꼴 해석기 RosyPalette

- 변경: `ui.js`에 `readColour`·`readPalette`·`cssColor`·`canvasFont`·`clearPalette`를 더해 export하고 `window.RosyPalette`로도 건다(D-75 번들러 없음; camera-capture.js는 Node에서도 import되므로 캔버스 파일은 전역으로 부른다). 색은 글자로 파싱하지 않는다 — 숨은 탐침 `<span>`에 `color: var(--x)`를 걸어 계산된 색(Chromium은 color-mix를 `color(srgb …)`/`oklab(…)`로 준다)을 1×1 캔버스에 칠해 sRGB 바이트 `[r,g,b,a]`(a 0–1)로 되읽고 캐시한다. `canvasFont(size, "body"|"mono")`는 `--body`/`--mono` 계산값과 12px 하한. `rosy:theme`에서 캐시를 비운다(ui.js가 캔버스 모듈보다 먼저 실행되므로 다시 그리기 전에 비워진다). 새 시험: `test_canvas_palette_contract.py`(캔버스 5파일에 hex 리터럴·hexToRgb·getPropertyValue·px 리터럴·sans-serif 없음, `ctx.font`는 canvasFont 경유, games 피치 색은 styles.css, Fleet 지형·범례는 raster 토큰), `test_canvas_palette_browser.py`(로봇 지도·Fleet 지도 빈 칸 픽셀 dark → `RosyTheme.set('light')` → light `--raster-free` ±3, color-mix 토큰 `--line-quiet`·`--ground-grad-1`이 검정이 아님, canvasFont(10) → 12px).
- 증거: 아래 US-003 묶음. `ROSY_RUN_BROWSER_TESTS=1 python -m pytest src/hmi/web_common/test -q` 146 passed. 1366×768 캡처 `X:/DevTemp/rosy-d359/shots/us003-{robot,fleet}-{dark,light}.png`(ROSY_D359_SHOTS로 켬).
- gate 변화: 없음. 라이브러리 계층이라 ROS-SIM~FIELD는 N/A.
- 결정: D-359 §4.

## 2026-09-30 · cda6c382 · D-359 US-004 공용 필드 클래스·버튼 상태·비활성 사유·active 태그

- 변경: 필드 API는 네이티브 `input/select/textarea`에 `class="ui-field"`(components.css가 이미 가진 `input.ui-field` 규칙을 확장) — `<ui-field>` 감싸개는 폼 제출·label 연결·기존 핸들러를 흔들어 제품 화면에는 쓰지 않는다(components.css 머리 주석·styleguide 기록). 필드는 body 글꼴·44px 바닥·공용 선/바탕/포커스/placeholder/readonly/`:user-invalid`·`aria-invalid`/비활성 흐림, 체크·라디오는 상자 없이 `label.ui-check`(44px)가 누름 면. 모든 `ui-button` 종류에 `:hover`·`:active`(비활성 제외, 채움 종류는 바탕색 안쪽 테), 토글 눌림은 `aria-pressed="true"`. `ui-button reason` 속성: ui.js가 버튼 안 `<small data-reason aria-hidden>`로 그리고 `aria-describedby`로 잇고, 갱신·삭제·`textContent` 교체(MutationObserver)를 따라간다. 사유가 있는 비활성은 흐리지 않고 점선·`--ink-quiet`. `ui-tag status="active"`(ink, 무색)와 `ui-tag[hidden]`. 공용 기본: `:where(a,button,input,select,textarea,summary,[tabindex]):focus-visible` 링, body `word-break: keep-all; overflow-wrap: break-word`(f2a836a7 — ADR 문구의 `anywhere`는 최소 내용 폭을 한 글자로 줄여 1366px Fleet 상단바의 짧은 라벨을 음절 사이에서 꺾어 break-word로 바꿨다).
- 시험(2824d8c6): `test_product_fields_carry_the_shared_field_class`(HTML 태그 + JS createElement/el/node 생성처, 체크는 `label.ui-check`), `test_fields_clear_the_secondary_target_on_every_surface`, `test_every_button_kind_has_shared_interaction_states`, `test_disabled_reason_is_a_shared_button_attribute`(title만의 사유 금지), 재도색 검사에 `outline` 추가, `test_letter_spacing_is_a_token_or_zero`, `test_dimming_uses_the_disabled_token_not_an_opacity_literal`, 브라우저 `test_shared_controls_browser.py`(사유 글자·describedby·이름 제외·색·갱신/삭제, Fleet·/dashboard DOM의 모든 필드 min-height ≥ 44).
- 증거: 변이 14건 전부 빨강 후 복구 초록(X:/DevTemp/rosy-d359/us004-mutations.log). `python -m pytest src/hmi/web_common/test src/hmi/dashboard/test src/site/fleet/test src/site/games/test src/runtime/sensing/test src/runtime/gateway/test/test_dashboard.py -q` 2708 passed 132 skipped. 브라우저 web_common 155 passed.
- gate 변화: 없음. 라이브러리 계층이라 ROS-SIM~FIELD는 N/A.
- 결정: D-359 §5·§7.4–7.6.
