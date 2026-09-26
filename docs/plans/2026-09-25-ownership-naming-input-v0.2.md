---
module: docs
---

> 입력 노트다. 채택된 결정은 D-227, D-228, D-229 다. 이 문서가 그리는 `src/runtime` 트리는 폴더가 아니다.

# ROSY Ownership, Naming, AI & Control-Plane Refactoring Plan v0.2

> 기준: 2026-09-25 현재 ROSY 저장소 구조  
> 목적: 현재 구현을 최대한 유지하면서 Naming / Ownership / AI / 통신 / 명령 / 관제 Frontend·Backend 구조를 명확히 한다.  
> 전략: **Rewrite 금지 / Ownership 먼저 / Contract 우선 / Wrap First, Extract Later**

---

## 1. 핵심 결론

현재 ROSY는 이미 다음을 상당 부분 구현하고 있다.

- Runtime / bridge / external API
- Command arbitration
- State / Safety
- Pinky sensing / planning / control
- Nav2
- Device drivers / deadman
- OMX adapter
- Fleet / swarm / traffic
- Web API / dashboard
- Simulation
- ARM64 image / signing / updater
- Validation / acceptance test

따라서 목표는 새 ROSY를 만드는 것이 아니다.

```text
CURRENT ROSY
    ↓
NAMING / OWNERSHIP 정리
    ↓
CONTRACT 표준화
    ↓
COMMUNICATION / COMMAND 경계 명확화
    ↓
SITE CONTROL PLANE 통합
    ↓
AI / LEARNING 기능 연결
    ↓
필요한 부분만 점진적으로 EXTRACT
```

---

## 2. ROSY를 6개의 책임 영역으로 본다

```text
                           ROSY
                            │
 ┌──────────────┬───────────┼───────────┬──────────────┬──────────────┐
 │              │           │           │              │              │
 ▼              ▼           ▼           ▼              ▼              ▼
Foundation   Robot       Command     Site Control   Experience       AI /
             Runtime      Plane        Plane          Plane        Learning
```

### Foundation
- Domain model
- Protocol model
- Contracts
- Capability
- Intent
- Identity
- Profile
- Provenance
- Version compatibility

### Robot Runtime
- Perception
- State
- Navigation
- Manipulation
- Local execution
- Control
- Local safety
- Hardware interaction

### Command Plane
- External command ingress
- Intent normalization
- Authority
- Priority
- Arbitration
- Skill dispatch
- Ack / result
- Cancel / timeout / fallback

### Site Control Plane
- Fleet
- Device registry
- Robot connection
- Mission dispatch
- Command routing
- Telemetry ingestion
- State projection
- Alert / incident
- Deployment
- Configuration
- Authentication / authorization

### Experience Plane
- Operations Console
- Robot local UI
- Fleet map
- Camera / diagnostics
- Mission UI
- Manual control UI
- AI / model status
- Incident UI

### AI / Learning
- Runtime inference
- Decision Providers
- Auto labeling
- Dataset
- Training
- Evaluation
- Replay
- Shadow / candidate comparison
- Model registry

---

## 3. Naming 문제

현재 다음 이름은 책임을 읽기 어렵게 한다.

```text
src/core/core
src/navigation/navigation
core_common
core_features
control
interfaces
face
apps
```

특히:

```text
src/core/core
```

는 상위 category와 package가 모두 `core`이므로 의미가 중복된다.

실제 역할은 단순 "core library"가 아니라:

```text
runtime
bridge
external API
system graph
final command path
```

에 가깝다.

장기 목표:

```text
src/core/core
        ↓
src/runtime/rosy_runtime
```

단, **폴더 이동과 ROS package rename은 같은 변경에서 하지 않는다.**

---

## 4. Naming Rules

지양:

```text
core
common
features
utils
helpers
misc
apps
manager
```

권장 suffix:

```text
*_runtime       지속 실행 Runtime
*_adapter       외부 제품/시스템을 ROSY contract에 적응
*_bridge        transport/protocol 연결
*_provider      교체 가능한 구현
*_controller    continuous control loop
*_planner       계획 생성
*_supervisor    lifecycle / health / mode 감독
*_registry      metadata / catalog 정본
*_gateway       northbound / southbound 연결 경계
*_service       site-side business/backend service
```

