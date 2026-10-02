# ROSY 플랫폼 v0.2 단계적 이전 실행 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 기존 Cell·Fleet·OMX 코드를 활용해 AI 없는 고정 셀 한 작업 흐름을 새 책임 경계로 연결하고, 기존 진입점·최소 설치·중단 복구를 검증한다.

**Architecture:** [D-413](../adr/D-413-platform-modules-integrations-apps-profiles.md)의 modules·integrations·apps·profiles 분리를 따른다. 사이트 Mission 원장과 장치 Action 원장을 유지하며 공정 → 계획 → Fleet grant → 로컬 Skill → owner → 증거의 경계를 단계별로 추출한다. 아직 옮기지 않은 패키지는 기존 경로와 계약을 유지한다.

**Tech Stack:** Python, 기존 FastAPI·SQLite·Pydantic, ROS 2 Jazzy, colcon/ament, namespace wheel, OMX Gazebo, 기존 pytest·harness. 새 빌드 도구·모델 SDK 도입은 이 계획의 전제가 아니다.

**Status:** Tasks 0-4 complete; Task 5 in progress (the ROS-free Skill boundary and receipt extraction are committed; the OMX provider binding is implemented and under checkpoint verification). Tasks 6-9 not run. PASS conditions below are instructions and do not imply unfinished tasks passed.

**설계:** [ROSY Platform Architecture v0.2](../reference/ROSY_Platform_Architecture_Design_v0.2.md) 3·5·6·15·16장.

## 범위와 기존 작업의 관계

작성 기준은 main `746a1984`와 설계 v0.2다. 구현 시작 시 main과 각 모듈 progress를 다시 확인한다. 현재 존재하는 `rosy_cell` 컴파일러, OMX `pose_plan.py`·`kinematics.py`·phase runner, Fleet Mission/dispatch 코드를 재사용한다. 과거 Cell 계획의 “IK 구현 없음” 같은 당시 조사 문구를 현재 사실로 재사용하지 않는다.

- [Cell 완성 계획 C1~C6](2026-10-01-rosy-cell-completion.md)의 C2 플래너, C3 물체/그리퍼 Gazebo, C4 Fleet Cell 경로는 의존 작업이다. 동일 기능을 다시 만들지 않고 Task 0에서 착지 여부와 남은 항목을 대응시킨다.
- D-403의 `CELL_TRANSFER`는 pick+place 한 쌍이고 `pallet_done`은 사이트 원장 표지다. 내부 PlanBundle을 도입해도 별도 PICK/PLACE API를 만들지 않는다.
- D-336의 같은 호스트 UDS, D-330/D-403의 시뮬레이션 하달 개방 조건, D-392의 모델 제안 경계를 유지한다.
- 첫 수용은 Gazebo의 2층·슬립시트 1장·팔레트 2개와 중단 복구다. 실물 배포, Pinky 인계, AI 자율 재발의, 학습 정책, 전체 플랫폼 소스 이동은 후속 범위다.
- C5의 새 Cell 서버·UI를 이 계획에서 중복 생성하지 않는다. 기존 사이트 앱 조합에 필요한 공정 진입점을 연결한다. UI 변경이 필요해지면 화면·인증·브라우저 수용을 별도 하위 계획으로 구체화한다.

## 작업 규칙과 증거

구현은 `.claude/skills/rosy-land-on-main/SKILL.md`와 `writing-plans`/`executing-plans` 절차를 따른다. 첫 구현 브랜치의 권장 이름은 `refactor/platform-cell-slice`, worktree는 `.worktrees/platform-cell`이다. 이 계획을 작성한 문서 브랜치는 `docs/platform-architecture-v02`다. 다른 세션의 Cell·OMX 작업을 덮어쓰지 않는다.

아래 **Create**는 앞으로 만들 파일이다. 기존 경로는 **Modify/Reuse**로 표시했다. task 완료 시 관련 파일만 커밋하고, 해당 모듈 logs/progress를 실제 결과에 맞춰 갱신한다. 상태가 바뀌지 않았으면 gate를 올리지 않는다.

새 wheel을 소비하는 import를 바꾸는 커밋에는 `.github/workflows/ci.yml`의 설치 단계도 함께 포함한다. CI는 현재 `src`만 colcon으로 빌드하므로 루트의 `modules`·`integrations`는 자동 설치되지 않는다. Task 2부터 해당 CI job의 Python으로 wheel을 빌드·설치하고, Task 3·5·6에서 추가하는 패키지를 같은 커밋의 명시적 설치 목록에 넣는다. 이 단계는 colcon 빌드와 모든 소비자 pytest보다 앞에 둔다. ROS job에서는 Jazzy와 호환되는 동일 Python을 사용한다.

