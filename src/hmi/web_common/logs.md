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

## 2026-09-30 · fd2249cd · D-359 US-004 비활성 사유 구조 검사

- 변경: `test_every_disabled_control_states_its_reason_or_is_listed` — dashboard·Fleet JS의 `.disabled =`/`setAttribute('disabled')` 자리와 `setOff`/`setEnabled` 호출은 reason을 쓰거나, (파일, 줄 조각) → 이유의 닫힌 목록에 있어야 한다(요청 중 잠금·초기값·네이티브·공용 안내·'할 일 0'). 목록의 옛 항목도 실패. Fleet 역할 잠금 안내 쌍도 확인.
- 증거: 변이 5건(setOff 사유 삭제, 직접 비활성의 사유 삭제, setEnabled 사유 삭제, 목록 옛 항목, Fleet 안내 삭제) 전부 빨강 후 복구. 브라우저 web_common 156 passed.
- gate 변화: 없음.

## 2026-09-30 · aeb31356 · D-359 US-005 세 단 반응형과 칸 반응 공용 부품

- 변경: `components.css`의 뷰포트 질의(30rem)를 `@container (width < 22rem)`로 바꿨다 — ui-form·ui-readout·ui-actions가 자기 칸에 반응한다(칸은 표면이 `container-type: inline-size`로 정한다). 22rem은 320px 폰 칸(18.5rem)과 1366px 콘솔 감지·조작 열(약 23–25rem)을 가른다. `.ui-readout dd`는 늘 `overflow-wrap: anywhere`. `surfaces.yaml`에 `breakpoints` 필드(값 정수 px/rem + reason; 세 단 값·쓰이지 않는 값 금지, 웹만) — Fleet 90rem, 진단 1279/900px(PARKED), lane_live_view 1000/640px. `surface_registry.py`에 `media_conditions`·`breakpoint_problems`와 `breakpoint:` 규칙. 새 `test_responsive_tiers.py`: 모든 웹 표면 CSS·`<style>`의 @media 크기 조건이 범위 문법 세 단(이웃 두 단의 합 포함)·§6.5 높이(40rem)·허용 목록 값인지, 필드 모양, drift(tmp), 공용 부품 @container·surface-panels ui-actions 재정의 없음, 괄호 짝. Fleet 테마 시험은 90rem 미만에서 접힌 '설정'을 연다.
- 증거: 단위 `python -m pytest src/hmi/web_common/test src/hmi/dashboard/test src/site/fleet/test src/site/games/test src/runtime/sensing/test src/runtime/gateway/test/test_dashboard.py -q` 2714 passed 132 skipped(tiers 시험 추가 전), tiers 6 passed. 브라우저 web_common 161 passed. 변이: Fleet CSS에 `@media (max-width: 41rem)` → 빨강, `}` 하나 추가 → 빨강, 복구 초록.
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 §6·§7.7.
- 교훈: CSS 블록을 문자열 치환으로 옮기면 닫는 괄호를 잃거나 남기기 쉽다 — 남은 `}` 하나가 다음 규칙을 조용히 지웠고 시험은 못 봤다. 괄호 짝 검사를 붙였다.

## 2026-09-30 · a1568095 · D-359 US-006 §7 구조 계약 시험의 빈칸을 닫았다

