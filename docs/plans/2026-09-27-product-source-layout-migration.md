# 제품 전용 소스 배치 이행 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 기존 ROS 패키지의 이름·실행 권한·설치 목록을 보존하면서 Pinky·OMX 전용 소스를 `src/products/<모델>/`, 제품 독립 BNO055 드라이버를 `src/drivers/`에 모은다.

**Architecture:** [D-310](../adr/D-310-product-specific-source-and-runtime-boundaries.md)의 목표는 소스 변경 이유에 따른 배치다. `runtime/gateway(core)`가 Pinky 주행 최종 명령을 계속 소유하며 Fleet·계약·HMI·시뮬레이션과 `deploy/robot`은 이 묶음에서 이동하지 않는다. 제품별 산출물 분리나 새 adapter 구현은 별도 작업이다.

**Tech Stack:** ROS 2 Jazzy/colcon, ament_python·ament_cmake, Python/pytest, Docker CORE·IO 이미지, native ARM64 payload, PowerShell/WSL.

**상태:** 소스 배치 통합 진행 (2026-09-28). D-310은 제품별 소스 위치에 한해 Accepted이며 D-231·D-305의 충돌하는 위치 조항만 부분 대체한다. SOURCE/LOCAL·CORE/IO OCI 동등성은 기록됐고 native payload의 실제 aarch64/Jazzy 비교는 `NOT_RUN`이다. 이 파일은 이미지 배포나 장치 수용 기록이 아니다.

---

## 범위와 완료 정의

| 범위 | 이 묶음에서 하는 일 | 별도 작업 |
|---|---|---|
| 소스 | `pinky_pro`, `omx` 설정 ROS 패키지를 각 `profile/`로, Pinky 하드웨어 넷과 OMX adapter를 제품 아래로, 독립 IMU를 `drivers/`로 이동 | `core`, `core_features`, `core_events`, `core_api_web`, `navigation`, `control`, `core_common`, 화면·URDF·지도 이동 |
| 계약 | ROS 패키지명, Python import, launch 실행 이름, CORE 단일 `cmd_vel` writer, 기존 JSON/API 유지 | 새 공통 Action API, OMX 원격 운영, 탑재형 인터록 구현 |
| 배포 | 기존 CORE/IO/native 이미지의 패키지 집합·필수 import 동등성 검증; CORE Docker COPY를 profile만으로 제한 | `deploy/robot` 개명, 제품별 독립 이미지·서명, 실제 장치 설치 |

완료란 SOURCE/LOCAL, ROS 빌드, 기존 이미지 빌드의 **동등성**을 기록한 소스 이동을 뜻한다. 새 설치 패키지·launch share 경로·서비스 또는 이미지 내용이 달라지면 이 계획의 단순 이동 완료로 처리하지 않는다. 장치/현장 수용은 D-305의 독립 게이트를 따른다. 출구는 `SOURCE_CANDIDATE`(경로·host·harness·colcon), `ARTIFACT_EQUIVALENT`(CORE·IO·native의 실제 설치 내용 비교), `DEVICE_ACCEPTED`(별도 장치 설치·동작 readback)로 기록하며 앞 출구만으로 뒤 출구를 주장하지 않는다.

**실행 순서:** 작업 공간·이동 전 기준선 → D-310의 구조 목표 수용 범위 결정 → 구조 시험과 여덟 패키지의 원자적 경로 이동 → 경로 문서·생성 색인과 SOURCE/ROS 검증 → 깨끗한 후보 커밋 → 그 정확한 SHA의 산출물 검증 → 결과만 기록한 문서 커밋 → 통합. 아래 Task 번호는 원래 기준이다. 사용자의 명시적 로컬 병합 요청에 따라 CORE/IO OCI 비교 후 native 비교 전에 **소스 통합만** 진행한다. 이 순서 변경은 native `ARTIFACT_EQUIVALENT`, 이미지 발행, DEVICE/FIELD 출구를 면제하지 않는다.

## 목표 경로와 현재 경로