---

## 5. 목표 Top-Level Source Tree

```text
src/
│
├── foundation/
├── interfaces/
├── runtime/
├── devices/
├── products/
├── hmi/
├── site/
└── sim/
```

의미:

```text
foundation = 의미와 계약
interfaces = ROS msg/srv/action wire contract
runtime    = 로봇에서 실행
devices    = hardware truth
products   = product composition
hmi        = local human interface
site       = robot 밖 control/backend/AI
sim        = simulation
```

---

## 6. Foundation

```text
foundation/
│
├── domain/
│   ├── capability/
│   ├── intent/
│   ├── identity/
│   ├── profile/
│   ├── command/
│   ├── decision/
│   ├── skill/
│   ├── state/
│   ├── provenance/
│   └── episode/
│
├── events/
│
└── protocols/
    ├── command/
    ├── telemetry/
    ├── robot_link/
    └── versioning/
```

원칙:

```text
foundation → runtime 의존 금지
foundation → product 의존 금지
foundation → site 의존 금지
```

---

## 7. ROS Interfaces

```text
interfaces/
└── rosy_interfaces/
    ├── msg/
    ├── srv/
    └── action/
```

예:

```text
msg/
├── CapabilityState.msg
├── DecisionResult.msg
├── ProviderHealth.msg
├── CommandStatus.msg
└── LearningEvent.msg

action/
├── FollowLane.action
├── RecoverLane.action
├── Dock.action
├── PickObject.action
└── PlaceObject.action
```

---

## 8. Robot Runtime

```text
runtime/
│
├── rosy_runtime/
├── orchestration/
├── perception/
├── mobility/
├── manipulation/
├── decision/
├── skills/
├── safety/
└── gateway/
```

---

## 9. rosy_runtime

현재 `src/core/core`의 장기 목표 위치.

책임:

```text
runtime boot
runtime lifecycle
ROS graph
external intent ingress
final command ownership
system health integration
```

---

## 10. Orchestration

```text
runtime/orchestration/
├── command/
│   ├── arbitration
│   ├── authority
│   └── lifecycle
├── state/
├── modes/
├── diagnostics/
└── power/
```

핵심:

> 최종 command authority는 하나만 존재한다.

---

## 11. Perception

```text
runtime/perception/
├── camera/
├── lane/
├── lidar/
├── obstacle/
├── objects/
├── tracking/
├── pose/
└── fusion/
```

AI/non-AI 모두 Provider로 취급한다.

```text
lane/
└── providers/
    ├── classical/
    ├── yolo_seg/
    └── future/
```

---

## 12. Mobility

```text
runtime/mobility/
├── pinky_runtime/
├── nav2/
└── behaviors/
    ├── line_follow/
    ├── docking/
    ├── waypoints/
    └── wander/
```

---

## 13. Manipulation

```text
runtime/manipulation/
├── orchestration/
├── grasp/
├── verification/
├── moveit/
└── recovery/
```

---

## 14. Safety Ownership

```text
S2 Policy Safety
runtime/safety/policy

        ↓

S1 Motion Safety
runtime/safety/motion

        ↓

S0 Hardware Safety
devices/.../hardware_safety

        ↓
Hardware
```

상태:

```text
NORMAL
DEGRADED
SAFE_STOP
ESTOP
FAULT
```

---

## 15. Product Composition

```text
products/
├── pinky_pro/
│   ├── product.yaml
│   ├── capabilities.yaml
│   ├── runtime.profile.yaml
│   └── launch/
└── omx/
    ├── product.yaml
    ├── capabilities.yaml
    └── launch/
```

Product는 구현이 아니라 composition을 소유한다.

---

## 16. Communication Architecture

ROSY 통신은 4종류로 분리한다.

```text
1. Sensor / Data
2. State / Event
3. Command / Skill
4. Management / Control
```

---

## 17. Robot 내부 통신

