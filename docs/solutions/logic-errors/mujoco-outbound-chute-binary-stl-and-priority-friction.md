---
title: MuJoCo 반출대 미끄럼틀 모델링의 바이너리 STL·접촉 우선순위(priority=2)·실물 대조 규칙
date: 2026-11-22
category: logic-errors
module: tools/sim omx_two_arm_world omx_two_arm_tasks
modules: [tools, learning]
problem_type: logic_error
component: simulation_world
severity: medium
symptoms:
  - "OpenSCAD에서 내보낸 ASCII STL을 MuJoCo MjSpec에 넣으면 'number of faces should be between 1 and 200000' 예외로 컴파일이 실패한다"
  - "24도 경사 슈트에 마찰 계수 0.22를 넣어도 컨테이너 마찰(1.0)이 우세해 상자가 경사에서 미끄러지지 않는다"
  - "ROS CAD 폴더의 최신 v8 스키점프 슈트와 분홍 구즈넥 게이트를 그대로 넣자 실시간 셀 사진과 색상·모양·높이(70.9 vs 80.9 mm)가 어긋났다"
root_cause: config_error
resolution_type: code_fix
tags: [mujoco, stl, friction, priority, outbound-stand, real2sim, omx]
applies_when:
  - "OpenSCAD·trimesh 출력 STL을 MuJoCo MjSpec 메시로 편입할 때"
  - "중력 활주 경사면처럼 특정 충돌체가 물체의 높은 기본 마찰을 덮어써야 할 때"
  - "CAD 폴더의 덮어쓴 최신 파일이 아니라 실제 셀에 출력·장착된 부품을 시뮬에 넣을 때"
---

# MuJoCo 반출대 미끄럼틀 모델링의 바이너리 STL·접촉 우선순위(priority=2)·실물 대조 규칙

## 증상

1. `rosy-modeling`의 OpenSCAD STL을 그대로 `learning/envs/isaac/assets/ship_r08_berth/`에 복사해 MuJoCo `MjSpec`으로 불러오면 face 수 상한 오류(`Error: number of faces should be between 1 and 200000 ... perhaps this is an ASCII file?`)로 실패했다.
2. 24° 반출대 미끄럼틀 충돌 geom에 낮은 마찰(`[0.22, 0.005, 0.0001]`)을 주었는데도 기본 `priority=0` 상태에서는 `cell_physics.yaml` 컨테이너 마찰 `1.0`과 결합해 상자가 `dx = 34.4 mm` 게이트 앞까지 미끄러지지 않았다.
3. 디스크에 남아 있던 CAD STL(`r05_outbound_chute_body.stl`, `r05_outbound_chute_gate.stl`)은 폐기된 v8(스키점프·구즈넥 갈고리)으로 덮어써져 있어, 2026-11-22 실시간 천장 카메라(`ceiling_north`)에 놓인 실물(회색 단색 v6 미끄럼틀·갈고리 없는 게이트·크래들 없는 바닥 r05 2층 70.9 mm·흰 곡선 U자 트랙)과 모양·색상·높이가 모두 달랐다.

## 원인

- MuJoCo의 STL 파서는 바이너리 STL 헤더(`84 + 50 * n_faces` 바이트)만 허용하며 ASCII STL 텍스트를 읽지 못한다.
- MuJoCo 접촉 쌍의 기본 마찰 결합(`priority=0`)은 두 충돌체 마찰의 최댓값을 취하므로, 높은 마찰(`1.0`)을 가진 컨테이너 geom과 만나는 활주 레일은 `priority`를 높이지 않으면 낮은 마찰이 적용되지 않는다.
- CAD 저장소 파일명이 동일해도 새 설계(v8)를 export할 때 실물(v6) STL을 덮어쓰므로, 파일 이름·수정 시각만으로 실물 형상을 단정할 수 없다.

## 해결

1. **바이너리 STL + 닫힌 입체 검증**: `trimesh.export(..., file_type="stl")`로 바이너리 STL을 생성해 `len(raw) == 84 + 50 * len(faces)`와 `is_watertight`를 확인한 뒤 `SOURCE.json`과 함께 자산 루트에 등록한다(추적 `.py` 안에는 `manifold3d`를 import하지 않는다 — `test_3d_asset_boundary.py`).
2. **`priority=2` 활주 마찰 분리**: `tools/sim/omx_two_arm_world.py:_stand()`의 경사 레일·옆벽·게이트 스토퍼·분할 후벽 충돌체에만 `priority=2, friction=[.22, .005, .0001], condim=4`를 설정해 선체·임시판 마찰은 유지하면서 슈트 위에서만 `tan(24°)` 이하 미끄럼을 얻는다.
3. **실물 대조 후 반영 및 근접 운반 회피**: 실시간 `ceiling_north` 프레임(`v6` 단색 회색 슈트, 크래들 없음 → `OUTBOUND_STAND_SPEC["rail_z_m"] = 0.0709`, 흰 테두리 r05 2층, 곡선 흰색 U자 트랙)을 기준으로 메시와 알베도(`COLOURS`)를 맞추고, `ship-h2r0-l0 -> stand` 근접 운반이 `a_link1`을 스치는 현상(`chord_dist = 55.8~59.9 mm`)은 `tools/sim/omx_two_arm_tasks.py`에 `STAND_CARRY_CLEAR_R = .065`를 두어 전면 우회(`_carry_via`)로 해소했다.

## 검증 근거

- AI PC `policy-gpu` MuJoCo pytest(`test/test_omx_stand_episodes.py`, `test/test_omx_two_arm_tasks.py`, `test/architecture/test_3d_asset_boundary.py`, `test/test_omx_real2sim.py`, `learning/curation/omx/test/test_data_gate.py`): `84 passed` (`0 failed`).
- `tools/sim/omx_two_arm_teacher.py run outbound-stand`: `o1..o4`(`belt`, `ship-h1r0-l0`, `tmp-a-2`, `ship-h2r0-l0`) `4/4 pass` (`dx_mm=34.4, dy_mm=0.1..0.2, z_mm=-0.0, tilt_deg=24.0, arm_link_contacts=[]`).
- 공식 원격 pytest(`tools/remote/remote_pytest.py`): `69 passed, 9 skipped`, `known_failures.py`: `0 new`. (접촉·미끄럼 수치는 MuJoCo 기하·모의 기준이며 실물 수용 근거가 아님 — D-947.)

## 복구와 다음 적용 조건

- 새 STL을 `learning/envs/isaac/assets/`에 추가하기 전에 반드시 ① 실시간 셀 카메라(`ceiling_north`/`top`)로 실물 형상·색상·받침 높이를 대조하고, ② 바이트 길이(`84 + 50 * faces`)로 바이너리 STL 여부를 검사한다.
- 현장에서 반출대 밑 크래들·심이 실제로 추가되어 레일 높이가 바뀌면 `OUTBOUND_STAND_SPEC["rail_z_m"]`와 `_stand()` 바닥 오프셋을 함께 갱신한다.
