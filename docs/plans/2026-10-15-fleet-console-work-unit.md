# Fleet 관제 작업 영역 크기 단위 분리

**날짜:** 2026-10-15
**범위:** D-168/D-753 구조 판정과 파일 두 개의 폴더 이동. 동작 변경 없음. D-763 조각 4(`feat/fleet-work-read-sources`, 작업 읽기의 trip·Cell Job 출처와 새 작업 종류 목록)와 같은 브랜치의 변경이다. 선례: `docs/plans/2026-10-14-fleet-console-size-unit.md`(조각 3, `site_ui/console`), `docs/plans/2026-10-14-fleet-ledger-size-unit.md`(조각 5·5b, `fleet/fleet/server/ledger`).

`site_ui/console` 판정은 17,933에 +150이다. 조각 4 전에 18,082로 149를 썼다. 조각 4의 화면 변경(trip·Cell Job 행, 보이는 상태, 서버 종류 목록)은 문장을 한 줄에 모으지 않고는 들어가지 않는다. 콘솔 계획은 다음 +150에서 수용으로 넘기지 않고 `work-view.js`와 작업 영역을 자기 하위 패키지로 낸다고 정했다. 이 계획이 그 분리다.

## 무엇을 단위로 하는가

`operations/site_ui/console/work`를 크기 단위 `site_ui/console/work`로 등록한다.

- 파일 두 개를 옮긴다: `work-view.js`(D-664 작업 읽기, `/console?view=work`)와 `channel-request-view.js`(D-680 대화 요청 검토, 작업 화면 안의 칸). 둘 다 `console.js`만 import하고 둘 다 작업 영역의 화면이다. 새 폴더에 `__init__.py`를 둔다(`cell/`과 같다). 그래서 Fleet 배포는 `fleet.server.web.work`를 찾고 `setup.py` package_data에 `work/*.js`를 더한다.
- 브라우저 주소는 그대로 `/console/assets/<파일이름>`이다. `console/static_routes.py` allowlist의 원본 경로만 `work/...`로 바뀐다. `console.js`의 `./work-view.js` import는 같은 주소로 풀린다. node 해석 훅(`test/web/resolve-console-assets.mjs`)과 문서 import 시험(`test_document_imports.py`)이 `work/`를 찾는다.
- 가장 안쪽 단위가 줄을 가져가므로(`_over_budget`) 두 파일과 `__init__.py`는 `site_ui/console` 대신 이 단위로 세어진다. 스캔에서 빠지는 파일은 없다.
- **콘솔 계획에서 벗어난 점(기록).** 콘솔 계획은 `work-view.js`와 함께 `console.js`의 작업 영역 연결을 내라고 적었다. 그 연결(`paintMove`, `work-new`·`work-move` 자리, 15줄 안팎)은 옮기지 않는다. 로봇 카드의 운행 폼(`roster.trip`), `view`, `render`를 닫아 쓰는 셸 코드라서, 옮기면 그 셋을 넘기는 새 경계가 생긴다. `console.js`는 HARD_TIER 위라 파일 증가 0이 그대로 지킨다. 조각 4는 거기서 한 줄을 지웠다.

## 기준선

D-757 판정 커밋 `61aa49b32`에서 앞의 두 계획과 같은 방법(그 커밋의 추적 파일 줄 수, `_lines`와 같은 줄바꿈 수)으로 쟀다.

| 단위 | D-757 판정 커밋 `61aa49b32` | 조각 4 전(`aa142d7e5`) | 지금(조각 4 뒤) | 판정값 |
|---|---|---|---|---|
| `site_ui/console`(작업 영역 제외) | 17,569 | 17,932 | 17,717 | 17,569 |
| `site_ui/console/work` | 364(`work-view.js` 143 + `channel-request-view.js` 221) | 364 | 379 | 364 |
| 합(등록 전 `site_ui/console`) | 17,933 | 18,082(+150 가운데 149) | 18,096 | — |

- 판정값은 콘솔 판정 17,933을 그 커밋에서 잰 두 단위로 나눈 것이다. 어느 단위도 기점에서 다시 잡지 않는다. 콘솔이 판정 뒤 쓴 149줄은 쓴 허용으로 남는다. `site_ui/console`은 17,569 + 150 = 17,719 한도에 17,717이다(남은 2줄).
- `site_ui/console/work`는 364에 +150이다. 조각 4가 15줄(행 출처·보이는 상태·종류 목록, 그리고 `__init__.py` 1줄)을 써서 135가 남는다.
- 합친 한도는 18,083에서 18,233으로 150 늘어난다. 이 등록은 실패하는 시험을 넘기려는 것이다: 등록 전 콘솔은 18,096으로 18,083을 넘는다. 그래서 수용이 아니라 콘솔 계획이 미리 이름 붙인 분리로 한다.

## 다른 두 단위

- `fleet`(서버)은 조각 4에서 순증이 음수다: 31,904 → 31,881(`work_routes.py`를 원장 holder로 옮김 −32, `work_read.py` Cell Job 조회 +8, `setup.py` +1). D-763의 서버 순증 0 규칙을 지킨다.
- `fleet/fleet/server/ledger`는 6,985 + 150 = 7,135 한도에 7,135다(검토 반영: Cell Job 상세 범위 +3, 닫힌 trip의 `wait` +1, 이벤트 루프 밖 읽기 +7을 포함). 남은 줄이 없다. 원장 계획은 다음 +150에서 Mission 승인·거절 경로(`mission_routes`)와 Mission 원장(`mission_store`)을 자기 하위 단위로 낸다고 정했다. 다음 원장 증가는 그 분리부터다.

## 그대로 두는 것

- 모든 안쪽 단위의 기준선과 +150. 파일 600·800줄 판정과 1,000줄 HARD_TIER의 증가 0. 콘솔 파일 판정(`console.js` 1,175, `map-view.js` 984, `shared/styles.css` 802)은 그대로 검사한다.
- `site_ui/console` 판정 문구 전부. 이 계획은 그 문구 앞에 한 줄을 붙일 뿐 지우지 않는다.
- 다음 작업 영역 증가가 +150에 닿으면 수용으로 넘기지 않는다. 그때는 승인 대기의 승인·거절 자리(조각 5c)를 이 단위 안의 자기 모듈로 낸다.

## 검증

`test/architecture/test_module_structure.py`의 실측(`test_over_budget_code_has_a_recorded_verdict`, `test_size_units_are_real_subpackages_with_a_split_plan`, `test_size_verdicts_are_well_formed_and_current`)과 배포 자원 시험(`test/test_remaining_platform_installed.py`)을 원격 시험 PC에서 돌린다. SOURCE 구조 증거이며 ROS-SIM·DEVICE·FIELD 수용을 뜻하지 않는다.

판정 상태: 2026-10-15 브랜치 검토의 크기 재판정 ACCEPT WITH CONDITIONS. 조건: (1) `paintMove`와 작업 자리가 `console.js`에 남는 것은 위 "벗어난 점"과 그 이유로 기록한다. (2) 다음 콘솔 증가(남은 2줄)는 그 연결을 이 단위로 내는 분리부터 시작하고, 다음 원장 증가(검토 반영 뒤 7,135로 남은 0줄)는 원장 계획이 이름 붙인 Mission 분리(`mission_routes`·`mission_store`, `docs/plans/2026-10-15-fleet-ledger-missions-unit.md`, 조각 6 착지 뒤 머지에서)부터 시작한다. 수용으로 넘기지 않는다.
