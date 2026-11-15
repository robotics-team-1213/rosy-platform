---
title: MuJoCo에서 같은 크기 상자를 정확히 한 줄로 쌓으면 가짜 깊은 접촉으로 튄다
date: 2026-11-09
category: logic-errors
module: tools/sim omx_two_arm_world
modules: [tools]
problem_type: logic_error
component: testing_framework
severity: medium
symptoms:
  - "측정 셀 배치의 시드 0 재생에서 반출·재배치가 첫 단계 전에 실패했다. ship-h1r2 줄 위 두 층(bar-6, bar-9)이 시작 상태를 안정시키는 동안 날아갔다(1193 mm, 기울기 90°)"
  - "같은 배치의 시드 1·2(±0.3 mm 흔들림)는 통과해서 배치·팔 문제처럼 보이지 않았다"
root_cause: logic_error
resolution_type: code_fix
tags: [mujoco, box-box, contact, stacking, seed, omx]
applies_when:
  - "MuJoCo에서 같은 크기 상자 geom을 흔들림 없이 정확히 겹쳐 쌓은 시작 상태를 만들 때"
  - "시드 0만 시작 상태가 무너지고 흔들림 있는 시드는 멀쩡할 때"
---

# MuJoCo에서 같은 크기 상자를 정확히 한 줄로 쌓으면 가짜 깊은 접촉으로 튄다

## 증상

측정 셀(`cell_snapshot=20261108-2257`, `ship_pose`·`belt_pose=snapshot`)에서 시드 0으로 반출·재배치를 재생하면 첫 단계 전에 bar-6, bar-9가 자리를 벗어났다. 두 세션이 각각 팔의 대기 자세나 고정물이 겹친 것으로 짐작했지만 둘 다 아니었다.

## 원인

배치 직후 `data.contact`에는 상자끼리의 접촉만 있었다(팔·고정물 없음). 325번째 물리 단계에서 bar-3/bar-6 상자-상자 접촉 하나가 `dist −34.9 mm`를 냈고, 다음 단계에 bar-6 속도가 2.75 m/s가 됐다. MuJoCo 3.3.7의 상자-상자 충돌이 같은 크기 상자를 정확히 한 줄로 쌓은 경우에 이런 가짜 깊은 접촉을 낸다. 시드 0은 흔들림이 없어 층이 완전히 정렬된다. 시드 1 이상은 층마다 다른 ±0.3 mm 흔들림이 있어 피해 간다.

`ccd_iterations`, `ccd_tolerance`, `mjENBL_MULTICCD`, 쌓음 전체를 같은 양 옮기기로는 사라지지 않았다. 상자-상자는 ccd 경로가 아니고, 전체를 옮기면 여전히 정렬돼 있기 때문이다.

## 해결

`World.put`이 흔들림 없이 놓을 때 층마다 x로 ±0.1 mm 엇갈리게 놓는다(`(-1) ** layer`). 흔들림이 있는 시드는 그대로다. 0.1 mm는 자리 홈 여유(한쪽 0.4 mm) 안이다.

## 검증

- 측정·기본 배치 × 적층·반출·재배치 × 시드 0~2의 시작 상태 18개가 모두 자리에서 2 mm 안에 남았다.
- 측정 셀 시드 0 두 팔 동시 재생: 적층 9/9, 반출 10/10, 재배치 12/12.
- 시뮬레이션 기하 근거다(D-947).

## 다음에

시작 상태가 시드 0에서만 무너지면 먼저 배치 직후와 폭발 직전 단계의 `data.contact`에서 `dist`가 수 mm를 넘는 상자-상자 쌍을 찾는다. 같은 크기 상자 geom을 정확히 겹치게 놓는 다른 코드(새 장면, 새 배)도 층을 조금 엇갈리게 둔다.