### Topic
- sensor stream
- telemetry
- state update
- event

### Service
- short query
- configuration
- snapshot

### Action
- navigation
- docking
- line recovery
- pick/place
- calibration job

Action은 반드시:

```text
goal
feedback
result
cancel
timeout
```

을 지원한다.

---

## 18. ROSY Command Protocol

```yaml
schema_version: 1

command_id: cmd_01J...
trace_id: tr_01J...

source:
  type: site_console
  id: ops_01

target:
  type: robot
  id: pinky_03

issued_at: ...
ttl_ms: 2000

authority:
  role: operator
  level: 50

priority: 50

command:
  type: intent
  name: FOLLOW_LANE

payload:
  speed_profile: normal

requires_ack: true
idempotency_key: ...
```

---

## 19. Command Types

```text
ADMIN COMMAND
MISSION COMMAND
INTENT COMMAND
SKILL COMMAND
CONTROL COMMAND
```

규칙:

> Site / Frontend는 정상 운용에서 Control Command를 직접 생성하지 않는다.

---

## 20. Command Flow

```text
Operations UI
     ↓
Site API
     ↓
Command Service
     ↓
Robot Link Gateway
     ↓
Robot Runtime Gateway
     ↓
Command Normalization
     ↓
Authority / Arbitration
     ↓
Intent / Skill
     ↓
Execution
     ↓
Control
     ↓
Safety
     ↓
Hardware
```

---

## 21. Command Result / ACK

```text
RECEIVED
ACCEPTED
REJECTED
STARTED
RUNNING
SUCCEEDED
FAILED
CANCELED
TIMEOUT
SUPERSEDED
```

---

## 22. Authority & Arbitration

명령 source 예:

```text
Physical Safety
Local Safety
Local Operator
Mission
Site Operator
AI Decision
Autonomy
Remote API
```

판정 요소:

```text
authority
mode
capability
freshness
safety state
command conflict
```

AI는 최종 `cmd_vel` owner가 아니다.

---

## 23. ROSY Robot Link

Robot과 Site backend 사이의 application-level contract.

```text
Presence
Heartbeat
Telemetry
State
Command
Ack
Event
Log reference
Version
Capability
Deployment status
```

Transport는 교체 가능:

```text
WebSocket
gRPC
ROS 2 WAN
MQTT
custom transport
```

---

## 24. Site Control Plane

```text
site/
├── control_plane/
│   ├── api_gateway/
│   ├── robot_gateway/
│   ├── registry/
│   ├── command_service/
│   ├── mission_service/
│   ├── telemetry/
│   ├── state_projection/
│   ├── incident/
│   ├── config/
│   ├── deployment/
│   └── auth/
├── fleet/
├── ai_worker/
├── operations_ui/
└── games/
```

현재 fleet 구현을 한 번에 옮기지 않고 이 책임 모델로 발전시킨다.

---

## 25. Site Backend Ownership

### API Gateway
- auth boundary
- API version
- request validation
- websocket session

### Robot Gateway
- connect/disconnect
- heartbeat
- presence
- capabilities
- version
- command delivery
- ack

### Registry
- robot identity
- product
- capabilities
- software version
- model version
- online state
- site assignment

### Command Service
- command validation
- authority
- idempotency
- routing
- status/history

### Mission Service
- mission create/state
- task decomposition
- robot assignment
- mission history

### Telemetry Ingest
- state
- health
- battery
- position
- AI status
- safety
- diagnostics

### State Projection
Frontend용 read model 생성.

### Incident Service
- safety event
- offline
- command timeout
- grasp failure
- model failure
- high latency
- human intervention

---

## 26. Frontend Architecture

장기적으로:

```text
site/operations_ui/
```

Frontend는 Control Plane API만 사용한다.

```text
Frontend
   ↓
HTTP / WebSocket
   ↓
Site Backend
```

Frontend가 ROS graph에 직접 의존하지 않는다.

---

## 27. Operations Console

