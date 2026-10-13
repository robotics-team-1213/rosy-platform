# 통합 셸 계획

[D-741](../adr/D-741-unified-app-shell-seats.md)의 실행 순서다. 조각 하나가 커밋 하나이고, 그 조각이 바꾸는 시험을 같은 커밋에서 고친다.

```text
넓은 폭
┌ 앱 · 대상 ─────────────────────────── 연결 · 알림 · 나 · 정지 ┐
├ 레일 ┬ 하위 탐색 ┬ 경로 줄: 영역 / 화면 ───────── 만들기 ┤
│ 72   │ 232       ├ 본문 ───────────────┬ 지금 상태    ┤
│      │           │                     ├ 입력·조작·근거┤
│      │           │                     │ 360           │
└──────┴───────────┴─────────────────────┴───────────────┘

셸 폭 64rem 아래: 레일 한 줄, 하위 탐색 한 줄
셸 폭 48rem 아래: 앱 바 한 줄 → 탐색 → 지금 상태 → 본문 → 나머지
```

## 화면별 자리

| 앱 · 화면 | 레일 | 하위 탐색 | 본문 | 오른쪽 칸 |
|---|---|---|---|---|
| Fleet 관제 | 관제, 작업, 기록, 지도, 설치 | 없음 | 현장 지도 | 현재 개입, 로봇, 최근 기록 |
| Fleet 작업 | 같음 | 전체 작업, 승인 대기, 끝난 작업, 새 작업 | 작업 목록 또는 미리보기 | 고른 작업 또는 새 작업 내용 |
| Fleet 기록 | 같음 | 사건 셋, AI 상황 사실, 관제 기록 | 사건 목록 또는 한 건의 흐름 | 요약 또는 원인과 조치 |
| Fleet 현장 지도 | 같음 | 지도 작업 일곱 | 지도 | 고른 작업의 내용 |
| Fleet 설치·보정 | 같음 | 설치 작업 다섯 | 폼과 결과 | 없음 |
| Robot 운용 | 운용, 준비, 설치 | 없음. 왼쪽 칸은 감지 값 | 지도와 전방 카메라 | 조작 |
| Robot 작업 준비, 설치·정비 | 같음 | 작업 목록 | 고른 작업 | 없음 |
| Pilot 주행 | 없음 | 없음 | 운전석 영상. 양옆 띠에 조종 | — |
| 학습 검수 | 목록, 객체, 픽셀, 자료 | 없음 | 사진 띠와 캔버스 | 고른 상자 |
| 경기 보드 | 없음 | 없음 | 점수와 경기장 | 필드 관측 |
| Cam | 없음 | 없음 | 미리보기 | 아래에 상태와 조작 |

## 조각

앞 조각이 들어가야 뒤 조각을 시작한다. 7 이후는 2만 있으면 서로 독립이다.