시험의 임시 파일·로그·wheel·설치 환경·영상은 `X:\DevTemp\rosy-platform-v02\` 아래에 둔다. Linux/WSL에서는 이 X: 경로의 마운트를 확인해 사용한다. `ROSY_SCRATCH`가 저장소 밖 X:를 가리키도록 설정한 뒤 아래 명령을 실행한다. Python bytecode와 pytest cache도 저장소에 만들지 않는다.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:ROSY_SCRATCH = 'X:\DevTemp\rosy-platform-v02'
New-Item -ItemType Directory -Force -Path $env:ROSY_SCRATCH | Out-Null
$env:TEMP = $env:ROSY_SCRATCH
$env:TMP = $env:ROSY_SCRATCH
```

각 코드 task의 반복은 **거부/오류 사례를 포함한 시험 작성 → 의도한 실패 확인 → 최소 구현 → 관련 회귀 확인 → 제한된 파일 커밋**이다. 기존 동작을 보호하는 구조 가드는 잘못된 import·변환·설치 누락을 실제로 주입해 실패를 확인한다. 문서만 바꾸는 task에 구현을 따라 쓰는 새 테스트를 추가하지 않는다.

## 순서와 출구

```text
Task 0 기준선 → 1 구조·설치 경계 → 2 최소 API → 3 공정 추출
    → 4 Fleet 연결 → 5 로컬 Skill 연결 → 6 앱·설치
    → 7 오류·복구 재생 → 8 Gazebo 종단 → 9 호환층 정리
```

| 단계 | 출구 | 증거 등급 |
|---|---|---|
| 0~1 | 기존 실패·소유권·설치 집합 고정, 단계별 import/설치 검사 | SOURCE/LOCAL 준비 |
| 2~5 | 변환·권한·phase·원장의 양 끝 시험, 기존 동작 회귀 없음 | SOURCE/LOCAL |
| 6~7 | 저장소 없는 설치 실행, 최소 의존성, 재시작·UNKNOWN 재생 | LOCAL. 배포 가능한 ARTIFACT는 별도 |
| 8 | formal Fleet-to-UDS-to-vendor Gazebo plus independent object/gripper evidence | fixed-cell ROS-SIM |
| 9 | remove only compatibility paths with migrated callers and install evidence | migration scope complete |

## Task 0: 현재 코드와 진행 중 작업의 기준선

**Reuse:** `STATUS.md`, `src/site/cell/progress.md`, `src/site/fleet/progress.md`, `src/products/omx/adapter/progress.md`, 기존 C1~C6 계획·증거, `test/known_failures.py`.

**Create:** `docs/validation/platform-architecture-v02-2026-10-02/README.md`, `docs/validation/platform-architecture-v02-2026-10-02/ownership.csv`. 날짜는 이 계획의 증거 묶음 ID이며 각 실행의 실제 날짜·커밋은 내부에 별도로 기록한다.

1. `git status`, HEAD, worktree/브랜치 목록에서 Cell C3/C4와 owner 관련 변경을 확인한다. M0 기록에 “main에 있음 / 타 브랜치에 있음 / 없음”을 구분한다.
2. 각 이관 대상의 `source_path, responsibility, owner, callers, entrypoint, wire_contract, installed_by, target_path, rollback`을 작성한다. 공유 schema는 타입 단위로 나눈다.
3. 기존 Cell, Fleet, OMX, 구조 suite를 아래처럼 **별도 실행**해 기준선을 남긴다. 로그를 `ROSY_SCRATCH`에 저장하고 알려진 실패와 새 실패를 비교한다.

```text
python -B -X utf8 -m pytest src/site/cell/test -q -p no:cacheprovider
python -B -X utf8 -m pytest src/site/fleet/test -q -p no:cacheprovider
python -B -X utf8 -m pytest src/products/omx/adapter/test -q -p no:cacheprovider
python -B -X utf8 -m pytest test/architecture -q -p no:cacheprovider
python -B -X utf8 test/known_failures.py <ROSY_SCRATCH의 해당 실행 로그>
```

**출구:** 기존 실패와 새 실패를 구별할 수 있고, D-402 플래너·D-403 경로의 남은 작업 및 담당 경로가 명시됨. 코드 이동 없음. 커밋: `docs: capture platform migration baseline`.

**완료 증거 (2026-10-02):** [Task 0 기준선](../validation/platform-architecture-v02-2026-10-02/README.md), [소유권 표](../validation/platform-architecture-v02-2026-10-02/ownership.csv). Cell 143 passed; Fleet 1336 passed/7 skipped; OMX 268 passed/5 skipped; architecture 76 passed/1 skipped. 네 suite의 known-failure 판정은 각각 0 new, 0 known. D-402 해석 IK는 main에 있고, C3 시뮬레이션 작업은 `feat/rosy-cell-c3-gazebo`에 남아 있으며, Fleet Cell ordered transfer 경로는 Task 4의 잔여 구현으로 남긴다. 이 완료는 SOURCE 기준선만 뜻한다.

## Task 1: 새 책임 경로와 설치 검사의 허용 범위

**검토 후 필요한 경우에만 수정:** `test/architecture/test_target_layout.py`, `test/architecture/test_folder_layout.py`, `test/architecture/test_folder_package_names.py`, `test/architecture/test_module_structure.py`, `tools/harness/harness.yaml`. 기존 `src` ROS package 목록은 이 task에서 달라지지 않아 exact-layout 예외나 새 harness module은 추가하지 않는다.

