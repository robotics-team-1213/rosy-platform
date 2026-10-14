# Fleet Mission 원장과 작업 읽기 크기 단위 분리

**날짜:** 2026-10-15
**범위:** D-168/D-753 구조 판정과 파일 열 개의 폴더 이동. 동작 변경 없음. 모듈 이름(`fleet.server.mission_*`, `fleet.server.work_read`, `fleet.server.work_routes`)은 그대로다. D-763 조각 4(`feat/fleet-work-read-sources`)를 조각 6(`feat/fleet-job-holds-lease`, API v1.236) 착지 뒤 main과 합친 같은 브랜치의 변경이다(머지 `ab8ac53f6`). 선례: `docs/plans/2026-10-14-fleet-ledger-size-unit.md`, `docs/plans/2026-10-14-fleet-console-size-unit.md`, `docs/plans/2026-10-15-fleet-console-work-unit.md`.

`fleet/fleet/server/ledger` 판정은 6,985에 +150(한도 7,135)이다. 조각 6이 7,036 → 7,116, 조각 4가 7,036 → 7,135로 키워, 머지 뒤 원장은 7,215다. 원장 계획은 다음 +150에서 수용으로 넘기지 않고 Mission 승인·거절 경로(`mission_routes`)와 Mission 원장(`mission_store`)을 자기 하위 단위로 낸다고 정했다. 이 계획이 그 분리다. 그것만으로는 모자라서(아래 기준선) 작업 읽기도 자기 단위로 낸다.

## 무엇을 단위로 하는가

**Mission 원장 `fleet/fleet/server/missions`.** `ledger/`의 Mission 파일 여덟 개를 새 Fleet 서버 보관 자리 `operations/fleet/fleet/server/missions`로 옮긴다: `mission_store`(원장), `mission_service`, `mission_routes`(제안·resolve·admit·reject·읽기 경로), `mission_progress`, `mission_dispatcher`, `mission_model_turn_store`·`_scheduler`·`_worker`. 코드가 이미 이름으로 묶은 것이고 서로 import한다. Task·trip 파일과 `action_receipts`는 이 여덟을 import하지 않는다(머지 뒤 `grep`으로 확인).

**작업 읽기 `fleet/fleet/server/work`.** `work_read.py`(서버 자리)와 `work_routes.py`(조각 4가 서버에서 `ledger/`로 옮겼다)를 새 보관 자리 `operations/fleet/fleet/server/work`로 옮긴다. D-664 작업 읽기 하나의 두 반쪽이다: Task·Mission·trip·Cell Job 원장을 읽기만 하고 어느 원장의 소유자도 아니다.

**왜 둘인가.** Mission 분리만 하면 원장은 7,215 − 2,575 = 4,640이고 그 판정값은 4,410 + 150 = 4,560이라 80줄 넘는다. 판정 뒤 원장 증가 230줄은 Mission이 아니라 trip(조각 1·2·6)과 조각 4가 옮겨 온 `work_routes`(95줄)에서 왔다. trip 파일은 다른 세션들(D-760, 차로 규제)이 지금 고치는 자리라 옮기면 그 브랜치마다 충돌한다. 작업 읽기는 이 브랜치의 파일이고 다른 원장과 한 묶음이 아니다. 그래서 작업 읽기를 낸다.

**이동의 모양.** 크기 단위는 폴더 경계로만 셀 수 있으므로(`_over_budget`의 `rel.startswith(unit + "/")`) 파일을 옮긴다. 모듈 이름은 그대로다: 두 폴더를 `fleet/_source_layout.py` `SERVER_HOLDERS`에 더하면 `fleet/server/__init__.py`가 `__path__`에 넣는다. `ledger/`처럼 `__init__.py`를 두지 않는다(`tools/packaging/fleet_sources.py`의 중복 모듈 검사). `FLEET_SERVER_HOLDER_UNITS`와 배포 시험(`test/test_remaining_platform_installed.py`)의 holder 목록에 둘을 더한다. 파일 판정 `ledger/mission_store.py`는 경로만 `missions/mission_store.py`로 바꾸고 줄 수와 문구는 그대로다. `docs/reference/fleet-rulebook.md`의 Mission 연결을 새 경로로 고친다.

## 기준선

D-757 판정 커밋 `61aa49b32`에서 앞의 계획과 같은 방법(그 커밋의 추적 파일 줄 수, `_lines`와 같은 줄바꿈 수)으로 쟀다.

