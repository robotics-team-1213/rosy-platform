---
module: docs
---

> 입력 노트다. 채택된 결정은 D-227, D-228, D-229 다. 이 문서가 그리는 `src/runtime` 트리는 폴더가 아니다.

# ROSY Decision Fabric & AI Judgment Architecture v0.8

> 기준: ROSY Final Target Architecture v0.7 + Fault-Aware Architecture v0.5  
> 목적: Rule, JEV/OpenJev, Decider, Local AI, Vision Judge, Heavy AI, Human Review를 하나의 판단 구조로 통합하고, AI가 Robot Control/Safety 권한을 침범하지 않도록 명확한 Contract와 Runtime 경계를 정의한다.  
> 핵심 원칙: **Bounded Decision / Typed Output / Allowed Action Set / Deadline / ABSTAIN / Fallback / Shadow / No Direct Actuator Authority**

---

# 1. 왜 Decision을 별도 Architecture로 다뤄야 하는가

ROSY에서 AI는 단순히 "모델을 호출하는 기능"이 아니다.

실제 판단 흐름에는 다음이 모두 존재한다.

```text
Deterministic Rule
JEV-style Decision Model
OpenJev-style Local Decision Model
Decider / Vision Decision Model
VLM / Semantic Judge
Human Review
Fallback Policy
```

이들을 각 기능 안에 제각각 구현하면:

```text
Pinky line-follow가 자체 AI 판단
OMX grasp가 자체 AI 판단
Fleet가 자체 judge
Auto-label이 자체 judge
```

가 되어 정책, threshold, timeout, evidence, model version 관리가 분산된다.

따라서 **Decision Fabric**을 공통 Runtime Capability로 만든다.

---

# 2. 중요한 구분: Perception != Decision != Control

ROSY에서 세 개를 절대 섞지 않는다.

```text
PERCEPTION
"무엇이 보이는가?"

DECISION
"허용된 선택지 중 무엇을 선택할 것인가?"

CONTROL
"선택된 행동을 물리적으로 어떻게 실행할 것인가?"
```

예:

```text
Camera
 ↓
Lane Segmentation
 ↓
lane confidence / geometry
          [PERCEPTION]

 ↓
FOLLOW / SLOW / RECOVER / STOP
          [DECISION]

 ↓
PID / Pure Pursuit / Nav2 Controller
          [CONTROL]
```

Decision AI가 steering angle, PWM, joint torque를 직접 생성하지 않는다.

---

# 3. Mission != Decision

Mission:

```text
무엇을 달성할 것인가
어떤 순서로 수행할 것인가
```

Decision:

```text
현재 상황에서 허용된 선택지 중 무엇을 할 것인가
```

예:

```text
Mission:
"Dock까지 이동"

Decision:
"현재 lane ambiguity에서 FOLLOW / SLOW / RECOVER / STOP 중 무엇?"
```

---

# 4. Safety != Decision

Safety는 Decision의 한 Provider가 아니다.

```text
Decision
→ 행동 후보를 선택

Safety
→ 선택된 행동이 실행 가능한지 최종 제한
```

Safety는 AI보다 아래에 있다.

```text
Decision
  ↓
Intent
  ↓
Command Authority
  ↓
Skill
  ↓
Control
  ↓
Safety Gate
  ↓
Actuator
```

Safety가 AI 결과를 신뢰해야 동작하는 구조를 만들지 않는다.

---

# 5. 새로운 Runtime Package: `rosy_decision`

최종 구조에 다음을 추가한다.

```text
src/runtime/
├── rosy_runtime/
├── rosy_decision/          # NEW
├── rosy_robot_api/
├── rosy_pinky_pro/
├── rosy_navigation/
└── rosy_manipulation/
```

Decision이 독립 package가 되는 이유:

```text
1. Pinky / OMX / Future Product에서 재사용
2. Rule/JEV/Decider/Remote AI를 공통 처리
3. Provider failure를 격리
4. 독립 test 가능
5. Decision policy와 Command authority를 분리
6. Shadow/benchmark 가능
```

---

