# 01. ROSY Platform Target Architecture

**범위:** 장기 목표 그림이다. 현재 배포/외부 API의 정본은 [D-59](../adr/D-59-.md), [D-65](../adr/D-65-core-d-62.md), [D-269](../adr/D-269-device-server-contracts-and-ros-boundary.md), [D-290](../adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md), [D-296](../adr/D-296-device-middleware-and-site-orchestration-terminology.md)과 API Reference다. 아래 `Control Plane`, `Compute Fabric`, 설치 프로파일 이름은 완성된 서비스·패키지를 뜻하지 않는다. 현재 실행 단위와 진입 조건은 [구조 간극 지도](../plans/2026-09-26-platform-structure-gap-map.md), 순차 구현과 폴더 역할은 [ROSY Platform 부모 계획](../plans/2026-09-27-rosy-platform-role-and-contract-implementation-plan.md)에 구분한다.

## 1. Layer Model

```text
Application / Mission
        |
ROSY Control Plane
        |
ROSY Task / Capability Layer
        |
ROSY Fabric
        |
ROSY Runtime
        |
ROS 2 / ros2_control / AI Runtime
        |
Ubuntu Linux
        |
Hardware
```

## 2. Major Subsystems

### ROSY Control Plane

Responsibilities:

- registry
- fleet manager
- task orchestrator
- compute scheduler
- model/policy manager
- deployment manager
- dashboard
- API

### ROSY Runtime

Target node-local role, not one shared controller for all devices (D-296). Today Pinky has its own CORE and fixed OMX has a disabled adapter/development runtime; there is no universal runtime process installed on every PC or camera. A future OMX local controller retains final arm command ownership even when OMX is mounted on Pinky; Fleet retains site mission ownership.

Responsibilities:

- identity
- configuration
- discovery
- heartbeat
- state
- health
- plugin loading
- local task execution
- logging
- update agent

### ROSY Fabric

Names the versioned contracts and adapters between roles (D-290). It is not one global DDS graph or a mandatory central broker. ROS 2 topics/services/actions below remain within each device's local control boundary; site-to-device links use admitted HTTPS REST/WSS contracts (D-269).

Includes:

- ROS 2 topics
- ROS 2 services
- ROS 2 actions
- device events
- task state
- compute jobs
- control-plane messages

### Device Framework

Provides adapters for:

- Pinky
- OMX
- Camera
- LiDAR
- RFID
- PLC
- generic ROS 2 devices

### Compute Fabric

Provides:

- CPU workers
- GPU workers
- OpenVINO
- CUDA
- TensorRT
- optional Ray backend
- model routing
- job scheduling

## 3. Example Deployment

The following GRAM/RTX and cross-node picture is a target concept, not the current site Compose or an approved ROS 2 connection between hosts. The currently implemented site entry and OMX placement candidates are described in the [role topology](../plans/2026-09-26-site-role-deployment-topology-design.md).

```text
                ROSY CONTROL PLANE
                      GRAM-01
                         |
==================== ROSY FABRIC ====================
      |             |             |            |
    PINKY         OMX-F         GRAM-02      RTX5080
      |             |             |            |
   ROSY RT        ROSY RT       ROSY RT      ROSY RT
      |             |             |            |
 Navigation     ros2_control    OpenVINO      CUDA
 Camera         DYNAMIXEL       Tracking      TensorRT
 LiDAR          Gripper         Vision        VLM/VLA
```

## 4. Safety Boundary

The Control Plane is never part of a hard real-time safety loop.

If the Control Plane is unavailable:

- Pinky must stop safely or continue only approved local behavior.
- OMX must preserve local joint and workspace safety.
- local device state must remain available.
- reconnection must be automatic.

## 5. Profile-Based Deployment

Illustrative target profile names, not currently installable package names or a claim of supported combinations:

- `rosy-profile-control`
- `rosy-profile-pinky`
- `rosy-profile-omx`
- `rosy-profile-edge`
- `rosy-profile-gpu`
- `rosy-profile-vision`
- `rosy-profile-rfid`
- `rosy-profile-dev`

Target roles may eventually be combined on one host after their device and stop-path acceptance. Today's Pinky CORE stays on its Pi. One or two fixed OMX workcells may be candidates to share an Ubuntu host after D-281/D-282 acceptance. A physically mounted Pinky+OMX composite robot is a separate later product gate (D-55/D-71).

## 6. Non-Functional Requirements

- modular installation
- minimal node footprint
- local degraded operation
- fault isolation
- versioned interfaces
- reproducible deployment
- backward-compatible profile evolution
- central observability
