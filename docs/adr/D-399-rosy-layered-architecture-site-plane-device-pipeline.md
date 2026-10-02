## D-399 ROSY 계층 아키텍처: Application · Fleet(사이트) · 장치별 Command Pipeline

**Status:** Proposed (2026-10-01, 구조·배치 결정). 패키지 이동, 새 서비스 구현, OMX 장치 API, 원격 추론 경로는 포함하지 않는다. 후속 ADR(§7)이 각 블록을 구체화한다.

## 배경

- 사용자는 ROSY 구조도 한 장을 제시했다. 구성은 다음과 같다.
  - 애플리케이션: Palletizing, Pick&Place 등
  - 명령 출처 셋: 고전 플래너, AI 정책, 수동 조종
  - 장치 공통 Command Pipeline: Action Gateway → Command Arbiter → Safety Guard → Motion Executor → Controller Adapter
  - 드라이버: OMX-AI, Pinky Pro, 미래 로봇
  - AI Runtime: LeRobot, VLA, Gemini Robotics, 고수준 의사결정 AI, Custom Policy
- 이 그림은 블록의 **역할**은 기존 결정과 대부분 같다. 다만 **배치**(사이트인지 장치인지)를 표시하지 않는다. 그대로 읽으면 다음 결정과 어긋난다. 각 결정 옆에 현재 Status를 적는다.
  - "ROSY CORE"에 Mission Manager와 Task Executor가 들어 있다. 하지만 현재 CORE(`src/runtime/gateway`, `rosy_core`)는 Pinky 한 대의 장치 런타임이고, 외부 API이자 최종 `cmd_vel`의 단일 writer다(D-38, D-62, D-74 Accepted). Mission, Step 순서, 스케줄, 원장은 사이트 Fleet이 맡는다(D-12, D-70, D-271, D-369 Accepted).
  - 하나의 Command Pipeline이 여러 장치를 관장하는 모양이다. 이는 OMX가 Pinky CORE를 거치지 않는다는 결정(D-390 Accepted)과 장치별 로컬 owner(D-336 Accepted; D-282, D-299 Proposed)에 어긋난다.
  - 미들웨어가 "ROS 2 / Zenoh"로 그려져 있다. 이는 CycloneDDS 단일 RMW(D-117 Accepted)와 사이트 패브릭으로서의 Zenoh 기각(D-59 Accepted)에 어긋난다.
  - AI Runtime이 Motion Intent를 직접 낸다. 이는 원격 AI가 로봇 명령 경로에 들어가는 것을 막은 결정(D-231 §4 Accepted, D-310 이후에도 유효)과, AI 출력을 제안·관측으로 시작한다는 결정(D-326 §2, D-331, D-369, D-376 Accepted)에 어긋난다.
  - Command Arbiter가 두 번 그려져 있다.