| ROS 패키지 | 현재 | 목표 |
|---|---|---|
| `pinky_pro` | `src/products/pinky_pro` | `src/products/pinky_pro/profile` |
| `omx` | `src/products/omx` | `src/products/omx/profile` |
| `bringup` | `src/devices/pinky_pro/bringup` | `src/products/pinky_pro/bringup` |
| `sensor_adc` | `src/devices/pinky_pro/adc` | `src/products/pinky_pro/adc` |
| `lamp_control` | `src/devices/pinky_pro/lamp` | `src/products/pinky_pro/lamp` |
| `led` | `src/devices/pinky_pro/led` | `src/products/pinky_pro/led` |
| `omx_adapter` | `src/devices/omx/adapter` | `src/products/omx/adapter` |
| `imu_bno055` | `src/devices/common/imu_bno055` | `src/drivers/imu_bno055` |

`profile/`은 부모 안의 ROS 패키지 중첩을 막기 위한 필수 위치다. 이동 후 `src/products/pinky_pro`·`src/products/omx`는 디렉터리 컨테이너이고 `package.xml`은 각각 `profile/`에 한 번만 존재해야 한다. `src/devices/`의 운영 상태 파일·무관 작업물을 강제로 제거하지 않는다.

## Task 0: 작업 공간 고정

**Files:** `docs/adr/D-310-product-specific-source-and-runtime-boundaries.md`, `docs/adr/D-231-layered-source-roots-keep-package-names.md`, `docs/adr/D-305-platform-boundary-outcome-invariants-and-independent-gates.md`, `docs/reference/ROSY ADR Log.md`.

