# 09. ROSY Composite Robot Specification

**범위:** Pinky에 OMX가 물리적으로 결합된 미래 Asset의 목표 예시다. 지금의 고정 OMX-AI 작업대 1~2대를 Pinky와 합성한다는 뜻이 아니다. 현행 v1 Asset은 단일 Pinky Device이며 합성 Asset은 [D-71](../adr/D-71-concept-05-09-12-15-apt-v1.md)에 따라 연기됐다. 이동 조작은 [D-55](../adr/D-55-mobile-manipulation-is-a-robot-local-mission-capability.md)의 장착·전원·충돌·보정·정지·실물 수용 뒤 별도 단계다.

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