# 6. `rosy_decision` 내부 구조

```text
rosy_decision/
├── package.xml
├── setup.py / CMakeLists.txt
├── config/
├── launch/
├── test/
└── rosy_decision/
    ├── router/
    ├── policy/
    ├── rules/
    ├── providers/
    │   ├── local/
    │   ├── remote/
    │   └── adapters/
    ├── validation/
    ├── calibration/
    ├── fallback/
    ├── shadow/
    ├── health/
    └── metrics/
```

---

# 7. `rosy_decision`이 소유하는 것

```text
Decision Request validation
Allowed Action Set
Risk classification
Provider selection
Deadline management
Provider health
Confidence threshold
Calibration policy
ABSTAIN handling
Fallback
Shadow comparison
Decision metrics
Decision provenance
```

소유하지 않는 것:

```text
Motor control
Safety override
Mission decomposition
Perception model training
Heavy model artifact storage
GPU training scheduling
```

---

# 8. Decision Contract는 `rosy_domain`에 둔다

```text
src/contracts/rosy_domain/
└── rosy_domain/
    └── decision/
        ├── request.py
        ├── option.py
        ├── result.py
        ├── risk.py
        ├── provider.py
        └── outcome.py
```

ROS-specific message는 `rosy_interfaces`.

Network protocol representation은 `rosy_protocols`.

---

# 9. DecisionRequest

모든 Decision Provider는 같은 입력 계약을 사용한다.

```yaml
decision_id: dec_01J...
trace_id: tr_01J...

decision_type: lane_recovery

product:
  id: pinky_pro

robot_id: pinky_03

world_snapshot:
  id: ws_10291
  timestamp: ...
  max_age_ms: 120

risk_class: OPERATIONAL

deadline_ms: 100

context:
  lane_confidence: 0.61
  left_boundary: ...
  right_boundary: ...
  obstacle_distance_m: 1.8

evidence:
  - ref: frame_10291
    type: image

allowed_actions:
  - id: FOLLOW
  - id: SLOW
  - id: RECOVER_LEFT
  - id: RECOVER_RIGHT
  - id: STOP
  - id: ABSTAIN

policy:
  min_confidence: 0.80
  on_timeout: RULE_FALLBACK
  on_abstain: SLOW_OR_STOP
```

---

# 10. Allowed Action Set는 매우 중요하다

AI에게:

```text
"무엇을 해야 할까?"
```

라는 열린 질문을 보내지 않는다.

항상:

```text
Allowed Action Set
```

을 먼저 만든다.

예:

```text
FOLLOW
SLOW
RECOVER_LEFT
RECOVER_RIGHT
STOP
ABSTAIN
```

AI는 이 범위 안에서만 선택한다.

Invalid output:

```text
TURN_180_AND_ACCELERATE
```

→ `INVALID_DECISION`

→ fallback.

---

# 11. Allowed Action Set 생성 책임

다음 계층을 통해 생성한다.

```text
Mission
  ↓
Current Robot Mode
  ↓
Capability State
  ↓
Safety Envelope
  ↓
Decision Policy
  ↓
Allowed Action Set
```

Decision Provider 스스로 행동 공간을 만들지 않는다.

---

# 12. DecisionResult

```yaml
decision_id: dec_01J...

status: DECIDED

selected_action:
  id: SLOW

probabilities:
  FOLLOW: 0.11
  SLOW: 0.74
  RECOVER_LEFT: 0.05
  RECOVER_RIGHT: 0.03
  STOP: 0.05
  ABSTAIN: 0.02

confidence: 0.74
uncertainty: 0.26

provider:
  type: local_decision
  name: decider
  model: decider-2b
  version: ...

latency_ms: 42

world_snapshot_id: ws_10291
valid_until: ...

evidence_refs:
  - frame_10291

reason_code: AMBIGUOUS_LANE
```

---

# 13. Decision Status

```text
DECIDED
ABSTAINED
TIMEOUT
INVALID
ERROR
STALE_INPUT
NO_PROVIDER
POLICY_REJECTED
```

`ERROR`를 `STOP`으로 위장하지 않는다.

