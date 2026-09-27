# 제품 전용 소스 배치 이행 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 기존 ROS 패키지의 이름·실행 권한·설치 목록을 보존하면서 Pinky·OMX 전용 소스를 `src/products/<모델>/`, 제품 독립 BNO055 드라이버를 `src/drivers/`에 모은다.

**Architecture:** [D-310](../adr/D-310-product-specific-source-and-runtime-boundaries.md)의 목표는 소스 변경 이유에 따른 배치다. `runtime/gateway(core)`가 Pinky 주행 최종 명령을 계속 소유하며 Fleet·계약·HMI·시뮬레이션과 `deploy/robot`은 이 묶음에서 이동하지 않는다. 제품별 산출물 분리나 새 adapter 구현은 별도 작업이다.

**Tech Stack:** ROS 2 Jazzy/colcon, ament_python·ament_cmake, Python/pytest, Docker CORE·IO 이미지, native ARM64 payload, PowerShell/WSL.

**상태:** 계획 (2026-09-27). D-310은 Proposed이고 기존 D-231·D-305가 현재 소스 위치의 기준이다. 이 파일은 폴더 이동이나 이미지 배포가 끝났다는 기록이 아니다.

---

## 범위와 완료 정의

| 범위 | 이 묶음에서 하는 일 | 별도 작업 |
|---|---|---|
| 소스 | `pinky_pro`, `omx` 설정 ROS 패키지를 각 `profile/`로, Pinky 하드웨어 넷과 OMX adapter를 제품 아래로, 독립 IMU를 `drivers/`로 이동 | `core`, `core_features`, `core_events`, `core_api_web`, `navigation`, `control`, `core_common`, 화면·URDF·지도 이동 |
| 계약 | ROS 패키지명, Python import, launch 실행 이름, CORE 단일 `cmd_vel` writer, 기존 JSON/API 유지 | 새 공통 Action API, OMX 원격 운영, 탑재형 인터록 구현 |
| 배포 | 기존 CORE/IO/native 이미지의 패키지 집합·필수 import 동등성 검증; CORE Docker COPY를 profile만으로 제한 | `deploy/robot` 개명, 제품별 독립 이미지·서명, 실제 장치 설치 |

완료란 SOURCE/LOCAL, ROS 빌드, 기존 이미지 빌드의 **동등성**을 기록한 소스 이동을 뜻한다. 새 설치 패키지·launch share 경로·서비스 또는 이미지 내용이 달라지면 이 계획의 단순 이동 완료로 처리하지 않는다. 장치/현장 수용은 D-305의 독립 게이트를 따른다.

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

## Task 0: 결정·작업 공간 고정

**Files:** `docs/adr/D-310-product-specific-source-and-runtime-boundaries.md`, `docs/adr/D-231-layered-source-roots-keep-package-names.md`, `docs/adr/D-305-platform-boundary-outcome-invariants-and-independent-gates.md`, `docs/reference/ROSY ADR Log.md`.