**Create:** `test/architecture/test_platform_dependency_boundaries.py`, `tools/harness/platform_dependencies.yaml`.

1. 현재 실제 존재하는 `core_common`·`rosy_cell`·`fleet`·`omx_adapter`만 패키지 표에 등록하고 기존 colcon 경로와 함께 검사한다. 아직 만들지 않은 플랫폼 package path는 등록하지 않는다.
2. execution→공정, decision→장치 SDK, Skill→execution의 금지 import를 절대/상대 fixture로 주입해 실패를 확인한다. 경로 이름만 확인하는 검사를 통과 기준으로 삼지 않는다.
3. 정적 import와 배포 의존성의 차이를 검사할 수 있게 현재 존재하는 경로/소유 package 표와 독립 간선 정책을 추가한다. 새 package가 실제 생성될 때 그 같은 변경에서 경로를 등록한다.
4. 기존 exact-layout 검사는 실제로 전환하는 항목만 좁게 고친다. 모든 루트·모든 패키지를 허용하는 예외를 만들지 않는다.

**검증:** `python -B -X utf8 -m pytest test/architecture -q -p no:cacheprovider`. 기대: 기준선 대비 NEW 0, 잘못된 의존 주입 시 새 가드 실패. 커밋: `test: enforce incremental platform boundaries`.

**완료 증거 (2026-10-02):** [platform dependency guard](../../test/architecture/test_platform_dependency_boundaries.py)와 `tools/harness/platform_dependencies.yaml`은 현재 네 Python root만 등록하고 future roots는 canary import fixture로만 확인한다. absolute·relative import prefix 우회도 잡는다. 전체 architecture suite 81 passed/1 skipped, commit 전 quick tier 95 passed/24 warnings, known-failure 비교 0 new, harness lint 0 errors/24 기존 progress warnings. 새 ROS package/root나 `harness.yaml` module은 만들지 않았다.

## Task 2: 첫 작업에 필요한 API와 호환 매핑

**Create:**

- `modules/world/pyproject.toml`, `modules/world/src/rosy/world/api/observation.py`
- `modules/skills/api/pyproject.toml`, `modules/skills/api/src/rosy/skills/api/contracts.py`
- `modules/execution/pyproject.toml`, `modules/execution/src/rosy/execution/api/plan.py`
- `test/test_platform_contract_mapping.py`

**Also modify:** `tools/harness/platform_dependencies.yaml` and `test/architecture/test_platform_dependency_boundaries.py` to register only the three newly created API roots, pin their import prefixes, and exercise their forbidden edges. A created package must enter this guard in the same commit as its first consumer.

**Reuse:** `src/contracts/foundation/core_common/protocol/schemas.py`, `src/site/cell/rosy_cell/compiler.py`, `src/site/fleet/fleet/server/mission_dispatcher.py`.

**Modify:** `.github/workflows/ci.yml` — 새 패키지를 사용하는 job의 wheel 빌드·설치 단계.

1. 첫 고정 셀에서 실제 사용하는 필드와 기존 타입의 대응표를 작성한다. 아래 항목 중 소비자가 없는 선택 필드는 만들지 않는다.
2. 관측 계약은 출처·캡처/수신 시각·좌표계·보정 revision·근거 참조·유효성을 표현한다. Skill 계약은 ID/버전·입력·전제/완료조건·자원·취소·결과 증거를 표현한다.
3. 계획 계약은 공정 artifact digest, recipe/cell 해시, 순서 있는 Skill 단계와 검증 참조를 표현한다. 승인·principal·authority epoch는 신뢰된 실행 경계가 부여하며 모델/공정 입력으로 받지 않는다.
4. 기존 Job의 recipe/cell hash, Observation evidence의 ns/frame/revision, grant/receipt의 ID·generation·revision·기존 `PICK_PLACE` request digest가 그대로 매핑되는지 시험한다. 잘못된 출처 hash·알 수 없는 계약 버전·형식이 깨진 단위/ID·변조 digest는 거부한다. 일반 PlanBundle은 Skill 입력을 재해석하지 않으며, 도메인 단위 검증은 Task 3/5의 process·Skill schema가 소유한다.
5. 최소 타입과 변환을 구현한다. 이 task는 내부 계약이며 기존 wire 타입의 정본은 유지한다. 불가피한 wire 변경은 Task 4의 D-18 동시 변경으로 넘긴다.
6. 공유 namespace 부모에는 `__init__.py`를 두지 않고 소유 하위 패키지에만 둔다. wheel 소유 범위를 명시한다. execution 배포물은 첫 API/필요 규칙만 포함하고 FastAPI·ROS·모델 SDK에 의존하지 않는다.
7. 위 세 패키지의 정확한 소스 경로를 CI 설치 목록에 등록한다. `python -m pip wheel --wheel-dir <외부 scratch>/wheels <패키지 경로들>`로 선언된 의존성과 함께 빌드한 뒤, 생성된 wheel 파일을 `python -m pip install --no-index --find-links <외부 scratch>/wheels <생성된 wheel 파일들>`로 설치한다. 버전과 의존성은 기존 잠금 정책에 맞춰 고정한다. CI의 임시 경로는 runner 외부 scratch를 사용하고 로컬 Windows/WSL 검증은 X:를 사용한다. editable 설치나 저장소 루트를 PYTHONPATH에 넣어 설치 누락을 숨기지 않는다.

   Windows에서는 setuptools가 source directory 아래 `build/`를 만들므로 로컬 패키지 세 디렉터리를 먼저 `ROSY_SCRATCH/sources/`로 복사하고 그 복사본으로 wheel을 만든다. 임시 venv도 `ROSY_SCRATCH/`에 만든다. 저장소 경로를 `PYTHONPATH`에 추가하지 않고 venv의 Python으로 아래 시험을 실행한다. CI는 버려지는 Linux runner의 `/tmp/rosy-platform-wheelhouse`를 사용한다.

