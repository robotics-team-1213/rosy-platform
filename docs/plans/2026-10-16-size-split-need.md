# D-766 묶인 파일, 실제로 나눠야 하나 (2026-10-16)

D-766 개정 2 뒤 `test/architecture/size_ratchet.txt`의 행은 76개다. 파일 72개, 단위 4개다. 이 문서는 "600줄(스크립트 600, 마크업 800, 시험 1,500)을 넘었으니 다 나눈다"가 맞는지 따져 보고, 나눌 차례를 정한다. 일정은 정하지 않는다. D-766 4항대로 묶인 파일은 자라야 할 때 먼저 나눈다.

## 600줄로 다 나누면 드는 양

| 대상 | 한도 | 넘은 파일 | 한도 위 줄 합계 |
|---|---|---|---|
| 제품 코드 | 600 | 48 | 11,191 |
| 스크립트 `.js`/`.mjs`/`.ts` | 600 | 10 | 2,342 |
| 마크업 `.html`/`.css` | 800 | 5 | 1,468 |
| 시험 파일 | 1,500 | 9 | 9,154 |

`size_ratchet.txt`의 파일 행 72개를 잰 값이다. 한도 위 줄만 24,155줄이다. 나누기는 C1/C2/C5/B 경계를 찾고, 이동 검사를 하고, 경계 검토를 받는 일이다(D-766 3항). 그래서 한 번에 다 하는 것은 맞지 않다. 대부분은 자라지 않으므로 나눌 이유도 없다.

## 기준

- 잰 값: 2026-10-02 이후 14일 동안의 커밋 수(`git log --since=2026-10-02 -- <경로>`)와 마지막 커밋 날짜다.
- 한계: `--follow` 없이 셌다. 2026-10-11–13 폴더 이동(D-427) 전 이력은 잘린다. 이동 커밋 1회만 보이는 파일은 실제로 거의 바뀌지 않은 것이다.
- **A. 곧 나눈다**: 14일에 20회 이상 바뀐다. 다음 기능이 거의 확실히 이 파일을 키우려 한다. 막히기 전에 경계를 정한다.
- **B. 자랄 때 나눈다**: 5–19회 바뀐다. 다음에 키워야 하는 변경이 먼저 나눈다.
- **C. 나누지 않는다**: 4회 이하 바뀌거나 이동 커밋만 있다. 천장이 자라지 못하게 막으니 그대로 둔다. `docking/manager.py`처럼 나눌 경계가 없으면 나누지 않는 것이 맞다(D-766 3항 마지막 문단).

## A. 곧 나눈다 (14개)

| 파일 | 줄 | 한도 | 14일 커밋 | 경계 후보 (검토 전) |
|---|---|---|---|---|
| `operations/fleet/fleet/server/app.py` | 989 | 600 | 205 | 라우트 등록을 기능별 라우터로 나눈다(C5: 서비스 주인이 여럿인 API 모듈) |
| `test/test_fleet_console_browser.py` | 3,884 | 1,500 | 121 | 콘솔 화면별 파일로 나누고 픽스처는 `conftest.py`로 옮긴다 |
| `operations/fleet/fleet/cli.py` | 923 | 600 | 87 | 하위 명령별 모듈로 나눈다 |
| `contracts/foundation/core_common/protocol/schemas.py` | 1,320 | 600 | 86 | 메시지 영역별로 나눈다(API 변경 횟수 자체는 줄지 않는다. 토론에서 엄격 측도 인정했다) |
| `operations/fleet/test/test_trip_runner.py` | 1,757 | 1,500 | 52 | 제품 `trip_runner.py`를 나눌 때 같은 경계로 나눈다 |
| `test/test_rosy_face.py` | 2,484 | 1,500 | 42 | 제품 `rosy-face.py`를 나눌 때 함께 나눈다 |
| `tools/harness/rosy_harness.py` | 858 | 600 | 39 | `generate`/`lint` 하위 명령별로 나눈다 |
| `deploy/robot/pinky_pro/native/rosy-face.py` | 1,273 | 600 | 34 | 화면 렌더와 상태 수집을 나눈다(C2) |
| `shared/web/components.css` | 943 | 800 | 29 | 컴포넌트 묶음별 파일로 나눈다 |
| `deploy/site/rosy_model_code.py` | 698 | 600 | 27 | 검토 때 정한다 |
| `middleware/core/gateway/core/bridge/ros_bridge.py` | 888 | 600 | 25 | 토픽 묶음별 mixin으로 나눈다(C1: ROS가 필요한 부분 분리) |
| `shared/web/ui.js` | 814 | 600 | 25 | 검토 때 정한다 |
| `test/test_dashboard_browser.py` | 3,049 | 1,500 | 22 | 화면별 파일과 `conftest.py`로 나눈다 |
| `learning/curation/perception/review_app.py` | 756 | 600 | 20 | 검토 때 정한다 |

