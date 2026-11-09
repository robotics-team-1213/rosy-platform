# OMX 팔 셀 식별자 전환 — CELL-A/cell-a → ARM-CELL/arm-cell

- **결정:** 2026-11-10 사용자 결정. 팔 셀(OMX 셀 관제) 식별자를 `CELL-A`/`cell-a`에서 `arm-cell`로 바꾼다. PC 이름은 이미 `rosy-arm-cell`이다.
- **새 id:** 관제 단위 id는 **`ARM-CELL`**(기존 관례: 단위 id는 대문자 `R`, `CELL-A`, [D-974](../adr/D-974-control-vocabulary-layers.md) 어휘 참조). 호스트 런타임 이름(Compose project, `/etc/rosy` 디렉터리, 볼륨, peer alias, token 파일명)은 소문자 **`arm-cell`**. 이 문서의 나머지 규칙 [D-1011](../adr/D-1011-arm-cell-identifier-rename.md)이 정본이다.
- **전환 중 단절 금지:** 입력(요청·peer 설정·DB 조회·service principal)에는旧 `CELL-A` 별칭을 계속 받아들이고, 출력·저장은 새 id만 한다. DB 행은 감사 행과 함께 한 번만 재작성하는 멱등 마이그레이션으로 옮긴다.

## 1. 재고 (2026-11-10, `main` 기준 grep `CELL-A`/`cell-a`/`cell_a`/`CELL_A` 대소문자 구분)

"cell-a"가 **팔 셀 식별자**를 뜻하는 곳만 바꾼다. `cell_a`/`cell_b`가 **팔 A/B 각각**(arm-level)을 뜻하는 곳은 그대로 둔다.

### 1.1 런타임 이름 (호스트, repo 밖 private 설정 — 전환 대상)

| 이름 | 현재 | 새 |
|---|---|---|
| Compose project (dev 이미지, D-960) | `cell-a` | `arm-cell` |
| 호스트 설정 디렉터리 | `/etc/rosy/cell-a` | `/etc/rosy/arm-cell` (기존 경로는 symlink 유지) |
| Docker volume | `cell-a_cell_a_data` | `arm-cell_arm_cell_data` (데이터 복사·검증) |
| peer TLS 이름/alias (R의 peers url) | `peer-cell-a` | `peer-arm-cell` |
| 송신 service token 파일 (R 측) | `secrets/r-to-cell-a.token` | `secrets/r-to-arm-cell.token` |
| 수신 service principal (users 파일) | `control-unit:CELL-A` | `control-unit:ARM-CELL` |

소스 코드는 이 id들을 하드코드하지 않는다. `unit_id`·`manifest`·`peers`는 모두 `control-unit.yaml`(private)에서 오고, 코드(`control_unit_config.py`·`control_unit_runtime.py`)는 검증만 한다. 그래서 코드 변경은 **입력 별칭 수용 + DB 마이그레이션**이 중심이다.

### 1.2 도메인 id — Fleet 코드·시험

| 위치 | 형태 | 처리 |
|---|---|---|
| `contracts/foundation/test/test_control_unit_protocol.py` (2) | `target_unit`/`owner_unit: CELL-A` | 기대값 `ARM-CELL`로 |
| `operations/fleet/test/test_control_unit_arm_delegation.py` (30) | manifest id·owner·peer | 〃 |
| `operations/fleet/test/test_control_unit_arm_http_pipeline.py` (20) | 〃 + `peer-CELL-A` principal | 〃 |
| `operations/fleet/test/test_control_unit_arm_admission.py` (22) | manifest id·owner | 〃 |
| `operations/fleet/test/test_control_unit_arm_app_wiring.py` (4) | 〃 | 〃 |
| `operations/fleet/test/test_control_unit_browser.py` (7) | unit_id·owner | 〃 |
| `operations/fleet/test/test_physical_transfer_store.py` (3) | `ControlUnitStore(unit_id="CELL-A")` | 〃 |
| `operations/fleet/test/web/fleet-header.test.mjs` (2) | 헤더 `unit: CELL-A` | 〃 |
| `operations/fleet/test/test_dispatch_stop_latch.py` (3), `test_dispatch_admission.py` (2) | workcell fixture `("workcell", "cell-a")` | 기대값 `arm-cell`로 |
| `operations/fleet/fleet/server/ledger/control_unit_*.py` | 하드코드 없음(설정 기반) | 별칭 수용 추가(§2) |
| DB 스키마/행 | `fleet_control_unit_identity.unit_id`, `fleet_control_delegations.origin_id/owner_unit`, `fleet_control_stops.unit_id/target_unit`, `fleet_control_stop_deliveries.delivery_unit`, 각 `*_json` 내 unit id | 멱등 마이그레이션 + 감사 행 |