Decision 실패와 Safe Policy 결과는 별도 기록한다.

---

# 14. Provider Contract

모든 Provider:

```text
evaluate(request) -> result
health()
capabilities()
```

Provider Capability:

```yaml
provider: openjev_local

modalities:
  - text

decision_types:
  - choice
  - score
  - boolean

deployment:
  location: SITE

sla:
  target_p95_ms: 100

supports:
  probabilities: true
  abstain: true
```

---

# 15. Provider 계층

ROSY에서는 다음 Provider 종류를 지원한다.

```text
P0 Hard Policy
P1 Deterministic Rule
P2 Fast Typed Decision Model
P3 Semantic / Vision Judge
P4 Human / Operator
```

P0는 일반 AI Decision Provider가 아니라 상위 제약이다.

---

# 16. P0 — Hard Policy / Constraints

예:

```text
Safety State = SAFE_STOP
→ MOVE 관련 action 제거

Battery critical
→ high-speed action 제거

MANUAL mode
→ autonomous movement decision 금지
```

AI 호출 전에 적용한다.

---

# 17. P1 — Deterministic Rule Provider

현재 ROSY의 기존 if/else / policy logic을 버리지 않는다.

예:

```text
if lane_confidence >= 0.95 and obstacle_clear:
    FOLLOW
```

특징:

```text
fast
deterministic
explainable
offline-safe
```

명확한 상황은 Rule로 끝낸다.

---

# 18. P2 — JEV-style Fast Typed Decision Provider

사용 목적:

```text
정해진 선택지
빠른 판단
확률 기반 결과
짧은 deadline
```

예:

```text
FOLLOW / SLOW / RECOVER / STOP
```

Provider 후보:

```text
JEV hosted
OpenJev-compatible local model
Decider
future typed-decision models
```

ROSY는 특정 제품에 종속되지 않는다.

---

# 19. P3 — Semantic / Vision Judge

필요할 때만 사용.

예:

```text
복잡한 장면 해석
이미지 기반 후보 비교
Auto-label 검수
Grasp 후보 semantic comparison
```

Provider:

```text
Vision decision model
VLM
local multimodal model
external multimodal model
```

일반 Runtime Decision에서 항상 호출하지 않는다.

---

# 20. P4 — Human / Operator

다음 경우:

```text
high risk
persistent ambiguity
recovery exhausted
maintenance
AI/provider disagreement
```

Human Review 가능.

단 Robot은 Human 응답을 무한 대기하지 않는다.

Deadline 이후:

```text
Safe fallback
```

---

# 21. Decision Router

핵심 구성요소.

```text
DecisionRequest
      ↓
Hard Constraints
      ↓
Rule Provider
      ↓ unresolved
Decision Router
      ↓
Provider Selection
      ↓
JEV / OpenJev / Decider / Vision / Human
```

---

# 22. Router가 고려하는 정보

```text
decision_type
risk_class
deadline
input modality
provider health
provider latency
robot connectivity
GPU availability
model version
cost policy
privacy policy
product profile
```

---

# 23. Risk Class

권장:

```text
R0 ANALYTIC
R1 LOW
R2 OPERATIONAL
R3 CRITICAL
```

---

# 24. R0 — ANALYTIC

Robot 실행에 직접 영향 없음.

예:

```text
Auto-label judge
Dataset curation
Offline replay judge
```

Heavy AI 허용.

---

# 25. R1 — LOW

낮은 위험.

예:

```text
UI categorization
non-motion behavior
diagnostic classification
```

JEV/OpenJev/Decider/LLM 등 사용 가능.

---

# 26. R2 — OPERATIONAL

Robot 움직임/작업에 영향.

예:

```text
lane recovery 선택
grasp candidate 선택
route recovery 선택
```

조건:

```text
Allowed Action Set
deadline
confidence threshold
deterministic fallback
Safety Gate
```

필수.

---

# 27. R3 — CRITICAL

직접적인 안전-critical/비가역 결정.

예:

```text
E-stop 해제
hardware safety bypass
unsafe zone entry override
```

AI 단독 authority 금지.

