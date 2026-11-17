---
title: MuJoCo에서 볼록 메시 위 상자는 접점 하나로 돌아간다
date: 2026-11-07
category: logic-errors
module: tools/sim omx_two_arm_world
modules: [tools]
problem_type: logic_error
component: testing_framework
severity: medium
symptoms:
  - "양팔 적층 연속 실행에서 앞 단계의 컨테이너가 팔이 멀리 있는데도 yaw 1.4°, 3.2°로 틀어져 다음 패드가 옆 컨테이너 모서리에 걸렸다"
  - "아무것도 움직이지 않는 장면에서 맨 위 상자가 30초에 16° 돌았다"
root_cause: config_error
resolution_type: code_fix
tags: [mujoco, multiccd, contact, convex-mesh, stacking, omx]
applies_when:
  - "MuJoCo에서 상자를 볼록 메시 갑판 위에 올려 두고 오래 시뮬레이션할 때"
---

# MuJoCo에서 볼록 메시 위 상자는 접점 하나로 돌아간다

## 증상

`tools/sim/omx_two_arm_teacher.py`의 연속 `stack`이 5/9에서 멈췄다. 단계별로 정상 상태에서 시작하면 9/9였다. 잡을 때, 옮길 때, 놓을 때의 yaw는 정상이었고 컨테이너가 다른 컨테이너 위에 놓인 뒤부터 늘어났다.

## 원인

볼록 메시와 상자의 충돌은 MuJoCo 기본 설정에서 접점을 하나만 낸다. 메시 갑판 위 상자가 흔들리고, 그 위 상자까지 조금씩 돈다.

## 해결

`mjENBL_MULTICCD`를 켰다(`tools/sim/omx_two_arm_world.py`). 마찰과 solref, 판정 기준은 바꾸지 않았다.

## 검증 근거

- 같은 정지 시험: 켜기 전 30초에 16°, 켠 뒤 0.0°.
- 연속 실행(시드 3개): `stack` 5/9 → 9/9, `rehandle`은 계획 변경과 함께 2/12 → 12/12. 판정 기준은 그대로다.

## 함께 시험했지만 원인이 아니었던 것

- 놓는 높이를 1 mm로 낮추기: 틀어짐을 가릴 뿐이었다. 기본값 5 mm로 되돌렸다.
- pyramidal cone, 반복 500회, 허용 오차 1e-12: 줄기만 하고 사라지지 않았다.
- 속도 기준으로 상자를 멈춰 두는 방식: 도움이 되지 않아 지웠다.

## 복구와 다음 적용 조건

연속 실행과 단계별 실행의 결과가 다르면 teacher보다 먼저 팔이 없는 정지 장면을 30초 돌려 본다. 이 수정은 이 장면에서만 확인했고, 접촉 수치는 시뮬 결과일 뿐 실물 근거가 아니다(D-947).

## 추가 교훈 (2026-11-10): 2단·3단 단계별 시작(`World.put`)에서 완전히 일치하는 상자-상자 XY 좌표의 퇴화 접점

- **증상**: 1단(`l0`)·2단(`l1`)·3단(`l2`)을 분리해 `stack-t3`를 시작할 때 `World.put()`으로 1단 위에 2단 컨테이너를 정확히 같은 `(x, y)` 좌표(`오프셋 0.000 mm`)에 배치하면, MuJoCo 3.3.7에서 팔이 닿지 않은 열(`h1r0`)의 2단 상자가 40초 동안 `6.8°`까지 돌아가 `s8`(`5.9° > 5.0°`)이 실패했다. 반면 1단부터 teacher가 직접 내려놓은 상자(`오프셋 0.1~0.5 mm`)는 `0.0°`로 멈춰 있었다.
- **원인**: MuJoCo 3.3.7에서 축이 완전히 일치하는 두 상자(`layer > 0`)가 정확히 같은 XY 중심에 놓이면 상자-상자 면 접촉 법선이 퇴화해 미세 회전 드리프트가 누적된다.
- **해결**: `tools/sim/omx_two_arm_world.py`의 `World.put()`에서 `layer > 0` 초기 배치 시 층별로 `±0.1 mm`(`0.0001 m`) 교차 x-오프셋을 부여해 퇴화 면 접촉을 깼다.
- **검증 근거**: AI PC(`MuJoCo 3.3.7`)에서 `stack-t1`, `stack-t2`, `stack-t3` 및 `cell-stack-t1`, `cell-stack-t2`, `cell-stack-t3` 모두 `3/3` 통과(최대 드리프트 `1.6° <= 5.0°`). 시뮬 결과이며 실물 근거가 아니다(D-947).
