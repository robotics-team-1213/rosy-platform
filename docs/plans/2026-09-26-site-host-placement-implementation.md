# Site Host Placement and OMX Instance Isolation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Pinky·사이트 서비스·OMX-AI 1~2대의 호스트 배치를 설정으로 관리하고, OMX별 장치·제어 인스턴스를 분리한 뒤 공유 PC의 적합성을 실측한다.

**Architecture:** [D-281](../adr/D-281-site-host-placement-and-omx-instance-isolation.md)의 장비 ID, 실행 인스턴스, 호스트 ID를 독립적으로 기록한다. 사이트 Fleet/Vision/Caddy는 현행 Compose를 사용하고, OMX의 현장 actuator 제어는 D-246에 따라 별도 native systemd 인스턴스를 첫 후보로 한다. 기존 OMX OCI 이미지는 개발·빌드·ROS-SIM 용도이며, Fleet에 새 OMX 명령 계약을 열지 않는다.

**Tech Stack:** Ubuntu 24.04 amd64, ROS 2 Jazzy, 잠긴 ROBOTIS `open_manipulator` 소스, Python/PyYAML/pytest, systemd, Docker Compose(사이트 서비스).

---

## 실행 전 기준

- 제품 소스 루트 `Rosy OS/`에서 현재 HEAD·dirty 경로·기존 worktree를 확인한다. 구현은 `.worktrees/<짧은이름>`에 `git worktree add --relative-paths`로 분리한다. 스크래치/로그/검증 임시 파일은 `X:\DevTemp\`에 둔다.
- [D-246](../adr/D-246-runtime-flexibility-native-default-container-sidecar-lane.md), [D-273](../adr/D-273-omx-camera-stream-and-arm-control-order.md), [D-281](../adr/D-281-site-host-placement-and-omx-instance-isolation.md), [OMX 실행 계획](2026-09-26-omx-ai-workstation-runtime.md), 현행 `deploy/omx/preflight.py`와 `deploy/site/compose.yaml`을 먼저 읽는다.
- D-281은 Proposed다. 아래 SOURCE/LOCAL 준비는 실행할 수 있지만, OMX의 장치 제어 활성화·원격 API·현장 기본 배치 확정은 각각 해당 ADR과 DEVICE/FIELD 게이트의 판정을 기다린다. `src/products/omx/config/omx.disabled.yaml`의 `enabled: false`를 소프트웨어 시험을 위해 바꾸지 않는다.
- 이 계획은 `robots.yaml`에 OMX를 넣거나, Fleet 이동 목표를 OMX로 보내거나, Pinky+OMX 이동 조작을 열지 않는다. 같은 호스트에서 실행해도 사이트와 OMX의 ROS/DDS graph를 합치지 않는다.

## Task 1: 호스트 인벤토리의 최소 계약

**Files:** Create `deploy/omx/host_inventory.py`, `deploy/omx/host-inventory.yaml.example`, `test/test_omx_host_inventory.py`; update `deploy/omx/README.md`.

1. 시험에서 순수 함수 `load_inventory(text: str) -> Inventory`와 `InventoryError`를 먼저 요구한다. `schema: rosy.omx-host-inventory.v1`, 비어 있지 않은 `site_id`, 호스트 목록, 작업대 목록이 기본 입력이다. 각 작업대는 `workcell_id`, `instance_id`, 기존 `host_id` 참조, follower/leader의 절대 `/dev/serial/by-id/<한 항목>` 선택값을 가진다. 선택 전 카메라는 `null`로 둔다.
2. 성공 사례는 한 호스트의 OMX 1대/2대와 두 호스트의 OMX 2대다. 실패 사례는 중복 `workcell_id`·`instance_id`·`host_id`, 알 수 없는 호스트, 한 호스트에서 중복 serial/camera 선택값, follower=leader, `/dev/ttyACM*` 추측 경로, 활성 설정의 예시 placeholder와 빈 장치값이다. 호스트 간 같은 경로 문자열만으로 충돌을 단정하지 않는다. 장치의 실제 동일성 검사는 Task 2가 맡는다.
3. 최소 구현은 YAML 자료 검증과 불변 객체 생성만 한다. 장치 파일 열기, ROS import, Fleet 등록, 네트워크 연결, secret 로깅은 넣지 않는다. 템플릿에는 가짜 주소·토큰·실제 serial을 기록하지 않고 `enabled: false`를 둔다. 채워진 현장 인벤토리는 gitignored `private/` 또는 호스트 `/etc/rosy/omx/`에만 둔다.
4. `python -X utf8 -m pytest test/test_omx_host_inventory.py -q -p no:cacheprovider --basetemp X:\DevTemp\rosy-omx-inventory`로 실패→구현→통과를 확인한다. 인벤토리 파일이 현행 Compose에 자동 투입된다고 주장하지 않는다. 해당 경로만 커밋한다.

## Task 2: 호스트의 실제 장치 배타성 사전점검

**Files:** Modify `deploy/omx/preflight.py`; create `test/test_omx_multi_preflight.py`; update `deploy/omx/README.md`.

1. 기존 `resolve_devices()`의 주입형 probe를 재사용해 `resolve_host_devices(inventory, host_id, probe=...)`를 시험으로 먼저 정의한다. enabled 작업대의 follower/leader가 존재하는 읽기·쓰기 가능한 character device인지 확인하고, symlink를 해석한 **실제 경로**가 한 호스트의 다른 작업대와 겹치면 거부한다.
2. 한 작업대 누락·권한 거부·동일 포트·두 작업대의 다른 by-id가 같은 실제 장치를 가리키는 사례를 거절한다. 한 작업대의 실패가 다른 작업대의 장치를 대체 선택하지 않게 한다. 카메라가 아직 선정되지 않았으면 카메라 장치 접근을 열지 않는다.
3. 출력에는 작업대별 검증된 장치 경로만 포함한다. 토큰·원본 영상·현재 `ttyACM` 번호 추측을 로그에 쓰지 않는다. Windows 단위시험에는 fake probe만 쓰고, 실제 Linux readback은 별도로 기록한다.
4. `python -X utf8 -m pytest test/test_omx_workstation.py test/test_omx_multi_preflight.py -q -p no:cacheprovider --basetemp X:\DevTemp\rosy-omx-preflight`로 회귀를 확인하고 해당 경로만 커밋한다.

## Task 3: 단일·이중 ROS graph의 실행 가능성 확인

**Files:** Create `docs/validation/omx-two-instance-ros-sim-<YYYY-MM-DD>/README.md`; modify `docs/plans/2026-09-26-omx-ai-workstation-runtime.md` only when verified commands are known. Implementation files, if needed, stay under `deploy/omx/` and receive focused tests under `test/`.

1. `deploy/omx/stack.lock.yaml`의 exact source를 사용해 vendor follower/leader launch와 mock 경로가 실제로 제공하는 인자, ROS node/action/topic/TF 이름, RMW를 기록한다. RMW가 다르거나 namespace/절대 이름이 겹치면 두 인스턴스 기동을 HOLD하고 명시적 bridge/launch 설계를 ADR로 결정한다. 임의의 ROS_DOMAIN_ID 값만 바꾸고 격리됐다고 판정하지 않는다.
2. 장치 허가가 없는 ROS-SIM에서 `omx_01`, `omx_02`를 함께 실행한다. 각 인스턴스의 action/feedback/status를 별도 관측하고, 한 인스턴스 종료·재시작·취소가 다른 인스턴스에 영향을 주는지 본다. mock 패키지가 없으면 그 사실과 필요한 exact package/launch를 기록하고 여기서 중단한다. 가짜 `joint_states`나 hardware plugin을 수용 증거로 넣지 않는다.
3. 명령 소유자는 인스턴스당 하나여야 한다. leader teleop과 trajectory action의 동시 실행은 거부되는지 확인한다. 관측·결과·실제 실행 revision을 ROS-SIM으로만 기록한다. SITE/DEVICE를 승격하지 않는다.

## Task 4: native OMX 서비스와 배포 산출물 후보

**Prerequisite:** Task 3에서 exact vendor launch, RMW, graph 격리와 명령 소유권이 확인되고, D-281의 native 후보가 수용돼야 한다.

**Files:** Create `deploy/omx/native/rosy-omx@.service`, `deploy/omx/native/run-workcell.py`, `test/test_omx_native_service.py`; update `deploy/omx/README.md` and the existing OMX 실행 계획. Native dependency/build manifest and artifact instructions stay under `deploy/omx/native/`.

1. 실패 시험을 먼저 작성한다. 인스턴스 설정 누락, `enabled: false`, 장치 사전점검 실패, 호스트 ID 불일치, pin/digest 불일치, 보정 revision 누락은 **vendor launch 전** 종료해야 한다. 서비스 재시작은 이전 목표를 복원하거나 자동 재발행하지 않는다. systemd unit은 인스턴스별 제한된 사용자·장치 ACL·설정 경로를 사용하고 Docker 데몬에 의존하지 않는다.
2. `run-workcell.py`는 검증된 인벤토리의 해당 인스턴스만 해석하고 Task 2의 장치 사전점검을 실행한 뒤, Task 3에서 확인한 잠긴 launch만 `exec`한다. shell 문자열 조합이나 `/dev` 전체 허가는 사용하지 않는다. 실제 driver/joint/camera 값을 알기 전에는 운용 enabled 프로필을 만들지 않는다.
3. native Jazzy 및 vendor dependency의 exact revision, 빌드 환경, 설치 파일, SHA-256/manifest를 산출물에 묶는다. 기존 Pinky ARM64 릴리스나 `deploy/robot` Docker 경로에 끼워 넣지 않는다. `python -X utf8 -m pytest test/test_omx_native_service.py test/test_native_runtime_docs.py -q -p no:cacheprovider --basetemp X:\DevTemp\rosy-omx-native`와 Linux systemd unit 정적 검증을 기록한다. ARTIFACT는 실제 amd64 호스트의 재현 빌드·digest readback 후에만 판정한다.

## Task 5: 첫 OMX 실물과 두 대 동시 시험

**Prerequisite:** 실물 OMX-AI revision, follower/leader의 물리 ID, 전원, 정지 수단, 카메라 모델·보정이 확보돼야 한다. 장치 소유자의 감독 아래 실행한다.

**Files:** `src/products/omx/progress.md`, `deploy/progress.md`, `docs/validation/omx-device-<YYYY-MM-DD>/README.md`; 실측 후에만 제품 프로필과 native 설정을 갱신한다.

1. 한 대에서 실제 serial·joint feedback·bounded trajectory·cancel/timeout·연결/전원 상실·물리 정지·재기동 후 무명령 상태를 관측한다. 카메라 frame timestamp와 calibration revision을 같은 장치 기록에 묶는다. 이 단계가 통과하기 전에는 `omx.enabled: false`를 유지한다.
2. 두 대를 같은 PC에 연결해 서로 다른 USB/controller path, graph, 카메라, 보정, 제어 인스턴스를 확인한다. 두 팔과 천장 Vision·Fleet을 함께 실행하여 제어 주기/지연, CPU·GPU·메모리·온도, USB drop, 사이트 요청 응답을 측정한다. 한 OMX 서비스/장치 장애가 다른 OMX에 주는 영향을 기록한다.
3. 제조사 요구, 실제 작업 허용 시간, 물리 정지 요구에서 수용 기준을 시험 **전** 정한다. 공유 PC가 이를 만족하지 못하거나 공통 장애가 현장 요구에 맞지 않으면 같은 장비 ID/설정 revision을 유지하며 OMX 한 대 또는 두 대를 별도 호스트로 옮겨 재시험한다. SOURCE/ROS-SIM 성공으로 DEVICE/FIELD를 대신하지 않는다.

## Task 6: 사이트 연동과 배치 이전의 별도 결정

1. 현행 Fleet `robots.yaml`·REST 목표·사이트 SQLite를 OMX 작업대 등록부나 원격 팔 명령으로 재사용하지 않는다. 사이트에서 workcell 상태/작업을 필요로 하는 구체적 시나리오를 수집한 뒤, capability·인증·작업 접수와 최종 완료·취소·정지·카메라 권한을 별도 ADR/API 계약으로 정한다.
2. 호스트 이전 절차는 이전 인스턴스 종료와 장치 점유 해제 확인 → 새 호스트 장치/보정/산출물/자격 증명 확인 → 무명령 상태 기동 → 작업 재승인 순서로 쓴다. 사이트 Compose의 Fleet task DB를 다른 호스트와 공유 마운트하지 않는다.
3. 실제 현장 호스트에서 Site/Fleet/Vision 재시작, 공유 PC 전원 상실, 백업·복구와 Pinky 로컬 CORE 존속을 따로 확인한다. 결과는 SITE/FIELD 증거로 남기고 D-281의 공유 배치 채택 또는 분리 배치 결론을 갱신한다.

## 완료 판정

- **지금 문서화된 범위:** D-281 제안과 이 실행 계획은 배치·검증 순서를 정한다. 로봇 기능을 켜지 않는다.
- **SOURCE/LOCAL:** 인벤토리와 장치 배타성 테스트, native unit/manifest 정적 검사, 사이트와 OMX의 런타임 경계 확인.
- **ROS-SIM/ARTIFACT:** 두 OMX graph 격리와 잠긴 native amd64 산출물 각각의 증거.
- **DEVICE/SITE/FIELD:** 한 대와 두 대의 정지·복구·동시 부하·호스트 장애 및 실제 작업 결과. 이 단계의 실패 원인으로 공유 호스트/분리 호스트를 선택한다.
