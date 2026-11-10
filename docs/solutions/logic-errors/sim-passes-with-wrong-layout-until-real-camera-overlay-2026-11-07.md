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
5. **`solve_line` 종점 부동소수점 언더플로가 `approach_m=0.04`를 거절하고 `0.02 m`로 낮춤 (`middleware/devices/omx/adapter/omx_adapter/kinematics.py`)**
   - **증상**: 실물 구동(`20261110T042820Z-001`)에서 `pallet-l0`(`z = 0.005 m = workspace_min_m[2]`) 상차 시 `z0 = 0.045 -> z1 = 0.005` 직선 보간 `z0 + (z1 - z0) * 1.0`이 IEEE-754 float64에서 `0.0049999999999999975 < 0.005`가 되어 `OUTSIDE_WORKSPACE`로 거절되었고, `plan_pick`이 `approach_near_m = 0.020 m`(`above_pick` `z = 0.025 m`)로 후퇴했다.
   - **해결**: `solve_line`에서 `(1.0 - s) * z0 + s * z1`(x, y 동일) 보간을 사용해 `s = 1.0` 종점이 `z1`과 정확히 일치하도록 수정했다.
   - **검증 근거**: `test_descent_to_exact_workspace_floor_with_40mm_approach_does_not_underflow` 통과 및 실물 셀 dry-run에서 `approach_m = 0.04` 유지 확인.
6. **설정 파일의 `tcp_x_m`이 플래너·표면 FK에 전달되지 않아 신형 집게(`0.0885 m`)가 `14.5 mm` 낮게 진입 (`deploy/robot/omx/grasp_planner.py`, `cell_pipeline_io.py`, `cell_surface.py`, `cell_pivot.py`)**
   - **증상**: `arm_b` 신형 집게(`0.0885 m`, 구형 `0.0740 m` 대비 `+14.5 mm`)에서 환경변수 `ROSY_OMX_TCP_X_M`이 누락되거나 `0.0740`으로 들어가면 `above_pick` 목표 높이가 실제 집게 끝 기준 `z = +0.0158 m`(컨테이너 상면 `+0.021 m` 아래 `5.2 mm`)가 되어 `goto above_pick` 도중 상면에 접촉(`z = +0.0213 m`, `overload-hold on wrist_flex`)했다.
   - **해결**: `write_library`, `Planner`, `fk_z`, `joints_tcp`가 설정의 `tcp_x_m`을 직접 받아 `load_kinematics`에 전달하도록 수정했다.
   - **검증 근거**: `test_a_jaw_tcp_from_the_environment_moves_the_tip_and_a_wild_one_is_refused` 통과 및 실물 셀 `cell_auto_pick --dry-run` 검증.
7. **`overload-hold` 하중 해제 중 즉시 전송된 `retreat`/`park` 거절 및 세션 종료 시 `restore_caps` 일시적 버스 타임아웃 (`deploy/robot/omx/cell_transfer.py`, `cell_pipeline_io.py`, `record_session.py`)**
   - **증상**: (a) `overload-hold` 발생 직후 러너가 하중을 푸는 동안(`shedding its load first`) `_transfer`가 0.2초 만에 보낸 `retreat`·`park`가 거절되었고, (b) 세션 종료 시 `restore_caps()`에서 쓰기는 성공했으나 읽기 응답이 일시적 `comm -3001` 타임아웃을 내어 정상 접힘·토크 OFF 상태에서도 `safe_end: false`로 기록되었다.
   - **해결**: `overload-hold` 시 `retreat`를 건너뛰고 하중 해제가 끝날 때까지 `park`를 재시도하며, `restore_caps()`가 레지스터별 최대 3회 재시도하도록 수정했다.
   - **검증 근거**: `test_overload_hold_contact_waits_for_load_shedding_before_parking`, `test_restore_caps_retries_transient_bus_timeout` 통과 및 `register_probe.py`로 실물 팔 `11..16` 전 축 `torque=0, hw_error=0, pwm_limit=20, current_limit=50` 복원 확인.