```text
AI recommendation
→ deterministic policy / human / certified safety mechanism
```

만 허용.

---

# 28. Decision Escalation Ladder

```text
Hard Rule
    ↓ unresolved
Fast Local Decision
    ↓ low confidence
Fast Site Decision
    ↓ unresolved
Heavy Vision / Semantic Judge
    ↓ unresolved
Human / Safe Fallback
```

하지만 모든 Decision에 전체 ladder를 쓰지는 않는다.

Product/Risk Profile별로 경로를 정의한다.

---

# 29. Pinky Pro Lane Example

정상:

```text
Camera
 ↓
Lane Provider
 ↓
Canonical Lane State
 ↓
Rule
 ↓
FOLLOW
 ↓
FollowLane Skill
 ↓
PID/Pure Pursuit
```

모호:

```text
Lane confidence = 0.62
intersection detected
         ↓
DecisionRequest
         ↓
Allowed:
FOLLOW
SLOW
RECOVER_LEFT
RECOVER_RIGHT
STOP
ABSTAIN
         ↓
Fast Decision Provider
         ↓
SLOW (0.84)
         ↓
Command Arbitration
         ↓
Skill
```

---

# 30. Pinky Pro Network Failure

```text
Remote JEV unavailable
        ↓
Local Decision Provider
        ↓
unavailable
        ↓
Rule Fallback
        ↓
unresolved
        ↓
SLOW / STOP
```

Remote AI 장애가 Robot Safety 장애로 이어지지 않는다.

---

# 31. Pinky Pro Provider Profile

`products/pinky_pro/ai.yaml`

```yaml
decision:
  lane_recovery:
    risk: OPERATIONAL

    providers:
      - rules
      - local_decider
      - site_jev

    deadline_ms: 120

    confidence:
      accept: 0.82
      escalate_below: 0.82

    fallback:
      timeout: SLOW
      unavailable: SLOW
      exhausted: STOP
```

---

# 32. OMX Grasp Decision

흐름:

```text
Object Detection
 ↓
Pose
 ↓
Grasp Candidate Generator
 ↓
Hard Filter
   collision
   reachability
   workspace
 ↓
Allowed Grasp IDs
 ↓
Decision Provider
 ↓
grasp_03
 ↓
MoveIt
 ↓
Execution
 ↓
Grasp Verification
```

Decision AI가 joint trajectory를 만들지 않는다.

---

# 33. Grasp Recovery Decision

Verification:

```text
SUCCESS
SLIP
EMPTY
UNCERTAIN
```

실패 시 Allowed Actions:

```text
RETRY_SAME
NEW_GRASP
REDETECT
CHANGE_APPROACH
ABORT
ABSTAIN
```

Decision Fabric이 선택.

MoveIt/Controller가 실제 움직임 생성.

---

# 34. Auto-label Judgment

이 영역은 R0이므로 AI 활용 폭을 크게 할 수 있다.

```text
Frame
 ↓
Segmentation Candidate
 ↓
Hard Validator
 ↓
Decision Judge
 ↓
ACCEPT
RETRY
HUMAN_REVIEW
REJECT
```

Provider:

```text
JEV-style typed judge
Vision Decider
VLM
ensemble
```

Runtime safety와 분리된다.

---

# 35. Auto-label Consensus

한 모델 결과를 바로 Ground Truth로 만들지 않는다.

예:

```text
Segmentation Model
     +
Vision Judge
     +
Geometry Validator
     ↓
Consensus
```

결과:

```text
AUTO_ACCEPT
REVIEW
REJECT
```

Golden Set은 human-verified 별도 유지.

---

# 36. Jev/OpenJev/Decider의 위치

이 이름들은 ROSY Architecture 요소가 아니다.

전부:

```text
DecisionProvider
```

구현체다.

```text
rosy_decision
└── providers/
    ├── rules/
    ├── jev/
    ├── openjev/
    ├── decider/
    └── future/
```

단 실제 heavy/local model runtime은 Site AI Worker에 둘 수 있다.

Robot package에는 client adapter만 둘 수 있다.