### 1.3 유지 (팔 셀 식별자가 아님)

| 위치 | 이유 |
|---|---|
| `test/test_omx_hardware_owner.py`, `operations/fleet/test/test_cli_omx_instances.py`의 `omx_cell_a`/`omx_cell_a_01`(+ `_b`) | 팔 A/B 각각의 workcell/instance id(D-785 `ROSY_FLEET_OMX_INSTANCES` 형식 예). 셀 단위 id가 아니다 |
| `test/test_omx_hardware_readiness.py`의 `/cell_a`, `/cell_b` namespace | 팔 A/B ROS namespace |
| `deploy/robot/omx/cell_two_arm.py`, `cell_coordinate.py` docstring의 `cell-a.json`/`cell-b.json` | 팔 A/B 설정 파일 예시 |
| `docs/adr/D-960`·`D-965`·`D-974`, `docs/plans/2026-10-29-*`, `2026-10-23-*`, `docs/logs.md`, `deploy/logs.md` | 날짜가 붙은 역사 기록(append-only). 새 ADR이 전환을 기록 |
| `CONCEPTS.md` "셀 관제 CELL-x" | 일반 어휘(D-974) |
| `applications/fleet/web/shared/fleet-header.js` 주석의 "R and CELL-A share one host" | 예시 문구 → 새 id로 갱신 |

### 1.4 문서 (현재 기준 문서만 갱신)

- `docs/deployment/control-units.md` (3 `CELL-A` + `peer-cell-a`/`r-to-cell-a.token` 예시, 22/27/109–117행): 단위표·peers 예시를 `ARM-CELL`/`peer-arm-cell`로 갱신. 160행 "DB를 새 unit ID에 재사용하지 않는다"는 이번 전환의 감사 마이그레이션 예외를 ADR로 링크.
- API reference·SRS: `CELL-A` 없음(단위 id는 데이터). 경로·enum 변경 없음 → API 버전 올림 없음.

## 2. 코드 변경 (이 브랜치)

1. `control_unit_config.py`: `UNIT_IDENTIFIER_ALIASES = {"CELL-A": "ARM-CELL"}` + `canonical_unit_id()`. `ControlUnitTopology.unit()`이 별칭을 정규화해 모든 범위 검사(`next_hop`·`child` 포함)가旧 id를 받아들인다.
2. `control_unit_runtime.py` `load_control_unit`: peers key를 정규화(구형 `peers.CELL-A` key 허용, 이중 정의 거절 유지). `install_control_unit`: 이웃 service principal 검사가 `control-unit:CELL-A`/`control-unit:ARM-CELL` 둘 다 허용.
3. `control_unit_routes.py` `peer_id`, `control_unit_stop_routes.py` `parent`, `control_unit_information_routes.py` `reader`: service principal의 단위 이름 정규화 — 이것이 "control-unit hello"(첫 접속이 매 요청에 싣는 신원)의 별칭 수용이다.
4. `control_unit_stops.py`: 정지 ingress의 `target_unit`·`expected_controls` key 정규화. `config_revision` 검사는 그대로(양쪽 설정을 같은 보수 창구에 갱신).
5. `control_unit_store.py`: `ControlUnitStore.__init__`에서 identity 충돌 검사 **전에** 멱등 마이그레이션. unit-id 열 정확값 재작성 + `*_json` 내 정확히 일치하는 값만 재작성(부분문자열 아님) + `fleet_control_unit_identifier_events` 감사 행(재적용 시 중복 없음).
6. 시험: 위 1.2 표의 기대값 교체(단정 약화 없음) + 신규 `test_control_unit_identifier_rename.py`(별칭 해석·peers 별칭·마이그레이션 멱등성).
7. ADR 1건(번호 선점) + Log 행 같은 커밋, `rosy_harness.py lint`.

## 3. 호스트 전환 (Stage A 스크립트, 실행하지 않는다)

`tools/ops/rename_arm_cell_runtime.sh` — 셀 호스트에서 dry-run 기본, `--apply`일 때만 변경. 팔 세션/작업/motor torque 확인 후 백업 → 볼륨 복사·sha256 검증 → `/etc/rosy/arm-cell` 생성(구 경로 symlink) → Compose project `arm-cell`로 재기동 → 건강 확인 → 롤백 안내 출력. R 측(관제 PC)의 `control-unit.yaml` 갱신(peers key·manifest revision)은 같은 보수 창구에 사람이 한다.

## 4. 완료 기준

- 원격 시험(변경 파일 + 영향 수입 파일) `known_failures.py` 0 NEW.
- `size_range.py main HEAD` 초록.
- 위 1.1 표의 호스트 항목은 스크립트 dry-run 출력으로만 확인(이 브랜치에서 실호스트 조작 없음).