8. **중단된 이전 세션의 자기 소유 구역 점유(`zone-*.lock`) 해제 및 MuJoCo `--video` `ffmpeg` 폴백 (`deploy/robot/omx/cell_transfer.py`, `cell_reach.py`, `cell_look.py`, `tools/sim/omx_two_arm_teacher.py`)**
   - **증상**: (a) 이전 세션에서 `goto above_pick`이 구역(`zone-middle.lock`, `zone-side-left.lock`)을 점유한 뒤 중단·수동 복귀되면 다음 세션의 첫 `goto above_pick`이 `park` 전에 실행되어 `"its guarded owner must park before recovery"`로 거절되었고, (b) 호버 훅 `cell_reach`·`cell_look`이 환경변수 없이 호출될 때 `config["tcp_x_m"]`이 빠졌으며, (c) AI PC `sim-mujoco` venv에 `PyAV`(`av`)가 없을 때 `omx_two_arm_teacher.py --video`가 실패했다.
   - **해결**: `_transfer`에서 첫 `goto above_pick`이 `"must park before recovery"`로 거절되면 먼저 `run("park")`로 홈 안착을 확인해 자기 소유 구역 점유만 정리한 뒤 재시도하도록 수정하고, `cell_reach`·`cell_look`에 `config.get("tcp_x_m")` 전달 및 `omx_two_arm_teacher.py --video`에 `ffmpeg` 파이프 폴백을 추가했다.
   - **검증 근거**: `test_transfer_folded_clears_own_stale_zone_via_confirmed_park_before_first_reach` 포함 원격 pytest 통과 및 AI PC에서 `cell-stack-t1/t2/t3` 4뷰 `.mp4` 영상 생성 확인.
9. **`FOLDED` 수송 중 파지된 컨테이너 그리퍼 위치 오탐, 인양·접힘 도중 미끄러짐 조기 감지, 열별(`Col 1..3`) 호모그래피 편차 분리 (`deploy/robot/omx/cell_pipeline_io.py`, `cell_transfer.py`, `cell_look.py`, `omx_incident.py`)**
   - **증상**: (a) 실물 Trial 1에서 인접 컨테이너와 간격이 좁은 격자(`jaw_margin_mm < auto.jaw_margin_mm`)일 때 `cell_reach`가 수렴했음에도 `cell_look.hover`가 `"no room to open the jaws"`로 정지했고, (b) Trial 3에서 30 mm 컨테이너를 파지(`state[5] ≈ 53.8`, `239 mA`)한 채 `FOLDED` 중간 `park`(`target[5] = 48.8`)로 접힐 때 그리퍼 축(`index 5`)의 `5.0 units` 편차를 외부 접촉(`"the jaws stopped 5.0 units short"`)으로 오탐했으며, (c) Trial 4에서 `lift_pick`/`park` 도중 컨테이너가 미끄러져 빠졌음에도 빈 손으로 `above_place -> descend_place -> release_place`까지 진행한 뒤 사후 `verify_placed`에서야 실패를 감지했고, (d) 상단 카메라 단일 평면 호모그래피와 실제 팔 FK 사이의 잔차(`x`축 좌→우 열 방향)가 1열(`0.0 mm`), 2열(`-3.8 mm`), 3열(`+1.5 mm`)마다 다르게 나타났다.
   - **해결**: (a) `cell_reach`가 이미 수렴한 상태에서 `cell_look`이 `jaw_margin_mm` 부족으로 거절되면 보정된 FK reach 자세를 유지하고 계속 진행하도록 수정하고, (b) `cell_pipeline_io.py`의 `park` 접촉 검사에서 파지 상태(`carrying`)일 때 그리퍼 축 편차를 정상 파지로 인정하며 `park` 시 첫 접촉·하중 해제는 1회 재시도하도록 보강하고, (c) `cell_transfer.py`에서 `lift_pick` 및 중간 `park` 직후 `holding == False`(`grip_pos < empty_below`)이면 즉시 `slipped during lift_pick/park`로 중단·재시도하도록 추가했으며, (d) 일정한 기구 오프셋(`tcp_x_m = 0.0885 m`)과 자세/영역별 편차(`rosy.omx-cell-bias.v1` `regions`)를 분리하고 자체 인시던트 홀드 조회·해제 CLI/API(`omx_incident.py status` / `clear`) 및 웹 패널(`cell_params_web.py`)을 구축했다.
   - **검증 근거**: `test_omx_cell_transfer.py`, `test_omx_cell_pipeline.py`, `test_omx_cell_look.py`, `test_omx_incident.py` (원격 pytest 166 passed) 및 실물 Trial 8(`20261110T094943Z-001`)·Trial 9(`20261110T100712Z-001`)에서 2단(`pallet-l0 -> pallet-l1`) 연속 첫 시도 완주(`result: "placed"`) 및 물리적 2단 적층 직립 확인.