---

# 37. Local vs Site Provider

```text
ROBOT LOCAL
small model / rule
fast fallback
network independent

SITE
RTX 5080
larger model
vision judge
high-quality decision

CLOUD
optional
external provider
not required
```

---

# 38. Provider Placement

`rosy_decision`:

```text
provider interface
routing
client adapters
policy
fallback
validation
```

`rosy_ai_worker`:

```text
actual model serving
GPU inference
model loading
batching
training
```

---

# 39. AI Worker Decision Endpoint

예:

```text
POST /v1/decision/evaluate
```

입력:

```text
DecisionRequest
```

출력:

```text
DecisionResult
```

특정 모델 이름을 API path에 넣지 않는다.

나쁜 예:

```text
/v1/jev/decide
```

권장:

```text
/v1/decision/evaluate
```

Provider는 policy/config가 선택.

---

# 40. Shadow Decision

새 Provider는 실제 명령을 내리기 전에 Shadow로 검증한다.

```text
Production:
Rule → actual

Shadow:
JEV/Decider → log only
```

비교:

```text
selected action
probability
latency
outcome
recovery
safety intervention
```

---

# 41. Champion / Challenger

Decision Provider도 Model Registry 정책 사용.

```text
decision/lane@champion
decision/lane@challenger
decision/lane@shadow
decision/lane@rollback
```

---

# 42. Confidence != Safety

중요:

```text
confidence 0.99
```

라고 해서 안전하지 않다.

Acceptance:

```text
valid input
fresh snapshot
allowed action
deadline met
provider healthy
confidence threshold
policy validation
```

모두 통과해야 한다.

---

# 43. Calibration

Provider가 주는 probability/confidence를 그대로 절대 기준으로 믿지 않는다.

Decision type마다 실제 데이터로 calibration을 평가한다.

지표 예:

```text
accuracy
false accept
false stop
abstention rate
Brier score
ECE
latency p95/p99
```

---

# 44. Provider Health

```text
READY
DEGRADED
UNAVAILABLE
UNKNOWN
```

Health 기준:

```text
model loaded
last successful inference
latency SLO
error rate
GPU memory
queue depth
```

---

# 45. Deadline Semantics

Request:

```text
deadline_ms: 100
```

100ms 이후 결과가 도착하면:

```text
LATE_RESULT
```

실행에는 사용하지 않는다.

Shadow metric에는 기록 가능.

---

# 46. Snapshot Consistency

Decision은 특정 World Snapshot을 기준으로 한다.

```text
world_snapshot_id: ws_10291
```

실행 전에:

```text
snapshot still valid?
```

검사.

상황이 이미 크게 변했으면 결과 폐기.

---

# 47. Decision Validity Window

```text
valid_until
```

을 둔다.

특히 움직이는 Robot에서는 오래된 판단 재사용 금지.

---

# 48. Evidence

Decision마다 가능하면:

```text
state refs
image/frame refs
sensor refs
provider/model
policy version
```

를 기록.

Free-form chain-of-thought는 요구하지 않는다.

사후 분석 가능한 machine-readable evidence를 남긴다.

---

# 49. Decision Audit

Episode/Incident에:

```text
decision_id
request
allowed_actions
selected_action
probabilities
provider
model
latency
fallback
final command outcome
```

기록.

---

# 50. Decision과 Command 연결

Decision Result가 곧 Command가 아니다.

```text
DecisionResult
      ↓
Intent Proposal
      ↓
rosy_runtime Authority
      ↓
Command Arbitration
      ↓
Command
```

이 구조가 매우 중요하다.

---

# 51. Command Authority가 Decision을 거부할 수 있다

예:

```text
Decision = FOLLOW

그러나:
Mode = MANUAL
```

이면:

```text
POLICY_REJECTED
```

Decision 자체는 기록하지만 실행하지 않는다.

---

# 52. Safety가 Command를 거부할 수 있다

예:

```text
Decision = NAVIGATE
Command accepted
Control generated
LiDAR guard detects person
```

Safety:

```text
STOP
```

Decision 결과와 실제 outcome이 다를 수 있다.

