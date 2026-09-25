# 11. ROSY AI & Physical AI Architecture

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