```powershell
$wheelSource = Join-Path $env:ROSY_SCRATCH 'task2-sources'
$wheelhouse = Join-Path $env:ROSY_SCRATCH 'task2-wheels'
$venv = Join-Path $env:ROSY_SCRATCH 'task2-venv'
New-Item -ItemType Directory -Force -Path $wheelSource,$wheelhouse | Out-Null
Copy-Item modules/world (Join-Path $wheelSource 'world') -Recurse
Copy-Item modules/skills/api (Join-Path $wheelSource 'skill-api') -Recurse
Copy-Item modules/execution (Join-Path $wheelSource 'execution') -Recurse
python -B -m pip wheel --no-deps --wheel-dir $wheelhouse `
  (Join-Path $wheelSource 'world') (Join-Path $wheelSource 'skill-api') (Join-Path $wheelSource 'execution')
python -B -m venv --system-site-packages $venv
& (Join-Path $venv 'Scripts/python.exe') -B -m pip install --no-index --find-links $wheelhouse `
  rosy-world==0.1.0 rosy-skill-api==0.1.0 rosy-execution==0.1.0
```

**검증:** 새 파일 설치 후 `python -B -X utf8 -m pytest test/test_platform_contract_mapping.py src/runtime/gateway/test/test_protocol_schemas.py -q -p no:cacheprovider`. 기대: 변환 round-trip과 거부 사례 PASS, 기존 wire/digest 불변. 커밋: `feat: define minimal platform work contracts`.

**완료 증거 (2026-10-02):** 세 wheel을 X: 아래 임시 source copy에서 빌드하고 fresh venv에 설치했다. import 경로가 세 wheel 모두 venv의 `site-packages`였고 smoke에서 `rclpy`/FastAPI 로드가 없었다. 매핑·경계·기존 protocol 시험 29 passed; 전체 architecture 81 passed/1 skipped; commit 전 quick tier 95 passed/24 warnings; known-failure 비교 0 new. CI에 동일 세 wheel 빌드/로컬 find-links 설치를 colcon 앞에 추가했다. `D-18` schema 및 protocol version은 변경하지 않았고, `CELL_TRANSFER`를 기존 grant schema에 넣지 않았다. 출처 Job의 개별 Step→Skill 의미 변환과 이동 단위 규칙은 Task 3/5에 남아 있다.

## Task 3: Cell 공정 추출과 계획 생성

**Modify/Reuse:** `src/site/cell/setup.py`, `src/site/cell/package.xml`, `src/site/cell/rosy_cell/{cell,compiler,fields,geometry,load,pattern,recipe,sequence,stack}.py`, 기존 `src/site/cell/test`, `.github/workflows/ci.yml`.

**Create:** `modules/processes/palletizing/pyproject.toml`, `modules/processes/palletizing/src/rosy/processes/palletizing/` 아래 위 동명 구현 파일 및 `plan_bundle.py`, `test/test_platform_palletizing_compat.py`.

**Also modify:** `tools/harness/platform_dependencies.yaml` and `test/architecture/test_platform_dependency_boundaries.py` in this commit so the newly created process root is scanned immediately.

1. 동일 recipe/cell fixture로 기존 Job·carry_z·해시·Step 순서를 기준값으로 잡는다. 새 네임스페이스와 기존 import가 같은 구현/타입으로 이어져야 한다.
2. 공정 계산을 새 모듈로 옮기고 기존 `rosy_cell`은 필요한 재수출·진입점 위임만 남긴다. 두 컴파일러를 유지하지 않는다.
3. pick/place 쌍을 하나의 transfer 단계로 연결하고 `pallet_done`을 원장 표지로 보존한다. 실행 plan은 Skill 버전과 recipe/cell digest를 포함한다.
4. 변조한 Step·carry_z·해시, 짝이 없는 pick/place를 거부한다. Fleet 재컴파일은 주입된 이 컴파일러를 호출하고 알고리즘을 복제하지 않는다.
5. palletizing wheel을 Task 2의 CI 빌드·설치 목록에 추가하고 기존 Cell/Fleet 소비자보다 먼저 설치한다. 기존 `rosy_cell`만 설치한 환경에서 새 의존 누락이 드러나는지 확인한 뒤 정식 설치 경로로 회복시킨다. 이 커밋부터 기존 Cell suite가 CI의 설치된 wheel을 실제로 사용해야 한다.

