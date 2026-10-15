# UI 스크린샷 결함 수정 — 남은 일 (2026-10-15)

브랜치 `uiux/screenshot-defects`. 기준은 D-763 스크린샷 검토(main `ccb1a2ae0`, 고정 자료 화면)에서 찾은 결함 일곱 개다. 착지·푸시는 하지 않았다.

## 결함별 상태

| # | 결함 | 원인 | 고침 | 시험 | 상태 |
|---|---|---|---|---|---|
| 1 | Pilot 시험 서버에서 `/pilot`이 그려지지 않음 | `test/dev_server.py`가 `/common` 허용 목록을 따로 들고 있었고 `account-profile.js`, `brand/mark.svg`가 빠졌다 | `shared/web/shared-assets.json`을 읽는다. 제품 서버(CORE `core_api_web`, OMX `pilot_sim_api`)는 이미 그 파일을 읽으므로 실제 장애는 없었다 | 기존 `test_connect_app_bar_is_one_row_from_64rem…`가 이 결함으로 시간 초과하던 시험이다 | 고침 |
| 2 | 관제 로봇 카드 "닿지 않음: undefined" | 헤더 시험 고정 자료가 `error`를 문자열로 줬다. 서버(`console_view._error_of`)는 늘 `{reachable, code, message}`를 보낸다. 제품 경로 결함 아님 | 고정 자료를 서버 모양으로 | `test_fleet_header_browser`: 카드가 `닿지 않음: 접속 실패`, 본문에 `undefined` 없음 | 고침 |
| 3 | 지도 390px: 선택 상자 글자 잘림, 지도 오른쪽 잘림 | 머리 줄에서 선택 상자가 눌려 네이티브 화살표가 글자를 덮었다 | 머리 줄 줄바꿈, 선택 상자는 제 폭. 60rem 아래 지도 가로 이동은 그대로 둔다(`test_site_map_fits_declared_widths`가 12px 라벨을 위해 고정한 설계이고 안내 문구가 있다) | `test_site_map_fits_declared_widths`가 화살표까지 잰 선택 상자 폭을 본다 | 고침 |
| 4 | 새 작업 종류 모양 다름 | `.work-list` 규칙이 `ui-button`에만 걸려 Cell 링크가 작은 밑줄 상자였다 | 같은 규칙을 링크에도(줄 수 늘지 않음) | `test_new_work_shows_only_kinds_that_run…`가 두 줄의 위치·폭·높이를 비교 | 고침 |
| 5 | 작업 상세에 승인 조건 없음, 고른 줄 표시 없음 | 작업 읽기의 `approval`을 그리지 않았다. 줄이 `quiet` 단추라 `aria-pressed` 모양이 없었다 | 읽기 전용 `승인 조건` 줄(D-763 7항 말). 줄은 `toggle` 단추로 기존 눌림 채움을 쓴다 | `test_work_overview_browser` | 고침 |
| 6 | 경기 보드 계정 링크 x=0 기본 파랑, 390px 브랜드 없음 | 링크가 앱 바 밖에 스타일 없이 있었다. 보드 호스트(`games/host/preview.py`)가 폴더가 있는 `/common` 이름을 거절해 R 심볼이 404였다(실제 보드에도 해당) | 링크를 앱 바 나 자리로, 페이지 잉크. 호스트는 목록만으로 거른다. 30rem 아래는 워드마크 글을 접고 R 심볼을 남긴다(D-741 5) | `test_compact_board_keeps_header_budget…`, `test_preview.py` | 고침. 390px에서 "1v1 피치" 글은 D-741 접힘 규칙대로 숨는다. 글까지 보여야 하면 결정이 필요하다 |
| 7 | 학습 검수: AI 초안 단추 글자가 테두리에 붙음, 390px 설명 잘림 | 사유가 붙은 단추는 세로 여백이 0이다. 설명은 가로 스크롤 줄 안에 있었다 | 학습 앱에서 사유 단추에 세로 여백, 도구 줄 줄바꿈, 설명은 한 줄 전체 | `test_disabled_ai_draft_and_photo_caption…` | 고침. 원인은 공용 `components.css`(사유 단추 `padding-block` 0)라 다른 표면에도 있을 수 있다. 공용 수정은 여러 표면 치수 시험을 다시 봐야 해서 하지 않았다 |