그래서 Episode에 둘 다 기록한다.

---

# 53. Decision Provider Configuration

Product-specific.

```text
products/pinky_pro/ai.yaml
products/omx/ai.yaml
```

공통 provider implementation은 `rosy_decision` / `rosy_ai_worker`.

---

# 54. Decision Policy Configuration

예:

```yaml
decision_type: lane_recovery

risk: OPERATIONAL

allowed_providers:
  - rules
  - local_decider
  - site_jev

remote_allowed: true

deadline_ms: 120

thresholds:
  accept: 0.82
  abstain_below: 0.60

fallback:
  timeout: SLOW
  low_confidence: SLOW
  no_provider: STOP
```

---

# 55. Decision Type Registry

Decision은 자유 문자열이 아니라 registry로 관리한다.

예:

```text
lane_recovery
intersection_choice
dock_recovery
grasp_selection
grasp_recovery
obstacle_semantic
autolabel_acceptance
incident_classification
```

각 type은:

```text
schema
allowed action schema
risk
default deadline
provider profile
fallback
```

를 가진다.

---

# 56. 새 Folder 추가

최종 v0.7 Tree에 다음을 추가한다.

```text
src/runtime/rosy_decision/
```

그리고 계약:

```text
src/contracts/rosy_domain/decision/
src/contracts/rosy_protocols/decision/
```

AI Worker:

```text
src/site/rosy_ai_worker/
└── .../inference/decision/
```

---

# 57. 최종 Runtime Tree

```text
src/runtime/
├── rosy_runtime/
├── rosy_decision/          # NEW
├── rosy_robot_api/
├── rosy_pinky_pro/
├── rosy_navigation/
└── rosy_manipulation/
```

책임:

```text
rosy_runtime
= authority / lifecycle / state / command

rosy_decision
= judgment / provider routing / fallback / shadow

rosy_pinky_pro
= Pinky perception/mobility/skills

rosy_navigation
= Nav2

rosy_manipulation
= grasp/moveit/manipulation

rosy_robot_api
= robot-local API
```

---

# 58. End-to-End Pinky Decision

```text
Camera
  ↓
Perception Provider
  ↓
Canonical State
  ↓
Decision Type: lane_recovery
  ↓
Allowed Action Set
  ↓
Rule
  ↓ unresolved
rosy_decision Router
  ↓
JEV / OpenJev / Decider Provider
  ↓
DecisionResult
  ↓
Policy Validation
  ↓
Intent Proposal
  ↓
rosy_runtime Arbitration
  ↓
FollowLane / Recover Skill
  ↓
Controller
  ↓
Safety
  ↓
Motor
```

---

# 59. End-to-End OMX Decision

```text
RGB-D
 ↓
Detection / Segmentation / Pose
 ↓
Grasp Candidates
 ↓
Hard feasibility filter
 ↓
Allowed Grasp IDs
 ↓
rosy_decision
 ↓
Decision Provider
 ↓
Selected Grasp
 ↓
rosy_runtime authority
 ↓
Pick Skill
 ↓
MoveIt
 ↓
Controller
 ↓
Safety
 ↓
Arm
 ↓
Verify
 ↓
Recovery Decision if needed
```

---

# 60. End-to-End Auto-label Decision

```text
Episode
 ↓
Candidate Label
 ↓
Hard Validator
 ↓
AI Judge
 ↓
Decision:
ACCEPT / RETRY / REVIEW / REJECT
 ↓
Dataset
```

이 판단은 Robot Runtime과 별도이며 R0 Analytics다.

---

# 61. Decision Failure Flow

```text
Provider unavailable
       ↓
next provider
       ↓
timeout
       ↓
fallback
       ↓
low confidence
       ↓
ABSTAIN
       ↓
safe policy / human
```

---

# 62. Decision System Invariants