- 목표 아키텍처 문서([01](../architecture/01_ROSY_OS_Target_Architecture.md), [11](../architecture/11_ROSY_AI_and_Physical_AI.md))는 이미 Control Plane과 노드 로컬 Runtime을 나눈다. 그리고 "AI는 액추에이터 루프를 직접 제어하지 않는다"고 적는다. 이 ADR은 사용자 구조도를 그 방향에 맞춰 블록마다 배치를 정한다.
- AI 정책은 두 부류로 나뉜다.
  - LeRobot은 OMX-AI(`omx_follower`/`omx_leader`)를 관절공간으로 지원한다. 공식 ROS 2 브리지는 없다(huggingface/lerobot RFC #4368, 2026-10-01 기준 open).
  - ACT 같은 모방학습 정책은 30 Hz 안팎의 관절 청크를 낸다. Pinky는 Wi-Fi와 relay를 거치므로, 이를 네트워크 너머에서 닫힌 루프로 돌릴 수 없다.
  - Gemini Robotics 같은 숙고형 모델은 초 단위로 제안을 낸다.
  - 두 부류를 한 "AI Runtime" 상자에 묶으면 배치와 안전 경로를 정할 수 없다.

## 결정

### 1. 다섯 층과 배치

```text
APPLICATION          Palletizing · Pick&Place · Navigation · Inspection · …
  (사이트)                 │  Mission 요청
FLEET                Mission Manager · Task Executor(Step 하달) · 등록/identity 정본
  (사이트, 구조도의       · 상태/Fault 집계 · 숙고형 AI 제안 입구(Fleet 승인)
   "Control Plane")        │  Task / Step — 역할 계약(REST/WSS, 동일 호스트는 UDS). DDS 아님
장치 미들웨어         장치마다 한 벌. 예: Pinky CORE, OMX 로컬 owner
  (구조도의            Action Gateway → 스킬(Classical Planner · 반응형 정책 · Manual Teleop)
   "Device Runtime")   → Motion Intent → Command Arbiter(1) → Safety Guard → Motion Executor
                       → Controller Adapter(단일 writer)
                       + 장치 상태·Lifecycle·Fault (장치가 정본)
                           │  ROS 2 (CycloneDDS, 장치 내부)
DRIVERS              Pinky Pro HW · Dynamixel OMX-F (+ OMX-L 읽기) · Future Robot
물리 E-stop          모든 층과 독립된 경로, 소프트웨어보다 우선 (D-369 §5)
```

- **용어:** D-296(Accepted)의 이름이 정본이다. 사이트 소유자는 "Fleet", 장치 경계는 "장치 미들웨어"라고 부른다. 구조도의 "Site Control Plane"과 "Device Runtime"은 그 두 이름의 별칭으로만 쓴다. D-296은 바꾸지 않는다.
- **CORE:** 구조도의 "ROSY CORE"는 두 부분으로 나누어 읽는다. Mission Manager, Task Executor, 등록, 집계는 Fleet이다. Command Arbiter, 상태, Lifecycle, Fault는 장치 미들웨어다. 이름 "CORE"는 지금처럼 장치 런타임(Pinky의 `rosy_core`)을 가리킨다. D-12, D-70은 그대로 유지한다.
- **Command Pipeline은 장치마다 한 벌이다.** 계약은 공통으로 둔다. 공통 계약은 Motion Intent 스키마, Arbiter 판정 형식, Safety Guard 판정 형식, 단일 writer다. 인스턴스는 장치 로컬이다. 하나의 Pipeline 프로세스가 여러 장치를 관장하지 않는다(D-390; D-282 Proposed).
- **Command Arbiter는 장치당 하나다.** Fleet은 Arbiter를 갖지 않고, Task를 장치에 제출할 뿐이다. 우선순위는 다음과 같다.
  - Pinky는 현행 CORE 순서를 따른다. 순서는 EMERGENCY > SAFETY > MANUAL > DOCKING > NAVIGATION > FLEET > IDLE이다. 출처는 CORE SRS §8.1과 `src/runtime/services/core_features/command/arbitration.py`다.
  - 다른 장치의 우선순위 표와, MANUAL이 진행 중인 OMX phase를 어떻게 선점하는지는 후속 ADR 5가 정한다. OMX phase 선점은 D-376 §6의 UUID 취소/HOLD와 맞아야 한다.
  - 이 ADR이 고정하는 것은 하나뿐이다. 어느 장치든 정지 계열(EMERGENCY, SAFETY)이 모든 동작 출처보다 위다.
- **Safety Guard는 단일 writer 바로 앞에 있다.** Fleet이 끊겨도 장치는 정지하거나, 승인된 로컬 동작만 계속한다([01 §4](../architecture/01_ROSY_OS_Target_Architecture.md)).

### 2. AI는 두 부류로 나눈다

| 부류 | 예 | 배치 | 출력 | 경로 |
|---|---|---|---|---|
| **숙고형 AI** | Gemini Robotics, VLA, 고수준 의사결정 AI(미션·태스크 선택과 재계획) | Fleet 또는 사이트 GPU 노드 | Mission·Task·Step **제안** | Fleet 승인(D-330) → 일반 Task 경로. 제공자 계약은 D-331, D-392 |
| **반응형 정책** | LeRobot ACT, Diffusion Policy, Custom Policy | **장치 미들웨어와 같은 호스트** | 관절/속도 청크 → 스킬 안의 Motion Intent | 스킬 엔벌로프 → Arbiter → Safety Guard → 단일 writer |

**숙고형 AI**
- Motion Intent를 내지 않는다.
- VLA 출력도 이 부류다. D-326 §2와 D-209의 `backend_learned` 경계에 따라 제안·관측으로 시작한다. VLA를 반응형 정책으로 옮기려면 별도 ADR이 필요하다.

**반응형 정책**
- **이미 Fleet이 승인해 장치에 하달한 Task 안의 스킬 하나로만** 실행된다.
- 스킬은 Task가 지정한 엔벌로프 안에서만 Motion Intent를 낸다. 엔벌로프는 작업 영역, 시간 상한, 속도·스텝 상한, 성공/실패 종료 조건이다.
- 엔벌로프를 벗어나거나 시간을 넘기면 HOLD로 끝난다.
- 정책 프로세스는 시리얼 버스, ROS 액션, `cmd_vel`을 직접 쓰지 않는다(D-299 Proposed). 정책을 게이트가 걸린 플러그인으로 다루는 D-99와 같은 방향이다.
- 이 스킬은 D-326 §3의 재판단 폐루프 밸브(`POLICY_DISPATCH_ENABLED`)와 다른 장치이고, 그 밸브를 열지 않는다(D-392 §7).

**추론 위치**
- 반응형 정책의 추론은 **장치 미들웨어와 같은 호스트**에서 한다. 고정 OMX 작업대라면 그 작업대 PC다.
- 다른 호스트(사이트 GPU, LAN 추론 서버)에서 추론하려면 후속 ADR 1이 D-231 §4를 명시적으로 개정해야 한다. 그 ADR은 전송 경로도 정해야 한다. 로봇의 Cyclone 프로필은 loopback이고(compose·`rosy_env.sh`가 설정하며 D-121은 CORE가 `CYCLONEDDS_URI`를 정하지 않는다고 기록한다), DDS 브리지는 D-282 §5에 따라 별도 ADR이 필요하다.

**LeRobot 개발/녹화 모드**
- 이 모드에서는 LeRobot이 버스를 단독으로 소유한다(D-299 §2). 이 구조 밖의 별도 모드다.
- 이때 운영 owner와 그 Action Gateway는 정지해 있다. 따라서 Fleet은 그 장치를 사용 불가로 보고 Task를 하달하지 않는다.
- 모드 전환은 D-299의 전환 절차를 따른다.

### 3. 미들웨어

- 장치 내부는 ROS 2 CycloneDDS다(D-117, D-121, D-122). 사이트와 장치 사이는 역할 계약이다. HTTPS REST/WSS를 쓰고, 동일 호스트는 UDS를 쓴다(D-59, D-336 Accepted; D-269 Proposed).
- ROBOTIS 스택의 Zenoh 설정은 별도 도메인에 격리할 때만 쓴다. Zenoh를 사이트 패브릭으로 채택하려면 D-117과 D-59를 대체하는 별도 ADR과 벤치가 필요하다. 이 ADR은 그 전환을 결정하지 않는다.

### 4. 등록 · 상태 · Lifecycle · Fault

- **Fleet은 등록과 identity의 정본이다**(enrollment, roster; D-361 Proposed). Fleet에 등록되지 않았거나 등록 identity와 다른 장치에는 Task를 하달하지 않는다.
- **capability의 출처는 장치 프로필이다**(D-11, D-347). **장치 상태의 정본은 장치다**(D-296 §4). Fleet은 이를 집계만 한다.
- capability lifecycle은 D-347이 그대로 맡는다. **장치 Lifecycle**(기동, 준비, 열화, 정지)과 **장치 Fault 계약**은 후속 ADR 2가 정의한다. 이 ADR은 D-347을 장치 Lifecycle로 확장하지 않는다.
- 후속 ADR 2가 묶을 Fault 조각은 다음과 같다.
  - D-32 오류 코드
  - `core_features/{recovery,diagnostics}`
  - `rosy-hw-probe`
  - 장치 카드
  - commissioning 인증서

### 5. Application 층

- **Mission을 실행하는** Application은 Fleet에 Mission을 요청한다. Fleet을 건너뛰고 장치에 동작을 하달하지 않는다.
- 사람용 제품 클라이언트가 장치 API를 쓰는 경로는 이 ADR이 좁히지 않는다. 대시보드, SDK, Pilot이 여기에 해당한다(D-74, D-369 §7).
- 팔 셋업과 티칭처럼 사람이 장치 곁에서 하는 작업은 OMX 장치 API가 있어야 한다. D-282 §5와 D-336은 아직 이를 열지 않았다. D-390의 lease는 시뮬레이션 전용이다. 따라서 셋업·티칭 경로는 별도 ADR로 정한다.
- 첫 Application 후보는 팔에 묶이지 않는 팔레타이징·셋업 앱 Rosy Cell이다(`src/site/cell`, `rosy_cell`, D-377 이름 규칙). 범위와 계약은 후속 ADR 4가 정한다. 실행 순서는 [로드맵](../plans/2026-10-01-rosy-layered-architecture-roadmap.md)에 둔다.

### 6. 사용자 구조도와의 대응

| 구조도 블록 | 이 ADR의 위치 |
|---|---|
| APPLICATION | Application (사이트) |
| ROSY CORE: Mission Manager, Task Executor, Device Registry | Fleet (Registry는 등록/identity 정본) |
| ROSY CORE: Command Arbiter, State Manager, Lifecycle Manager, Fault Manager | 장치 미들웨어 (장치마다). Fleet은 집계 |
| Classical Planner | 장치 스킬 (Nav2; OMX 플래너는 D-376 HOLD, 후속 ADR 3) |
| AI Policy Gateway / AI Runtime | 숙고형 → Fleet 제안 입구. 반응형 → 같은 호스트 엔벌로프 스킬 |
| Manual Teleop | 장치 Action Gateway의 MANUAL 입력 (Pilot, dashboard. OMX 리더 팔은 후속 ADR) |
| Motion Intent | 장치 내부, 스킬과 Arbiter 사이의 계약 |
| COMMAND PIPELINE | 장치마다 한 벌 |
| ROS 2 / Zenoh | 장치 내부 CycloneDDS. 사이트와 장치 사이는 REST/WSS/UDS |
| Drivers | 장치 드라이버 (`src/products/*`, `src/drivers/*`) |

### 7. 후속 ADR

1. **반응형 정책 엔벌로프 스킬 계약.** LeRobot 추론 → Motion Intent, 종료 조건, 녹화 모드와의 관계, LeRobotDataset 변환 매핑을 정한다. 같은 호스트 밖에서 추론하려면 이 ADR이 D-231 §4를 개정해야 한다.
2. **장치 Lifecycle·Fault 계약.** Fleet 집계 형식도 포함한다.
3. **OMX 경로 계획에 MoveIt 2 채택.** D-376 HOLD를 해제하는 조건, 5축 수직하향 IK, Gazebo+MoveIt 런치를 정한다.
   - **보강 (2026-10-01, D-402):** 시뮬레이션 실행은 [D-402](D-402-omx-motion-planner-v1-analytic-top-down-ik.md)의 해석 IK로 먼저 한다. MoveIt 2 채택은 같은 플래너 인터페이스의 두 번째 구현으로 나중에 정한다.
4. **Rosy Cell 애플리케이션.** 셀 설정과 레시피, Step 계약, 셋업·티칭 경로를 정한다(OMX 장치 API ADR 포함 또는 선행).
5. **Motion Intent 공통 스키마와 장치별 Arbiter 우선순위 표.** MANUAL의 phase 선점 규칙도 정한다.

## 검토한 대안

| 대안 | 판단 |
|---|---|
| 하나의 중앙 ROSY CORE가 Mission부터 Arbiter까지 소유 | 사이트가 끊겼을 때 장치 안전을 원격 프로세스에 맡기게 된다. D-12, D-70, D-390, D-369도 대체해야 한다. 채택하지 않는다. |
| 사이트 패브릭을 Zenoh로 통일 | D-59가 기각한 선택이다. ROBOTIS Zenoh와 CycloneDDS를 섞어 쓴 검증도 없다. 별도 ADR과 벤치 전에는 채택하지 않는다. |
| AI Runtime을 한 상자로 두고 Motion Intent로 직행 | 숙고형 모델의 지연과 실패 모드가 액추에이터 경로로 들어온다. D-231 §4와 D-326 §2를 우회한다. 채택하지 않는다. |
| 반응형 정책을 사이트나 LAN 추론 서버에서 실행 | 30 Hz 청크가 Wi-Fi와 relay 지연을 탄다. 사이트가 끊겼을 때의 정지 경로도 불명확하다. D-231 §4와도 충돌한다. 이 ADR에서는 채택하지 않고, 후속 ADR 1이 개정 여부를 판단한다. |
| 블록 이름과 배치를 이 ADR 없이 문서별로 해석 | 같은 단어(CORE, Arbiter, Gateway)가 문서마다 다른 층을 가리키는 현 상태가 계속된다. 채택하지 않는다. |

## 결과

- 사용자 구조도의 모든 블록이 사이트와 장치 중 한 곳에 놓인다. "CORE"는 장치 런타임 이름으로 남고, Mission과 Task는 Fleet에 남는다.
- 새 장치를 붙이는 일은 장치 미들웨어 한 벌과 Fleet 등록으로 정의된다. 장치 미들웨어 한 벌은 Action Gateway, 스킬, Arbiter, Safety Guard, 단일 writer, 상태·Fault를 포함한다.
- LeRobot은 운영 모드에서 같은 호스트 스킬 안의 추론 엔진이다. 개발/녹화 모드에서만 버스를 소유한다.
- 이 ADR이 대체하거나 좁히는 Accepted 결정은 없다. 다음 사항은 각 후속 ADR이 명시적으로 다룬다.
  - D-376 플래너 HOLD 해제 (후속 3)
  - D-231 §4 개정 여부 (후속 1)
  - OMX 장치 API (후속 4)

## 수용 기준과 증거 경계

- **SOURCE:** 이 ADR은 구조와 배치에 대한 결정이다. 수용 조건은 두 가지다.
  - (a) [01 Target Architecture](../architecture/01_ROSY_OS_Target_Architecture.md), [11 AI](../architecture/11_ROSY_AI_and_Physical_AI.md), `CONCEPTS.md`에 §6 대응표와 별칭을 반영한다. D-296의 이름은 그대로 둔다.
  - (b) 후속 ADR 1–5가 이 배치를 전제로 작성된다.
- **ROS-SIM / DEVICE / FIELD:** 이 결정으로 승격하지 않는다.

**관련 결정:** [D-11](D-11-capability-yaml-api.md), [D-12](D-12-mission-fleet.md), [D-38](D-38-core.md), [D-59](D-59-.md), [D-62](D-62-core.md), [D-74](D-74-core-ros-core.md), [D-99](D-99-policy-cmd-vel.md), [D-117](D-117-rmw-cyclonedds.md), [D-121](D-121-cyclone-core.md), [D-209](D-209-perception-folder-and-learned-backend.md), [D-231](D-231-layered-source-roots-keep-package-names.md), [D-269](D-269-device-server-contracts-and-ros-boundary.md), [D-271](D-271-site-fleet-task-scheduling-and-broker.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-299](D-299-omx-lerobot-development-and-command-ownership.md), [D-326](D-326-agent-loop-boundary.md), [D-330](D-330-fleet-action-admission-stop-and-recovery.md), [D-331](D-331-gemini-er2-proposal-adapter.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-347](D-347-capability-lifecycle-vocabulary.md), [D-361](D-361-site-console-enrolls-robot-by-screen-code.md), [D-369](D-369-control-authority-and-stop-evidence.md), [D-376](D-376-omx-pick-place-planning-and-execution-boundary.md), [D-377](D-377-app-names-rosy-plus-one-english-word.md), [D-390](D-390-pilot-omx-simulation-practice-boundary.md), [D-392](D-392-provider-neutral-model-tool-contract.md).
