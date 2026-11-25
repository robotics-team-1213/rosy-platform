---
title: OMX folded-home elbow-first unfold clearance and D435 container-height remap z_view elevation
date: 2026-11-25
category: runtime-errors
module: middleware/devices/omx/adapter/omx_adapter/chunk_library.py, deploy/robot/omx/cell_remap_plan.py, deploy/robot/omx/cell_calibrate.py
problem_type: runtime_error
component: hardware_control
symptoms:
  - "arm_a remap stopped on contact in goto above_pick at shoulder_lift=-58.05 (lag 2.3 units, PWM 312->406) on 2026-11-25 03:57 and 17:37 right after lifting off folded home (-62.2, elbow_flex=53.1)"
  - "Fixed coarse.z_view during cell_calibrate remap risked sweeping low over stacked ship containers (~66 mm over table) or colliding when containers remained in the ship"
root_cause: simultaneous_home_unfold_inward_dip_and_static_remap_z_view
resolution_type: code_fix
severity: high
tags: [omx, arm-a, arm-b, transit-path, home-unfold, remap, d435-depth, z-view, contact]
applies_when: "diagnosing OMX goto contact near folded home (shoulder_lift <= -50) or running cell_calibrate remap with containers on the ship/table"
---

# OMX 접힌 홈(`home`) 외측 펼침(`elbow_flex` 우선) 및 D435 컨테이너 높이 연동 `remap` `z_view` 상승

## Symptoms (2026-11-25 `rosy-arm-cell` 실기 관측)

1. **`goto above_pick` 홈 이탈 접촉 정지:** `trace-arm_a-20261125-035715.jsonl`, `trace-arm_a-20261125-173737.jsonl`에서 접힌 `home = [0.8, -62.2, 53.1, 51.6, 45.2, 49.0]` 출발 직후 `shoulder_lift = -58.05` 부근에서 `shoulder_lift PWM`이 `312 -> 406`까지 치솟고 `lag`가 2.3유닛을 넘어 `contact in goto above_pick`로 정지했다(`2026-11-24 13:42` 성공 로그에서도 같은 구간에서 `elbow_flex PWM=-394` 피크 기록).
2. **적재 상태 `remap` 고정 높이 위험:** 선박 위에 1·2단 컨테이너(D435 실측 `arm_b pallet p99=62.3 mm, max=66.3 mm`, `arm_a pallet p99=55.3 mm, max=59.6 mm`)가 놓인 상태에서 `cell_calibrate.py remap`이 `config["coarse"]["z_view"]`만 고정 참조했다.

## Root Cause

1. **동시 보간 펼침의 내접/하강(`transit_path`):** `park_path()`는 접을 때 `el_clear = 43.0` 경유점을 두지만, `transit_path()`는 `shoulder_lift(-62.2 -> -27.0)`와 `elbow_flex(53.1 -> 18.0)`를 동시에 선형 이동시켰다. 중력 부하로 `elbow_flex`가 1.5~2유닛 뒤처진 채 `shoulder_lift`가 먼저 세워지면 FK 상 그리퍼 끝이 `x: 50.3 -> 39.8 mm`, `z: 21.7 -> 14.3 mm`로 **베이스 마운팅 브래킷 쪽으로 파고들며** 걸린다. 반면 `elbow_flex`를 먼저 `43.0`까지 열면 `x: 50.3 -> 63.7 mm`, `z: 21.7 -> 82.1 mm`로 외측·상방으로 즉시 빠진다.
2. **D435 깊이 미반영:** `cell_calibrate.py main()`이 `depth-verify` 단계에서만 D435 깊이를 캡처하고 `remap` 사전 계획(`rp.plan`)에는 현장 장애물 높이를 반영하지 않았다.

## Fix & Verification

1. **홈 외측 펼침 우선(`chunk_library.py` `transit_path`):**
   - `FOLDED_UNFOLD_ELBOW = 43.0` 추가. `start[1] <= -50.0`이고 `start[2] > 43.5`이며 `transit[2] < 43.0`일 때, `blend=False` 세그먼트로 `[shoulder_pan, shoulder_lift, 43.0, ...]`를 먼저 경유해 팔꿈치를 바깥/위로 펼친 뒤 `transit`으로 이동한다.
2. **D435 기반 동적 `z_view` 상승(`cell_remap_plan.py`, `cell_calibrate.py`):**
   - `site_obstacle_mm()`가 D435 `table_plane`, `height_map`, `align_edges`로 `map_sites`의 `auto_roi` 내 최대 물체 높이(mm)를 측정한다. 넓은 받침 위에 솟은 작은 장애물도 높이 계산에 남긴다.
   - `resolve_z_view()`가 테이블 기준면(`-0.025 <= surface_z <= 0.0`, 저고도 `beltend=-0.0721` 및 상단 `stack` 제외)에 대해 `max(base_z, table_z + (obstacle_mm + 35.0) / 1000)`로 `z_view`를 올리기만 하며(하향 금지), `cell_calibrate.py main()`이 `rp.plan()`으로 이동 전 IK 한계를 사전 거절(`fail-closed`)한다. `--plan-only` 무카메라 불변식은 `--obstacle-mm`로만 오프라인 검증한다.
3. **검증:**
   - 원격 pytest (`test/test_omx_cell_calibrate.py`, `test/test_omx_chunk_runner.py`, `middleware/devices/omx/adapter/test/test_chunk_library.py`)로 회귀 확인.
   - 실기 `rosy-arm-cell` D435 깊이 + FK 읽기 전용 검증(배포 전 `omx-tools-current` 심볼릭링크 무변경). 실기 적용은 표준 착지/릴리스 배포 파이프라인으로 진행한다.
4. **깊이를 잡지 못하면 닫힘(독립 검토 `57c7848c5b` 지적):** `capture_top_depth_z16`은 실패를 예외가 아니라 `None`으로 돌려준다. `cell_remap_plan.site_obstacle_mm()`은 프레임이 없거나 색·깊이 정렬이 8 px 넘게 느슨하면 `ValueError`를 내고, `remap_view()`는 그것을 `depth_error`에 남기며, `cell_calibrate.py`는 `depth_error`가 있으면 움직이기 전에 거절한다(`--obstacle-mm`을 준 경우만 명시적으로 진행). `z_view` 기록은 올라갔을 때뿐 아니라 항상 출력된다.
5. **부분 깊이 프레임(2026-11-26 독립 검토):** 전체 영상 정합이 통과해도 remap 구역마다 ROI가 색·깊이 영상에 모두 들어오고 유효 깊이가 80% 이상이어야 한다. 유효 표본이 부족하거나, 돌출 표본이 너무 적거나, 측정 높이 범위를 넘으면 remap 전에 보류한다. 회귀시험은 빈 구역, 부분 프레임, 넓은 받침 위 작은 장애물을 각각 확인한다. 실물 수용은 현장 검증을 거친다.
6. **기준면 표본(2026-11-26 원격 회귀시험):** 프레임에 기준면을 맞출 수 없으면 remap을 보류한다. 기본 기준면이 유효하고 나머지 표본으로 보조 평면을 맞출 수 없으면 기본 기준면을 쓴다. 이때 돌출된 표본은 그대로 높이 판정에 들어간다.
