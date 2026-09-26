# 01. ROSY OS Target Architecture

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

Runs on every ROSY Node.

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

Standardizes communication between ROSY nodes.

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

Supported profiles:

- `rosy-profile-control`
- `rosy-profile-pinky`
- `rosy-profile-omx`
- `rosy-profile-edge`
- `rosy-profile-gpu`
- `rosy-profile-vision`
- `rosy-profile-rfid`
- `rosy-profile-dev`

Profiles can be combined.

Example:

```yaml
profiles:
  - rosy-profile-pinky
  - rosy-profile-omx
```

This allows Pinky and OMX to share one host if necessary.

## 6. Non-Functional Requirements

- modular installation
- minimal node footprint
- local degraded operation
- fault isolation
- versioned interfaces
- reproducible deployment
- backward-compatible profile evolution
- central observability
