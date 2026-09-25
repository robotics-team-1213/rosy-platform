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