1. 최신 `main`의 HEAD·status·다른 worktree의 이동 작업을 확인한다. 릴리스 사이여야 한다(D-191/D-231). 작업은 저장소 `.worktrees/<짧은이름>`의 `--relative-paths` worktree에서 한다. `F:`에 일회성 로그를 쓰지 말고 `X:\DevTemp\`에 둔다.
2. D-310의 제어권·배포 경계를 다시 읽고 기존 D-231·D-305와 충돌하는 정확한 소스 위치 조항을 표시한다. 이 단계에서는 상태를 바꾸지 않는다. Task 1 기준선을 얻은 뒤 구조 목표의 수용 여부를 판정한다.

**출구:** 작업 HEAD·릴리스 창과 D-310 판정에 필요한 충돌 조항이 명확하다. 그렇지 않으면 기준선 작업을 시작하지 않는다.

## Task 1: 이동 전 기준선과 반례 기록

**Files:** `test/architecture/test_target_layout.py`, `test/architecture/test_module_structure.py`, `tools/harness/harness.yaml`, `deploy/robot/Dockerfile`, `deploy/image/required-ros-packages.txt`, `deploy/image/build-native-payload.sh`, `deploy/image/inputs.lock.yaml`.

1. `rg --files src | rg '(package.xml|setup.py|CMakeLists.txt)$'`와 `colcon list --base-paths src --names-only`로 패키지 이름과 경로를 기록한다. colcon 명령은 ROS Jazzy 환경에서 실행한다.
2. `rg -n 'src/(devices|products)/(pinky_pro|omx|common)' .github deploy tools test src --glob '!*.md'`로 살아 있는 경로 소비자를 목록화한다. `test_target_layout.py`의 기대 패키지 1개 1경로와 harness module path를 별도로 대조한다.
3. CORE/IO Dockerfile `COPY`·`--packages-*`, native payload `--base-paths src`, 필수 패키지 목록과 실제 설치 목록을 **이미지별**로 기록한다. 동일한 base image digest·Docker build args·requirements·apt 입력을 고정해 CORE·IO·native를 실제 빌드하고, 각 overlay의 ament index 패키지 전체 집합, 이동 패키지의 share/config/launch·console script, 필수 Python import를 기준선으로 남긴다. 존재 여부만 보는 inventory나 native `colcon list` 출력은 설치 closure가 아니다. 특히 CORE Dockerfile은 `interfaces`, `gateway`, Pinky profile만 복사하는 반면 `core/package.xml`에는 `core_common`, `core_events`, `core_features`, `core_api_web` 의존성이 있어 기존 빌드 실패 가능성을 먼저 확인한다.
4. `omx_adapter`가 현재 IO/native에 포함된 이유와 제거 조건, `imu_bno055` 필수 목록 포함 이유를 기록한다. 둘을 이 소스 이동 때문에 임의로 제외하지 않는다.
5. 기준선을 보고 D-310의 **구조 목표**를 수용할지 결정한다. 기준선 빌드가 실패했거나 `NOT_RUN`이면 먼저 원인을 해결해 새 기준선을 세우거나 D-310을 Proposed/HOLD로 둔다. 채택하면 D-231의 `products=config only`와 소스 위치 조항, D-305 결정 5의 현 배치 유지 부분을 **범위를 적어** 부분 대체한다. D-231의 검증 규칙과 D-305의 결과 불변식은 유지한다. ADR 로그와 생성 index를 정렬한다. 실제 이행은 D-310의 실행 게이트 기록처럼 native 기준선 `NOT_RUN` 상태에서 사용자 요청으로 로컬 소스 통합을 앞당겼다. native 동등성 선언과 배포는 계속 HOLD다. D-303의 Rejected 본문을 실행 기준으로 바꾸지 않는다.

**출구:** 이름·경로·이미지별 설치/share/entrypoint/import 기준선과 경로 소비자 목록이 `X:\DevTemp\`의 검증 로그 및 저장소의 검토 기록에 남고, D-310 구조 목표의 수용 범위가 명확하다. 기존 빌드 실패 또는 `NOT_RUN`은 동등성 증거가 아니다. CORE/IO 결함은 별도 선행 변경으로 고쳐 기준선을 다시 얻었다. native 기준선은 아직 `NOT_RUN`이며 위에 기록한 사용자 요청으로 로컬 소스 통합만 진행한다. `ARTIFACT_EQUIVALENT`는 계속 HOLD다.

## Task 2: 폴더 계약 시험을 새 목표로 먼저 갱신

**Files:** `test/architecture/test_target_layout.py`, `test/architecture/test_module_structure.py`, `test/test_native_ros_payload.py`, 제품 패키지의 경로 계약 시험, `tools/harness/harness.yaml`.

1. `test_target_layout.py`의 `TARGET` 여덟 행을 위 표의 `현재 → 목표`로 바꾸고 `TARGET_DOMAINS`에 `drivers`를 넣는다. 현재의 `test_moves_keep_the_package_name`은 경로 마지막 이름을 비교하므로 `profile/`, `adc/`, `lamp/`에서 거짓 실패한다. 이를 `package.xml`의 `<name>`과 이 표의 ROS 패키지명(`pinky_pro`, `omx`, `bringup`, `sensor_adc`, `lamp_control`, `led`, `omx_adapter`, `imu_bno055`)을 비교하는 검사로 바꾼다. `src` 전체의 XML 패키지명을 세어 전역 유일성, 각 이름의 **정확한 목표 경로 한 곳**, 이전 경로의 `package.xml` 부재와 부모 제품 폴더의 `package.xml` 부재를 모두 검사한다. 현재 시험의 이전·목표 경로 동시 허용만으로는 중복을 놓친다.
2. `test_products_hold_configuration_not_packages`의 기존 `products=config only` 불변식은 D-310 수용 시 폐기한다. 대신 제품 루트의 허용 ROS 패키지 집합과 두 `profile/`의 config 설치 계약을 검증한다. `test_module_structure.py`의 `ROLE_DIR`, `_family`, `layout_ok`, `_allowed`, `KNOWN_DIRECTION`, `SIZE_VERDICTS` 및 제품 3단계 경로와 `drivers`·`sim` 의존 방향도 실제 목표에 맞춰 갱신한다. 현 `MOVED = True`는 유지하고 실제 이동 후 목표 경로를 요구한다. 기존 writer·계약 검사는 삭제하지 않는다.
3. 이동 전 `python -m pytest test/architecture/test_target_layout.py test/architecture/test_module_structure.py -q`를 실행해 목표 경로 검사만 예상대로 실패하고 기존 안전 검사는 유지되는지 본다. 구조 시험이 임의의 새 runtime/owner API를 요구하지 않게 한다.
4. 테스트의 경로 상수는 이동과 같은 원자적 변경에서만 확정한다. 운영 브랜치에 목표 시험만 먼저 병합하지 않는다.

**출구:** 실제 이동을 확인하는 실패 시험이 있고, 기존 writer·계약 검사를 삭제하지 않았다.

## Task 3: 기존 패키지를 원자적으로 경로 이동

**Files:** 목표 경로 표의 여덟 패키지, `src/AGENTS.md`, `src/products/**/AGENTS.md`, `src/devices/AGENTS.md`, `src/runtime/AGENTS.md`, `.gitignore` 또는 `.dockerignore`의 경로 규칙.

1. `src/products/pinky_pro`와 `src/products/omx`의 기존 패키지 파일(`package.xml`, `CMakeLists.txt`, `config/`, `test/`, `AGENTS.md`, `progress.md`, `logs.md`, `index.md`)을 각각 같은 부모의 `profile/`로 `git mv`한다. 부모 폴더 자체를 자기 하위로 이동하는 명령을 쓰지 않는다.
2. Pinky 네 패키지, OMX adapter, 공용 IMU를 목표 표대로 `git mv`한다. ROS 패키지명·Python import 이름·console script·서비스 이름은 바꾸지 않는다. history용 ADR·날짜 붙은 기록의 옛 경로는 고치지 않는다.
3. `deploy/robot/Dockerfile` CORE stage의 `COPY src/products/pinky_pro`는 `COPY src/products/pinky_pro/profile ...`처럼 프로필 패키지만 복사하게 고친다. IO stage는 `products/omx/profile`과 `products/omx/adapter`를 각각 복사하거나 부모를 한 번 복사하되 중복 `COPY`와 예상 밖 패키지 유입을 막는다. Pinky bringup·OMX 경로와 런타임 CycloneDDS 설정 COPY, `.dockerignore`, `.github/workflows/ci.yml`, image/release 스크립트, harness, 현재 README·AGENTS, `test_robot_runtime.py`·`test_image_customization_contract.py`·`test_native_systemd_contract.py` 등 경로 참조 시험을 함께 고친다.
4. `rg -n 'src/devices/(pinky_pro|omx|common)' .github deploy tools test src --glob '!*.md'` 결과에서 **이동한 기존 패키지 경로**를 참조하는 살아 있는 소비자가 0개인지 확인한다. `src/products/(pinky_pro|omx)`는 새 경로의 부모로도 쓰이므로 0건을 요구하지 않고, 각 참조가 정확한 `profile/`·제품 패키지로 resolve되는지 분류한다.
5. 경로 이동·참조 수정·구조 시험은 하나의 리뷰 가능한 소스 변경 단위로 만든다. 제품 패키지 부모의 `profile/` 이동을 먼저 하여 중첩 `package.xml`을 없앤 뒤 나머지 여섯 패키지를 옮긴다. 커밋은 Task 4의 현재 경로 문서·생성 색인·시험이 끝난 뒤 후보 SHA로 고정한다. unrelated WIP는 stage하지 않는다.

**출구:** `colcon list`에 각 ROS 패키지가 한 번만 보이고, `products/<모델>` 부모는 ROS 패키지가 아니며 기존 실행 이름이 남는다. `deploy/robot` 경로·태그·유닛은 그대로다.

## Task 4: SOURCE/LOCAL·ROS 빌드 게이트

**Files:** `test/architecture/`, `src/products/**/test/`, `src/drivers/imu_bno055/test/`, `test/`, `tools/harness/rosy_harness.py`.

1. Windows에서 `python -m pytest test/architecture/test_target_layout.py test/architecture/test_module_structure.py test/test_native_ros_payload.py -q`와 경로가 바뀐 각 패키지의 host 시험을 실행한다. 같은 이름의 test 모듈 충돌은 별도 호출로 분리한다.
2. 기존 D-231의 **전체 host pytest**를 중복 basename을 고려한 저장소 명령으로 실행하고 실패는 이동 관련/기존 기준선으로 분류한다.
3. ROS Jazzy 환경에서 `colcon list --base-paths src --names-only`와 `colcon build --base-paths src`를 실행한다. 이동 전후 package 이름 집합을 비교하고 `ros2 pkg executables core`, `ros2 pkg prefix pinky_pro`, bringup·OMX·IMU share lookup의 경로·import 스모크를 한다. 운영 launch의 입력과 단일 최종 `cmd_vel` writer 구조를 대조하고, 실제 ROS graph 확인은 실행 조건이 마련된 ROS-SIM에서 별도로 수행한다. 실제 `core` 실행은 identity·mode·하드웨어 조건을 갖춘 별도 런타임 게이트이며 이 소스 이동의 단순 import 스모크로 실행하지 않는다.
4. 현재 폴더 지도·AGENTS·harness module 기록을 실제 이동 경로로 갱신하고 `python tools/harness/rosy_harness.py generate`를 실행한다. 생성 index 및 현재 경로 문서, ADR 상태가 후보 커밋에 포함되도록 한다. 그런 다음 lint와 문서 계약 시험을 실행한다.
5. 모든 소스·구조 문서·생성 색인과 검증 입력을 명시적으로 stage해 후보 커밋을 만든다. native builder의 요구에 맞게 깨끗한 작업 트리와 **40자 후보 SHA**를 기록한다. 이 뒤 검증 결과를 알기 전에는 검증 PASS를 문서에 쓰지 않는다.

**출구:** host/harness/colcon 녹색과 패키지 이름·import 동등성을 갖춘 `SOURCE_CANDIDATE`의 깨끗한 후보 SHA. 실패 시 해당 단위는 merge HOLD다.

## Task 5: 이미지·설치 closure 게이트

**Files:** `deploy/robot/Dockerfile`, `deploy/image/build-native-payload.sh`, `deploy/image/required-ros-packages.txt`, `deploy/release/`의 image input·검증 스크립트.

1. Task 4에서 고정한 **깨끗한 40자 후보 SHA**와 고정 입력으로 CORE와 IO 이미지를 각 target별로 빌드한다. native payload는 지정된 aarch64/Jazzy 환경에서 해당 SHA의 깨끗한 checkout으로 빌드한다. native 스크립트는 source revision을 기록하므로 후보 SHA와 뒤의 문서 커밋 SHA를 혼동하지 않는다. Windows host pytest가 이 게이트를 대신하지 않는다.
2. 각 overlay의 `share/ament_index/resource_index/packages` 전체 집합, 이동 패키지의 share/config/launch·ament marker·console script 존재와 모드, `ros2 pkg prefix`·launch lookup, CORE의 `core`·`core_common`·`core_events`·`core_features`·`core_api_web`, IO의 `omx_adapter`·`control` import를 Task 1 기준선과 비교한다. CORE에 Pinky hardware나 OMX adapter가 새로 들어오지 않았는지, IO/native의 OMX·IMU 필수 목록이 이동 때문에 누락되지 않았는지 확인한다. native `rosy-packages.txt`는 `colcon list` 결과이고 필수 verifier도 subset 검사이므로 어느 쪽도 정확한 설치 closure의 단독 증거가 아니다.
3. 비교 대상은 설치 closure와 운영 import·lookup의 동등성이다. source revision·빌드 메타데이터가 바뀌므로 이미지 digest 또는 바이트 동일성을 요구하지 않는다. COPY 범위, ROS share 경로, native 필수 package inventory가 달라졌다면 원인을 분류하고 같은 소스 변경에서 해결한 뒤 후보 SHA를 다시 고정해 빌드한다. 설치 목록·API·유닛 변경이 의도된 것이라면 별도 ARTIFACT/DEVICE 이행 계획으로 분리한다.
4. 빌드 명령·고정 입력·후보 SHA·설치 목록·비교 결과를 우선 `X:\DevTemp\`에 원본 증거로 남긴다. 기존 이미지가 실패했거나 `NOT_RUN`인데 이동 후 같은 상태여도 동등성 통과로 처리하지 않는다.

**출구:** 세 이미지의 실제 빌드와 설치 closure·import·lookup 동등성 근거가 후보 SHA에 연결된 `ARTIFACT_EQUIVALENT`. 수행하지 못한 native payload의 출구는 `NOT_RUN`/HOLD다. 이번 사용자 요청으로 소스 경로를 로컬 `main`에 통합하더라도 이 출구를 통과한 것으로 기록하지 않는다.

## Task 6: 결과 문서·통합·되돌리기

**Files:** `src/AGENTS.md`, 관련 package `AGENTS.md`, `docs/reference/ROSY ADR Log.md`, `docs/progress.md`, `docs/logs.md`, `docs/index.md`, `STATUS.md`.

1. Task 5의 원본 증거를 근거로 ADR 검증 기록·progress·logs에 **후보 SHA의 결과**를 적는다. 결과 문서는 별도 evidence-only 커밋으로 남기고 후보 SHA와 문서 HEAD를 구분한다. `git diff --name-only <candidate>..<evidence-head>`의 **전체 경로**가 `docs/**`와 명시한 `STATUS.md` 등 증거 문서 allowlist에만 속하는지 확인한다. 다른 경로가 있다면 해당 HEAD에서 SOURCE/ARTIFACT 게이트를 다시 수행한다.
2. `runtime=현재 로컬 실행`, `products=제품 전용 소스·구성`, `drivers=제품 독립 칩 드라이버`로 범위를 정의한다. 현재 폴더 지도·AGENTS·harness 생성 색인은 Task 4 후보 SHA에 이미 포함돼 있어야 한다. 결과 문서에서 폴더를 writer나 설치 증거로 설명하지 않는다.
3. 최신 `main`과 변경 경로 겹침·HEAD 선조 관계를 확인한 뒤 검증된 후보와 입력 불변인 결과 문서만 통합한다. 이번 사용자의 요청에 따른 통합은 SOURCE/LOCAL 및 CORE/IO OCI 증거를 가진 **로컬 소스 배치**에 한하며 native `ARTIFACT_EQUIVALENT` 이전이라는 차이를 ADR·검증 기록에 남긴다. push·CI·아티팩트 게시·Pi 설치는 수행 증거가 있을 때만 별도로 보고한다. 최종 릴리스 HEAD의 산출물을 발행하려면 그 SHA에서 다시 빌드·서명·digest 검증한다. 이번 후보 SHA 산출물을 문서 HEAD나 릴리스 HEAD의 산출물로 부르지 않는다.
4. 후보 브랜치에서 실패하면 main을 건드리지 않고 경로 이동 커밋과 소비자·Docker COPY를 같은 단위로 되돌린다. 이미 main에 통합됐다면 main을 reset하지 않고 해당 커밋 revert와 회귀 게이트를 실행하며 append-only ADR/log에 되돌림 기록을 추가한다. 이미 배포된 산출물은 이전 서명 digest로 복귀하고 장치 설치/readback을 별도로 확인한다.

**이번 로컬 소스 통합 출구:** 문서와 생성 색인이 실제 소스 위치에 맞고 SOURCE/LOCAL·WSL Jazzy 및 CORE/IO OCI 설치 closure 결과가 각 검증 SHA에 연결된다. 전체 `ARTIFACT_EQUIVALENT`는 native aarch64/Jazzy 기준선·후보 비교 후 별도로 닫는다. `DEVICE_ACCEPTED`는 이 소스 작업의 출구가 아니다.

## 후속 설계: 실제 제품별 runtime 연결

이번 이행에서 `products/pinky_pro/runtime_adapter/`, `products/omx/control/`, `products/drone/`을 생성하지 않는다. 별도 ADR에서 다음을 결정한다.

- Pinky: `core/bridge/control_sensor_adapter.py`의 Pinky 센서·보정 결합과 주변장치 port를 분리할 수 있는지 감사한다. CORE의 `core=core.main:main`·단일 `cmd_vel` writer는 유지하고 새 adapter의 최종 publisher 수는 0이어야 한다. `navigation`의 Pinky bringup 결합, 현장 지도, Gazebo launch, 재사용 Nav2 helper를 소비자별로 분류한다.
- OMX: `omx_adapter`의 profile·owner policy·ROS action port·실제 vendor driver 경계를 P1 SOURCE/ROS-SIM, ARTIFACT, DEVICE 증거로 판정한다. 고정형과 탑재형은 같은 소스의 별도 인스턴스이고 두 최종 writer는 유지한다.
- 드론: 기종·비행 스택·링크 단절 시 로컬 동작과 실제 actuator authority를 확인하기 전 폴더·owner·공통 action schema를 만들지 않는다.

새 ROS 패키지·CORE import·launch share 위치나 이미지 내용이 생기는 후속 설계는 이번 **source-only 동등성**과 다른 변경이다. SOURCE/ROS-SIM은 먼저 진행할 수 있지만 운영 capability는 해당 ARTIFACT/DEVICE/FIELD 출구가 닫힐 때까지 HOLD다.