| 파일 | `61aa49b32` | 지금 |
|---|---|---|
| `mission_store.py` | 929 | 936 |
| `mission_routes.py` | 483 | 486 |
| `mission_model_turn_store.py` | 431 | 427 |
| `mission_dispatcher.py` | 261 | 261 |
| `mission_service.py` | 171 | 165 |
| `mission_model_turn_scheduler.py` | 109 | 109 |
| `mission_model_turn_worker.py` | 109 | 109 |
| `mission_progress.py` | 82 | 82 |
| Mission 합 | 2,575 | 2,575 |
| `work_read.py`(그때 서버 자리) | 25 | 33 |
| `work_routes.py`(그때 서버 자리) | 32 | 95 |
| 작업 읽기 합 | 57 | 128 |

| 단위 | `61aa49b32` | 머지 뒤, 분리 전 | 분리 뒤 | 판정값 | 한도 |
|---|---|---|---|---|---|
| `fleet`(서버) | 31,837 | 31,881 | 31,846 | 31,780 | 31,930 |
| `fleet/fleet/server/ledger` | 6,985 | 7,215 | 4,545 | 4,410 | 4,560 |
| `fleet/fleet/server/missions` | — | — | 2,575 | 2,575 | 2,725 |
| `fleet/fleet/server/work` | — | — | 128 | 57 | 207 |

- 판정값은 그 커밋에서 잰 파일로 나눈 것이다. 원장 6,985 = 4,410 + 2,575. 서버 31,837 = 31,780 + 57. 어느 단위도 기점에서 다시 잡지 않는다. 판정 뒤 쓴 허용은 쓴 허용으로 남는다: 원장 135, 서버 66, 작업 읽기 71.
- 합친 한도는 두 단위만큼 300 늘어난다. 이 등록은 머지 뒤 실패하는 시험(원장 7,215 > 7,135)을 받으려는 것이다. 그래서 수용이 아니라 원장 계획이 이름 붙인 분리와, 그것이 모자란 만큼의 작업 읽기 분리로 한다.

## 서버 단위

`fleet`(서버) 판정의 문구를 그대로 지킨다: 기능 성장 허용을 더하지 않았다. 이후 D-763 조각은 서버 단위에서 순증 0이다. 조각 4는 같은 경계(작업 읽기 제외)로 재면 조각 전 31,847, 뒤 31,846이다. 서버 쪽 변경은 `app.py`(같은 줄 수), `console/static_routes.py`(경로만), `_source_layout.py`(같은 줄), `setup.py`(관제 하위 패키지 자원을 `*/*.html`·`*/*.css`·`*/*.js` 한 줄로, −1)다.

## 그대로 두는 것

- 모든 안쪽 단위(`fleet/fleet/traffic`, `observe`, `server/channel`과 그 아래, `localization`, `stuck`과 그 아래, `incidents`와 그 아래, `decision/...`, `site_ui/console`, `site_ui/console/work`)의 기준선과 +150.
- 파일 600·800줄 판정과 1,000줄 HARD_TIER의 증가 0. `ledger/task_store.py`, `ledger/trip_runner.py`, `ledger/trip_ports.py`의 판정은 그대로다.
- `ledger`와 `fleet` 판정 문구 전부. 각각 앞에 한 줄을 붙일 뿐 지우지 않는다.
- safety 태그(`ledger/task_dispatch_routes.py`, D-430)는 옮기지 않는다. 옮긴 열 파일은 `tools/harness/platform_parts.yaml`의 safety 목록과 safety 루트에 없다(확인).
- 다음 증가가 +150에 닿으면 수용으로 넘기지 않는다. Mission은 모델 턴(`mission_model_turn_*`)을 자기 단위로 낸다. 원장(남은 15줄)은 trip 파일(`trip_*`)을 자기 단위로 낸다. 그 분리는 trip을 고치는 세션들과 날을 맞춘다.

## 검증

`test/architecture/test_module_structure.py`의 실측 셋(`test_over_budget_code_has_a_recorded_verdict`, `test_size_units_are_real_subpackages_with_a_split_plan`, `test_size_verdicts_are_well_formed_and_current`)과 `test_fleet_server_holder_units_are_declared_holders`, 배포 자원 시험, Mission·Cell·작업 읽기 시험을 원격 시험 PC에서 돌린다. SOURCE 구조 증거이며 ROS-SIM·DEVICE·FIELD 수용을 뜻하지 않는다.

판정 상태: 독립 재판정 전이다.
