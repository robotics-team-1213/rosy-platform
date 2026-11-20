---
title: The post-eval "opposing yaw" pair can plan one pose twice (top-down IK twin), and a one-jaw map's bias holds the jaw offset
date: 2026-11-17
category: logic-errors
module: deploy/robot/omx (cell_post_eval.py, cell_jaw_side.py, grasp_planner top-down IK)
problem_type: logic_error
component: development_workflow
symptoms:
  - "post-eval visit rejected yaw_pair_gap with sigma 25.09 and raw ~52 mm, twice at different points"
  - "visit-<site>-0.json and visit-<site>-1.json (yaw 0 and 180) have identical above_pick joints"
  - "pivot bias ~30 mm refused by pivot.max_bias_mm 25 although the pivot circle fits at rms 3 mm"
root_cause: wrong_assumption
resolution_type: code_fix
severity: high
tags: [omx, calibration, post-eval, pivot, yaw, jaw, arm-a]
applies_when: "a check asks the top-down planner for yaw and yaw+180, or reads a pivot/visit bias from a map built from single-jaw marks"
---

# 마주 보는 yaw 짝이 같은 자세가 된다

## 증상

arm_a post-eval이 01:46 (0.115, 0.034)과 17:15 (0.14, 0.039) 두 번 모두 `yaw_pair_gap`으로 거절됐다.
`sigma_mm` 25.09는 `half_mm` 0을 25로 바꾼 값에 pair_err ≈ 180도(두 FK yaw가 같음)를 넣은 결과다.

## 원인

`OmxKinematics.solve_top_down`은 yaw와 yaw+180을 모두 후보로 보고 홈 wrist_roll에 가장 가까운 쪽을 고른다
(집게가 180도 대칭이라는 가정). 그래서 요청 yaw 0과 180은 같은 관절을 낸다. 셀의 두 라이브러리 above_pick이
`[8.775, -19.293, 21.588, 47.791, 8.775]`로 같았고, 같은 플랜으로 오프라인 재현해도 같았다. arm_a wrist_roll 범위
(-31~62 단위, 약 167도)로는 180도 차이 자체가 닿지 않는다. raw (-8.8, 51.8) mm는 17:00 pivot yaw 5.6의 같은
집게 blob(-10.2, 52.1)과 1.5 mm 안이다. 쪽이 바뀐 짝이 아니라 같은 자세를 두 번 본 것이다.

## 해결

- `select_visit_yaws`는 각 yaw의 계획 라이브러리 above_pick FK yaw를 읽고, 두 계획 yaw가 180 ± `post.yaw_pair_tol_deg`
  일 때만 짝으로 쓴다. 아니면 1-yaw advisory 경로(기하가 없으면 skipped)로 간다.
- 진짜 짝은 `cell_jaw_side.label`(pivot `relabel`과 같은 공동 판정)로 두 표시의 집게 쪽을 정한다. 같은 집게면
  가운데가 중심이다. 쪽이 바뀌면 두 조합이 같은 rms로 맞고 중심이 `jaw_side.other_mm`만큼 갈리므로 거절한다.
- `yaw_pair_gap`, `finger_identity`, bias 가드는 바꾸지 않았다.

## 한 집게 지도의 bias

11-15 arm_a remap 표시는 위쪽(팔 y가 작은) 집게를 따랐다. 두 집게가 함께 보인 remap 시도 4점에서 간격은 지도로
58-61 mm, 방향 FK yaw+80~88도였다(K 618.5, 높이 496 mm로 57-60 mm). 그래서 지도는 TCP가 아니라 그 집게를 TCP로
놓는다. pivot 중심 - FK에는 그 집게의 회전축 거리(약 28 mm)가 들어간다. 17:00 pivot의 자유 적합(집게 매개변수
없음, 단일 표시 5개를 모두 같은 집게로 보면 rms 2.8 mm)에서 bias는 (-15.4, 26.8) mm였다. 그중 y 약 27 mm는 이
집게 오프셋이고, 남은 약 20 mm(주로 x)는 지도 표본 밖 41 mm 외삽이다(homography와 affine이 9 mm 다름).
`pivot.max_bias_mm` 25는 한 집게를 따르는 지도의 정상 bias보다 작다. 가드를 올리지 말고 remap을 두 집게 가운데로
하는 결정이 필요하다(2026-11-17 결정: 지도를 고친다). `calibrate.tcp_marks`의 remap은 표시마다 집게 쪽을 함께
정하고 TCP 지도를 만든다. 11-15 프레임 재생에서 17:00 pivot bias는 29.8에서 19.6 mm로 줄었고 y 성분(집게 오프셋)은
사라졌다. 남은 x 약 -18 mm(한 점씩 뺀 지도 -17~-27)는 원인 미확인이다(지도 밖 외삽 또는 팔 FK).

## 다음에 적용할 조건

- top-down 계획에서 yaw와 yaw+180을 다른 자세로 기대하는 코드는 계획된 관절의 FK yaw로 확인한다.
- wrist_roll 범위가 180도보다 좁은 팔은 마주 보는 짝을 만들 수 없다. 그 팔의 lateral 확인은 짝이 아닌 다른 방법이 필요하다.
- pivot bias가 크면 먼저 remap 표시가 어느 집게를 따랐는지 두 blob 프레임으로 본다.

## 검증

셀 읽기 전용 파일, 오프라인 플래너 재현(`D:/DevTemp/jaw-loc/posteval-1117/select_real.py`), 단위 시험
`test/test_omx_cell_post_eval.py`. 실물 post-eval 재실행은 하지 않았다.