**검증:** 새 호환 시험과 기존 Cell suite를 별도 실행한다. 기대: 출력·오류 의미가 기준선과 같고 ROS/OMX import 없음. 커밋: `refactor: extract palletizing process with legacy imports`.

**Task 3 completion evidence (2026-10-02, `9da93450`):** Recipe/Cell/Job calculations now have one implementation in `modules/processes/palletizing`; existing `rosy_cell` imports re-export the same types and functions. Each pick/place pair maps to one versioned `pallet.transfer` Skill step, while `pallet_done` remains ordered site-ledger metadata. Mapping recompiles the Job from the supplied Recipe/Cell and rejects changed steps, carry height, or source hashes. See palletizing and Cell progress/logs.

**Validation:** Built and installed the actual wheel in an isolated X: venv. Wheel compatibility 11 passed, legacy Cell suite 143 passed, API mapping 7 passed, architecture 81 passed/1 skipped, known-failure comparison 0 new/0 known; final quick tier 95 passed/24 existing warnings and 0 new known failures. Confirmed legacy import failure without the wheel and recovery after installation. CI YAML parsed; remote CI and ROS/Gazebo were not run. D-18 wire schemas and Fleet dispatch remain unchanged.

**Latest-main follow-up (`cc76161f5`, merged as `d9e70f71`):** After `184185f92` exposed the Fleet size-verdict budget mismatch on clean main, main updated that verdict allowance. The unfiltered architecture suite now passes 81/1 skipped and the quick tier passes 95 with 24 existing warnings; both known-failure comparisons report 0 new/0 known. This resolves the prior latest-main test boundary without changing Fleet implementation in this migration.

## Task 4: Fleet 접수와 순서 있는 작업 원장

**진행 기록 (2026-10-02):** 실행 계층에 process compiler port 기반 Cell Job 재컴파일·PlanBundle 검증 경계를 추가했다. `PICK_PLACE` wire는 고정한 채 `FleetCellTransferGrant` schema를 별도 합집합으로 정의하고 API Reference v1.78에 기록했다. 다음 구현은 service principal 제안/별도 운영자 승인, SQLite ordered-step migration, 독립 목표 증거와 dispatcher 연결이다. 현재 변경은 아직 Fleet endpoint나 장치 하달을 열지 않는다.

**Modify/Reuse:** `src/site/fleet/fleet/server/{app,mission_routes,mission_service,mission_store,mission_dispatcher,proposal_store,goal_evidence}.py`, `src/contracts/foundation/core_common/protocol/schemas.py`, `docs/reference/ROSY API & Protocol Reference.md`.

**Create:** `modules/execution/src/rosy/execution/site/cell_submission.py`, `src/site/fleet/test/test_platform_cell_job_route.py`, `src/site/fleet/test/test_platform_cell_job_recovery.py`.

1. D-403 C4 착지 여부를 확인하고 누락된 부분만 구현한다. Cell service principal의 제안과 이름 있는 운영자의 승인을 구분한다. 동일 운영자 credential을 Cell 컴파일러에 주입하지 않는다.
2. 앱 조합이 공정 컴파일러를 주입한다. 실행 모듈은 컴파일러 포트와 PlanBundle API만 소비하고 palletizing 구현을 import하지 않는다.
3. 순서 있는 Step와 grant/attempt를 영속화한다. 기존 단일 `PICK_PLACE` 데이터의 migration fixture를 먼저 시험한다. 새 CHECK/테이블은 버전 있는 migration으로 적용한다.
4. Step k는 k−1의 독립 목표 확인 뒤에만 제출한다. 바뀐 generation·만료·중복 digest·재시작 후 제출 결과 불명을 거부/UNKNOWN 처리한다.
5. 공개 envelope 또는 endpoint 의미를 바꾸면 API Reference·schema·생산자/소비자 시험을 같은 커밋에서 고친다. PlanBundle 전체를 기존 wire에 무조건 노출하지 않는다.

**검증:** 새 2개 시험과 기존 `test_mission_store.py`, `test_mission_service.py`, `test_mission_dispatcher.py`, `test_mission_api.py`, `test_fleet_omx_action_phase_contract.py` 실행. 기대: 기존 PICK_PLACE 호환, 권한 분리, 다음 Step 선행 실행 없음, 불명 결과 자동 재제출 없음. 커밋: `feat: connect cell plans to fleet admission and steps`.

### Task 4 ?? ????? (2026-10-02)

Cell compiler port, additive `CELL_TRANSFER` ??, `service` ???? ?? operator ?? ??, ??? ?? SQLite ordered-step ??? ????. ??? ?? `PICK_PLACE` Mission ???? ???? ???, ???? ????fence ?????? ??? ?? ?? HOLD? ???. Action ??? ???? ??/??? ?? ??? ?? ?? ?? ??? ????, ?? ?? ? ?? Step? ?? ??? ???? ???.

