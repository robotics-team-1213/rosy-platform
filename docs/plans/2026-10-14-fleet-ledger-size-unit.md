# Fleet 작업 원장 크기 단위 분리

**날짜:** 2026-10-14
**범위:** D-168/D-753 구조 판정만. 코드 이동이나 동작 변경 없음. D-763 조각 5·5b(`feat/fleet-approval-registry`, 승인 등록부와 승인 대기 작업의 거절 경로)와 같은 브랜치의 변경이다. 선례: `docs/plans/2026-10-14-fleet-console-size-unit.md`(조각 3, `site_ui/console` 단위).

D-763 구현 조각 표는 조각마다 Fleet 크기 단위에서 순증 0 이하이거나, 먼저 새 크기 단위를 등록하는 날짜 있는 계획을 내라고 정했다.
조각 5·5b는 새 경로 하나(`POST /api/fleet/missions/{mission_id}/reject`)와 승인 판정을 더한다. 같은 브랜치에서 admit의 두 원장 분기를 한 경로로 합치고 Cell 역할 검사를 도우미 하나로, Cell 거절을 기존 `cancel`로 줄였지만 순증 0을 맞추지 못했다. 이 계획이 그 날짜 있는 계획이다.

## 무엇을 단위로 하는가

`operations/fleet/fleet/server/ledger`를 크기 단위 `fleet/fleet/server/ledger`로 등록한다.

- 경계는 코드가 이미 묶은 대로다. `ledger/`는 Fleet 서버의 작업 원장 소유자 보관 자리다: Task(`task_store`·`task_service`·`task_dispatch_routes`·`task_*`), trip(`trip_*`), Mission(`mission_store`·`mission_service`·`mission_routes`·`mission_progress`·`mission_dispatcher`·`mission_model_turn_*`), 그리고 `action_receipts`, `core_event_store`. 승인과 거절 경로(`mission_routes`)와 Mission 원장(`mission_store`)이 여기 있다. Mission만 떼려면 파일을 옮겨야 하므로(코드 이동) 폴더 경계를 쓴다.
- 이 폴더는 `fleet.server`의 소스 보관 자리다(`fleet/_source_layout.py` `SERVER_HOLDERS`, `fleet/server/__init__.py`가 `__path__`에 더한다). 모듈은 `fleet.server.<이름>`으로 import된다. `__init__.py`를 두면 `tools/packaging/fleet_sources.py`가 `fleet.server`의 모듈 이름 `__init__`을 두 번 모아 빌드가 `Duplicate Fleet server source module`로 실패하므로 두지 않는다.
- 그래서 `test_size_units_are_real_subpackages_with_a_split_plan`의 "colcon 루트 아래 `__init__.py`" 조건에 한 가지를 더한다: `SERVER_HOLDERS`에 이름이 있는 Fleet 서버 보관 자리 폴더(`fleet/fleet/server/<holder>`)도 하위 패키지로 센다. 다른 규칙(줄 수가 0보다 클 것, 판정이 있는 `docs/plans` 계획을 인용할 것)은 그대로다.
- 스캔에서 빠지는 파일은 없다. 줄은 `fleet` 대신 이 단위로 세어진다(가장 안쪽 단위가 가져간다).
- `cell/`(Cell Job 원장, 1,8xx줄 — `61aa49b32`에서 1,815)은 이 단위에 넣지 않는다. 조각 5b의 Cell 쪽 증가는 기존 `cancel`을 넓힌 몇 줄이고, 등록부(`step_action_kinds.py`)와 함께 서버 단위에 남아 서버의 남은 허용에서 보인다.

## 왜 나누는가

- D-763은 원장에 승인 판정, 거절, 다음 조각(작업 claim, 단계 원장 어댑터)을 더한다. 원장 줄은 다른 서버 코드와 다른 속도로 는다.
- 한 합계로 두면 원장 조각이 서버의 남은 여유를 쓰고, 원장 증가가 서버 합계 뒤에 숨는다. 원장의 증가는 자기 단위에서 따로 보여야 한다.

## 기준선

D-757 판정 커밋 `61aa49b32`에서 `site_ui/console` 계획과 같은 방법(그 커밋의 추적 파일 줄 수. `_over_budget`이 세는 접미사 `.py`·`.cpp`·`.hpp`·`.sh`·`.js`·`.html`·`.css`; `ledger/`에는 `.py`만 있다)으로 쟀다.

| 단위 | D-757 판정 커밋 `61aa49b32` | 브랜치 기점 `06e97383b` | 지금(조각 5·5b와 검토 반영 뒤) | 판정값 |
|---|---|---|---|---|
| `fleet`(서버·decision·discord, 관제·원장 제외) | 31,837 | 31,862 | 31,886 | 31,837 |
| `fleet/fleet/server/ledger` | 6,985 | 7,006 | 7,036 | 6,985 |
| `site_ui/console`(변경 없음) | 17,933 | 17,988 | 18,023 | 17,933 |

