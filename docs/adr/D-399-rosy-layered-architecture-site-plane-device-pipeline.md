## D-399 ROSY 계층 아키텍처: Application · Site Control Plane · 장치별 Command Pipeline

**Status:** Proposed (2026-10-01, 구조·용어·배치 결정). 패키지 이동, 새 서비스 구현, 기존 Accepted ADR의 대체는 포함하지 않는다. 후속 ADR(아래 §7)이 각 블록을 구체화한다.

## 배경

- 사용자는 Palletizing·Pick&Place 같은 애플리케이션, 고전 플래너·AI 정책·수동 조종이라는 세 명령 출처, 장치 공통 Command Pipeline(Action Gateway → Command Arbiter → Safety Guard → Motion Executor → Controller Adapter), OMX-AI·Pinky Pro·미래 로봇 드라이버로 이루어진 한 장의 ROSY 구조도를 제시했다. AI Runtime에는 LeRobot, VLA, Gemini Robotics, 고수준 의사결정 AI, Custom Policy가 놓인다.
- 이 그림은 블록의 **역할**은 기존 결정과 대부분 같지만 **배치**(사이트인지 장치인지)를 표시하지 않는다. 그대로 읽으면 다음 Accepted 결정과 충돌한다.
  - 그림의 "ROSY CORE"는 Mission Manager·Task Executor를 품는다. 현재 CORE(`src/runtime/gateway`, `rosy_core`)는 Pinky 한 대의 장치 런타임이고 외부 API·최종 `cmd_vel` 단일 writer다(D-38, D-62, D-74). Mission·Step 순서·스케줄·원장은 사이트 Fleet 소관이다(D-12, D-70, D-271, D-369).
  - 하나의 Command Pipeline이 여러 장치를 관장하는 모양은 OMX가 Pinky CORE를 거치지 않는다는 결정(D-390)과 장치별 로컬 owner(D-282, D-299, D-336)에 어긋난다.
  - "ROS 2 / Zenoh" 미들웨어는 CycloneDDS 단일 RMW(D-117)와 사이트 패브릭으로서의 Zenoh 기각(D-59)에 어긋난다.
  - AI Runtime이 Motion Intent를 직접 내는 모양은 AI 출력은 제안이라는 결정(D-99, D-231 §4, D-326, D-331, D-369, D-376)에 어긋난다.
  - Command Arbiter가 CORE와 Pipeline에 두 번 그려진다.