## 남은 일

1. 아래 시험 묶음 결과를 확인한다(이 노트를 쓸 때 실행 중이었다). `NEW`가 있으면 브랜치에서 고친다.
2. 공용 시험 도구 `test/browser_harness.py`의 `BODY_FIT`은 선택 상자 글자 잘림을 화살표 없이 잰다. 그래서 결함 3을 놓쳤다. 고치면 다른 표면의 숨은 잘림이 드러날 수 있어 따로 한다.
3. 결함 7의 공용 원인(위 표).
4. 착지는 사용자가 말한 뒤 `python tools/land.py --tests auto`.

## 시험

```bash
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/ui-shot-fixes -- ROSY_RUN_BROWSER_TESTS=1 \
  middleware/robot_ui/pilot/test/test_pilot_browser.py operations/fleet/test/test_fleet_header_browser.py \
  operations/fleet/test/test_site_map_browser.py operations/fleet/test/test_console_card_trips_browser.py \
  operations/fleet/test/test_work_overview_browser.py test/test_games_board_browser.py \
  operations/apps/games/test/test_preview.py test/learning/perception/test_review_flow_browser.py \
  test/learning/perception/test_pixel_review_browser.py test/architecture/test_module_structure.py \
  shared/web/test/test_asset_manifest.py
python test/known_failures.py X:/DevTemp/ui-shot-fixes/run-1.txt
```

## 스크린샷을 시험 PC에서 다시 찍는 법

노트북에서 브라우저를 띄우지 않는다(D-584). `remote_pytest.py`는 사진 파일을 가져오지 않으므로 손으로 한다.

1. `python tools/remote/remote_pytest.py --pick pytest`로 여유 있는 시험 PC를 고른다. `remote_pytest.py`를 한 번 돌리면 그 PC의 `~/rosy-test/venvs/<hash>`에 맞는 venv가 생긴다.
2. 브랜치를 그 PC에 보낸다: `git bundle create head.bundle refs/heads/uiux/screenshot-defects`, `scp`, 그 PC의 `~/rosy-test/repo`에서 `repo.lock`을 `flock`으로 잡고 `git fetch head.bundle` 후 `git worktree add --detach ~/rosy-test/ui-shot-fixes/src <sha>`. `~/rosy-jobs/<이름>.lock`에 `"$$ pytest 2 6"`을 써서 부하를 알린다.
3. 찍기는 저장소 시험의 고정 자료를 그대로 쓴다. 여러 시험이 `ROSY_SHOT_DIR`이 있으면 사진을 남긴다(`test_fleet_header_browser`, `test_console_card_trips_browser`의 `_shot`, 경기 보드 시험). 화면별로 더 찍으려면 같은 폴더에 버리는 시험 파일을 두고 그 fixture를 가져다 `page.screenshot`만 한다(Fleet: `test_fleet_header_browser._api/_fleet`, `test_console_queue_inline_browser._open/site`; Pilot: `test_pilot_browser.tablet_page`; 학습: `test_review_flow_browser.browser_workspace`; 경기: `test_games_board_browser.PreviewServer/_play_payload`). 버리는 파일은 커밋하지 않는다.
4. `ROSY_RUN_BROWSER_TESTS=1 ROSY_SHOT_DIR=<출력> nice -n 15 <venv>/bin/python -m pytest -q -p no:cacheprovider <파일>`로 돌리고 `scp`로 `X:\DevTemp\<이름>\`에 가져온 뒤 그 PC의 worktree를 지운다.

2026-10-15 사진(전·후)은 이 노트북의 `X:\DevTemp\ui-shot-fixes\shots\`에 있다(`before-*`는 원래 검토 사진, `after-*`는 `76a06b166`).
