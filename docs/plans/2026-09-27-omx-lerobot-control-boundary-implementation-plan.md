# OMX LeRobot Control Boundary Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** OMX-AI 고정 작업대에서 ROS 운영 제어와 native LeRobot 실험을 배타적으로 실행하고, 데이터·정책 입력을 장치 로컬 제어 경계에 안전하게 연결할 수 있는 근거를 단계별로 확보한다.

**Architecture:** 기존 `omx_adapter`의 단일 명령 소유 정책과 ROS action/camera 바인딩을 유지한다. OMX-F 직렬 버스는 한 시점에 하나의 작업대 인스턴스만 열며, ROS 운영 후보와 LeRobot 직접 제어 실험은 명시적 모드 전환을 거친다. Fleet은 미래의 Device Action만 요청하고 최종 trajectory와 하드웨어 정지는 OMX 로컬에 둔다. 이 문서는 [기존 작업대 구현 계획](2026-09-26-omx-ai-workstation-runtime.md)의 후속 경계 계획이며 이미 끝난 OCI/ROS-SIM 작업을 재수행하라는 뜻이 아니다.

**Tech Stack:** Ubuntu 24.04, ROS 2 Jazzy, ROBOTIS `open_manipulator`/`ros2_control`, 기존 `omx_adapter` Python, systemd 운영 후보, 별도 고정 버전 LeRobot/Dynamixel SDK 실험 환경, rosbag2/LeRobotDataset 오프라인 데이터 검증.

**상태:** [ROSY Platform 역할·계약 부모 계획](2026-09-27-rosy-platform-role-and-contract-implementation-plan.md)의 OMX 장치·LeRobot 하위 트랙. D-273 Accepted(구현 순서), D-281/D-282/D-299 Proposed(OMX 실행·제어 배치). 이 계획의 작성으로 `omx.enabled: false`, 원격 OMX API, DEVICE/FIELD gate가 바뀌지 않는다.

---

## OMX 하위 트랙의 현재 폴더와 책임 (2026-09-27 checkout)

```text
Rosy OS/
├─ src/
│  ├─ contracts/foundation/core_common/   # 현행 Pinky CORE 중심 공유 타입·프로토콜
│  ├─ devices/omx/adapter/
│  │  ├─ omx_adapter/
│  │  │  ├─ command_owner.py                 # ROS-free 단일 명령 소유·HOLD 정책
│  │  │  ├─ ros_runtime.py                   # ROS action/joint-state 바인딩
│  │  │  ├─ camera_contract.py
│  │  │  └─ ros_camera_runtime.py
│  │  └─ test/
│  ├─ products/omx/config/omx.disabled.yaml # 제품 설정, 현재 비활성
│  └─ site/fleet/                       # 현행 Pinky 중심 사이트 작업
├─ deploy/omx/                          # 잠긴 벤더 소스·OCI/Compose 개발 후보
│  ├─ stack.lock.yaml
│  ├─ host_inventory.py                 # 호스트/작업대 정적 배정
│  ├─ preflight.py                      # by-id 장치 검사
│  └─ compose.yaml
└─ docs/{adr,plans,reference,validation}/
```

현재 `command_owner.py`/`ros_runtime.py`는 실물 OMX 운영 승인이나 독립 물리 정지를 제공하지 않는다. `deploy/omx`의 OCI 하드웨어 셸은 개발 후보이며 D-246의 운영 actuator 배포 방식이 아니다. LeRobot 직접 제어 코드와 OMX 원격 작업 API는 이 트리에 아직 없다.

## OMX 하위 트랙의 목표 폴더 배치 (단계별 생성 제안)