- 목표 아키텍처 문서([01](../architecture/01_ROSY_OS_Target_Architecture.md), [11](../architecture/11_ROSY_AI_and_Physical_AI.md))는 이미 Control Plane과 노드 로컬 Runtime을 나누고 "AI는 액추에이터 루프를 직접 제어하지 않는다"고 적는다. 이 ADR은 사용자 구조도를 그 방향에 맞춰 블록 이름과 배치를 한 번에 고정한다.
- LeRobot이 OMX-AI(`omx_follower`/`omx_leader`)를 공식 지원하지만 관절공간 전용이고 공식 ROS 2 브리지는 없다(huggingface/lerobot RFC #4368, 2026-10-01 기준 open). 학습 정책(ACT 등)은 30 Hz 안팎의 관절 청크를 내므로 사이트↔장치 네트워크 너머에서 닫힌 루프로 돌릴 수 없다. 반면 Gemini Robotics 같은 숙고형 모델은 초 단위 제안이다. 두 부류를 한 "AI Runtime" 상자로 묶으면 배치와 안전 경로를 정할 수 없다.

## 결정

### 1. 다섯 층과 배치

```text
APPLICATION          Palletizing · Pick&Place · Navigation · Inspection · …
  (사이트)                 │  Mission 요청
SITE CONTROL PLANE   Fleet: Mission Manager · Task Executor(Step 하달) · Device Registry(정본)
  (사이트 1개)              · 상태/Fault 집계 · 숙고형 AI(제안만, Fleet 승인)
                           │  Task / Step   — 역할 계약(REST/WSS, 동일 호스트는 UDS). DDS 아님
DEVICE RUNTIME       장치마다 한 벌. 예: Pinky CORE, OMX 로컬 owner
  (장치 1대 = 1벌)     Action Gateway → 스킬(Classical Planner · 반응형 정책 · Manual Teleop)
                       → Motion Intent → Command Arbiter(1) → Safety Guard → Motion Executor
                       → Controller Adapter(단일 writer)
                       + State · Lifecycle · Fault (장치 로컬)
                           │  ROS 2 (CycloneDDS, 장치 내부)
DRIVERS              Pinky Pro HW · Dynamixel OMX-F (+ OMX-L 읽기) · Future Robot
물리 E-stop          모든 층과 독립된 경로, 소프트웨어보다 우선 (D-369 §5)
```

- 사용자 구조도의 "ROSY CORE"는 **Site Control Plane**(Mission Manager, Task Executor, Device Registry 정본, 상태/Fault 집계)과 **Device Runtime**(Command Arbiter, State, Lifecycle, Fault의 장치 로컬 부분)으로 나누어 읽는다. 이름 "CORE"는 지금처럼 장치 런타임(Pinky의 `rosy_core`, 그리고 같은 계약을 따르는 다른 장치의 로컬 owner)을 가리킨다. D-12, D-70, D-296은 그대로 유지한다.
- Command Pipeline은 **장치마다 한 벌**이다. 계약(Motion Intent 스키마, Arbiter 우선순위 규칙, Safety Guard 판정 형식, 단일 writer)은 공통이고 인스턴스는 장치 로컬이다. 여러 장치를 하나의 Pipeline 프로세스가 관장하지 않는다(D-282, D-390).
- Command Arbiter는 장치당 **하나**다. Site Control Plane은 Arbiter를 갖지 않고, Task를 장치 Action Gateway에 제출할 뿐이다. 우선순위는 기존 CORE 순서(EMERGENCY > SAFETY > MANUAL > DOCKING > NAVIGATION > FLEET > IDLE, D-2/D-38)를 Pinky의 기준으로 두고, 다른 장치는 같은 상위 세 단계(EMERGENCY, SAFETY, MANUAL)를 공유한 뒤 장치별 하위 단계를 정의한다.
- Safety Guard는 단일 writer 바로 앞에 있다. Site Control Plane이 끊겨도 장치는 정지하거나 승인된 로컬 동작만 계속한다([01 §4](../architecture/01_ROSY_OS_Target_Architecture.md)).

### 2. AI는 두 부류로 나눈다

| 부류 | 예 | 배치 | 출력 | 안전 경로 |
|---|---|---|---|---|
| **숙고형 AI** | Gemini Robotics, VLA 계획, 고수준 의사결정 AI(미션·태스크 선택과 재계획) | Site Control Plane (또는 사이트 GPU 노드) | Mission·Task·Step **제안** | Fleet 승인(D-326, D-331, D-392) → 일반 Task 경로 |
| **반응형 정책** | LeRobot ACT/Diffusion/SmolVLA, Custom Policy | **Device Runtime** (같은 호스트 또는 같은 장치 LAN의 추론 서버) | 관절/속도 청크 = 스킬 내부 Motion Intent | 스킬 엔벌로프 → Arbiter → Safety Guard → 단일 writer |

- 숙고형 AI는 Motion Intent를 내지 않는다. 사용자 구조도의 "AI Policy Gateway"는 숙고형 AI에 대해서는 Fleet의 제안 입구다.
- 반응형 정책은 **스킬 하나로만** 실행된다. 스킬은 Task가 지정한 엔벌로프(작업 영역, 시간 상한, 속도·스텝 상한, 성공/실패 종료 조건) 안에서만 Motion Intent를 내고, 엔벌로프를 벗어나거나 시간을 넘기면 HOLD로 끝난다. 정책 프로세스는 시리얼 버스·ROS 액션·`cmd_vel`을 직접 쓰지 않는다(D-99, D-299). 이 "엔벌로프 스킬"이 D-326 §3의 게이트 밸브를 처음 구체화하는 형태이며, 세부 계약과 활성화 조건은 후속 ADR이 정한다.
- LeRobot 네이티브 개발/녹화 모드(LeRobot이 버스 단독 소유, D-299)는 이 구조 밖의 별도 모드로 남는다. 그 모드에서는 장치 Action Gateway가 lease를 거부하므로 Application·Fleet 작업이 실행되지 않는다.

### 3. 미들웨어

- 장치 내부는 ROS 2 CycloneDDS다(D-117, D-121, D-122). 사이트↔장치는 역할 계약(HTTPS REST/WSS, 동일 호스트는 UDS)이다(D-59, D-269, D-336).
- ROBOTIS 스택의 Zenoh 설정은 별도 도메인에 격리할 때만 쓴다. Zenoh를 사이트 패브릭으로 채택하려면 D-117·D-59를 대체하는 별도 ADR과 벤치가 필요하다. 이 ADR은 그 전환을 결정하지 않는다.

### 4. 상태 · Lifecycle · Fault · Registry

- **Device Registry 정본은 사이트**다(Fleet roster/enrollment, D-361). 장치는 자기 identity·capability·adapter manifest(D-69)를 보고하고, 사이트 등록과 다르면 사이트가 해당 장치의 Task 하달을 막는다.
- **State·Lifecycle·Fault는 장치 로컬이 원천**이고 사이트는 집계만 한다. Lifecycle 어휘는 D-347(ready, activating, unavailable)을 따른다. 현재 흩어진 Fault 조각(D-32 오류 코드, `core_features/{recovery,diagnostics}`, `rosy-hw-probe`, 장치 카드, commissioning 인증서)을 하나의 장치 Fault 계약으로 묶는 일은 후속 ADR로 넘긴다.

### 5. Application 층

- Application은 Fleet에 Mission을 요청하는 사이트 소프트웨어다. 장치 API를 직접 호출하지 않는다. 예외는 셋업·티칭처럼 사람이 장치 곁에서 하는 작업이며, 이 경우에도 장치 Action Gateway의 lease와 Arbiter의 MANUAL 등급을 거친다.
- 첫 Application 후보는 팔 무관 팔레타이징·셋업 앱 Rosy Cell(`src/hmi/cell`, `rosy_cell`, D-377 이름 규칙)이다. 레시피·패턴·프레임은 Application이, 경로 계획(MoveIt 2)과 반응형 정책은 장치 스킬이, 최종 명령은 장치 owner가 맡는다.

### 6. 사용자 구조도와의 대응

| 구조도 블록 | 이 ADR의 위치 |
|---|---|
| APPLICATION | Application (사이트) |
| ROSY CORE: Mission Manager, Task Executor, Device Registry | Site Control Plane (Fleet) |
| ROSY CORE: Command Arbiter, State Manager, Lifecycle Manager, Fault Manager | Device Runtime (장치마다), 사이트는 집계 |
| Classical Planner | 장치 스킬 (Nav2, MoveIt 2) |
| AI Policy Gateway / AI Runtime | 숙고형 → Site Control Plane 제안 입구, 반응형 → 장치 엔벌로프 스킬 |
| Manual Teleop | 장치 Action Gateway의 MANUAL 입력 (Pilot, dashboard, OMX 리더 팔) |
| Motion Intent | 장치 내부, 스킬 → Arbiter 사이 계약 |
| COMMAND PIPELINE | 장치마다 한 벌 |
| ROS 2 / Zenoh | 장치 내부 CycloneDDS, 사이트↔장치 REST/WSS/UDS |
| Drivers | 장치 드라이버 (`src/products/*`, `src/drivers/*`) |

### 7. 후속 ADR

1. 반응형 정책 엔벌로프 스킬 계약 (LeRobot 추론 → Motion Intent, 종료 조건, lease, 녹화 모드와의 관계).
2. 장치 Lifecycle·Fault 계약 (사이트 집계 형식 포함).
3. OMX 경로 계획에 MoveIt 2 채택 (D-376 HOLD 해제 조건, 5축 수직하향 IK, Gazebo+MoveIt 런치).
4. Rosy Cell 애플리케이션 (셋업 마법사, 팔레타이징 레시피, Step 계약).
5. Motion Intent 공통 스키마와 장치별 Arbiter 우선순위 표.

## 검토한 대안

| 대안 | 판단 |
|---|---|
| 하나의 중앙 ROSY CORE가 Mission부터 Arbiter까지 소유 | 사이트 단절 시 장치 안전을 원격 프로세스에 맡기게 되고 D-12·D-70·D-390·D-369를 대체해야 하므로 채택하지 않는다. |
| 사이트 패브릭을 Zenoh로 통일 | D-59에서 기각한 선택이고 ROBOTIS Zenoh(domain 30)와 CycloneDDS 혼용 검증이 없다. 별도 ADR·벤치 전에는 채택하지 않는다. |
| AI Runtime을 한 상자로 두고 Motion Intent 직행 | 숙고형 모델의 지연·실패 모드가 액추에이터 경로로 들어오고 D-99·D-326을 우회하므로 채택하지 않는다. |
| 반응형 정책도 사이트에서 실행 | 30 Hz 청크가 Wi-Fi·relay 지연을 타고 들어오며 사이트 단절 시 정지 경로가 불명확하다. 추론 서버는 장치 LAN 안에 둘 수 있지만 엔벌로프와 Arbiter는 장치에 둔다. |
| 블록 이름·배치를 이 ADR 없이 문서별로 해석 | 같은 단어(CORE, Arbiter, Gateway)가 문서마다 다른 층을 가리키는 현 상태가 지속되므로 채택하지 않는다. |

## 결과

- 사용자 구조도의 모든 블록이 사이트 또는 장치 중 한 곳에 놓인다. "CORE"는 장치 런타임 이름으로 남고, Mission·Task는 Fleet에 남는다.
- 새 장치를 붙이는 일은 "Device Runtime 한 벌(Action Gateway, 스킬, Arbiter, Safety Guard, 단일 writer, State/Fault) + 사이트 등록"으로 정의된다.
- LeRobot은 운영 모드에서 장치 스킬 안의 추론 엔진이고, 개발/녹화 모드에서만 버스를 소유한다.
- 기존 Accepted ADR 중 이 ADR이 대체하는 것은 없다. D-376의 플래너 HOLD 해제는 후속 ADR 3이 다룬다.

## 수용 기준과 증거 경계

- **SOURCE:** 이 ADR은 구조·용어 결정이다. 수용은 (a) [01 Target Architecture](../architecture/01_ROSY_OS_Target_Architecture.md)·[11 AI](../architecture/11_ROSY_AI_and_Physical_AI.md)·`CONCEPTS.md`의 용어를 이 표와 맞추는 문서 변경, (b) 후속 ADR 1–5가 이 배치를 전제로 작성되는 것이다.
- **ROS-SIM / DEVICE / FIELD:** 이 결정으로 승격하지 않는다.

**관련 결정:** [D-2](D-2-cmd-vel.md), [D-12](D-12-mission-fleet.md), [D-38](D-38-core.md), [D-59](D-59-.md), [D-99](D-99-policy-cmd-vel.md), [D-117](D-117-rmw-cyclonedds.md), [D-228](D-228-decision-lives-in-core-features.md), [D-231](D-231-layered-source-roots-keep-package-names.md), [D-269](D-269-device-server-contracts-and-ros-boundary.md), [D-271](D-271-site-fleet-task-scheduling-and-broker.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-299](D-299-omx-lerobot-development-and-command-ownership.md), [D-326](D-326-agent-loop-boundary.md), [D-331](D-331-gemini-er2-proposal-adapter.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-347](D-347-capability-lifecycle-vocabulary.md), [D-361](D-361-site-console-enrolls-robot-by-screen-code.md), [D-369](D-369-control-authority-and-stop-evidence.md), [D-376](D-376-omx-pick-place-planning-and-execution-boundary.md), [D-390](D-390-pilot-omx-simulation-practice-boundary.md), [D-392](D-392-provider-neutral-model-tool-contract.md).