경계 후보는 출발점일 뿐이다. 나누기마다 날짜 계획 하나와 경계 검토 하나로 한다(D-766 7(c)). 시험 파일은 픽스처를 `conftest.py`로 옮기는 것만으로 크게 준다. 같은 픽스처를 새 파일마다 복제하지 않는다.

## B. 자랄 때 나눈다 (19개)

`trips/trip_runner.py`(899, 19회), `test/learning/perception/test_review_flow_browser.py`(1,531, 19회), `native/sync-image-layer.py`(1,023, 17회), `tools/perception/rosy_ml.py`(749, 14회), `release/secret_scan.py`(815, 13회), `pilot/test/test_pilot_browser.py`(3,059, 13회), `console/shared/site-map-model.js`(800, 11회), `site_ui/console/console.js`(1,069, 10회), `deploy/site/rosy_site_autoupdate.py`(616, 9회), `tools/device_test/run.py`(609, 9회), `native/rosy-ssh-access.py`(862, 6회), `cell/cell_job_store.py`(943, 6회), `console/shared/styles.css`(856, 6회), `line_follow/manager.py`(822, 5회), `swarm/session.py`(628, 5회), `pilot/styles.css`(956, 5회), `site_ui/console/roster.js`(711, 5회), `test/test_rosy_auto_update.py`(2,632, 5회), `native/rosy_auto_update.py`(1,591, 4회. 10-01 이후 18회라 B에 넣는다).

한도를 조금 넘은 파일은 기능 하나를 옮기는 것으로 한도 아래가 된다. `rosy_site_autoupdate.py`는 16줄, `device_test/run.py`는 9줄, `swarm/session.py`는 28줄, `site-map-model.js`는 200줄을 덜어내면 된다. 파일 바닥 150줄(D-766 3항)은 지킨다.

## C. 나누지 않는다 (39개)

행에 남은 나머지 39개 파일이다. 14일 동안 4회 이하로 바뀌었거나 폴더 이동 커밋만 있다. 예: `omx_adapter/action_store.py` 1,141줄, `diagnostic.html` 1,857줄, `ledger/task_store.py` 1,014줄, `console/console.py` 1,325줄. 천장 때문에 자라지 않으니 지금 나눌 이득이 없다. 바뀌기 시작하면 B로 옮긴다.

## 단위 4개

| 단위 | 줄 | 처리 |
|---|---|---|
| `fleet` | 17,800 | Fleet 서버 단위 등록(`size_units.txt`)으로 이미 나누는 중이다. 새 기능은 여유 있는 등록 단위에 둔다(D-766 Consequences) |
| `control` | 15,918 | 같은 방식이다. `middleware/drive/*` 보관 자리 단위로 옮긴다 |
| `site_ui/console` | 13,327 | `work`처럼 화면 묶음 단위로 나눈다 |
| `perception/front_camera/perception` | 10,075 | 75줄 넘었다. D-766 7(c)의 첫 강제 분리 후보다 |

## 다음 행동

1. A의 `app.py`, `test_fleet_console_browser.py`, `cli.py`, `schemas.py`는 이번 주 기능 작업에서 막힐 가능성이 가장 크다. 막히기 전에 각각 날짜 계획을 쓴다.
2. 한 달 뒤(2026-11-16) 같은 스크립트로 다시 잰다. 시험 한도를 1,000으로 내릴지(27개 묶음) 그때 정한다.
3. 다시 재는 방법: 저장소 루트에서 `size_ratchet.txt`의 행마다 `git log --since=<14일 전> --format=%h -- <경로>`를 센다.
