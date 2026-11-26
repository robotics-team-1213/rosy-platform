---
title: "MuJoCo RGB-D는 엔코더를 읽은 상태에서 기하를 갱신한 뒤 렌더한다"
date: 2026-11-26
category: runtime-errors
module: tools/sim/omx_two_arm_world.py
problem_type: runtime_error
component: simulation
severity: medium
symptoms:
  - "직전 명령 이후 팔의 깊이 윤곽과 현재 관절값으로 예측한 윤곽이 같은 화면 위치에서 어긋난다"
  - "무작위 가림이 없는 시뮬레이션에서도 운반·하강·주차 중 이웃 관측 가드가 보류한다"
root_cause: async_timing
resolution_type: code_fix
tags: [mujoco, rgbd, encoder, exposure-timing, omx, occlusion]
applies_when: "MuJoCo 물리 적분 직후 RGB-D를 렌더하고 같은 회차의 관절값으로 자체 팔 윤곽을 설명할 때"
---

# MuJoCo RGB-D를 엔코더 상태에 맞춘다

## 증상과 원인

B c3 시뮬레이션에서 움직이는 팔의 깊이 윤곽을 현재 관절값으로 설명하지 못해
운반, 하강 또는 주차가 보류됐다. 같은 시드에서 배경을 고정해도 발생했다.

[OMX 시뮬레이터](../../../tools/sim/omx_two_arm_world.py)의 동작 경로는
`mj_step`으로 적분한 뒤 `MjData`를 반환한다. `qpos`는 적분 결과를 담지만
그 즉시 렌더에 쓰는 `geom_xpos`가 같은 관절값을 반영한다고 가정하면 안 된다.
렌더러의 `update_scene`은 전달받은 기하를 사용한다. 따라서 같은
`data.time`에서 읽은 관절값과 렌더 기하도 어긋날 수 있다.
이 경우 주변 물체에 대한 실제 관측 부족과 팔 자체의 깊이 시간차가 같은 보류 사유에 섞인다.

## 적용

시뮬레이션에서 사진을 찍는 경계에만 적용한다. 물리에 사용하는 상태를 복제해
파생 기하를 갱신하고 RGB와 깊이를 같은 복제본에서 얻는다. 관절 입력도
그 상태에 속한 것을 쓴다.

```python
from copy import copy

exposure = copy(data)
mujoco.mj_forward(model, exposure)
encoder = exposure.qpos[arm_qpos_indices].copy()
renderer.update_scene(exposure, camera="top")
depth = renderer.render().copy()
```

목적지와 가드 임계값, 관절 명령과 적분 순서는 유지한다. 원본 상태는 그대로
물리에 사용한다. 이후 관측이 부족하면 해당 단계에서 보류한다.
지원 여부를 다시 확인하려면 위 복제본 경계와 기존 렌더 경계를 같은
장면에서 비교하고 다음 회귀를 수행한다.

## 재현과 검증

- 최소 재현은 중력 없는 Z 슬라이드에 4 m/s 초기 속도를 주고 20 ms를 한 번
  적분한다. 반지름 0.10 m인 구를 원점에 두고, 높이 1.00 m에서 원점을 보는
  64×64 상단 카메라의 중앙 깊이를 원본과 복제본에서 읽는다.
  MuJoCo 3.3.7에서 관절 위치는 0.080 m, 원본 깊이는 0.9010 m,
  갱신 후 깊이는 0.8209 m였다. 시각은 0.020 s로 같고, 원본의
  `mjSTATE_INTEGRATION`과 복제본의 `qpos`·`qvel`은 그대로였다.
  재현은 `verify_mujoco_exposure_clone.py`, 실행 영수증은
  `verify-mujoco-exposure-clone.json`에 있다.
- 실제 B 진단에서 새로 복원한 각 정지 상태를 복제하고 같은 관절값으로
  대조했다. 유효 거리로 해석할 수 있는 두 픽셀의 예측 잔차가 7.698 mm와
  18.673 mm에서 각각 0 mm로 줄었다. 역사 실행과 재생의 시작 해시는
  달랐으므로 이 수치는 각 재생 내부의 대조에 적용된다.
  나머지 두 진단의 깊이 센티널은 거리 차이 통계에서 제외했다.
  원본은 `optical-epoch-same-q-20831.json`이다.
- 독립 시드 20881–20890에서 같은 ACT 파지 상태와 고정 운반 경로를
  대조했다. B c3 완주는 정상 1/10에서 4/10, 측면 입력 차단 3/10에서
  8/10으로 바뀌었다. 정상 20887은 기존에는 완주했고 갱신 분기는 운반
  중 바닥 지지를 확인하지 못해 보류했다. 정지 위치·접촉·지지 원본의
  검증 영수증은 `optical-epoch-heldout-20881-audit.json`이다.
- 별도 시드 20875에서 외부 근접 가림, 잘못된 목표 깊이, 이웃 이동을
  각각 주입했다. 두 시야 조건의 여섯 대조 모두 이송 명령 전에 보류했다.
  원본은 `optical-epoch-negative-20875.json`이다.

회귀 시험에서 원본과 복제본의 시각과 원본 상태 해시를 먼저 비교하고,
렌더 카메라와 고정 경로를 일치시킨다. 유효 깊이만 거리로 읽고 센티널은
별도로 집계한다. 2026-11-26 OMX 좌표 이송 30분 점검의 B c3 단일 이송
항목에서 독립 시드 원본 두 건과 체크섬을 확인할 수 있다.

## 현장 적용 범위

이 방법은 시뮬레이터 내부의 관절값과 렌더 기하를 맞춘다. 실물 카메라의
노출 시각, 관절값 수신 시각, 깊이 등록은 장치에서 확인해야 한다.
[D435 시작 프레임 검증](../workflow-issues/d435-first-depth-frame-is-not-a-ready-measurement-2026-11-05.md)과
[카메라 이동 후 등록 검증](omx-camera-shift-rebase-must-move-config-pixels-and-remap-fails-over-a-pile-2026-11-13.md)은
별도 현장 증거다. 2026-11-26 11:45 무명령 관측에서도 A는 기준 영상
보정이 필요했고 B는 지정 바닥·팔 좌표 보정이 확인되지 않아 두 팔 모두
HOLD였다.

[Isaac NativeRecorder의 오래된 촬영 캐시](isaac62-native-recording-stale-reference-time-2026-10-29.md)는
물리 시간과 카메라 반환 시간의 불일치를 다룬다. 여기서는 MuJoCo에서
같은 시각 값에 담긴 파생 기하를 확인한다.
