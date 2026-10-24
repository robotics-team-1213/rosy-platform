---
title: lerobot 0.4.4 Dynamixel 버스는 drive_mode를 적용하지 않는다 — OMX 단위 변환에 drive_mode를 넣지 않는다
date: 2026-10-24
category: logic-errors
module: contracts/learning action_space (D-854), 은퇴한 rosy-vault device_core/backends/lerobot_policy.py (V-018)
problem_type: logic_error
component: data_conversion
symptoms:
  - "rad ↔ lerobot 정규화 변환 시험이 녹색인데, 보정 파일의 drive_mode가 1인 관절은 부호가 뒤집히고 그리퍼는 100 - n이 됨"
  - "공장 기본 보정(omx_follower.calibrate()는 모든 모터에 drive_mode=0을 씀)에서는 증상이 보이지 않음"
root_cause: wrong_assumption
resolution_type: code_fix
severity: high
applies_when: OMX(omx_follower·omx_leader) 관절 값을 lerobot 정규화 값과 rad·raw 사이에서 직접 변환하는 코드를 쓰거나 고칠 때
tags: [lerobot, dynamixel, drive_mode, omx, units, normalization, d-854, v-018]
---

# lerobot 0.4.4 Dynamixel 버스는 drive_mode를 적용하지 않는다

## Problem

D-854 1단계 변환기(`action_space.py`)와 은퇴한 V-018 `Units`는 `motors_bus._normalize`의 식을 옮기면서 `drive_mode`가 1이면 몸 관절을 `-n`, 그리퍼를 `100 - n`으로 바꿨다. 시험의 골든 값도 같은 식으로 손으로 계산해서 녹색이었다. 독립 검토에서 lerobot 원본과 대조하다 어긋남을 찾았다.

## Root cause

`motors_bus._normalize`는 `drive_mode = self.apply_drive_mode and self.calibration[motor].drive_mode`를 쓴다. `motors/dynamixel/dynamixel.py`의 `DynamixelMotorsBus`는 `apply_drive_mode = False`다(lerobot v0.4.4, 109행). 그래서 OMX에서는 보정 파일의 `drive_mode` 값과 무관하게 부호·뒤집기가 일어나지 않는다. `_normalize` 본문만 읽고 버스 클래스 속성을 보지 않으면 놓친다.

## Solution

- 변환기는 `drive_mode`를 읽지 않는다. 보정 digest도 `range_min`·`range_max`만 쓴다.
- 시험 `test_drive_mode_is_ignored_like_lerobot_dynamixel_bus`가 `drive_mode`를 모두 1로 바꿔도 결과와 digest가 같음을 확인한다.

## Verification

- lerobot v0.4.4 원본: `dynamixel.py:109 apply_drive_mode = False`, `motors_bus.py:847` · `876`의 `apply_drive_mode and ...`.
- 원격 시험 PC에서 `test/test_learning_action_space.py` 통과.

## Prevention

- 남의 라이브러리 식을 옮길 때 함수 본문뿐 아니라 그 함수가 읽는 클래스 속성(여기서는 `apply_drive_mode`)과 실제 쓰는 서브클래스를 확인한다.
- 골든 값은 옮긴 식이 아니라 원본 라이브러리 동작에서 뽑는다. 원본을 쓸 수 없으면 원본 소스의 행 번호를 시험 주석에 남긴다.
- 은퇴 전 V-018 방식으로 `drive_mode: 1` 보정을 써서 만든 변환 값이 있으면 D-854 변환기로 다시 만든다.