- 변경: §7.2 원시 색 스캔(`test_no_raw_colour_outside_the_token_file`)을 레지스트리의 모든 웹 표면(dashboard 최상위·shell/·panels/, web_common, Fleet, games, 진단, lane 뷰어)의 CSS·JS·HTML로 넓혔다. hex·`rgb(`·`hsl(`·`hwb(`·`oklch(`·`oklab(`·`lab(`·`lch(`·`color(`를 원시 색으로 본다(예전 판정은 dashboard 최상위 `*.css|*.js`만 보고 oklch·color(를 놓쳤다). 예외는 tokens.css 테마 팔레트 블록, ui.js RosyPalette rgba 형식기, 정적 theme-color(§7.3 판정이 따로 본다), `surfaces.yaml` `raw_colours`(`[dark]` 고정 웹 표면만, 이유 필수, 쓰이지 않는 항목 금지) — games `:root` 경기장 블록, PARKED `diagnostic.html`, 개발 도구 `lane_live_view.html`. `@container` 값도 `@media`처럼 세 단 경계 또는 표면 `container_breakpoints`(web-common 22rem)로 대조한다. 캔버스를 그리는 모든 웹 표면 스크립트는 캔버스 계약 목록이나 이유 있는 예외에 있어야 한다. 자간 규칙이 HTML·JS(`style.letterSpacing`·`setProperty`)도 본다.
- 증거: 변이 19건 전부 빨강 후 `git checkout --`로 복구 초록, 트리 깨끗(`X:/DevTemp/rosy-d359/us006_mutations.py`, `us006-mutations.log`) — PRD 여섯(파생 hex, light 키 삭제, Fleet 입력 공용 필드·min-height, `@media (max-width: 41rem)`, 자간 0.1em, outline 덧칠)과 새 검사 13. 단위 묶음(+ 뿌리 `test`) 5490 passed 321 skipped 10 failed — 9건은 base 1eba8cbb에서도 같은 실패(ADR 로그·harness·보안 스캔 등), `test_sd_writer_contract` 1건은 33분 부하 실행의 시간 의존 실패. 브라우저 web_common 162 passed.
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 §6.3·§7.

## 2026-09-30 · 04a9b587 · D-359 US-007 비활성 사유 글자가 불가역 버튼에서도 조용한 잉크다

- 변경: `components.css` 사유 선택자를 `ui-button[kind] > small[data-reason]`까지 적어 `ui-button[kind="irreversible"] small`(ink-on-crit, 위험 채움용)보다 앞서게 했다. 밝게 `/device`에서 "삭제 / 지금 쓰는 토큰" 사유가 채움 없는 밝은 바탕 위 밝은 글자로 사라졌다(어둡게는 두 값이 같아 숨었다). 시험: `test_shared_controls_browser.py::test_a_reason_reads_quiet_on_every_kind_and_theme[dark|light]` — 다섯 종류 모두 사유 색이 `--ink-quiet`.
- 함께: 뿌리 `DESIGN.md`(7b1c8e70, D-359 §8)와 `.impeccable/design.json`(무시되는 로컬 사이드카). ADR §2.5·§5.1·§5.5·§6.3·§6.4 실측 다듬음(1b2eb48a). 해법 노트 두 건(20147779).
- 증거: 수정 전 시험 빨강 2건, 수정 후 초록. 최종 캡처 `X:/DevTemp/rosy-d359-captures/`(README에 목록·소견).
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 §5.3·§8.

## 2026-09-30 · ea5a36bd · D-359 US-008 한글에는 라틴 자간을 주지 않는다

- 변경: `ui.js`가 자기 글자(직계 텍스트 노드)에 한글이 있는 요소에 `data-hangul`을 달고 MutationObserver로 글자 변화를 따라간다. `components.css`가 그 요소의 `--track-label/-wide/-state`를 0으로 다시 정의한다(더 구체적인 선택자의 `var(--track-*)`도 0으로 풀린다). 모든 페이지가 `lang="ko"`라 `:lang()`으로는 가를 수 없고, 섞인 글은 0을 따른다. `DESIGN.md` The Latin Tracking Rule. 시험: `test_shared_controls_browser.py::test_hangul_labels_drop_the_latin_tracking`, `test_no_hangul_text_on_a_surface_is_tracked[/console|/dashboard]`.
- 증거: 수정 전 3 빨강, 수정 후 초록.
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 §5·§6 (US-008).

## 2026-09-30 · 999c2642 · D-359 US-008 한글 요소는 등폭 대신 본문 가족

- 변경: 자간 0 뒤에도 로봇 캡처가 "점유  지도"로 떠 보였다. 등폭 글꼴에 한글이 없어 대체 글꼴로 그려지고 띄어쓰기만 등폭 칸 폭(14px에서 8.2px, 본문 3.9px)이 남았다. `[data-hangul]`이 `--mono`를 `--body`로 둔다. 시험: 같은 시험에 글꼴 가족 단언.
- 증거: `--mono` 재정의를 지우는 변이에서 빨강.
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 §5·§6 (US-008).

## 2026-09-30 · ee98ad09 · D-359 US-008 체크 상자는 비활성에서도 3:1

- 변경: `input.ui-field[type=checkbox]`를 토큰으로 그린다(`appearance: none`, 테 `--ink-quiet`, 켜짐 `--focus-ring`, 체크는 `clip-path`). 비활성은 `--disabled-opacity`로 흐리지 않고 잉크만 `--ink-quiet`로 바꾼다. Chromium 네이티브 비활성 체크는 accent를 버려 light 1.19:1, dark 1.75:1이었다. 시험: `test_checked_checkboxes_hold_three_to_one_even_when_disabled[dark|light]` 픽셀 표본.
- 증거: 수정 전 held/off 1.19–1.75:1 빨강, 수정 후 6.5:1 이상.
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 §5·§6 (US-008).

## 2026-09-30 · 998a9197 · D-359 US-008 빈 상태 줄은 ui-section에서 칸을 차지하지 않는다

- 변경: `ui-section > [role=status]:empty { display: contents }`. /setup 웨이포인트의 빈 저장·목록 상태 줄 둘이 각각 gap+여백(44px)을 먹어 짧은 목록 위에 88px 빈 칸이 생겼다. 상자만 없어지고 live region은 접근성 트리에 남는다. 시험: dashboard `test_waypoint_readiness_browser.py::test_short_waypoint_list_sits_under_the_status_line`.
- 증거: 수정 전 빨강(빈 줄이 목록 바로 위), 수정 후 초록.
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 §5·§6 (US-008).

## 2026-09-30 · 0f10bb91 · D-359 US-009 공용 한국어 열거 표(MODE_LABEL)

- 변경: `core_ui_logic.js`에 `MODE_LABEL`·`NAVIGATION_LABEL`·`DOCK_STATE_LABEL`·`enumLabel()`. 두 서버가 이미 `/common/`으로 서빙하는 파일이라 번들러 없이 로봇 대시보드와 Fleet이 같은 표를 읽는다. 모르는 값은 받은 그대로. 시험 `test_enum_labels.py`(schemas.py의 RobotMode·NavigationState·DockState 전 값 대조).
- 증거: 수정 전 export 없음(빨강), 수정 후 5 passed.
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 (US-009).

## 2026-09-30 · 5518f9bc · D-359 US-009 운용자 말 린트

- 변경: `test/test_operator_copy.py` — 대시보드(패널·최상위 js·index/surface html)·Fleet web·games web의 한글 문자열 리터럴(템플릿 구멍은 따로 판정, 주석·정규식 제외)과 HTML 글·aria-label/placeholder/reason/alt에서 `profile|capability|hardware 모드|Navigation|프로필`과 맨 열거값을 막는다. 허용 목록은 이유 필수·죽은 항목 금지(지금 비어 있음).
- 증거: 처음 46건 → 0건. 변이 증명: 실제 파일에서 고친 문자열 다섯 개를 되돌리면 각각 빨강.
- 미증명: 한글 없는 순수 열거값 표시(`OFFLINE` 등)는 린트가 보지 않는다.
- gate 변화: 없음.
- 결정: D-359 (US-009), CONCEPTS.md.

## 2026-09-30 · c1ecd8e0 · D-359 US-009 꺼진 체크 상자는 점선 테

- 변경: `input.ui-field[type=checkbox]:disabled { border-style: dashed }`. 색은 `--ink-quiet` 그대로(3:1), 흐리지 않는다. 시험 `test_a_disabled_unchecked_box_does_not_look_like_an_enabled_one[dark|light]`, 대비 시험에 켜진 빈 상자 추가.
- 증거: 수정 전 빨강(둘 다 solid).
- gate 변화: 없음.
- 결정: D-359 §5 (US-008 잔여).

## 2026-09-30 · 5bcd9617 · D-371 US-010 공용 확인 대화상자 confirmIrreversible

- 변경: `ui.js` `confirmIrreversible({message, action, opener})` — 네이티브 `<dialog class="ui-confirm">`(showModal), 대상 문장 + quiet `취소` + irreversible 실행 버튼 하나. Esc·취소는 false, 닫히면 포커스를 행 버튼으로(목록이 다시 그려졌으면 opener 함수로 다시 찾는다). `components.css` `dialog.ui-confirm`, `tokens.css` `--inset-dialog`·`--gap-dialog`. 계약 시험 `test_list_row_irreversible.py`(HTML li/tr/ul/ol/table/role=row 안 irreversible 금지, 스크립트는 ui.js 대화상자만 irreversible을 만든다, 행 삭제는 `삭제…`, 메시지는 대상을 따옴표로 부르고 묻는다).
- 증거: 변이 5/5 빨강(`X:\DevTemp\rosy-d359\us010\mutations.log`); `python -m pytest src/hmi/web_common/test -q` 167 passed, 24 skipped.
- gate 변화: 없음.
- 결정: D-371 (D-218 §1 "커스텀 확인 다이얼로그를 만들지 않는다"를 목록 행에 한해 좁힘 — 실행 버튼의 위험 채움은 window.confirm으로 그릴 수 없다).
- 교훈: 모달 `<dialog>`는 window.confirm처럼 뒤 화면(비상 정지 포함)을 막는다. 퇴행은 아니지만 열린 동안 비상 정지를 누를 수 없다.

## 2026-09-30 · 79787e7a · D-371 US-010 확인 대화상자는 비모달, 정지는 살아 있다

- 변경: `ui.js` `confirmIrreversible`이 `showModal()` 대신 `dialog.show()`로 연다. 대화상자와 `[data-always-live]` 밖의 곁가지에 `inert`를 걸고(조상 사슬만 타고 내려간다), MutationObserver가 폴링이 새로 붙인 노드도 다시 막는다. 스크림은 형제 `div.ui-confirm-scrim`(`--scrim`)이고 보이는 정지 상자마다 `clip-path: polygon(evenodd …)` 구멍을 낸다. Esc는 취소, Tab은 취소 → 실행 → 보이는 정지를 돈다(정지 단축키가 없어 새로 만들지 않았다). 정지 클릭은 캡처 단계에서 표시만 하고 대화상자를 취소로 닫는다 — 정지 처리기는 그대로 돈다. `aria-modal`은 달지 않았다(보조기기가 정지를 못 찾는다). `components.css` `::backdrop` 삭제, 고정 가운데 배치·z-index. `template.html` 정지에 `data-always-live`. 호스트 계약 `test_stop_always_live.py`(ui.js를 싣는 모든 페이지의 `…정지…` irreversible 버튼, 변이 증명 포함), `test_list_row_irreversible.py`는 이제 `showModal()` 부재를 요구한다.
- 증거: `python -m pytest src/hmi/web_common/test src/hmi/dashboard/test src/site/fleet/test src/site/games/test -q` 1089 passed, 84 skipped; `test/test_web_dialog_contract.py` 3 passed; ROSY_RUN_BROWSER_TESTS=1: `test_list_row_confirm_browser.py` 6 passed, `test_role_menu_panels_browser.py`+`test_web_dialog_contract.py` 27 passed, `test_dashboard_browser.py -k "setting or token or dock or waypoint"` 7 passed, 2 skipped (`X:\DevTemp\rosy-d359\us010b\browser.txt`)
- gate 변화: 없음.
- 결정: D-371 Refinement(2026-09-30), D-280 원칙 2.
- 교훈: 네이티브 모달은 "E-stop 항상 도달" 계약과 충돌한다 — 모달 흉내는 살릴 요소를 명시한 inert + 구멍 난 막으로 한다. z-index로 정지를 막 위로 올리는 방법은 붙박이 상단바의 쌓임 맥락(z-index 10) 안에 갇혀 통하지 않는다.
## 2026-09-30 · uncommitted · fix(harness): 역할 표면 검증을 저장소 안 도구로 — LOCAL cmd 재현 가능화

- 변경: design-system-polish worktree의 평가 스크립트(visible_roles.py)가 X:\DevTemp 임시 경로에만 있어 LOCAL gate cmd가 다른 호스트에서 재현 불가능했다. 같은 측정(실 CORE TestClient + Chromium, 역할×표면×뷰포트, kind 누락·페이지 오류·수평 오버플로·첫 응답 실패 검사)을 `tools/web_visible_roles.py`로 저장소 안에 들였다 — headless, 루트 자체 위치 계산, 위반 시 exit 1. LOCAL cmd를 이 도구로 교체했다.
- 증거: 도구 실행 10 표면 방문 exit 0 (2026-09-30 Windows, 리포트: 0 missing kinds·0 page errors·오버플로 없음·첫 응답 전부 200). 계약 시험 test_web_visible_roles 9 passed(판정 함수 변이 3종·실 CORE /console·/setup·/device 200 포함).
- gate 변화: 없음 (LOCAL GO 유지, cmd만 재현 가능해짐).
- 결정: 스크린샷·리포트는 기본 임시 디렉터리, --out-dir로 증거 디렉터리 지정 — 검증 게이트와 증거 보관을 분리한다.
- 교훈: 검증 cmd가 임시 디렉터리를 가리키는 순간 그 gate 기록은 그 호스트에서만 유효하다 — 도구가 저장소에 없으면 gate가 아니다.

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

## 2026-09-30 · uncommitted · fix(ci): D-370 리뷰 — 아이콘 시험이 Pillow 없이도 수집되고, 토큰 이름 중복을 막음

- 변경: `tools/icons/render_png.py`는 `render()` 안에서만 PIL을 import한다. `test_surface_icons.py`의 실루엣 시험은 `pytest.importorskip("PIL")`, CI는 `python3-pil`을 깐다. 새 시험 `test_token_names_are_defined_once`.
- 증거: `test_surface_icons.py` 9 passed; PIL을 막으면 8 passed, 1 skipped(토큰 시험 추가 전 기준 7/1).
- gate 변화: 없음.
- 결정: D-370 3항, D-359(테마 블록이 생기면 정규식 사전이 뒤 값을 고르는 위험).
- 교훈: 없음.

## 2026-09-30 · uncommitted · refactor(web_common): D-377 icon files and registry ids follow one word
- 변경: 아이콘 `ceiling-camera.svg` → `cam.svg`, `fleet-console.svg` → `console.svg`, `robot-dashboard.svg` → `robot.svg`(`git mv`), SVG `<title>`을 `Rosy <Word>`로. `surfaces.yaml` id `cam`·`console`·`robot`과 표시 이름 `Rosy Cam`·`Rosy Console`·`Rosy Robot`, 경로 `src/site/cam`. `manifest.json` 허용 목록·`CMakeLists.txt`. `test_surface_icons.py` 표를 D-377로, `test_surface_titles.py`는 앱 행이면 제목이 표시 이름(`Rosy <Word>` 또는 `Rosy <Word> — <화면>`)인지 본다.
- 증거: `python -m pytest src/hmi/web_common/test -q` 111 passed (2026-09-30 Windows).
- gate 변화: 없음.
- 결정: D-377. 경로 `/common/icons/<id>.svg`는 D-374 3항 예외대로 링크하는 HTML과 같은 커밋에서 바뀐다.

## 2026-09-30 · 12f322f9 · feat(web_common): toggle 의 good 톤 변형
- 변경: `components.css` 에 `ui-button[kind="toggle"][tone="good"]` — 대기는 `--status-good` 테두리·글자, `.active` 는 `--status-good` 채움과 `--button-primary-ink` 글자. Pilot 의 "진행"(누르는 동안만 도는 차선 추종, D-344)이 쓴다. 표면 재도색 대신 공용 변형으로 둔다.
- 증거: `src/hmi/web_common/test` 통과(원시 색 없음), Pilot 스크린샷 `X:\DevTemp\pilot-polish\after4-drive-auto-*.png`.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(web): D-359 리뷰 P1-1/P2-2 — 한글 없는 열거값 표시도 린트가 본다

- 변경: `test_operator_copy.py`에 `enum_text_problems()` — 텍스트 싱크(`.textContent =`, `tag(`, `setText(`, `setStatus(`, `el(`, `setChip(`, `pill(`, `setAttribute("reason"|…)`)로 가는 순수 열거값 리터럴(`"OFFLINE"`)과, 한국어 템플릿에 날것으로 들어간 mode/state 구멍(`${requestedMode}`)을 잡는다. 비교·인덱스·메서드 인자 위치는 프로토콜 키로 본다. 예외 표 `ENUM_TEXT_ALLOWLIST`(사유 필수, 낡은 항목 실패). `core_ui_logic.js`에 `NETWORK_MODE_LABEL`.
- 증거: `test_operator_copy.py` 22 passed(열거 라벨 시험 포함). 변이: 합성 10형과 실제 파일 4곳(roster·app·settings·line-follow)을 되돌리면 실패.
- gate 변화: 새 시험 `test_no_bare_enum_reaches_operator_text`·`test_the_lint_catches_bare_enums_flowing_to_text`·`test_reverting_an_enum_text_fix_fails_the_lint`·`test_every_enum_text_allowlist_entry_still_matches`.
- 결정: D-359 US-009. 실행 모드 이름(core/motor/hardware)·릴리스 상태·차선 추종 결과 상태는 한국어 지도가 아직 없어 예외 표에 사유와 함께 둔다.
- 교훈: 2026-09-30 항목의 "미증명: 한글 없는 순수 열거값"이 이 회차에서 닫혔다.

## 2026-10-01 · uncommitted · fix(web): D-359 리뷰 P1-2/P2-3 — 비모달 열기를 openLiveDialog로 공유

- 변경: `ui.js` `confirmIrreversible`의 봉인·스크림 구멍·Tab 고리·정지 클릭·Esc·포커스 복원을 `export openLiveDialog(dialog, {initialFocus, opener, onClose})`로 뽑았다. 마크업에 있던 대화상자는 열린 동안 body 끝으로 옮겼다가 닫히면 제자리로 돌린다. Tab 고리는 대화상자 안 포커스 가능 요소 → 보이는 정지. `components.css` 위치 규칙은 `dialog.ui-live-dialog`(+`.ui-confirm`). `test_stop_always_live.py`에 `showModal(` 금지 스캔(dashboard·web_common·pilot·fleet·games JS)과 변이 증명. `test_list_row_irreversible.py`는 `IRREVERSIBLE_VERBS`(삭제·등록 해제·폐기·초기화) 표로 말줄임을 보고, `action:` 값만 면제한다.
- 증거: `test_stop_always_live.py`·`test_list_row_irreversible.py` 통과. `src/hmi/dashboard/test/test_list_row_confirm_browser.py` 6 passed(2026-10-01, 7분 — 부하).
- gate 변화: 새 시험 `test_no_surface_script_opens_a_modal_dialog`·`test_the_modal_scan_fires_on_the_old_enrollment_call`. 행 말줄임 검사가 동사 표로 넓어짐.
- 결정: D-280 원칙 2, D-371.
- 교훈: showModal 금지를 한 함수 본문에만 걸면 다른 파일의 새 대화상자가 빠져나간다 — 스캔은 표면 전체에 건다.

## 2026-10-01 · uncommitted · test(web_common): D-359 리뷰 P2-4 — 사유 없는 비활성 목록은 경로와 자리 수로 묶는다

- 변경: `test_shared_controls.py` `DISABLED_WITHOUT_REASON` 키를 파일 이름에서 `src/` 기준 경로로 바꿨다(map.js·teleop.js·docking.js가 여러 폴더에 있다). 조각 하나는 한 자리만 덮고, 일부러 두 자리를 덮는 키는 `DISABLED_SITE_COUNT`에 적는다. 검사는 `scan_disabled()`로 뽑았다. 낡은 항목 검사는 그대로.
- 증거: `test_shared_controls.py` 26 passed. 변이: hardware.js에 같은 `refresh.disabled = true;` 줄을 붙이면 `widened`로 실패, 다른 폴더의 같은 이름 파일은 키를 빌리지 못함(`test_a_copied_disabled_line_needs_its_own_entry`).
- gate 변화: 새 시험 `test_a_copied_disabled_line_needs_its_own_entry`, 기존 시험에 자리 수 검사.
- 결정: D-359 §5.3.
- 교훈: 없음.

## 2026-10-01 · uncommitted · fix(web_common): D-359 리뷰 P2-5 — 테마 선택지 단일 출처, 고정 표면은 사유를 적는다

- 변경: `theme.js` `CHOICES`([{value, label}])가 선호 검증과 `RosyTheme.choices`(얼린 배열)의 단일 출처다. `surfaces.yaml`의 [dark] 웹 표면 넷(games·diagnostic·pilot·lane_live_view)에 `theme_reason`, `surface_registry.py`가 고정 웹 표면의 사유 누락과 테마 표면의 남은 사유를 막는다. 새 `test_theme_choices.py`: Fleet 정적 버튼 = `CHOICES`(순서·값·이름), `/device` display.js는 `RosyTheme.choices`로만 그린다. `DESIGN.md` 새 테마 절차(팔레트 블록 + `CHOICES` 한 줄, Fleet 마크업은 시험이 알려 줌)와 고정 표면 목록에 Pilot.
- 증거: `test_surface_registry.py` 14 passed, `test_theme_choices.py` 4 passed, `test_theme_browser.py -k "device_display or fleet_topbar"` 2 passed (2026-10-01 Windows).
- gate 변화: 새 시험 파일 `test_theme_choices.py`(변이: Fleet 이름 바꿈·theme.js에 테마 추가가 실패), 레지스트리 `theme_reason` 검사(변이: `test_a_theme_drift_is_caught`).
- 결정: D-359 §2.5·§3.3.
- 교훈: 없음.

## 2026-10-01 · uncommitted · D-390 Pilot simulation surface registry
- Change: Register the existing Pilot surface on the isolated OMX simulation port 8088 and its sim-arm-practice role. The sim server reads the common asset manifest.
- Evidence: surface registry and Pilot API tests 15 passed.
- Gate: no new product surface acceptance.

## 2026-10-01 · uncommitted · test(web_common): D-396 G1 단일 언어 계약 시험

- 변경: test/test_single_language.py — 서피스 JS/HTML 의 customElements.define 금지, 서피스 CSS 의 :root/[data-theme] --토큰 선언 금지(raw_colours :root 예외는 등록부 선언으로 존중 — 게시판 피치 색).
- 증거: 변이 증명 2종(pilot 에 :root 토큰·인라인 커스텀 엘리먼트 주입 시 각각 빨강).
- gate 변화: 없음.


## 2026-10-01 · uncommitted · D-398 증거 어휘 단일 출처 + 범위 게이트 4종

- 변경: core_ui_logic.js에 EVIDENCE_LABEL·evidenceAgeText() 추가(증거 한국어와 ' · N초 전' 규격의 단일 출처). test_token_parity.py가 RGBA 4-튜플·소문자 이름 사본도 비교. test_design_scope_gates.py 신규 — 정지(D-220)·장미색 부정(D-277)·역할 우선(ground-soft/card 두 쌍)·100vh 금지.
- 근거: D-398(2026-10-01 전 레이어 감사). 게이트 4종은 실제 파일에 위반을 심어 전부 붉어지는 것을 확인(돌연변이 증명). web_common·dashboard·fleet·pilot·face 시험 통과.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · D-398 후속 — 표면 줄 간격 예외 폐쇄

- 변경: test_surface_typography_focus_contracts 의 줄 간격 예외 화이트리스트({1.15,1.35,1.45,1.55,1.6,1.7})를 폐쇄 — 표면 CSS 의 줄 간격은 --leading-* 토큰만 쓴다. 폐쇄 직후 font: 단축형 /1.45 잔존을 적발(수리됨)해 게이트가 실제로 걷어 낸다는 증명이 됐다.
- 근거: D-398 후속. web_common 209 passed.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · D-405 아이콘 우선 선택지 — theme.js icon 필드와 공용 .ui-icon
- 변경: theme.js CHOICES에 icon(인라인 SVG, currentColor)을 더하고 choices에 그대로 노출. components.css에 .ui-icon 추가(글자 척도 value 단계 재사용, flex:none — 새 크기 척도를 만들지 않는다). test_theme_choices.py의 CHOICE regex가 icon 필드를 허용(이름 대조 원리는 버튼 텍스트 콘텐츠 그대로).
- 근거: D-405. 표준 trio(달/해/모니터 — shadcn mode-toggle·GitHub·Linear 준용), 사용자 지시 2026-10-02.
- gate 변화: 없음.
- 최종 증거: web_common 209 passed 24 skipped; Fleet 브라우저 렌더에서 3종 아이콘 + sr-only 이름 확인.

## 2026-10-02 · uncommitted · D-410 등록부 audience에 설치 경로 반영 + 두 문서 role-lock 게이트
- 변경: surfaces.yaml console audience에 "/console/install 기기 등록·카메라 보정(설치자)" 추가. test_shared_controls의 role-lock 대수 계산을 두 문서(index.html ≥1, install.html ≥1)로 갱신 — 운용 문서는 대형 잠금, 설치 문서는 카메라·보정 잠금이 각자 자기 안내를 둔다.
- 근거: D-410. 사용자 지시 2026-10-02.
- gate 변화: 없음.
- 최종 증거: web_common 209 passed 24 skipped.