```text
Rosy OS/
├─ src/
│  ├─ contracts/foundation/core_common/           # 현행 계약 유지; OMX 강제 의존 없음
│  ├─ devices/omx/adapter/
│  │  ├─ omx_adapter/
│  │  │  ├─ command_owner.py                        # 기존 최종 명령 중재 정책
│  │  │  ├─ ros_runtime.py                          # 기존 ROS action 접점
│  │  │  ├─ control_mode.py                         # [제안] 모드/소유권 전환 검증
│  │  │  └─ policy_input.py                         # [후순위] 학습 정책 제안 검증
│  │  └─ test/                                     # 모드·fault·중복 소유 거부 시험
│  ├─ products/omx/config/omx.disabled.yaml       # 실물 게이트 전 비활성 유지
│  └─ site/fleet/                                  # 첫 OMX bench 단계에서는 변경 없음
├─ deploy/omx/
│  ├─ stack.lock.yaml                             # 기존 ROS 벤더 버전 잠금
│  ├─ host_inventory.py · preflight.py            # 기존 host/장치 검사 재사용
│  ├─ native/                                     # [제안] 작업대별 systemd 실행·정지 후보
│  └─ lerobot/                                    # [제안] 독립 bench 환경 잠금·실행 안내
├─ tools/omx/                                     # [후순위] 오프라인 bag→dataset 검증 도구
└─ docs/
   ├─ adr/                                       # 제어권·API 결정
   ├─ plans/                                     # 실행 절차
   └─ validation/                                # ROS-SIM·DEVICE·FIELD별 증거
```

`native/`, `lerobot/`, `tools/omx/`는 **아직 존재하지 않는 목표 경로**다. 저장소 밖의 실제 포트·보정·자격 정보는 호스트 `/etc/rosy/omx/` 등 비공개 설정에 둔다. 영상·학습 데이터와 모델 가중치도 소스 트리에 넣지 않고 ID·해시·보정 revision의 manifest만 추적한다. 이 단계에서 `src/runtime/` 아래에 범용 OMX 실행기나 Pinky `core_common` 전체를 새 공통 라이브러리로 복제하지 않는다(D-296).

## 실행 순서와 완료 조건

| 단계 | 결과물 | 확인할 증거 | 중단 조건 |
|---|---|---|---|
| 0. 장비·버전 확정 | OMX-L/F 실물 리비전, 포트, 펌웨어, 전원·독립 정지 수단, ROS·LeRobot 버전 표 | serial/by-id·관절·그리퍼·카메라·보정 provenance | 실물 identity나 정지 수단 불명 |
| 1. 모드/포트 배타성 | 작업대별 ROS/LeRobot/비활성 모드 전환 계약과 native runner 후보 | 중복 포트, 미종료 프로세스, 재시작, 포트 분리의 거부 시험 | 전환 후 이전 owner가 FD를 유지하거나 자동 재개 |
| 2. ROS 운영 후보 | 기존 action owner와 vendor controller의 native 연결·시간 경계 | 단일 최종 trajectory, joint readback, 취소 최종 결과·stale/HOLD | 동시 writer, 가짜 피드백, cancel 응답만으로 정지 주장 |
| 3. LeRobot bench | 고정 버전 독립 환경에서 leader/follower 실험 | ROS owner 종료 및 포트 반환 뒤 teleop·기록; 종료 후 재시작 금지 확인 | ROS·LeRobot 동시 접근 또는 무단 운영 capability 노출 |
| 4. 데이터 호환 | rosbag2/LeRobot dataset 매핑·검증 도구 | 시각·단위·joint/gripper·카메라·보정·결과의 샘플 대조 | 누락/불일치 데이터가 조용히 학습 입력으로 승격 |
| 5. 정책 입력 | 정책 출력을 유한한 제안으로 받는 어댑터 | 제한·fresh state·deadline·취소·fault·재시작 거부 | 정책이 최종 ROS action 또는 serial을 우회 호출 |
| 6. 사이트 연결 | 별도 승인된 OMX Device Action API와 Fleet Mission Step | ID 연결, 수락/완료/UNKNOWN, 인증·취소·readback | OMX를 기존 Pinky `robots.yaml`에 끼워 넣거나 Fleet이 arm을 직접 제어 |

1–3의 SOURCE/LOCAL·ROS-SIM 통과와 4–5의 데이터/정책 검증은 DEVICE를 대체하지 않는다. 실제 팔 동작, 물리 정지, 전원 상실, 부하·보정은 DEVICE에서 측정하고 고정 작업대 작업 결과는 FIELD에서 별도로 판정한다. Pinky 탑재와 이동 조작은 이 계획의 단계 6 이후 별도 계약·FIELD 수용이다.

### Task 1: 실물 inventory와 두 런타임 잠금

