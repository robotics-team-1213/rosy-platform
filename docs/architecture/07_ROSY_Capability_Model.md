# 07. ROSY Capability Model

## 1. Purpose

Capabilities decouple tasks from specific hardware.

## 2. Capability Categories

### Mobility

- navigate
- move
- rotate
- dock
- follow

### Manipulation

- pick
- place
- grip
- release
- move_joint
- execute_trajectory

### Perception

- detect
- classify
- segment
- track
- estimate_pose
- scan_rfid

### AI / Compute

- infer
- embed
- reason
- train
- simulate

## 3. Capability Descriptor

Example:

```yaml
id: manipulate.pick
version: 1.0

requirements:
  - gripper
  - pose_estimation

constraints:
  max_payload_g: 250
```

## 4. Provider Model

Capabilities can be provided by:

- Device
- Asset
- Compute Node

## 5. Dynamic Availability

Capability availability depends on:

- device state
- node health
- runtime profile
- current load
- installed models
- safety policy
