---
title: 시뮬이 통과해도 배치가 틀릴 수 있다. 실제 카메라 시점으로 겹쳐 본다
date: 2026-11-07
category: logic-errors
module: tools/sim omx_two_arm_sites
modules: [tools]
problem_type: logic_error
component: testing_framework
severity: medium
symptoms:
  - "양팔 stack 9/9, rehandle 12/12가 통과했는데 임시 칸이 실제보다 약 57 mm 멀리 있었다"
  - "실제 top 사진에서는 임시 칸이 다 보이는데 시뮬 top 시점에서는 아래가 잘렸다"
root_cause: config_error
resolution_type: code_fix
tags: [mujoco, camera, pnp, overlay, omx, two-arm]
applies_when:
  - "사진이나 CAD에서 추정한 배치로 만든 시뮬 장면을 근거로 쓸 때"
---

# 시뮬이 통과해도 배치가 틀릴 수 있다. 실제 카메라 시점으로 겹쳐 본다

## 증상

양팔 장면의 임시 칸은 사진에서 추정한 반지름 214 mm 부채꼴이었다. 판정이 위치를 장면 안의 칸과 비교하므로 칸이 어디 있어도 태스크는 통과했다. 기록 영상도 셀에 없는 overview 시점이어서 어긋남이 보이지 않았다.

## 원인

장면이 스스로의 배치를 기준으로 판정했다. 실제와 대조하는 단계가 없었다.

## 해결

기록을 셀의 네 카메라(top·side·양 손목, D-960)로 바꿨다. top과 side는 돌기 PnP로 실측한 값이다. 실제 top 사진에서 칸의 검은 자리를 찾아 작업면으로 역투영해 `TEMP_LANES_PHOTO`에 넣었다. 왼쪽과 오른쪽 칸은 같은 거리가 아니고 팔 중심을 정확히 향하지도 않았으므로, 반지름 하나로 나타낼 수 없다.

## 검증 근거

- 역투영한 검은 자리 크기 89.2 x 29.6 mm, 컨테이너 90 x 30 mm: 카메라 자세와 높이가 맞다는 뜻이다.
- 팔 중심에서 arm_b 가운데 칸까지 156.6 mm, 214 mm가 아니었다.
- 고친 뒤 실제 사진과 겹침에서 칸, 배 판, 팔 받침이 맞았다.
- 컨테이너에 덮인 tmp-a-3은 1, 2번으로 추정했다. 끝에 보이는 검은 조각의 방향과 0.1도 안에서 맞았다.
- stack 9/9, rehandle 12/12(시드 3개). 시뮬 결과이며 실물 근거가 아니다(D-947).

## 복구와 다음 적용 조건

칸은 고정되지 않았으므로 옮기면 다시 잰다. 손목 카메라는 CAD 값이고, arm_a 쪽 장착은 같다고 가정했다. 이 값들은 실측이 아니다. 다른 장면에서 배치를 추정했다면, 시험 통과를 근거로 삼기 전에 실제 카메라 시점으로 사진과 겹쳐 본다.
