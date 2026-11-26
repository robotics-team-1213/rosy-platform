---
title: "OMX 이송 시험에서 시각이 최신인 가림 프레임 재현하기"
module: OMX Cell
date: 2026-11-26
problem_type: test_failure
component: testing_framework
severity: high
tags: [omx, side-camera, observation, dispatch]
symptoms:
  - "완전히 검은 JPEG로 측면 영상을 바꿔도 모의 명령이 전달됐다."
root_cause: missing_validation
resolution_type: code_fix
---

# 최신 측면 영상에서도 가림을 따로 시험한다

임시대에서 선박으로 가는 경로의 기존 시험은 정상 프레임에도 단색 배열을 썼다.
같은 상단 영상과 깊이 판정을 유지하고 측면만 바꾸자, 기록한 현장 JPEG와 새로 인코딩한 검은 JPEG 모두 모의 실행기에 명령 한 건을 전달했다.
노출 시각과 촬영 장치가 맞는다는 정보만으로는 덮인 렌즈를 검출할 수 없었다.

재현할 때는 실제 장치에 연결하지 않은 실행기로 명령 수를 센다.
정상 측면 영상과 가린 영상에 각각 유효한 새 시각을 주고 상단·깊이·보정 입력을 고정한다.
이때 정상 입력을 단색 픽스처로 대체하면 정상과 실패를 구별할 수 없다.

수정한 `cell_route_depth._receipt`는 채널별 공간 명암 범위를 검사한다.
고립된 밝은 픽셀 하나를 둔 단색 프레임은 동작 전과 놓기 후 모두 거부하고, 기록한 현장 프레임은 모의 실행기에 전달한다.
실제 장면에서 이 조건으로 멈추면 렌즈와 시야를 확인한 뒤 원래 좌표와 보정을 유지한 채 영상을 새로 받는다.
배경이 보이는 부분 가림을 판정하려면 해당 칸의 별도 관측 근거가 필요하다.
