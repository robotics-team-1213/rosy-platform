# Fleet trip 소유자 크기 단위 분리

**날짜:** 2026-10-15
**범위:** D-168/D-753 구조 판정과 파일 여덟 개의 폴더 이동. 동작 변경 없음. 모듈 이름(`fleet.server.trip_*`)은 그대로다. D-763 조각 4(`feat/fleet-work-read-sources`, API v1.237) 브랜치의 변경이다. 선례: `docs/plans/2026-10-15-fleet-ledger-missions-unit.md`(같은 브랜치, Mission 원장과 작업 읽기), `docs/plans/2026-10-14-fleet-ledger-size-unit.md`.

`docs/plans/2026-10-15-fleet-ledger-missions-unit.md` 뒤 원장 판정(4,410, 한도 4,560)은 "다음 +150에서 trip 소유자(`trip_*`)를 자기 단위로 낸다"고 적었다. 조정자의 착지 순서(D-760 4단계 `rosy-84`가 먼저, 다음이 이 브랜치)에서 그 4단계가 `trip_progress.py`에 약 15줄을 더한다. 원장은 지금 4,545로 남은 15줄이라 그 착지로 넘는다. 지금 trip 파일을 고치는 다른 브랜치는 없다(조정자 확인). 그래서 이 브랜치에서 그 분리를 한다.

## 무엇을 단위로 하는가

**trip 루프 `fleet/fleet/server/trips`.** `ledger/`의 trip 파일 여섯을 새 Fleet 서버 보관 자리 `operations/fleet/fleet/server/trips`로 옮긴다: `trip_runner`(루프), `trip_routes`(HTTP), `trip_ports`(CORE·자세 이음), `trip_guard`(주인 검사), `trip_halts`(정지), `trip_laps`(반복 운행 계산).

**trip 검사 `fleet/fleet/server/trip_checks`.** trip 루프의 두 mixin, 시작 검사(`trip_admission`)와 진행 판정(`trip_progress`)을 새 보관 자리 `operations/fleet/fleet/server/trip_checks`로 옮긴다. 둘은 2026-10-10에 `trip_runner`에서 이름 붙여 떼어 낸 것이다(`docs/plans/2026-10-07-fleet-site-map-web-server-seam.md`, `trip_runner.py` 파일 판정이 그 이음을 적는다). `TripRunner(TripAdmission, TripProgress)`가 섞어 쓴다.

**왜 둘인가.** trip 파일 여덟을 한 단위로 하면 판정값 2,510에 지금 2,674라 +150을 14줄 넘는다. 판정 뒤 trip 증가 164줄 가운데 133줄이 두 mixin(시작 검사 +93: D-601·D-603·D-760·D-763 조각 6, 진행 판정 +40: D-760 4 `link_wait`, D-763 조각 2 기다림)에 있다. 그 둘은 이미 이름 붙은 경계다. 그래서 수용이 아니라 이미 있는 경계로 나눈다.

**이동의 모양.** 앞 계획과 같다. 두 폴더를 `fleet/_source_layout.py` `SERVER_HOLDERS`, `tools/harness/platform_parts.yaml`의 `source_packages`(앞 계획의 `missions`·`work`도 이 커밋에서 더한다), `FLEET_SERVER_HOLDER_UNITS`, 배포 시험 holder 목록에 더한다. `__init__.py`를 두지 않는다. 파일 판정 `ledger/trip_runner.py`는 경로만 `trips/trip_runner.py`로 바꾼다. 경로를 적은 곳(`operations/fleet/AGENTS.md`, `fleet/routing/__init__.py`·`execute.py`·`fleet/traffic/__init__.py` 독스트링, `docs/reference/fleet-rulebook.md`, `test_boundaries.py`의 `IDENTITY_NEVER` glob — 두 폴더 모두)을 고친다.

## 기준선

D-757 판정 커밋 `61aa49b32`에서 앞의 계획과 같은 방법(그 커밋의 추적 파일 줄 수)으로 쟀다.

| 파일 | `61aa49b32` | 지금(`rosy-84` 머지 전) |
|---|---|---|
| `trip_runner.py` | 870 | 898 |
| `trip_ports.py` | 600 | 600 |
| `trip_routes.py` | 319 | 319 |
| `trip_laps.py` | 233 | 233 |
| `trip_guard.py` | 135 | 138 |
| `trip_halts.py` | 81 | 81 |
| trip 루프 합 | 2,238 | 2,269 |
| `trip_admission.py` | 192 | 285 |
| `trip_progress.py` | 80 | 120 |
| trip 검사 합 | 272 | 405 |