10. **실물 3단(`pallet-l1 -> pallet-l2`) 적층 시 손목 카메라(`arm_b_wrist`) 기반 컨테이너 정중앙 정렬, 컨테이너 폭 맞춤 집게 개방(`grip_open`/`grip_release`), 이동·작업 구간 속도 이원화 (`deploy/robot/omx/cell_fingers.py`, `cell_reach.py`, `cell_auto_pick.py`, `grasp_planner.py`, `middleware/devices/omx/adapter/omx_adapter/chunk_library.py`)**
   - **증상**: (a) 실물 Trial 10에서 선박 홀 우측의 노란 테이블(`H ≈ 21.7`)이 `colour_mask`에 합쳐지며 3열 우측 여유(`jaw_margin_mm`)를 `0.8 mm`로 깎았고, Trial 11(`20261110-200031`)에서 `pallet-l1 -> pallet-l2` 3단 적층을 완주해 실제 3단 타워(`side-2990.jpg`, `side-3150.jpg`, `top-3150.jpg`)를 세웠으나 상단 카메라 시차로 `pick.x`가 컨테이너 중심 대비 좌측으로 `~6.6 mm` 치우쳤으며(`wrist-0400.jpg`), `surface_px` 우측 경계(`395 px`) 때문에 `cell_place_fit.options`가 3열 `place.x`를 `-10 mm` 좌측(`0.193 m -> 0.183 m`)으로 밀어냈다. (b) 집게를 `57.3..58.9`(`46–52 mm`)까지 넓게 벌리면 `30 mm` 컨테이너 격자(`열 간격 3–4 mm`)에서 인접 열과 간섭하고 적층 상단에서 놓을 때 유격이 커졌다. (c) `transit_speed = 0.4`와 호버 미세 보정 시마다 `TRANSIT` 경유(`35초`)가 발생해 전체 사이클이 느렸다.
   - **해결**: (a) `cell_auto_pick.py`에서 `markings_px`가 `colour_mask` 병합 이후에도 적용되도록 수정하고, `cell_fingers.py`에 신형 흰색 집게(`finger_pads`) 및 인접 컨테이너 접촉 시 상면 좌우 경계 검출(`top_face_between_fingers`)을 추가해 손목 카메라(`arm_b_wrist`)로 컨테이너 정중앙 오차(`wrist-0400.jpg` 기준 `along_mm = -6.6 mm`)를 직접 보정하며 `cell_reach.py`의 중력 처짐 보정치(`target["pick"]`)가 후속 훅에서도 보존되도록 수정했다. (b) `grasp_planner.py`에 `grip_release` 및 구간별 속도(`descend_pick_*`, `descend_place_*`, `lift_*`)를 도입해 파지 개방은 `56.58`(`~34.4 mm`, 양측 `+2.2 mm`), 적층 릴리스 개방은 `56.10`(`~32.0 mm`, 양측 `+1.0 mm`)으로 컨테이너 폭에 꼭 맞게 제한했다. (c) `chunk_library.py`의 `transit_path`에서 관절 변화량 `<= 8.0 units`인 호버 미세 이동은 `TRANSIT` 상승 없이 즉시 직선 보간(`0.8초`)하도록 개선하고, 자유 공간 이동(`transit_speed = 0.82`)·Pick 하강(`0.020 m/s`, `guard_frac = 0.68`)·인양(`0.030 m/s`, `guard_frac = 0.72`)은 빠르게, 적층 안착 하강(`descend_place_m_s = 0.010 m/s`, `descend_place_guard_frac = 0.38`)은 느리고 정밀하게 이원화했다.
   - **검증 근거**: `test_omx_cell_fingers.py`, `test_omx_cell_look.py` 통과 및 실물 `wrist-0400.jpg` 프레임 검증(`along_mm = -6.6 mm, across_mm = -0.2 mm, mode = top_face`), 실물 Trial 11(`20261110-200031`) 3단 적층 영상(`real-20261110-200031-{top,side,wrist}.mp4`).
