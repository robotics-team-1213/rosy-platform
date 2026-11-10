---
title: MuJoCo 비전 벨트 피킹 시 주황색 안벽(ship_quay) 윤곽 병합과 미수거 벨트 상자 겹침 폭발
date: 2026-11-10
category: logic-errors
module: tools/sim omx_two_arm_teacher
modules: [tools]
problem_type: logic_error
component: testing_framework
severity: medium
symptoms:
  - "omx_ladder.py two-arm --task stack --pick-vision --belt-skew 실행 시 2026-11-10 실측 선택자를 따로 넘기지 않으면 s1부터 'top camera did not see bar-1 at belt'로 막히고, 이어지는 단계에서 'bar-5 is 485 mm from belt'로 상자가 튕겨 나갔다"
root_cause: logic_error
resolution_type: code_fix
tags: [mujoco, vision, belt, contour, omx, ladder]
applies_when:
  - "MuJoCo 상단 카메라(top) 렌더링에서 컨테이너 색상(주황)과 인접 고정물(ship_quay 등) 색상이 같은 HSV 대역을 공유할 때"
  - "벨트(belt)에서 연속 공급되는 단계가 blocked/unreachable로 조기 반환될 때"
---

# MuJoCo 비전 벨트 피킹 시 주황색 안벽(ship_quay) 윤곽 병합과 미수거 벨트 상자 겹침 폭발

## 증상

`omx_ladder.py two-arm --task stack --pick-vision --belt-skew --choice container_colours=multi`를 실행했을 때, `2026-11-10` 실측 셀 선택자(`belt_pose=photo-20261110`, `ship_pose=photo-20261110` 등)를 함께 지정하지 않으면 `s1..s4`가 `"top camera did not see bar-N at belt"`로 실패하고 `s5`, `s7`, `s8`은 `"bar-5 is 485 mm from belt"`처럼 벨트 밖으로 튕겨 나갔다.

## 원인

1. **상단 카메라와 미실측 벨트·선박 기본값 불일치 및 `ship_quay` 주황색 윤곽 병합**:
   `CHOICES`의 기본 `top_camera`는 `"2026-11-10"` 실측 포즈지만 `belt_pose="fixture"`(`belt_stop_x=0.158`)와 `ship_pose="assumed"`(`ship_stern_x_m=0.155`)를 그대로 두면 `r08-berth`의 주황색 안벽 메쉬(`ship_quay`, `rgba=[.88, .48, .16, 1]`)가 벨트 픽업 위치(`x=0.2075`) 바로 옆까지 뻗는다. 상단 카메라 이미지에서 주황색 컨테이너와 `ship_quay`가 한 덩어리로 합쳐져 윤곽 길이가 `125 mm` 상한을 넘으면서 `perceive_pick` 후보에서 탈락했다.
2. **벨트 조기 실패 시 미수거 상자 잔류**:
   `step_gen`이 `"blocked"` 또는 `"unreachable"`로 반환될 때 `belt_in_g`가 벨트 위에 올려둔 상자를 치우지 않아, 다음 벨트 단계가 같은 좌표에 새 상자를 겹쳐 소환하면서 깊은 접촉 폭발(`485 mm` 이탈)이 일어났다.

## 해결

1. `--pick-vision` 또는 `--belt-skew`가 켜진 실행(`omx_two_arm_teacher.py`, `omx_two_arm_policy.py`)은 사용자가 `--choice`로 덮어쓰지 않은 항목에 대해 `VISION_SKEW_CHOICES`(`temp_lanes=photo-20261110`, `ship_pose=photo-20261110`, `belt_pose=photo-20261110`, `arm_bases=plate-centre`, `wrist_camera=photo-20261110`, `physics=twin-kp-20261109`)를 기본 적용한다.
2. `Teacher.perceive_pick`이 벨트(`sa["kind"] == "belt"`)를 촬영할 때 `ship_quay` geom의 알파를 일시적으로 `0`으로 두어 `belt_pose=fixture`를 명시적으로 시험할 때도 안벽 메쉬가 컨테이너 윤곽과 합쳐지지 않게 한다.
3. `Teacher.run_task`에서 벨트 공급 단계가 `"blocked"` / `"unreachable"`로 끝나면 벨트 위 미수거 상자를 셀 밖 대기 위치로 치워 다음 단계 소환과 겹치지 않게 한다.
4. `omx_ladder.judge_isaac_stage`가 실제 Stage 2 Isaac Sim(`arm-s-cell-report.json`)의 성공 판정값 `"placed"`를 `"success"`·`"completed"`와 함께 통과로 인정하고, MuJoCo handoff 후보(`expect: null`) 행이 `"placed"` 이외(`"dropped"`, `null` 등)로 끝난 경우도 `failed_cases`로 판정하도록 보강했다.

## 검증

- 원격 시뮬레이션(AI PC, Stage 1 MuJoCo): `omx_ladder.py two-arm --task stack --seed 0 --pick-vision --belt-skew --choice container_colours=multi` → `steps_pass: 9/9`, `status: "passed"`, `isaac-handoff.json`·`isaac-suite.json` 9건 생성 확인.
- 원격 시뮬레이션(Model PC, Stage 2 Isaac Sim): Stage 1이 생성한 `isaac-suite.json`의 `mujoco-stack-s1-bar-1`(`box: [0.0065, 0.0064, 18.0]`, `grasp_turn: 18.0`)을 `deploy/robot/omx/cell_case_suite.py`로 실행 → `run_id: 7b1818e331c7566f990bd87765797a78`, `status: SUCCEEDED`, `result: placed`(`lifted_samples: 143`, `frame_contact: false`) 확인.
- 원격 pytest: `test/test_omx_two_arm_policy.py`, `test/test_omx_ladder.py`, `test/learning/perception/test_ladder_web.py`, `test/test_omx_cell_cases.py` 통과.