| 단위 | 판정값 | 지금 | 한도 |
|---|---|---|---|
| `fleet/fleet/server/ledger`(Task 소유자, `action_receipts`, `core_event_store`) | 1,900(= 4,410 − 2,238 − 272) | 1,871 | 2,050 |
| `fleet/fleet/server/trips` | 2,238 | 2,269 | 2,388 |
| `fleet/fleet/server/trip_checks` | 272 | 405 | 422 |

- 어느 단위도 기점에서 다시 잡지 않는다. 판정 뒤 쓴 허용은 쓴 허용으로 남는다.
- **`trip_checks`는 남은 줄이 17이다.** `rosy-84`의 D-760 4단계(`trip_progress.py` 약 +15)가 착지하면 2줄 남는다. 다음 증가는 시작 검사와 진행 판정을 두 단위로 나누는 것부터다(판정 문구).
- 합친 한도는 두 단위만큼 300 늘어난다. 원장 판정의 다음 분리를 미리 하는 것이고 실패하는 시험을 넘기려는 수용이 아니다.

## 그대로 두는 것

- 모든 안쪽 단위와 다른 Fleet 서버 holder 단위(`missions`, `work`)의 기준선과 +150. 서버 단위(`fleet`) 판정과 그 순증 0 규칙.
- 파일 600·800줄 판정과 1,000줄 HARD_TIER의 증가 0. `trip_runner.py`(판정 751, 지금 898, 한도 901)는 그대로 검사한다.
- `ledger` 판정 문구 전부. 앞에 한 줄을 붙일 뿐 지우지 않는다. safety 태그(`ledger/task_dispatch_routes.py`, D-430)는 옮기지 않는다. 옮긴 여덟 파일은 `platform_parts.yaml`의 safety 목록과 safety 루트에 없다(확인).
- 다음 증가가 +150에 닿으면 수용으로 넘기지 않는다. trip 루프는 `trip_ports`를, trip 검사는 시작 검사와 진행 판정을 서로 다른 단위로, 원장은 Task dispatch 경로를 낸다.

## 검증

`test/architecture` 전체(크기 시험 셋, `test_fleet_server_holder_units_are_declared_holders` 포함), 배포 자원 시험(`test/test_remaining_platform_installed.py`), `operations/fleet/test` 전체를 원격 시험 PC에서 돌린다. SOURCE 구조 증거이며 ROS-SIM·DEVICE·FIELD 수용을 뜻하지 않는다.

판정 상태: 독립 재판정 전이다.

## 부기 2026-10-15 — `trip_checks`를 두 단위로 나눈다(feat/regulation-capabilities)

- 왜: 브랜치 `feat/regulation-capabilities`(D-763 10항 (c), API v1.238)가 main `0cf827362`과 병합한 뒤 `trip_checks`는 474줄(`trip_admission.py` 338, `trip_progress.py` 136)로 한도 422(272+150)를 넘었다. main은 421이었다. 늘어난 53줄은 모두 `trip_admission.py`의 D-763 10항 (c)다: `crosswalks_on`, `signals_on`(`traffic` 단위가 자라지 않게 여기 둔다), `_caps_checks`의 규제 능력 검사와 `regulation_caps_unknown` 경고, 운영자 재계획 확인의 `_admit_replan`.
- 무엇: 위 「그대로 두는 것」이 정한 대로 수용하지 않고 나눈다. `trip_progress.py`를 바이트 그대로 새 보관 자리 `operations/fleet/fleet/server/trip_progress/`로 옮기고 `SERVER_HOLDERS`, `platform_parts.yaml`, `FLEET_SERVER_HOLDER_UNITS`, `SIZE_UNITS`, 배포 자원 시험, 신원 경계 시험의 glob에 더한다. import(`fleet.server.trip_progress`)는 그대로다. `trip_checks`는 시작 검사 `trip_admission.py` 하나만 갖는다.
- 기준선(D-757 판정 커밋 `61aa49b32`에서 잼, 다시 잡지 않음): `trip_checks` 192(지금 338, 한도 342), `trip_progress` 80(지금 136, 한도 230).
- 다음 증가: `trip_checks`는 규제 검사(`crosswalks_on`, `signals_on`, 10항 (c) 검사)를 자기 단위로, `trip_progress`는 기다림 판정(`_waiting`, `_wait_bound`)을 자기 단위로 낸다. 수용으로 넘기지 않는다.
- 판정 상태: 독립 재판정 전이다.