11. **기존 `judge_seat` (`schema_version = 2`)·`cell_decisions`·`cell_diagnose` 구조 위 모델 불문(Model-Agnostic) 멀티-모델 정합성 심의(`GLM-5.3` ↔ `GLM-5.3-flash` 등) 및 불안정 파지 시 제자리 재투입(`reinsert_pick` / `release_pick`) 후 재파지 (`deploy/robot/omx/judge_seat.py`, `cell_grasp_debate.py`, `cell_decisions.py`, `cell_diagnose.py`, `grasp_planner.py`, `cell_transfer.py`, `cell_hooks.py`, `cell_auto_pick.py`)**
   - **증상**: (a) 파지 후 컨테이너가 모서리에 얕게 물리거나(`state[5] < held_30mm - 1.2`, 예: Trial 4의 `52.4`) 대각선으로 끼인 상태(`state[5] > held_30mm + 0.7`), 또는 손목 카메라에서 중심이 크게 벗어난 상태(`|along_mm| > 4.0 mm`)에서 그대로 `park -> above_place`로 이동하면 도중에 미끄러지거나 2단·3단 상부에서 비스듬히 놓여 타워를 무너뜨릴 위험이 있고, 반대로 인양(`lift_pick`) 상태에서 집게를 바로 열면 40 mm 높이에서 컨테이너가 낙하한다. (b) 기존 `judge_seat.py`와 `cell_auto_pick.py`는 단일 로컬 `ollama` 호출에 고정되어 있었고, `reinsert` 결정이나 이종/다중 모델(`glm-5.3`, `glm-5.3-flash`, `ollama`, `openai`, `opencode`/`claude` CLI) 간 `proposal -> critique -> arbiter` 정합성 심의(`schema_version = 2`)가 통합되어 있지 않았다.
   - **해결**: (a) 기존 ROSY 의사결정 좌석 `judge_seat.py`를 `SCHEMA_VERSION = 2`로 격상해 `DECISIONS`에 `"reinsert"`, `PRECONDITION`에 `"transport": "stable"`을 추가하고, 단일/다중 모델 설정을 모두 수용하는 `from_config(spec)`·`cooperate(backends, arbiter=...)`·`openai_chat(model="glm-5.3")`·`cli_model(model="zai-coding-plan/glm-5.3-flash")`·`ollama()`를 구현했으며, `cell_decisions.py`(`grasp_stability`, `target_judge` 원장 기록) 및 `cell_diagnose.py`(`unstable_grasp` 원인·전략)와 직결했다. (b) `grasp_planner.py`에 제자리 해제 청크 `release_pick`(바닥에서 `grip_release = 56.10`으로 좁게 열고 수직 상승)과 제자리 재투입 청크 `reinsert_pick`(`lifted`에서 저속 `descend_place_guard_frac`으로 원래 `pick.z` 바닥까지 수직 하강해 컨테이너를 내려놓은 뒤 `grip_release = 56.10`으로 살짝 열고 수직 상승)을 추가했다. (c) `cell_grasp_debate.py`가 `judge_seat.measured`·`judge_seat.from_config`·`cell_decisions.emit("grasp_stability", ...)` 위에서 동작하도록 통합해, 불안정 파지 감지 시 `reinsert_pick`으로 컨테이너를 원래 슬롯에 안전하게 다시 넣은 뒤 심의된 `(dx_mm, dy_mm)`만큼 `target["pick"]`을 보정해 재파지(`reinsert_and_retry`)하거나 안전하게 `park`(`reinsert_and_park`)하도록 `cell_transfer.py`·`cell_auto_pick.py`에 연결했다.
   - **검증 근거**: `test_omx_judge_seat.py`, `test_omx_cell_grasp_debate.py`, `test_omx_cell_pick_judge.py`, `test_omx_cell_diagnose.py`, `test_omx_grasp_planner.py`, `test_omx_cell_fingers.py` (47 passed) 및 실물 `wrist-0400.jpg` + Trial 4/8 텔레메트리 대상 최신 `zai:glm-5.3` (`proposal`) ↔ `zai:glm-5.3-flash` (`critique`/`arbiter`) `schema_version = 2` 실호출 검증(`seat_deliberation_v2.decision = "reinsert"`, `consensus = true`, `case_1.verdict = "reinsert_and_retry"`, `recovery_chunk = "run reinsert_pick"`, `dx_mm = +5.61 mm`).