**Files:** Modify `deploy/omx/host-inventory.yaml.example`, `deploy/omx/stack.lock.yaml`(ROS 쪽 변경이 있을 때만), `deploy/omx/README.md`; Create `deploy/omx/lerobot/README.md`, `deploy/omx/lerobot/requirements.lock` 또는 동등한 해시 고정 파일; Test `test/test_omx_host_inventory.py` 및 잠금 검증 시험.

1. 실물 OMX-L/F 모델·리비전, serial/by-id, 모터·카메라 식별, 물리 정지 경로를 비공개 inventory와 증거에 기록한다. 공식 문서의 기본 장치명·공장 설정은 실물 readback을 대신하지 않는다.
2. 선택한 LeRobot 릴리스/커밋과 Dynamixel 의존성을 재현 가능한 독립 환경으로 잠근다. 기존 ROS 벤더 소스 잠금과 혼합하지 않는다.
3. 테스트에서 빈 값, 같은 follower/leader 포트, 두 작업대의 중복 포트, 버전 미고정을 거부하도록 한 뒤 최소 구현·재검증·커밋한다.
4. Exit: 실제 하드웨어 owner 후보와 버전·정지 수단을 표로 설명할 수 있다. 실물 정보가 없으면 정적 설계만 완료로 기록하고 장치 실행은 대기한다.

### Task 2: 모드 전환·단일 owner 계약

**Files:** Create `src/devices/omx/adapter/omx_adapter/control_mode.py`, `src/devices/omx/adapter/test/test_omx_control_mode.py`, `deploy/omx/native/`의 service/runner 후보; Modify `deploy/omx/preflight.py`, `deploy/omx/README.md` as needed.

1. 먼저 ROS→LeRobot, LeRobot→ROS, 중단·크래시·USB 재연결·재부팅의 상태 전이표를 작성한다. 허용 조건은 신규 명령 차단, 동작/정지 readback, 이전 프로세스 종료 및 FD 해제, 포트·보정 재확인, 명시적 재승인이다.
2. 단위 시험을 먼저 추가해 중복 owner, stale 포트, owner 미종료, 전환 중 요청, 이전 명령 재생이 거부되는지 확인한다.
3. 하나의 관리 진입점만 장치 접근 권한을 받아 선택한 모드를 실행하도록 구현한다. 파일 잠금만으로 임의 외부 프로세스의 포트 점유까지 방지한다고 주장하지 않는다; Linux 서비스 권한·프로세스 FD·장치 점유를 함께 시험한다.
4. Exit: 소프트웨어 전환 계약 LOCAL 통과. 실제 포트 배타성과 정지는 DEVICE에서 검증할 때까지 비활성 유지.

### Task 3: 기존 ROS action 경로의 native 검증

**Files:** Modify `src/devices/omx/adapter/omx_adapter/command_owner.py`, `ros_runtime.py`와 해당 기존 테스트는 검증에서 확인된 결함이 있을 때만; Create `deploy/omx/native/`의 작업대별 systemd 구성·설치/복구 안내; Update 기존 [작업대 구현 계획](2026-09-26-omx-ai-workstation-runtime.md) P1 증거.

1. 잠긴 벤더 ROS stack, RMW, namespace/domain, 실제 실행 파일·FD·publisher/action server를 읽어 단일 owner임을 확인한다.
2. ROS-SIM에서 trajectory 한계, 서로 다른 입력 후보의 경합, cancel ack와 최종 결과, stale joint state, 타임아웃·재시작을 검증한다. 기존 시뮬 결과는 재사용하되 target Linux에서 남은 timing/gripper 이슈를 닫는다.
3. 실물 bench에서는 독립 정지 수단을 준비한 절차로 무부하·낮은 범위부터 실행하고, 포트 분리·전원·정지 후 실제 관절/드라이버 상태를 기록한다.
4. Exit: SOURCE/ROS-SIM/DEVICE 증거를 각각 기록한다. 하나의 action 성공이나 software HOLD만으로 물리 정지를 주장하지 않는다.

### Task 4: native LeRobot 격리 실험

**Files:** Create `deploy/omx/lerobot/README.md`와 실행 검증 스크립트(필요 시); Test `test/test_omx_lerobot_mode.py` 등 환경·모드 가드 시험; Store 실험 기록 under `docs/validation/`.