| # | 조각 | 고치는 파일 | 같은 커밋에서 고치는 시험 |
|---|---|---|---|
| 0 | 결정 | D-741을 Accepted로. D-658·D-683·D-466·D-359·D-641·D-201·D-540에 바뀌는 항을 적음 | 없음 |
| 1 | 공용 토큰 | `shared/web/tokens.css`: `--line-40`, `--control-line`, `--surface-chrome`, 자리 치수와 간격 역할 | `shared/web/test/test_app_shell_seats.py` (새로) |
| 2 | 공용 자리 | `shared/web/app-shell.css` (새로), `shared-assets.json`, `CMakeLists.txt`, `surfaces.yaml`의 web-common, `template.html`, 로봇 `styleguide.html`, `DESIGN.md` | 위 시험, `test_asset_manifest.py`는 그대로 통과해야 함 |
| 3 | 조작 테두리 | `tokens.css`의 `--field-line`, `components.css`의 단추 테두리 | `test_design_scope_gates.py`의 `COLOR_ROLES`, `test_ui_token_contracts.py:308-323` |
| 4 | Fleet 앱 바 | 네 HTML, `shared/fleet-header.css`, `shared/fleet-header.js`. 시계를 앱 바로, 푸터와 그 안의 알림 링크 제거 | `test_fleet_header.py`, `test_fleet_header_browser.py`, `web/fleet-header.test.mjs`, `test_chrome_layout.py:26-33`, `test_site_map_api.py:304-325`, `test_development_console_browser.py:88-143`, `test/test_fleet_console_browser.py:2482-2625`, `test_grammar_separation.py:33-48`, `test_theme_choices.py`, `test_action_icon_contract.py`, `surfaces.yaml:103-104` |
| 5 | Fleet 레일 이름 | `shared/doc-tabs.css`, 네 HTML | `test_doc_tabs.py:36`, `test_fleet_header_browser.py:160-170` |
| 6 | Fleet 하위 탐색 | `site-map.html/.css/.js`, `cell/cell.html/.css`, `doc-tabs.css:34-42` | `test_site_map_browser.py`, `test_cell_app_browser.py`, `test_document_imports.py`, `test_grammar_separation.py` |
| 7 | Fleet 작업 영역 | `index.html`, `work-view.js`, `console.js`, `cell/cell.html`의 탐색, `channel-request-view.js:26`, `login-return.js` | `test_doc_tabs.py:9-10`, `test_work_overview_browser.py:105, 247-252`, `web/login-return.test.mjs`, `test/test_fleet_console_browser.py:2097, 2507` |
| 8 | Fleet 기록 영역 | `index.html`, `incident-view.js`, `console.js`. `?view=records`로 사건 패널을 본문에 올림 | `test_console_queue_inline_browser.py`, `web/line-stuck.test.mjs`, `test/test_fleet_console_browser.py`의 사건 패널 부분 |
| 9 | Robot 레일 | `surface.html`, `shell/shell.css:13-32, 218-246`, `shell/shell.js:83-91` | `test_surface_layout_browser.py:36-79`, `test_chrome_layout.py:29`, `test_palette_gates.py:286-294`, `test_stop_always_live.py:83`, `test_surface_viewport_budget_browser.py:91`, `test_dashboard_package.py:181` |
| 10 | Robot 하위 탐색 자리 | `shell/mount.js:50-73`, `shell/shell.css:195-199` | `test_procedure_tasks_browser.py`, `test_role_g2_browser.py:38-39`, `test_chrome_layout.py:19` |
| 11 | Pilot 웹 앱 바 | `index.html`, `styles.css`, `sw.js:5`의 캐시 이름 | `test_pilot_browser.py`, `test_pilot_app_proxy.py`, `test_d283_console_browser.py:59` |
| 12 | 학습 검수 앱 바와 레일 | 네 HTML, `app.css:16-19, 211-221` | `test_review_flow_browser.py:442-630`, `test_design_scope_gates.py:103-109` |
| 13 | 경기 보드 앱 바 | `index.html`, `styles.css:231-287`, `board.js:244-277` | `test/test_games_board_browser.py:286, 354-456, 759-805`, `test_preview.py:84, 97` |
| 14 | Cam 앱 바 | `MainActivity.kt`의 `OverheadApp()`, 네 화면의 제목 | Gradle |

Pilot Android의 자기 줄은 이 계획에 없다(D-741 "하지 않는 것").

## 조각마다 지키는 것

- 제품 파일은 `rosy-platform/.worktrees/<짧은이름>`에서만 고친다. 조각마다 주제에 맞는 브랜치를 새로 딴다.
- 시험은 커밋한 뒤 원격에서 돌린다: `python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<이름> -- <경로>` 그리고 `python test/known_failures.py X:/DevTemp/<이름>/run-1.txt`.
- 브라우저 시험(`*_browser.py`)은 원격 시험 PC에 Chromium이 없어 돌지 않는다. 푸시 뒤의 CI 결과가 증거다. 착지 보고에 "브라우저 시험은 CI 대기"라고 적는다.
- 고친 모듈의 `logs.md`에 한 줄을 더하고, 관문이 움직였으면 `progress.md`를 고친다. 대상: `shared/web`, `operations/fleet`, `operations/ui/console`, `middleware/ui/robot`, `middleware/ui/pilot`, `operations/apps/games`, `learning/curation/perception`, `operations/ui/cam`.
- 줄 수 예산(D-168)이 걸린 파일: `shared/web/ui.js`, `shared/web/components.css`, `middleware/ui/pilot/styles.css`, `operations/ui/console/console.js`(지금 1035줄, 상한 1175), `operations/ui/console/shared/styles.css`. 넘으면 `test/architecture/test_module_structure.py`의 판정을 다시 적는다.
- 폭 320, 390, 768, 1024, 1366, 1920에서 정지의 위치, 가로 넘침, 앱 바 높이(D-359 머리 예산 20%)를 브라우저 시험이 잰다.
- 소스 시험, CI, 설치본, 실물 화면 수용은 서로 다른 증거로 적는다. D-153의 G2 캡처와 G3 사람 검토는 표면마다 따로 남긴다.

## 지금 상태

설계 캔버스(저장소 밖)에 다섯 쪽 40장이 있다. 독립 검토 한 차례와 정적 점검 한 차례를 소스로만 했다. 화면을 렌더해서 본 적은 없다. 저장소의 제품 코드는 바뀌지 않았다. 조각 1과 2의 단계별 계획은 [공용 자리](2026-10-13-unified-app-shell-shared-seats.md)에 있다.
