# 09. ROSY Composite Robot Specification

## 1. Purpose

ROSY can combine multiple Devices into one logical Asset.

## 2. Initial Target

```text
PINKY-01
+
OMX-F-01
+
VISION
=
MOBILE-MANIPULATOR-01
```

## 3. Asset Capabilities

The composite asset may expose:

- navigate
- perceive
- approach
- manipulate
- pick
- place
- transport
- dock

## 4. Example Asset Definition

```yaml
asset_id: MOBILE-MANIPULATOR-01
type: mobile_manipulator

devices:
  - PINKY-01
  - OMX-F-01
  - CAMERA-01

capabilities:
  - navigate
  - detect
  - pick
  - place
  - transport
  - dock
```

## 5. Control Boundary

Pinky remains responsible for:

- mobile base control
- local mobility safety
- docking

OMX remains responsible for:

- joint control
- trajectory execution
- gripper control
- local manipulation safety

ROSY orchestrates the sequence.
