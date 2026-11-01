---
title: Marking the gripper by open/close frame difference has four pitfalls, and the visible part is off the TCP
date: 2026-10-28
category: logic-errors
module: deploy/robot/omx (top-camera map, cell_objects.py)
problem_type: logic_error
component: development_workflow
symptoms:
  - "mark pixels scatter across the frame or jump between measurements of the same pose"
  - "the same TCP at a different wrist yaw lands 44 mm apart on the map"
root_cause: wrong_assumption
resolution_type: code_fix
severity: medium
tags: [omx, top-camera, calibration, map, yaw, arm-s]
applies_when: "a map from the top camera marks the gripper by the part that changes between open and closed frames"
---

# The open/close difference mark: four pitfalls and a TCP offset

위 카메라(650 mm)에서 집게를 열고 닫은 두 프레임의 차이로 집게 위치를 표시한다.

## 함정과 수정 (모두 검증됨)

1. **센서 잡음.** 프레임 사이 약 200 px가 화면 전체에 흩어진다. 3×3 열림 연산 뒤 0이 된다.
   멈춤 판정은 열림 후 40 px 미만.
2. **조임 반작용.** 기계적 끝(48.5, 명령 46.6)까지 조이면 뻗은 손목이 비틀려 닫힘/열림 사이
   팔 자세가 달라진다. 50.5까지만 닫는다.
3. **흔들리는 케이블.** 여닫을 때 그리퍼 케이블 점이 생긴다. 손가락 크기 덩어리(≥300 px,
   ≤90×90 px)만, 이미 잡은 표시에서 60 px 이내만 채택한다. 그 뒤 같은 점 두 번 측정이 ±0.3 px.
4. **화면 가장자리.** 아래쪽은 집게가 화면 밖으로 나가 표시할 수 없다. 위쪽 컨테이너를 기준으로 한다.

## TCP에서 벗어난 표시 (진행 중)

보이는 "변하는 부분"은 손가락 끝이 아니라 TCP에서 약 29 mm 옆 연결부(도구 −y, 약 7° 벗어남)다.
그래서 표시는 yaw와 함께 돈다: 같은 TCP에서 yaw를 96.5° 바꾸면 지도상 44 mm 움직인다.
yaw −67.8°로 만든 지도는 약 (−28, −8) mm 밀린 것으로 **한 쌍에서 추정**했다.
**이 보정은 아직 피벗 측정으로 확정 중이다.** 확정 전에는 보정 적용을 사실로 쓰지 않는다
(컨테이너 중심 보정값도 미검증). 현재 지도 오차(LOO)는 이 밀림을 보정하지 않은 값이다.

## 예방

- 표시 방법을 바꾸면 yaw를 바꿔 같은 TCP를 재서 표시가 도는지 먼저 본다.
- 피벗 측정 결과가 나오면 이 문서의 진행 중 절을 결과로 바꾼다.
