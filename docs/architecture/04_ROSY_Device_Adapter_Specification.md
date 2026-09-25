# 04. ROSY Device Adapter Specification

## 1. Purpose

Adapters translate vendor- or hardware-specific interfaces into ROSY-standard interfaces.

## 2. Adapter Package Layout

```text
adapter/
  manifest.yaml
  config/
  launch/
  src/
  interfaces/
  capabilities/
  tests/
```

## 3. Adapter Manifest

Example:

```yaml
id: rosy.device.omx
version: 0.1.0
device_type: manipulator

requires:
  - rosy-runtime-base
  - rosy-runtime-ros2

provides:
  - joint_control
  - gripper
  - manipulation
```

## 4. Pinky Adapter

Expected capabilities:

- drive
- battery
- camera
- lidar
- docking
- local_safety

## 5. OMX Adapter

Expected capabilities:

- joint_state
- joint_command
- gripper
- trajectory
- manipulation
- ros2_control bridge
- DYNAMIXEL integration

## 6. Adapter Responsibility Boundary

Adapters may implement:

- device-specific translation
- validation
- state mapping
- hardware access

Adapters must not contain:

- global mission logic
- fleet orchestration
- AI scheduling
- cross-device workflow logic