12. **팔별(`arm_s` 검정 집게 vs `arm_a`·`arm_b` 흰색 v2.1 집게) 집게 색상 극성 분리 및 `cell_params` 스키마 통합 (`deploy/robot/omx/cell_fingers.py`, `cell_pinch.py`, `cell_params.py`, `cell_grasp_debate.py`, `cell_auto_pick.py`)**
   - **증상**: (a) `arm_s`는 검정(`dark`) 집게를, `arm_a`·`arm_b`는 흰색(`white` v2.1) 집게를 사용하는데, 기존 `finger_pads`는 항상 어두운 영역(`g < 60`)을 먼저 찾고 실패할 때만 흰색 집게(`x < 0.35w`, `x > 0.75w`)를 탐색하여 흰색 집게 팔(`arm_a`·`arm_b`)에서 배경 그림자를 검정 집게로 오인하거나 좁게 열린 흰색 집게(`arm_a_wrist.jpg`, `arm_b_wrist.jpg`)를 놓칠 수 있었다. (b) `cell-params.json` 검증기(`cell_params.DEFAULTS`)에 `wrist.finger_color` 및 `grasp.*` 임계값이 등록되어 있지 않아 팔별 파라미터 파일 로드 시 `unknown parameter` 예외가 발생할 수 있었다.
   - **해결**: (a) `cell_params.DEFAULTS`에 `wrist.finger_color`(`0`=auto, `1`=dark/black, `2`=white)와 `grasp.*`(`grasp.stability_check`, `grasp.shallow_tol_units`, `grasp.wedged_tol_units`, `grasp.max_skew_mm`, `grasp.max_reinsert`, `grasp.min_stable_current_ma`, `grasp.vision_after_grasp`, `grasp.reach_on_reinsert`)를 정식 등록했다. (b) `cell_fingers.resolve_finger_color(params, wrist_spec, color)` 및 `_dark_pads`/`_white_pads`(하단 경계 `y >= 0.90h` 정박 조건 + 좁은 개방/넓은 개방 흰색 집게 검출)를 구현하고 `cell_fingers.py`, `cell_pinch.py`, `cell_grasp_debate.py` 전체에 연결해 `arm_s`(검정 집게)와 `arm_a`·`arm_b`(흰색 집게) 모두에서 흔들림 없이 동작하도록 했다.
   - **검증 근거**: `test_per_arm_finger_color_distinguishes_arm_s_black_pads_and_arm_a_arm_b_white_pads`, `test_white_fingers_and_dark_fingers_both_measure_inner_pad_gaps`, `test_wrist_finger_color_and_grasp_stability_params_validate` 포함 원격 전체 OMX 테스트 `196 passed`.