1. 이 계획과 D-310을 검토해 목표가 제품 전용 소스 배치이고 제어권·배포 분리가 아님을 확인한다. 채택하면 새 ADR에서 D-231의 `products=config only`와 소스 위치 조항, D-305 결정 5의 현 배치 유지 부분을 **범위를 적어** 부분 대체한다. 그 외 D-231 검증 규칙과 D-305 결과 불변식은 유지한다.
2. 최신 `main`의 HEAD·status·다른 worktree의 이동 작업을 확인한다. 릴리스 사이여야 한다(D-191/D-231). 작업은 저장소 `.worktrees/<짧은이름>`의 `--relative-paths` worktree에서 한다. `F:`에 일회성 로그를 쓰지 말고 `X:\DevTemp\`에 둔다.
3. 실제 소스 이동 전 D-310의 수용 상태와 ADR 로그·문서 index를 정렬한다. 번호 충돌이 생기면 새 번호를 발급하고 링크를 갱신한다. D-303의 Rejected 본문이나 과거 이행 계획을 실행 기준으로 바꾸지 않는다.

**출구:** D-310 수용 범위·작업 HEAD·릴리스 창이 명확하다. 그렇지 않으면 폴더를 이동하지 않는다.

## Task 1: 이동 전 기준선과 반례 기록

**Files:** `test/architecture/test_target_layout.py`, `test/architecture/test_module_structure.py`, `tools/harness/harness.yaml`, `deploy/robot/Dockerfile`, `deploy/image/required-ros-packages.txt`, `deploy/image/build-native-payload.sh`, `deploy/image/inputs.lock.yaml`.

1. `rg --files src | rg '(package.xml|setup.py|CMakeLists.txt)$'`와 `colcon list --base-paths src --names-only`로 패키지 이름과 경로를 기록한다. colcon 명령은 ROS Jazzy 환경에서 실행한다.
2. `rg -n 'src/(devices|products)/(pinky_pro|omx|common)' .github deploy tools test src --glob '!*.md'`로 살아 있는 경로 소비자를 목록화한다. `test_target_layout.py`의 기대 패키지 1개 1경로와 harness module path를 별도로 대조한다.
3. CORE/IO Dockerfile `COPY`·`--packages-*`, native payload `--base-paths src`, 필수 패키지 목록과 실제 설치 목록을 **이미지별**로 기록한다. 존재 여부만 보는 inventory와 정확한 package closure를 구분한다. CORE 이미지가 이동 전 어떤 Python import를 제공하는지 `core`, `core_features`, `core_events`, `core_api_web`, `core_common`, `pinky_pro`로 확인한다.
4. `omx_adapter`가 현재 IO/native에 포함된 이유와 제거 조건, `imu_bno055` 필수 목록 포함 이유를 기록한다. 둘을 이 소스 이동 때문에 임의로 제외하지 않는다.

**출구:** 이름·경로·이미지별 package/import 기준선과 경로 소비자 목록이 `X:\DevTemp\`의 검증 로그 및 저장소의 검토 기록에 남는다. 기준선을 얻을 수 없는 이미지는 해당 이미지 동등성 게이트를 HOLD로 표시한다.

## Task 2: 폴더 계약 시험을 새 목표로 먼저 갱신

**Files:** `test/architecture/test_target_layout.py`, `test/architecture/test_module_structure.py`, `test/test_native_ros_payload.py`, 제품 패키지의 경로 계약 시험, `tools/harness/harness.yaml`.

1. `test_target_layout.py`의 `TARGET` 여덟 행을 위 표의 `현재 → 목표`로 바꾸고 `TARGET_DOMAINS`에 `drivers`를 넣는다. 현재의 `test_moves_keep_the_package_name`은 경로 마지막 이름을 비교하므로 `profile/`, `adc/`, `lamp/`에서 거짓 실패한다. 이를 `package.xml`의 `<name>`과 이 표의 ROS 패키지명(`pinky_pro`, `omx`, `bringup`, `sensor_adc`, `lamp_control`, `led`, `omx_adapter`, `imu_bno055`)을 비교하는 검사로 바꾼다. 각 목표에는 `package.xml`이 **한 번만** 존재하고 부모 제품 폴더에는 없어야 한다.
2. `test_products_hold_configuration_not_packages`의 기존 `products=config only` 불변식은 D-310 수용 시 폐기한다. 대신 제품 루트의 허용 ROS 패키지 집합과 두 `profile/`의 config 설치 계약을 검증한다. 현 `MOVED = True`는 유지하고 실제 이동 후 목표 경로를 요구한다. 기존 writer·계약 검사는 삭제하지 않는다.
3. 이동 전 `python -m pytest test/architecture/test_target_layout.py test/architecture/test_module_structure.py -q`를 실행해 목표 경로 검사만 예상대로 실패하고 기존 안전 검사는 유지되는지 본다. 구조 시험이 임의의 새 runtime/owner API를 요구하지 않게 한다.
4. 테스트의 경로 상수는 이동과 같은 원자적 변경에서만 확정한다. 운영 브랜치에 목표 시험만 먼저 병합하지 않는다.

**출구:** 실제 이동을 확인하는 실패 시험이 있고, 기존 writer·계약 검사를 삭제하지 않았다.

## Task 3: 기존 패키지를 원자적으로 경로 이동

**Files:** 목표 경로 표의 여덟 패키지, `src/AGENTS.md`, `src/products/**/AGENTS.md`, `src/devices/AGENTS.md`, `src/runtime/AGENTS.md`, `.gitignore` 또는 `.dockerignore`의 경로 규칙.

1. `src/products/pinky_pro`와 `src/products/omx`의 기존 패키지 파일(`package.xml`, `CMakeLists.txt`, `config/`, `test/`, `AGENTS.md`, `progress.md`, `logs.md`, `index.md`)을 각각 같은 부모의 `profile/`로 `git mv`한다. 부모 폴더 자체를 자기 하위로 이동하는 명령을 쓰지 않는다.
2. Pinky 네 패키지, OMX adapter, 공용 IMU를 목표 표대로 `git mv`한다. ROS 패키지명·Python import 이름·console script·서비스 이름은 바꾸지 않는다. history용 ADR·날짜 붙은 기록의 옛 경로는 고치지 않는다.
3. `deploy/robot/Dockerfile` CORE stage의 `COPY src/products/pinky_pro`는 `COPY src/products/pinky_pro/profile ...`처럼 프로필 패키지만 복사하게 고친다. IO stage의 bringup·OMX 경로와 런타임 CycloneDDS 설정 COPY, `.github/workflows/ci.yml`, image/release 스크립트, harness, 현재 README·AGENTS, 시험 경로 참조를 함께 고친다.
4. `rg -n 'src/devices/(pinky_pro|omx|common)' .github deploy tools test src --glob '!*.md'` 결과에서 **이동한 기존 패키지 경로**를 참조하는 살아 있는 소비자가 0개인지 확인한다. `src/products/(pinky_pro|omx)`는 새 경로의 부모로도 쓰이므로 0건을 요구하지 않고, 각 참조가 정확한 `profile/`·제품 패키지로 resolve되는지 분류한다.
5. 위 경로 이동·참조 수정·구조 시험을 하나의 리뷰 가능한 소스 변경 단위로 커밋한다. unrelated WIP는 stage하지 않는다.

**출구:** `colcon list`에 각 ROS 패키지가 한 번만 보이고, `products/<모델>` 부모는 ROS 패키지가 아니며 기존 실행 이름이 남는다. `deploy/robot` 경로·태그·유닛은 그대로다.

## Task 4: SOURCE/LOCAL·ROS 빌드 게이트

**Files:** `test/architecture/`, `src/products/**/test/`, `src/drivers/imu_bno055/test/`, `test/`, `tools/harness/rosy_harness.py`.

1. Windows에서 `python -m pytest test/architecture/test_target_layout.py test/architecture/test_module_structure.py test/test_native_ros_payload.py -q`와 경로가 바뀐 각 패키지의 host 시험을 실행한다. 같은 이름의 test 모듈 충돌은 별도 호출로 분리한다.
2. 기존 D-231의 **전체 host pytest**를 중복 basename을 고려한 저장소 명령으로 실행하고 실패는 이동 관련/기존 기준선으로 분류한다. `python tools/harness/rosy_harness.py lint`와 문서 계약 시험도 실행한다.
3. ROS Jazzy 환경에서 `colcon list --base-paths src --names-only`와 `colcon build --base-paths src`를 실행한다. 이동 전후 package 이름 집합을 비교하고 `ros2 pkg executables core`, `ros2 pkg prefix pinky_pro`, bringup·OMX·IMU share lookup의 경로·import 스모크를 한다. 실제 `core` 실행은 identity·mode·하드웨어 조건을 갖춘 별도 런타임 게이트이며 이 소스 이동의 단순 import 스모크로 실행하지 않는다.

**출구:** host/harness/colcon 녹색과 패키지 이름·import 동등성. 실패 시 해당 단위는 merge HOLD다.

## Task 5: 이미지·설치 closure 게이트

**Files:** `deploy/robot/Dockerfile`, `deploy/image/build-native-payload.sh`, `deploy/image/required-ros-packages.txt`, `deploy/release/`의 image input·검증 스크립트.

1. CORE와 IO 이미지를 기존 빌드 명령·고정 입력으로 각각 한 번 빌드한다. native ARM64 payload는 지정된 Jazzy/ARM64 환경에서 빌드한다. Windows host pytest가 이 게이트를 대신하지 않는다.
2. 각 이미지의 설치 ROS package 이름·선택 패키지·Python import 결과를 Task 1 기준선과 **동일성** 비교한다. CORE에 Pinky hardware나 OMX adapter가 새로 들어오지 않았는지, IO/native의 OMX·IMU 필수 목록이 이동 때문에 누락되지 않았는지 확인한다. 필수 subset 통과만으로 정확한 closure를 증명했다고 쓰지 않는다.
3. COPY 범위, ROS share 경로, native 필수 package inventory가 달라졌다면 원인을 분류하고 같은 소스 변경에서 해결한다. 설치 목록·API·유닛 변경이 의도된 것이라면 별도 ARTIFACT/DEVICE 이행 계획으로 분리한다.

**출구:** 세 이미지의 빌드와 동등성 근거가 있다. 수행하지 못한 이미지의 출구는 `NOT_RUN`/HOLD이며 소스 이동 완료로 승격하지 않는다.

## Task 6: 문서·통합·되돌리기

**Files:** `src/AGENTS.md`, 관련 package `AGENTS.md`, `docs/reference/ROSY ADR Log.md`, `docs/progress.md`, `docs/logs.md`, `docs/index.md`, `STATUS.md`.

1. 실제 이동된 경로만 현재 폴더 지도·AGENTS·harness module 기록에 반영한다. `runtime=현재 로컬 실행`, `products=제품 전용 소스·구성`, `drivers=제품 독립 칩 드라이버`로 범위를 정의하고 폴더를 writer나 설치 증거로 설명하지 않는다.
2. ADR 상태와 검증 로그를 갱신하고 `python tools/harness/rosy_harness.py generate`, `python tools/harness/rosy_harness.py lint`, `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`를 실행한다.
3. 최신 `main`과 변경 경로 겹침·HEAD 선조 관계를 확인한 뒤 검증된 커밋만 통합한다. push·CI·아티팩트 게시·Pi 설치는 수행 증거가 있을 때만 별도로 보고한다.
4. 소스 이동이 실패하면 그 이동 커밋만 되돌리고 마지막 통과 패키지 경로·이미지 입력을 사용한다. 이미 배포된 산출물은 경로가 아닌 서명·digest·설치 readback 기준으로 복구한다.

**출구:** 문서와 생성 색인이 실제 소스 위치에 맞고 SOURCE/LOCAL·ROS·기존 이미지 게이트가 닫혔다.

## 후속 설계: 실제 제품별 runtime 연결

이번 이행에서 `products/pinky_pro/runtime_adapter/`, `products/omx/control/`, `products/drone/`을 생성하지 않는다. 별도 ADR에서 다음을 결정한다.

- Pinky: `core/bridge/control_sensor_adapter.py`의 Pinky 센서·보정 결합과 주변장치 port를 분리할 수 있는지 감사한다. CORE의 `core=core.main:main`·단일 `cmd_vel` writer는 유지하고 새 adapter의 최종 publisher 수는 0이어야 한다. `navigation`의 Pinky bringup 결합, 현장 지도, Gazebo launch, 재사용 Nav2 helper를 소비자별로 분류한다.
- OMX: `omx_adapter`의 profile·owner policy·ROS action port·실제 vendor driver 경계를 P1 SOURCE/ROS-SIM, ARTIFACT, DEVICE 증거로 판정한다. 고정형과 탑재형은 같은 소스의 별도 인스턴스이고 두 최종 writer는 유지한다.
- 드론: 기종·비행 스택·링크 단절 시 로컬 동작과 실제 actuator authority를 확인하기 전 폴더·owner·공통 action schema를 만들지 않는다.

새 ROS 패키지·CORE import·launch share 위치나 이미지 내용이 생기는 후속 설계는 이번 **source-only 동등성**과 다른 변경이다. SOURCE/ROS-SIM은 먼저 진행할 수 있지만 운영 capability는 해당 ARTIFACT/DEVICE/FIELD 출구가 닫힐 때까지 HOLD다.