?? ??? SOURCE/LOCAL ?? ????. Cell Job ???? ?? ??? ?? API??, ??? ?? producer?Fleet dispatcher?UDS/OMX Action???? reconciliation? ?? ???? ???. ??? Task 4? ?? ??? ?? ???? fixed-cell ROS-SIM ??? ??? ???. ?? Fleet ? ??/?? ?? ??? ?? ??? ??? Fleet progress? ????. Task 5?? manipulation Skill/OMX owner? ????, Task 7?? persisted interruption recovery? ??? ? Task 8? Gazebo ?? ??? ????.

## Task 5: 조작 Skill과 OMX owner 연결

**Modify/Reuse:** `src/products/omx/adapter/omx_adapter/{action_api,action_runner,action_store,command_owner,pick_place_runner,pose_plan,kinematics,ros_runtime,gripper_contract}.py`, `.github/workflows/ci.yml`.

**Create:** `modules/skills/manipulation/pyproject.toml`, `modules/skills/manipulation/src/rosy/skills/manipulation/transfer.py`, `modules/execution/src/rosy/execution/local/receipts.py`, `integrations/robots/omx/pyproject.toml`, `integrations/robots/omx/src/rosy/integrations/robots/omx/transfer_provider.py`, `test/test_platform_transfer_owner_boundary.py`.

1. 기존 phase runner와 owner에서 실행 순서·권한·장치 의존을 분리한다. `transfer.py`는 계획기·phase 실행 포트, 전제조건·완료 근거를 소비한다. OMX provider는 기존 해석 IK·gripper·ROS runtime에 연결한다.
2. 기존 ActionStore의 저장과 최종 제출 순서를 보존한다. 단순한 코드 위치 변경을 이유로 DB 스키마나 attempt ID를 새로 만들지 않는다.
3. generation 변경, 늦은 ACK, phase 취소, 오래된 joint state, 시작 오차 초과, gripper 근거 없음에서 HOLD/UNKNOWN과 exact cancel이 유지되는지 먼저 시험한다.
4. 공유 가능한 receipt 연결 규칙만 execution/local로 추출한다. 최종 owner와 제품별 한계는 제품 runtime에 남긴다. 초기 wrapper는 한 방향으로 새 Skill을 호출하며 Skill이 legacy runner를 다시 호출하는 순환을 만들지 않는다.
5. manipulation·OMX integration wheel을 CI 설치 목록에 추가해 소비자 시험 전에 설치한다. ROS 없는 계약 시험에는 ROS 실행 의존성이 유입되지 않도록 선택 의존성을 구분한다.

**검증:** 새 owner 경계 시험과 기존 OMX `test_omx_command_owner.py`, `test_omx_action_store.py`, `test_omx_pick_place_runner.py`, `test_omx_cell_transfer_runner.py`, `test_omx_pose_plan.py`를 실행한다. 기대: ROS를 직접 호출하는 Skill 없음, 중복 writer/attempt 없음, 거부 및 phase 결과 의미 보존. 커밋: `refactor: separate transfer skill from omx ownership`.

**Progress (2026-10-02):** Added `integrations/robots/omx` as the explicit provider seam. It projects a validated `FleetCellTransferGrant` into `pallet.transfer`, adapts accepted-recipe geometry and the current joint-state snapshot to the existing analytic OMX planner, and wraps the existing `PickPlaceRunner` start/exact-cancel methods. The integration wheel is in the CI install list and the dependency-boundary registry. Provider/owner boundary 12 passed; dependency-boundary suite 5 passed; platform mapping/submission/compatibility 27 passed; OMX adapter suite 333 passed/5 skipped. Six wheels built and the Skill/integration wheels installed offline into a fresh X: venv with provider import smoke PASS. ROS-SIM and device acceptance remain unproven.

## Task 6: 기존 앱 조합과 최소 설치

**Modify/Reuse:** `src/site/fleet/fleet/cli.py`, `src/site/fleet/fleet/server/app.py`, `src/products/omx/adapter/omx_adapter/pilot_sim_server.py`, `deploy/site/Dockerfile.fleet`, `deploy/robot/omx/Dockerfile.pilot`, `deploy/robot/omx/stack.lock.yaml`, `.github/workflows/ci.yml`.

**Create:** `apps/gateway/rosy_gateway/compose.py`, `apps/agent/rosy_agent/omx_sim.py`와 각 `pyproject.toml`, `profiles/installations/omx_cell_sim.yaml`, `profiles/installations/site_cell.yaml`, `test/test_platform_installed_entrypoints.py`, `test/test_platform_minimal_install.py`.