1. AI does not define its own action space.
2. AI does not own actuator authority.
3. AI result must reference a world snapshot.
4. Late result is invalid for execution.
5. Invalid output is not coerced into a valid action.
6. Low confidence can lead to ABSTAIN.
7. Provider failure must have explicit fallback.
8. Remote provider loss must not disable local safety.
9. Decision result and executed command are separately logged.
10. Shadow provider cannot influence actuator output.
11. Critical safety decisions cannot rely on AI alone.
12. Provider/model/version are always recorded.
13. Product controls provider policy, not hardcoded application logic.
14. Decision routing is common across Products.
15. Training/serving implementation is separate from runtime decision authority.

---

# 63. Migration from Existing ROSY

현재 `core_features` / `control` 내부에 흩어진 판단 로직을 세 부류로 분류한다.

```text
A. Safety invariant
→ Safety ownership

B. Deterministic operational rule
→ rosy_decision/rules

C. Product-specific perception/control
→ rosy_pinky_pro or rosy_manipulation
```

분류 후 Decision API를 통해 연결한다.

---

# 64. 초기 구현 우선순위

## P0
1. Decision domain schema
2. Allowed Action Set
3. DecisionResult
4. Decision Router
5. Rule Provider
6. Deadline / ABSTAIN / fallback
7. Decision audit

## P1
8. Pinky lane_recovery Decision Type
9. Shadow Provider Adapter
10. Local Decider/OpenJev adapter
11. Site AI Worker Decision API

## P2
12. Grasp selection Decision Type
13. Grasp recovery
14. Auto-label judge
15. Model registry aliases
16. Provider calibration metrics

## P3
17. JEV hosted provider optional adapter
18. Vision decision provider
19. Human escalation UI
20. multi-provider ensemble / consensus where justified

---

# 65. 첫 번째 실제 Reference Use Case

첫 적용은 Pinky Pro `lane_recovery`로 권장한다.

이유:

```text
이미 perception/control pipeline 존재
선택지가 제한 가능
Rule baseline 존재
Shadow 비교 가능
실패 시 SLOW/STOP fallback 가능
```

즉 Decision Fabric 검증에 적합하다.

---

# 66. 두 번째 Reference Use Case

Auto-label acceptance.

```text
ACCEPT
RETRY
REVIEW
REJECT
```

Runtime actuator 위험이 없기 때문에 Provider benchmark와 calibration을 빠르게 반복할 수 있다.

---

# 67. 세 번째 Reference Use Case

OMX grasp recovery.

```text
RETRY_SAME
NEW_GRASP
REDETECT
CHANGE_APPROACH
ABORT
```

Decision과 Motion Planning이 명확히 분리되는 좋은 사례다.

---

# 68. Final Architecture

```text
                         ROSY DOMAIN CONTRACTS
                                  │
                                  ▼
                           CANONICAL STATE
                                  │
                                  ▼
                           ROSY DECISION
                  ┌───────────────┼────────────────┐
                  ▼               ▼                ▼
               RULE          TYPED MODEL      HEAVY JUDGE
                            JEV/OpenJev/
                               Decider
                  │               │                │
                  └───────────────┼────────────────┘
                                  ▼
                         DECISION RESULT
                                  │
                                  ▼
                         INTENT PROPOSAL
                                  │
                                  ▼
                          ROSY RUNTIME
                     Authority / Arbitration
                                  │
                                  ▼
                                SKILL
                                  │
                                  ▼
                         CONTROL / NAV / ARM
                                  │
                                  ▼
                               SAFETY
                                  │
                                  ▼
                              HARDWARE
```

---

# 69. 최종 정의

> **ROSY Decision Fabric은 JEV/OpenJev/Decider/Rule/Local AI/Heavy AI를 교체 가능한 Decision Provider로 취급하고, 각 Provider가 Mission과 Safety가 정의한 Allowed Action Set 안에서만 typed decision을 반환하도록 하며, deadline·confidence·ABSTAIN·fallback·shadow·audit을 공통으로 처리하는 Runtime 판단 계층이다.**

JEV나 Decider는 ROSY의 중심이 아니다.

중심은:

```text
Decision Contract
Allowed Action Set
Provider Routing
Risk Policy
Fallback
Authority Separation
```

이다.

모델은 바뀌어도 구조는 유지되어야 한다.