- 판정값은 콘솔 계획의 `fleet` 38,822를 그 커밋에서 잰 두 단위로 나눈 것이다. 어느 단위도 기점에서 다시 잡지 않는다. 기점에서 다시 잡으면 판정 뒤의 증가가 기준선 안으로 사라진다.
- `fleet`은 D-753 문구를 그대로 지킨다: 기능 성장 허용을 더하지 않았다. 기점까지 쓴 허용과 이 조각의 서버 몫(등록부·Cell `cancel`)은 다시 잡지 않고 쓴 허용으로 남는다.
- `fleet/fleet/server/ledger`는 6,985에 +150이다. 기점까지 21, 기점 뒤 30(조각 1 `feat/fleet-work-move-entry`에 든 trip 주인 검사 8, 이 브랜치 22)을 써서 51을 썼고 99가 남는다.
- `fleet`은 31,837에 +150이다. 기점까지 25, 기점 뒤 24(조각 1의 서버 몫 5, 이 브랜치의 등록부 `step_action_kinds.py` 15와 Cell `cancel` 4)를 써서 49를 썼고 101이 남는다.
- 세 단위(서버·원장·관제)의 판정값 합은 56,755로 D-757 판정과 같다. 합친 한도는 단위마다 +150이라 150 늘어난다. 이 등록은 실패하는 시험을 넘기려는 것이 아니다: 등록 전 `fleet`(서버+원장)은 38,972 한도에 38,922였다. 등록 뒤 서버+원장 한도는 39,122로 150 늘고, 세 단위 합은 56,945, 합친 한도는 57,055에서 57,205가 된다. D-763의 "조각마다 순증 0 또는 날짜 있는 단위 계획"을 따르려는 것이다.

- 서버 단위의 남은 101줄은 다음 D-763 조각이 쓰지 않는다. 다음 조각은 서버 단위에서 순증 0이어야 하고, 등록부(`step_action_kinds.py`)나 Cell 원장의 증가를 그 여유로 받지 않는다.

## 순서

코드 조각(`6bb334d16` 조각 5, `65bea79df` 조각 5b, `65e315231` 보안 검토 반영)은 이 계획보다 먼저 커밋됐다. D-763은 "먼저 새 크기 단위를 등록하는 날짜 있는 계획"을 요구한다. 이 순서는 코드 조각과 이 계획이 한 브랜치로 함께 착지하기 때문에만 받아들여진다. 코드 조각만 따로 착지하거나 cherry-pick하지 않는다.

## 그대로 두는 것

- 모든 안쪽 단위(`fleet/fleet/traffic`, `observe`, `server/channel`과 그 아래, `localization`, `stuck`과 `stuck/submission`, `incidents`와 그 아래, `decision/.../deliberation`·`conversation`과 그 아래, `site_ui/console`)의 기준선과 +150.
- 파일 600·800줄 판정과 1,000줄 HARD_TIER의 증가 0. 원장 파일 판정(`ledger/mission_store.py`, `ledger/task_store.py`, `ledger/trip_runner.py` 등 600줄 위 파일)은 그대로 검사한다.
- `fleet` 판정 문구의 이전 분리 의무(observe/server/UI, D-728 channel, D-757 account, D-763 조각 3 console) 전부. 이 계획은 그 문구 앞에 한 줄을 붙일 뿐 지우지 않는다.
- `ledger/task_dispatch_routes.py`의 safety 태그(D-430)는 그대로다. 단위 등록은 그 파일을 바꾸지 않는다.
- 다음 원장 증가가 +150에 닿으면 수용으로 넘기지 않는다. 그때는 Mission 승인·거절 경로(`mission_routes`의 `decidable`·admit·reject)와 Mission 원장(`mission_store`)을 자기 하위 단위로 낸다.

## 검증

`test/architecture/test_module_structure.py`의 실측(`test_over_budget_code_has_a_recorded_verdict`, `test_size_units_are_real_subpackages_with_a_split_plan`, `test_size_verdicts_are_well_formed_and_current`)을 원격 시험 PC에서 돌린다. SOURCE 구조 증거이며 ROS-SIM·DEVICE·FIELD 수용을 뜻하지 않는다.

판정 상태: 2026-10-14 독립 재판정 ACCEPT WITH CONDITIONS(기준선 재계산 일치). 조건: 위 한도 문장 정정, 센 접미사 명시, `FLEET_SERVER_HOLDER_UNITS` ⊆ `SERVER_HOLDERS` 시험, 코드 조각이 계획보다 먼저 커밋된 순서의 기록, 서버 단위의 다음 조각 순증 0.