1. ROS native owner가 종료되고 follower 포트 FD가 비었는지 확인한 뒤 명시적으로 실험 모드에 진입한다.
2. 공식 OMX LeRobot의 leader/follower 연결과 선택 카메라를 실물 모델에 맞춰 최소 teleop·짧은 기록으로 확인한다. 종료 후 LeRobot도 FD를 반환해야 한다.
3. ROS owner가 남아 있을 때, 다른 workcell 포트를 선택했을 때, 카메라·보정이 불일치할 때 실행이 거부되는 음성 시험을 한다.
4. Exit: 독립 실험 환경의 SOURCE/DEVICE 기록. 이 단계는 ROSY 운영 팔 제어 또는 Fleet 접근을 활성화하지 않는다.

### Task 5: 데이터·정책 경계

**Files:** Create `tools/omx/`의 오프라인 변환·검증 도구와 테스트; Add `src/devices/omx/adapter/omx_adapter/policy_input.py` 및 테스트는 규칙 기반 작업·데이터 기준선 후에만; Update 데이터 manifest 계약 문서.

1. 동일한 짧은 episode에서 ROS 관절/명령·카메라 시각과 LeRobot observation/action을 수작업 기준표로 먼저 매핑한다.
2. 변환 시험은 누락 프레임, 시각 역전, 단위·joint 순서·그리퍼 부호·보정 revision 불일치를 거부한다. 결과 manifest에 원본 bag, 변환 도구, dataset 버전과 해시를 남긴다.
3. 정책 출력은 `ArmCommandOwner` 앞의 제안으로만 받는다. joint limit, freshness, deadline, owner lease, 취소·fault/HOLD를 통과한 명령만 action으로 보낸다.
4. Exit: 데이터 품질과 규칙 기반 작업의 DEVICE 기준선 대비 정책 성공률·지연·개입률을 별도로 측정한다. LeRobot dataset 생성 자체는 성공 판정이 아니다.

### Task 6: 장치 API와 사이트 미션 경계 (별도 승인 전 설계만)

**Files:** Future OMX API contract and typed schema under `src/contracts/` only after D-18/API decision; `src/site/fleet/` only after Device Action contract; `docs/reference/ROSY API & Protocol Reference.md` in same change.

1. `workcell_id`, `instance_id`, `mission_id`, `step_id`, `action_id`, request expiry, cancel, accepted/completed/unknown evidence를 먼저 계약한다. `task_id` 등 현행 Pinky 필드를 몰래 재해석하지 않는다(D-298).
2. 인증·상태 freshness·중복 요청·연결 상실·UNKNOWN 재조회 테스트를 작성한다. Fleet은 공개 API만 호출하고 DDS/serial/trajectory를 직접 열지 않는다.
3. 필요가 두 장치에서 확인될 때만 식별·결과 의미를 작은 공통 계약으로 추출한다. OMX 로컬 실행 코드를 Pinky CORE에 합치지 않는다.
4. Exit: 별도 ADR/API·DEVICE/FIELD 수용 전에는 구현을 배포·광고하지 않는다.

## 검증과 되돌리기

- 문서 단계: `python tools/harness/rosy_harness.py generate`, `python tools/harness/rosy_harness.py lint`, `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`.
- 코드 단계: 해당 `src/devices/omx/adapter/test/`와 `test/test_omx_*`를 먼저 실행한다. ROS-SIM, target Linux, 실제 장치·현장 증거는 별도 기록한다.
- 실패 시: 서비스/프로필을 비활성으로 되돌리고 신규 명령을 차단한다. 모드 전환 실패, action 결과 불명, USB 재연결은 자동 재시도나 이전 trajectory 재생으로 복구하지 않는다. 기록된 상태·원인·물리 readback을 확인한 뒤 명시적으로 재승인한다.

**근거:** [D-273](../adr/D-273-omx-camera-stream-and-arm-control-order.md), [D-281](../adr/D-281-site-host-placement-and-omx-instance-isolation.md), [D-282](../adr/D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-296](../adr/D-296-device-middleware-and-site-orchestration-terminology.md), [D-298](../adr/D-298-mission-action-and-stop-evidence-terminology.md), [D-299](../adr/D-299-omx-lerobot-development-and-command-ownership.md), [공식 LeRobot OMX](https://huggingface.co/docs/lerobot/omx), [ROBOTIS open_manipulator](https://github.com/ROBOTIS-GIT/open_manipulator).