```text
Operations Console
├── Overview
├── Fleet
├── Robot Detail
├── Mission
├── Manual Control
├── Map
├── Camera / Perception
├── Safety / Incidents
├── Diagnostics
├── AI / Models
├── Deployment
└── Replay / Evidence
```

---

## 28. Manual Control

```text
Operator
   ↓
Manual Control API
   ↓
Command Service
   ↓
Robot Arbitration
```

Frontend에서 직접 `cmd_vel` publish 금지.

Teleop command:

```text
source
lease
deadman
ttl
sequence
authority
```

---

## 29. Local HMI vs Site UI

```text
hmi/
= 로봇 로컬 사람 인터페이스

site/operations_ui/
= 원격/사이트 관제 인터페이스
```

---

## 30. core_api_web

현재 `core_api_web`은 Robot-local API로 정의한다.

장기:

```text
runtime/gateway/
├── local_api/
└── websocket/
```

Site Control Plane API와 분리한다.

---

## 31. AI Integration Principle

`src/ai/` 같은 거대한 바구니를 만들지 않는다.

```text
Perception AI
→ runtime/perception/*/providers

Decision AI Client
→ runtime/decision/providers

Learning / Heavy Inference
→ site/ai_worker
```

---

## 32. Runtime AI

```text
runtime/perception/lane/providers/
├── classical/
├── yolo_seg/
└── future/
```

AI가 아닌 구현도 같은 Provider 계약을 따른다.

---

## 33. Decision AI

```text
runtime/decision/
├── router/
├── rules/
├── fallback/
├── client/
└── providers/
```

Heavy model은 site-side일 수 있다.

```text
Robot Decision Client
         ↓
ROSY Robot Link
         ↓
site/ai_worker/inference/decision
```

Network failure:

```text
Remote AI unavailable
        ↓
Local Rule / Local Model
        ↓
DEGRADED
```

---

## 34. AI Decision Flow

```text
World State
    ↓
Hard Rule
    ↓ unresolved
Decision Provider
    ↓
Decision Intent
    ↓
Command Arbitration
    ↓
Skill
```

Decision output:

```text
decision
confidence
uncertainty
abstain
provider
model_version
latency
```

---

## 35. Site AI Worker

```text
site/
└── ai_worker/
    ├── inference/
    │   ├── decision/
    │   ├── segmentation/
    │   ├── pose/
    │   └── vision_judge/
    ├── autolabel/
    │   ├── lane/
    │   ├── object/
    │   └── video/
    ├── dataset/
    ├── training/
    ├── evaluation/
    ├── replay/
    └── model_registry/
```

---

## 36. AI Worker API

```text
POST /v1/decision
POST /v1/inference/segment
POST /v1/inference/pose
POST /v1/jobs/autolabel
POST /v1/jobs/train
GET  /v1/models
GET  /v1/jobs/{id}
```

내부 Provider:

```text
Jev
OpenJev
Decider
SAM2
YOLO
SegFormer
FoundationPose
Future Model
```

---

## 37. Runtime AI vs Learning AI

```text
ONLINE
latency first
bounded queue
fallback required

OFFLINE
quality / throughput first
batch allowed
human review allowed
```

Priority:

```text
P0 Runtime critical inference
P1 Runtime normal inference
P2 Interactive analysis
P3 Auto label
P4 Training
```

---

## 38. Episode / Data Architecture

```text
Episode
├── episode.yaml
├── telemetry.mcap
├── video/
├── artifacts/
└── outcome.json
```

Capture Profile:

```text
LIGHT
DEBUG
LEARNING
INCIDENT
```

---

## 39. Learning Loop

```text
Runtime
  ↓
Episode Capture
  ↓
Learning Event
  ↓
Curate
  ↓
Auto Label
  ↓
AI Judge
  ↓
Human Review
  ↓
Dataset
  ↓
Train
  ↓
Evaluate
  ↓
Replay
  ↓
Shadow
  ↓
Release
  ↓
Existing Updater
  ↓
Runtime
```

---

## 40. Model Deployment

기존 release/signing/updater를 확장한다.

```yaml
release: rosy-2026.10

software:
  version: ...

models:
  lane:
    alias: champion
    version: v5
    hash: ...

  decision:
    alias: champion
    version: v3
    hash: ...
```