1. 사이트 조합은 기존 Fleet 서버, OMX 시뮬 조합은 기존 vendor runtime·UDS·Skill을 사용한다. 기존 CLI는 새 조합으로 위임한다. 새로운 운영 서비스나 물리 장치 접근을 추가하지 않는다.
2. 명시된 provider ID allowlist와 schema를 사용하는 profile을 만든다. 프로파일에서 임의 import/script 경로를 실행하지 않는다. 물리 dispatch는 비활성이다.
3. 두 설치 프로파일에 필요한 wheel만 빌드하고 artifact/ROS 패키지 잠금을 기록한다. 빌드 frontend가 없으면 설치를 별도 준비 작업으로 기록하고 검증을 PASS 처리하지 않는다.
4. X:의 깨끗한 환경에 산출물만 설치한다. 저장소 cwd·개발 PYTHONPATH를 제거한 subprocess에서 gateway/agent import, CLI, fake lifecycle과 정적 자산을 확인한다. ROS가 필요한 기동은 Jazzy 환경에서 따로 실행한다.
5. OMX 설치에서 Pinky·학습·모델 SDK 제거를 확인한다. 기존 Pinky 설치 집합이 바뀌지 않았음을 비교한다. Pinky의 새 agent 전환은 첫 회차의 완료 요건이 아니다.

**검증:** `python -B -X utf8 -m pytest test/test_platform_installed_entrypoints.py test/test_platform_minimal_install.py -q -p no:cacheprovider`. 기대: wheel/ament 파일 중복 0, 소스 경로 없는 실행, 필요 없는 전이 의존성 없음. 커밋: `build: compose and install the fixed-cell slice`.

## Task 7: 결과 불명과 재시작의 재생 시험

**Create:** `test/test_platform_cell_replay.py`, `test/fixtures/platform_cell_replay/`의 사건 fixture, `modules/execution/src/rosy/execution/local/reconcile.py` — 기존 규칙을 추출할 필요가 있을 때만.

**Modify/Reuse:** Fleet `mission_store.py`·`mission_dispatcher.py`, OMX `action_store.py`, 독립 goal-evidence 경로. 변경할 파일은 Task 0의 실제 이전 상태에 맞춘다.

1. 정상 완료·취소 요청 직후·제어기 수락 직후·release 뒤 기록 전·사이트 재시작·장치 재시작을 각각 fixture로 만든다.
2. SQLite 파일을 보존한 채 프로세스 객체를 다시 만들고 receipt와 독립 관측을 대조한다. 단순 객체 초기화를 물리 재시작 증거로 부르지 않는다.
3. 같은 ID/내용의 재요청은 원기록을 반환하고 다른 내용의 같은 ID는 거부해야 한다. 늦은 성공 응답이 HOLD를 자동 해제하지 않아야 한다.
4. 관측과 원장이 충돌하면 UNKNOWN/HOLD를 유지한다. 확인된 boundary에서만 다음 단계를 선택한다. 만료된 자원 예약이 실제 점유 해제를 뜻하지 않는 사례도 포함한다.

**검증:** `python -B -X utf8 -m pytest test/test_platform_cell_replay.py -q -p no:cacheprovider`. 기대: 제출 횟수·저널 행·projection watermark와 최종 상태를 함께 검증. 커밋: `test: replay cell interruption and reconciliation`.

## Task 8: 정식 경로의 Gazebo 종단 수용

**Modify/Reuse:** `deploy/robot/omx/probe_fleet_ros_vendor_sim.sh`, `src/sim/gz_sim/worlds/omx_pilot_workcell.sdf`, 기존 C3/C4 harness와 Cell fixture.

**Create:** `tools/sim/verify_platform_cell.py`, `test/test_platform_cell_sim_evidence.py`, Task 0 증거 묶음의 `ros-sim.md`. 대용량 원본 로그·영상은 X:에 두고 문서에는 provenance·요약·digest만 남긴다.

1. rclpy/Jazzy·vendor lock·제어기 ready·격리 ROS domain·시뮬 시각·물리 장치 접근 없음부터 확인한다. 빠진 의존성이나 skipped 수집은 HOLD다.
2. 등록된 서비스 principal 제안 → 운영자 승인 → Fleet grant → UDS → owner → vendor Action의 전체 경로로 실행한다. 직접 Python 함수 호출만으로 종단 PASS를 만들지 않는다.
3. 2층·슬립시트 1장·팔레트 2개를 실행하고, 각 transfer의 object identity·모델 포즈·그리퍼 readback·Action/attempt·Step을 연결한다. 물체/접촉 근거가 없으면 제어기 완료와 별도로 목표는 미확인이다.
4. 진행 중 정지 세대 변경·늦은 goal 수락·owner 재시작을 재현한다. 기존 D-403 개방 조건을 만족한 simulation profile에만 하달을 허용한다.
5. `verify_platform_cell.py`는 누락/위조/다른 attempt의 증거를 거부한다. 먼저 `test_platform_cell_sim_evidence.py`에서 양성·음성 제어로 검증기를 확인한다.

**명령:** Task 8에서 구현하는 `python tools/sim/verify_platform_cell.py --evidence-root <ROSY_SCRATCH의 실행 디렉터리>`를 사용한다. 기존 probe는 Task 0에서 확인한 인자와 잠금 버전으로 실행한다. 새로운 CLI를 이미 존재하는 명령처럼 실행하지 않는다.

