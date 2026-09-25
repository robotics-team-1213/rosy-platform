# 02. ROSY Domain Model

## 1. Core Objects

ROSY OS uses six primary domain objects.

## 2. Node

A computer on which ROSY Runtime executes.

Examples:

- `PINKY-COMPUTE-01`
- `GRAM-02`
- `GPU-01`

Core fields:

- node_id
- hostname
- architecture
- os
- runtime_version
- profiles
- resources
- state
- health

## 3. Device

A physical or logical device managed by a Node.

Examples:

- `PINKY-01`
- `OMX-F-01`
- `RFID-GATE-01`

## 4. Component

A functional element inside a Device.

Examples:

- motor
- camera
- LiDAR
- joint
- gripper
- antenna
- GPIO

## 5. Capability

A normalized statement describing what a Device or Asset can do.

Examples:

- navigate
- detect
- track
- pick
- place
- dock
- scan_rfid
- infer
- train

## 6. Asset

A logical composition of one or more Devices.

Example:

```text
PINKY-01
+
OMX-F-01
+
CAMERA-01
=
MOBILE-MANIPULATOR-01
```

## 7. Task

A unit of work requested from a Device or Asset.

Examples:

- MoveTo
- Pick
- Place
- Transport
- Dock
- Inspect
- InventoryScan

## 8. Relationships

```text
Node
  -> hosts Device

Device
  -> contains Component

Device
  -> exposes Capability

Asset
  -> combines Device

Task
  -> requires Capability
```

## 9. Scheduling Principle

ROSY should assign work by required capability, not hard-coded hardware identity.

Example:

```yaml
task: detect_object
requires:
  - vision
  - object_detection
```

ROSY may choose:

- RTX GPU
- Intel OpenVINO node
- local device inference

based on policy and availability.