---

## 41. Observability Plane

필요:

```text
Logs
Metrics
Events
Traces
Incidents
Evidence
```

공통 ID:

```text
robot_id
mission_id
command_id
skill_id
decision_id
episode_id
trace_id
```

---

## 42. Frontend Live Data

WebSocket event 예:

```text
robot.presence
robot.state
mission.state
command.state
safety.alert
ai.decision
camera.preview.metadata
```

Raw high-rate sensor stream은 별도 경로를 둔다.

---

## 43. API Versioning

```text
/api/v1/robots
/api/v1/missions
/api/v1/commands
/api/v1/incidents
/api/v1/models
/api/v1/deployments
```

---

## 44. Security / Authority

Role 예:

```text
viewer
operator
engineer
admin
service
robot
```

Permission 예:

```text
view
teleop
mission
config
update
reboot
maintenance
```

AI Worker는 operator authority를 갖지 않는다.

---

## 45. Ownership Rules

1. **One State, One Authority**
2. **One Final Command Owner**
3. **Product Owns Composition, Not Implementation**
4. **Device Owns Hardware Truth**
5. **Site Never Becomes Mandatory Safety Dependency**
6. **Frontend Never Talks Directly to Actuator**
7. **AI Never Owns Final Authority**

---

## 46. Current → Target Mapping

| 현재 | 목표 소유권 | 처리 |
|---|---|---|
| `src/core/core` | `runtime/rosy_runtime` | MOVE later / package name initially KEEP |
| `core_common` | `foundation/domain` | KEEP + CLARIFY |
| `core_events` | `foundation/events` | KEEP + CLARIFY |
| `core_features/command` | `runtime/orchestration/command` | KEEP / promote |
| `core_features/state` | `runtime/orchestration/state` | KEEP / clarify authority |
| `core_features/safety` | `runtime/safety/policy` | CLARIFY |
| `control/safety` | `runtime/safety/motion` | CLARIFY |
| `bringup/command_deadman` | hardware safety | KEEP |
| `control/sensing` | `runtime/perception` | WRAP then EXTRACT |
| `control/control` | `runtime/mobility/pinky_runtime` | KEEP then rename |
| `navigation/navigation` | `runtime/mobility/nav2` | MOVE later |
| `core_api_web` | `runtime/gateway/local_api` | SPLIT API vs UI |
| `web_common` | `hmi/web_shared` or site UI shared | CLARIFY |
| `face/emotion` | `hmi/emotion_display` | RENAME later |
| `products/omx_adapter` | `products/omx` | KEEP |
| missing Pinky product | `products/pinky_pro` | ADD |
| `site/fleet` | Site Control Plane base | KEEP + evolve |
| AI worker | `site/ai_worker` | ADD |
| `tools/run_data.py` | Episode Capture tooling | EXTEND |
| `apps/` | none | RETIRE |
| `interfaces/` | `interfaces/rosy_interfaces` | EXPAND / rename later |

---

## 47. Target Repository Shape

```text
src/
├── foundation/
│   ├── domain/
│   ├── events/
│   └── protocols/
├── interfaces/
│   └── rosy_interfaces/
├── runtime/
│   ├── rosy_runtime/
│   ├── orchestration/
│   ├── perception/
│   ├── mobility/
│   ├── manipulation/
│   ├── decision/
│   ├── skills/
│   ├── safety/
│   └── gateway/
├── devices/
├── products/
│   ├── pinky_pro/
│   └── omx/
├── hmi/
│   ├── emotion_display/
│   └── local_web/
├── site/
│   ├── control_plane/
│   ├── fleet/
│   ├── ai_worker/
│   ├── operations_ui/
│   └── games/
└── sim/
```

---

## 48. End-to-End Control Path

