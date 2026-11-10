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

## 추가 교훈 (2026-11-10): 1·2·3단 적층 Sim → Real → Sim 왕복에서 드러난 세 가지 간극

1. **`temp_slot_plate v11` 흰색 칸 표식(`R1`, `R3`)과 정렬 점이 검은 패드 윤곽을 반으로 가름 (`tools/sim/omx_real2sim.py`)**
   - **증상**: 실물 셀 top 카메라에서 `omx_real2sim.py capture` 실행 시 빈 칸 `a-1`, `b-1`, `b-3`의 검은 패드가 흰색 글자·점 때문에 약 `33 mm` 조각 두 개로 쪼개져 `PARTIAL_MIN(40 mm)` 미만으로 버려졌다.
   - **해결**: `blobs(frame)`의 `pad` 마스크에 `9x9` `cv2.MORPH_CLOSE`를 적용해 흰색 표식 간극을 메웠다.
   - **검증 근거**: `test_white_printed_lane_labels_across_a_pad_do_not_split_it` 통과 및 실물 셀 캡처에서 `a-1`(`78.7x30.0 mm`), `b-1`(`87.3x30.7 mm`), `b-3`(`89.0x34.8 mm`) 패드 실측 복구 확인.
2. **실물 스냅샷 배치에서 180° 대칭 컨테이너의 최단 회전(`wrap_pi`)이 손목 롤 하한(`roll_floor`)을 침범 (`tools/sim/omx_two_arm_tasks.py`)**
   - **증상**: 기본 시뮬 배치에서는 `cell-stack` 9단계가 모두 `roll_below_floor: False`였으나, 실물 스냅샷(`20261108-2257.json`)에서는 `c1, c2, c4, c5, c8`의 `arm_a` joint5가 `-1.30 rad`(`< -0.565 rad`)까지 내려갔다.
   - **해결**: 컨테이너와 그리퍼 조는 `±180°`(`±pi`) 대칭이므로, `solve_chain`에서 기본 회전(`0 rad`) 경로가 실패하거나 `roll_floor` 아래로 내려가면 `wps[4:]`(`carry..retreat`)에 `-pi`, `+pi` 회전을 시도해 `roll_floor` 이상인 분기를 선택하도록 수정했다.
   - **검증 근거**: 실물 스냅샷(`20261108-2257.json`) 기준 `cell-stack` 9단계 모두 `roll_below_floor: False`(`min_roll_rad: -0.144 ~ +0.233 rad`) 확인(`test_stack_and_cell_stack_divide_into_three_validated_tier_stages`).
3. **실물 2·3단(`layer > 0`) 안착 시 중심점 지지 검사만으로는 1단 컨테이너와 직교(`90°`)하는 허공 돌출 배치를 막지 못함 (`deploy/robot/omx/cell_place_fit.py`)**
   - **증상**: 실물 셀 `pallet` 사이트의 기본 `yaw_deg`는 `0.0°`이고 1단(`pallet-l0`) 컨테이너는 `±89°`(`y`축 방향, 폭 `30 mm`)로 놓여 있는데, `why_not()`이 중심점(`centre`) 하나만 검사해 2단·3단 컨테이너가 1단 컨테이너를 가로질러 양쪽으로 돌출되는 후보를 허용했다.
   - **해결**: `layer > 0`에서 중심점뿐 아니라 컨테이너 `footprint` 점들의 `60%` 이상이 아래 단 `occupied` 마스크 위에 놓이는지 검사하도록 강화했다.
   - **검증 근거**: `test_with_tiers_expands_three_tiers_and_upper_tiers_require_support` 및 실물 셀(`rosy-arm-cell`) 라이브 카메라 대상 `pallet-l0 -> pallet-l1`, `pallet-l0 -> pallet-l2`, `pallet-l1 -> pallet-l2` dry-run 계획 검증 완료.
4. **다리 v7(`200 mm`)에 장착된 `temp_slot_plate v11`의 노란 컨테이너와 프레임 하단(`y = 479`) 클리핑 (`tools/sim/omx_real2sim.py`)**
   - **증상**: 2026-11-10 상단 카메라 재연결 후 다리 v7(`200 mm`)에 놓인 v11 판을 측정할 때, (a) `a-2`·`b-2`의 노란 컨테이너(`H ≈ 25..26`)가 주황 컨테이너 마스크(`H < 22`)에 잡히지 않고, (b) 반지름 `200 mm` 배치에서 칸들의 `-x` 끝단이 640×480 영상 하단 경계(`y = 479`)에 잘려 외곽 패드 길이가 `83~85 mm`, 중앙 컨테이너 길이가 `64 mm`(`partial`)로 줄어들며, (c) `--prev 20261108-2257.json` 전달 시 구형 판 모양(`13.57°, 217.3 mm`)을 고정 재사용해 신형 v11 판(`17.0°, 203.4 mm`) 맞춤이 틀어졌다.
   - **해결**: `blobs(frame)`에 노란 컨테이너 대역(`22 <= H < 29, S > 140, V > 140`)을 추가하고, `lane_blobs`에서 하단 경계(`y >= h - 2`)에 잘린 칸은 화면 안에 온전히 들어오는 `+x` 끝단(팔 쪽 끝)으로부터 중심·길이를 복원하며 사선 시야 컨테이너 옆면 번짐을 보정하고, `measure_temp_plates`가 현재 프레임에서 두 패드가 보이는 판으로부터 판 모양을 먼저 맞추도록 수정했다.
   - **검증 근거**: `test_yellow_containers_and_bottom_clipped_v11_plates_are_measured` 통과 및 2026-11-10 실물 스냅샷(`20261110-1231.json`)에서 `a-1..3`, `b-1..3` 6칸 모두 검출(잔차 `0.2~2.1 mm`, 패드 폭 오차 최대 `1.9 mm <= 3.0 mm`).