**출구:** SOURCE/LOCAL 결과와 별도로 이 고정 셀 ROS-SIM 증거가 완결됨. 물리 정지·실물 물품·DEVICE/FIELD는 미승격. 실패 시 원본을 유지하고 HOLD 사유를 기록한다. 커밋: `test: verify fixed-cell fleet-to-gazebo flow`.

## Task 9: 검증된 호환층 정리와 후속 범위

**Modify:** Task 3~6에서 생성한 호환 import/CLI, 관련 `pyproject.toml`·`package.xml`, import/설치 검사, 각 모듈 progress/logs, 설계 v0.2의 실제 이전 상태.

1. 정적 검색과 설치 시험으로 구 import/entrypoint 소비자를 목록화한다. 실제 소비자가 남은 호환층은 종료 조건과 예정 릴리스를 적고 유지한다.
2. 전환된 구현의 정본을 하나로 유지하고 사용되지 않는 중복 구현만 제거한다. 기존 외부 ROS 이름 변경은 별도 마이그레이션이다.
3. 새 구조와 기존 미전환 코드가 혼재하는 범위를 문서화한다. 이 회차로 플랫폼 전체 이전을 완료 처리하지 않는다.
4. 후속 계획은 Pinky agent/주행 Skill, decision/provider, perception/world, learning/worker 순서 후보에서 실제 필요를 선택한다. 각 설치·실행 경계는 별도 증거로 검증한다.

**출구:** 관련 회귀와 설치 시험 통과, writer·원장 중복 없음, 호환층 제거/유지 이유가 명확함. 커밋: `refactor: retire verified cell compatibility paths`.

## 커밋 전 공통 확인

```text
python -B -X utf8 tools/harness/rosy_harness.py generate
python -B -X utf8 tools/harness/rosy_harness.py lint
python -B -X utf8 -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q -p no:cacheprovider
git diff --check
```

코드 변경은 저장소 AGENTS의 quick tier와 해당 모듈 suite도 실행한다. `test/known_failures.py` 대비 새 실패를 숨기지 않는다. package.xml/setup.py/CMake 변경은 Jazzy colcon 빌드로 확인하고, wheel 추가는 설치 산출물 시험으로 확인한다. host pytest는 ROS-SIM을 대신하지 않는다.

## 중단과 되돌리기

- **계약/출력 회귀:** 해당 task에서 멈추고 기존 fixture와 의미 차이를 해결한다. 허용 범위를 넓혀 가드를 통과시키지 않는다.
- **설치 회귀:** 소스 import 성공으로 넘기지 않고 이전 설치 경로를 유지한다. wheel/ament 파일 소유자와 자산 경로를 바로잡는다.
- **원장 migration 이후:** 백업·schema 버전·미종결 Action을 확인한다. 다운그레이드 가능성을 시험하기 전 구 바이너리로 같은 DB를 열지 않는다.
- **실행 결과 불명:** UNKNOWN/HOLD로 남기고 새 attempt를 자동 발급하지 않는다. 현재 물리/시뮬 상태와 기록의 조정이 먼저다.
- **병행 작업 충돌:** 기존 Cell/OMX 기능이 다른 브랜치에서 들어오면 Task 0 표를 갱신하고 새 구현 대신 해당 결과를 통합·재검증한다.

## 완료 추적

| Task | 상태 | commit / 시험 / 증거 |
|---|---|---|
| 0 Baseline | PASS | `7e577452`; Cell 143, Fleet 1336, OMX 268, architecture 76 passed/1 skipped; ownership manifest committed |
| 1 Boundary guard | PASS | `59cd3bce`, main sync `d082bf18`; boundary suite 81 passed/1 skipped; quick 95 passed; no new known failures |
| 2 Minimal APIs | PASS | `d502290b`, main sync `eb306385`; 3 installed wheels, mapping/boundary/protocol 29 passed, docs 80 passed |
| 3 Process extraction | PASS (source); runtime/artifact/device gates remain open | `9da93450`, docs `bb84551a`, latest-main sync `cc76161f5` / merge `d9e70f71`; wheel compatibility 11, Cell 143, mapping 7; architecture 81/1 skipped, quick 95 passed/24 existing warnings; known-failure comparisons 0 new/0 known |
| 4 Fleet connection | IN PROGRESS | execution compiler-port mapping 6 passed; CELL_TRANSFER contract + core schema suite 424 passed/1 skipped; endpoint/ordered journal/recovery remain |
| 5 Local Skill | IN PROGRESS | tagged `FleetCellTransferGrant` reaches only its registered phase runner; added ROS-free `pallet.transfer` Skill and `execution/local` receipt seam; boundary/compiler/submission tests 25 passed and three wheels install in an isolated venv. OMX provider and owner integration remain |
| 6 App and install | TODO | not run |
| 7 Failure replay | TODO | not run |
| 8 Gazebo | TODO | not run |
| 9 Compatibility cleanup | TODO | not run |
