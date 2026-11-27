---
title: "재매핑은 유효한 지도에선 무동작이고, surface_px는 지도 형상에 묶인다"
module: OMX Cell
date: 2026-11-27
problem_type: workflow_issue
component: tooling
severity: medium
tags: [omx, remap, surface-px, map-binding, camera]
applies_when:
  - "셀 카메라 지도를 다시 만들거나 surface_px를 바꿀 때"
  - "remap이 7초 만에 끝났는데 지도가 그대로일 때"
  - "surface_px만 고친 뒤 카메라 작업이 전부 보류될 때"
---

# 재매핑은 유효한 지도에선 무동작이고, surface_px는 지도 형상에 묶인다

- 지도가 아직 유효하면 remap은 약 7초 만에 끝나는 무동작이다. 실제로 다시 재려면 "remeasure"로 움직임을 강제한다.
- 움직이는 동안 장면이 바뀌면(로봇이 시야에 들어옴) 지도가 저장되지 않는다. 훑는 경로에 아무것도 없을 때 실행한다.
- `surface_px`는 묶인 지도 형상의 일부다. 단독으로 고치면 다시 매핑하기 전까지 모든 카메라 작업이 보류된다.
  `surface_px`는 remap과 함께, 훑는 경로가 비었을 때만 바꾼다.
