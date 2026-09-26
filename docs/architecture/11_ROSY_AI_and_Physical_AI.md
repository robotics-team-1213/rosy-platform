# 11. ROSY AI & Physical AI Architecture

**범위:** 모델 레지스트리·VLA·정책 배포·GPU 스케줄러는 [D-71](../adr/D-71-concept-05-09-12-15-apt-v1.md)의 후속 목표다. 현재 사이트 Vision은 천장 폰의 CPU ArUco 관측 경로이며 [D-268](../adr/D-268-policy-eligible-vision-evidence-for-fleet-tasks.md)이 Proposed인 동안 자동 작업 증거가 아니다. 아래 AI 출력은 후보/관측이고, Fleet의 작업 검증과 장치 로컬 제어·안전 경계를 통과하기 전에는 물리 동작을 만들지 않는다([D-290](../adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md)).

## 1. Purpose

ROSY AI coordinates AI capabilities across devices and compute nodes.

## 2. AI Runtime Responsibilities

- model registry
- model deployment
- inference routing
- GPU resource management
- edge fallback
- policy deployment
- version tracking

## 3. AI Workload Classes

### Edge AI

Examples:

- lightweight detection
- tracking
- preprocessing
- feature extraction

### GPU AI

Examples:

- DINO
- YOLO heavy models
- segmentation
- VLM
- VLA
- policy inference
- training

## 4. Physical AI Boundary

AI does not directly control actuator loops.

Preferred structure:

```text
AI Policy
  -> desired action
  -> ROSY Runtime
  -> validation
  -> ROS 2 / ros2_control
  -> actuator
```

## 5. Degraded AI

ROSY should support:

```text
FULL_AI
DEGRADED_AI
EDGE_ONLY
AI_OFFLINE
```

When GPU compute is unavailable, ROSY may:

- use edge fallback
- reduce model quality
- queue non-critical jobs
- reject tasks that require unavailable AI
