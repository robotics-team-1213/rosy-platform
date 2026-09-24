---
title: 카메라 마운트를 손으로 유도하면 기울어진 조인트 안쪽 오프셋을 빠뜨린다 — URDF 조인트 체인에서 다시 계산해 시험으로 묶는다
date: 2026-09-24
category: logic-errors
module: sim/gz_sim launch + core/control (dock_observer, line_observer 카메라 외부 파라미터)
problem_type: logic_error
component: development_workflow
severity: medium
symptoms:
  - "Gazebo의 모든 프레임에서 도킹 태그 거리가 길게 읽힘 (이 세션 측정으로 합계 약 10 mm)"
  - "camera_info의 주점(W/2, H/2)을 그대로 쓰면 u, v가 -0.5 px 어긋남"
  - "보정 후에도 +4~+9 mm의 거리 편향이 남음"
root_cause: logic_error
resolution_type: code_fix
related_components:
  - testing_framework
tags: [camera-extrinsics, urdf, xacro, principal-point, gazebo, dock-tag, launch-params]
---

# 카메라 마운트를 손으로 유도하면 기울어진 조인트 안쪽 오프셋을 빠뜨린다 — URDF 조인트 체인에서 다시 계산해 시험으로 묶는다

## Problem

`src/sim/gz_sim/launch/map_v2_fleet_lane.launch.py`의 dock_observer가 카메라 위치를
`camera_x_offset_m: 0.034`로 선언했다. 이 값은 `0.020 + 0.015*cos(25°)`로 손으로 유도한 것이다.
URDF에서 카메라 링크는 25° 기울어진 마운트 안에서 -0.0121 m 내려가 있다. 기울어진 좌표계에서는
이 수직 오프셋도 x 성분(-0.0121·sin 25° ≈ -5.1 mm)을 만드는데, 손 계산은 이를 빠뜨렸다.
실제 센서 위치는 base_footprint 기준 x = 0.028481 m다(`gz sdf -p`로 확인한 값이 0.0284809).

주점도 틀렸다. Gazebo는 픽셀 i의 광선을 i + 0.5로 쏘는데 camera_info는 W/2를 보고한다.
OpenCV 규약(픽셀 중심이 정수)에 맞는 주점은 ((W−1)/2, (H−1)/2)다.

## Symptoms

- x 오프셋만으로 태그 거리가 매 프레임 5.5 mm 길게 읽혔다(가드 시험 docstring).
- 주점 반 픽셀 오차는 렌더된 쐐기에서 u, v 모두 -0.5 px, 측방 0.5 mm, 요 0.13° 편향으로
  측정됐다(`src/core/control/control/sensing/dock_observer.py`의 `camera_matrix_from_hfov`
  docstring). 이 세션 측정으로는 둘을 합쳐 거리가 약 10 mm 길었다.

## What Didn't Work

- 조인트 체인을 머릿속으로 펼친 삼각함수 한 줄. 부모 조인트의 회전이 자식 오프셋 전체에
  걸린다는 점, 즉 z 오프셋도 회전되어 x로 샌다는 점을 놓친다.
- Gazebo camera_info의 주점을 그대로 믿기. 렌더러와 보고값이 반 픽셀 다르다.

## Solution

1. dock_observer의 `camera_x_offset_m`을 `0.028481`로 고쳤다. `camera_height_m`은 `0.060194`로, 같은 체인의 z 값과 일치한다.
2. `camera_matrix_from_hfov`가 `cx, cy = (width - 1.0) / 2.0, (height - 1.0) / 2.0`을 쓴다.
3. 가드: `src/sim/gz_sim/test/test_map_v2_fleet_launch.py`의 `test_the_dock_observer_mount_is_the_urdf_camera`.
   `_urdf_camera_on_base_footprint`가 xacro의 조인트 체인(base_footprint → base_link →
   front_camera_mount(기울기) → front_camera_link)에서 원점을 읽어, 마운트 회전을 링크 오프셋에
   적용해 위치를 다시 계산한다. launch 파일의 dock_observer 블록에 선언된 값이 그 결과와
   1e-5 m 안에서 같아야 통과한다. URDF나 launch 중 어느 한쪽만 바뀌어도 시험이 깨진다.

**남은 것(보류):** 같은 launch 파일의 line_observer 파라미터는 아직 `camera_x_offset_m: 0.034`
(주석도 `0.020 + 0.015*cos(25 deg)`)다. 같은 체인으로 고치고 가드를 넓히는 작업이 열려 있다.

보정 후에도 +4~+9 mm의 거리 편향이 남는다. 이 세션의 판단으로는 비스듬히 보이는 태그 텍스처가
sRGB 렌더에서 흐려져 생기는 것이고, 마운트 기하 오차는 아니다.

## Why This Works

카메라 위치는 URDF가 정의하고 Gazebo가 그대로 배치한다. 그러니 정답의 출처는 조인트 체인
하나다. 시험이 같은 xacro를 읽어 위치를 유도하면, 손으로 옮겨 적은 상수와 모델이 갈라지는 순간을
잡는다. 주점은 렌더러의 광선 규약을 따를 때만 투영 모델이 일치한다.

## Prevention

- 카메라 외부 파라미터를 launch 파라미터로 옮겨 적을 때는 URDF/xacro 조인트 체인에서 계산한
  값을 쓰고, 그 계산을 시험으로 남긴다. 기울어진 조인트 아래의 모든 오프셋은 회전을 거친다.
- 같은 카메라를 쓰는 노드가 여럿이면(dock_observer, line_observer) 한 노드만 고치고 끝내지 않는다.
- 시뮬 렌더러의 픽셀 중심 규약과 camera_info 값을 한 번은 렌더된 표적으로 대조한다.

## Related Issues

- [시뮬에서 인식을 튜닝하기 전에 녹화 영상으로 실물 카메라부터 잰다](../workflow-issues/measure-the-real-camera-from-recorded-video-before-tuning-sim-perception-2026-09-24.md) — 25° 마운트 자체가 실물과 다르다. 기울기가 바뀌면 이 유도도 다시 한다.
- [A fixture written from the same model as the code is one belief, not two](../workflow-issues/a-fixture-from-the-same-model-is-one-belief-not-two.md)