```text
                 OPERATIONS UI
                       │
                 HTTP / WebSocket
                       │
                       ▼
                SITE API GATEWAY
                       │
                       ▼
                 COMMAND SERVICE
                       │
                       ▼
                ROBOT LINK GATEWAY
                       │
                       ▼
                   ROSY RUNTIME
                       │
                COMMAND ARBITER
                       │
              ┌────────┴────────┐
              ▼                 ▼
            RULE            AI DECISION
              │                 │
              └────────┬────────┘
                       ▼
                     INTENT
                       │
                       ▼
                     SKILL
                       │
                       ▼
               NAV / MANIPULATION
                       │
                       ▼
                    CONTROL
                       │
                       ▼
                    SAFETY
                       │
                       ▼
                   HARDWARE
```

---

## 49. End-to-End Telemetry Path

```text
Sensors / Runtime / Safety / AI
               │
               ▼
          Robot Events
               │
               ▼
       Robot Link Gateway
               │
               ▼
        Telemetry Ingest
               │
       ┌───────┴────────┐
       ▼                ▼
 State Projection   Event / Incident
       │                │
       └───────┬────────┘
               ▼
          WebSocket/API
               │
               ▼
        Operations UI
```

---

## 50. End-to-End AI Learning Path

```text
Robot Runtime
    ↓
Episode Capture
    ↓
Site AI Worker
    ↓
Curate
    ↓
Auto Label
    ↓
Decision / Vision Judge
    ↓
Human Review
    ↓
Dataset
    ↓
Train
    ↓
Evaluate / Replay
    ↓
Candidate Model
    ↓
Shadow
    ↓
Approve
    ↓
Release Manifest
    ↓
Existing Deployment / Updater
    ↓
Robot
```

---

## 51. Migration Strategy

### Phase 0 — Freeze Baseline
packages / nodes / topics / services / actions / launch / configs / models / hardware / dependencies 기록

### Phase 1 — Ownership Only
코드를 거의 움직이지 않고 Ownership 확정

### Phase 2 — Contract Layer
CommandEnvelope / DecisionResult / Capability / Skill / Robot Link / Episode Manifest 추가

### Phase 3 — Site Control Plane
현재 Fleet backend와 core API 역할 분리

### Phase 4 — AI Worker
RTX 5080 AutoLabel / Decision / Evaluation

### Phase 5 — Adapter / Shadow
기존 Runtime 유지 + 새로운 AI/contract shadow 연결

### Phase 6 — Physical Move
안정화 후 디렉터리 이동

### Phase 7 — Package Rename
폴더 이동과 별도 변경

---

## 52. 우선 구현 권장 순서

### P0
1. Ownership Matrix
2. Naming Rules
3. CommandEnvelope
4. Command Status / Ack
5. Robot Link Contract
6. Frontend ↔ Backend API boundary
7. Pinky Product Composition

### P1
8. Episode Capture
9. Site AI Worker skeleton
10. Decision Provider API
11. AI Shadow mode
12. Operations UI State Projection

### P2
13. Skill Actions
14. Dataset / Model Registry
15. Replay
16. Deployment model manifest
17. Incident pipeline

### P3
18. Folder movement
19. Package rename
20. deeper runtime extraction

---

## 53. Final Rule Set

항상 묻는다.

```text
1. 이 코드의 owner는 누구인가?
2. 이 데이터의 canonical authority는 누구인가?
3. 이 명령의 final authority는 누구인가?
4. 이 기능은 Robot-local인가 Site-side인가?
5. Safety에 Site/AI dependency가 생기지 않는가?
6. AI가 Provider인가, Architecture를 지배하고 있는가?
7. Frontend가 Backend contract를 우회하고 있지 않은가?
8. 특정 transport가 domain contract에 침투하고 있지 않은가?
9. 기존 구현을 Wrap해서 해결할 수 없는가?
10. 폴더 이동 없이 먼저 ownership을 명확히 할 수 없는가?
```

---

## 54. Final Definition

> **ROSY는 Robot Runtime, Command Plane, Site Control Plane, Operations UI, AI/Learning을 공통 Domain Contract로 연결하되, 모든 실행 명령은 Arbitration과 Safety Boundary를 통과하고, AI와 Frontend는 최종 Actuator Authority를 소유하지 않는 Local-First Robotics Platform이다.**
