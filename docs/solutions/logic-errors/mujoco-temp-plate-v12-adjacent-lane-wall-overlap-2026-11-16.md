---
title: MuJoCo temp_slot_plate v12 부채꼴 임시판 벽을 이웃 레인 간격으로 클리핑하지 않으면 인접 칸 안착이 실패한다
date: 2026-11-16
category: logic-errors
module: tools/sim omx_two_arm_world
modules: [tools]
problem_type: logic_error
component: simulation_world
severity: high
symptoms:
  - "실물 동일 v12 2색 STL 렌더링 테스트(test_omx_real2sim.py)는 통과했는데, MuJoCo outbound(ship -> tmp) 교사 시연이 임시 칸 안착 시 컨테이너가 기울며 실패했다"
  - "stack(9/9)과 달리 여러 임시 칸을 동시에 쓰는 outbound·rehandle 구간에서만 비정상 기울기·높이 이탈이 발생했다"
root_cause: logic_error
resolution_type: code_fix
tags: [mujoco, cad, temp_slot_plate, v12, collision, real2sim, omx]
applies_when:
  - "부채꼴(원호) 배치 슬롯의 충돌 box를 로컬 좌표 고정 폭으로 생성할 때"
  - "시각 렌더링 STL은 교체됐지만 접촉용 primitive box가 이웃 포켓 중심선을 넘는지 확인하지 않았을 때"
---

# MuJoCo temp_slot_plate v12 부채꼴 임시판 벽을 이웃 레인 간격으로 클리핑하지 않으면 인접 칸 안착이 실패한다

## 증상

`temp_slot_plate.scad v12` 기반 2색 STL(`temp_slot_plate_v12_sky`/`white`)과 접안 v24(`194.0 mm`)를 반영한 뒤 시각 정합 테스트는 통과했으나, 실제 MuJoCo `outbound`(`ship -> tmp`) 교사 실행에서 임시 칸 안착 단계가 컨테이너 기울기·z 이탈로 실패했다.

## 원인

`temp_slot_plate v12`는 안쪽 끝단에서 부채꼴(`13.76°`, 최소 틈 `0.6 mm`)로 모여 인접 레인 중심 간격이 좁아진다(`36.43 mm` 구간 포함). 그런데 `tools/sim/omx_two_arm_world.py`의 `_temp()`는 렌더링용 2색 STL 아래에 두는 충돌용 box 벽을 이웃 포켓 거리와 무관하게 바깥쪽으로 고정 돌출시켜, 인접 칸 포켓 내부까지 약 `4 mm` 침범했다. 시각 렌더는 STL만 보므로 정상처럼 보였지만, 물리 접촉은 겹친 충돌 box를 밟아 컨테이너가 들리거나 기울었다.

## 해결

`tools/sim/omx_two_arm_world.py`의 `_temp()`(`13685189ad`)에서 다음 두 가지를 함께 고쳤다.

1. **인접 레인 반거리 한계(`lim`) 클리핑**: 각 레인의 측면 벽과 종단 벽(`lim(es * hl, ±1)`)이 인접 레인 중심선 절반 한계를 넘지 않도록 횡방향 범위를 잘라 이웃 포켓 침범을 제거했다.
2. **CAD `flare`·45도 경사 반영(`sec_side` 4분할)**: v12 포켓 형상(`flare` 및 경사면)에 맞춰 레인 길이 구간별 측면 폭을 4분할하고, 기본값 바인딩(`(xy=xy, long=long, side=side, i=i)`, `(lim=lim)`)으로 클로저 지연 바인딩(B023)을 막았다.

또한 `test/test_omx_real2sim.py`에 6개 임시 칸 동시 안착 회귀 시험(`test_temp_plate_v12_lanes_seat_containers_without_interlane_wall_overlap`, `xy < 0.5 mm`, `z < 0.3 mm`, `tilt < 0.5 deg`)을 추가했다.

## 검증 근거

- **로컬 회귀 시험**(`fix/omx-map-194` `13685189ad`): `pytest test/test_omx_real2sim.py test/test_omx_two_arm_tasks.py -v -rs` (AI PC `sim-mujoco`) → **54 passed, 0 skipped (69.73 s)**.
- **로컬 가드 스위트**: `pytest test/test_robot_literals.py test/test_harness_contracts.py test/architecture/test_module_structure.py test/architecture/test_platform_parts.py -q` → **195 passed, 1 skipped (77.03 s)**.
- **교사 3종 실물 동일 MuJoCo 검증**(`13685189ad`, AI PC `policy-gpu`):
  - `outbound`: steps pass **10/10**, final poses ok **4/4**, completed `True`, makespan `274.5 s`
  - `stack`: steps pass **9/9**, final poses ok **9/9**, completed `True`, makespan `235.4 s`
  - `rehandle`: steps pass **12/12**, final poses ok **6/6**, completed `True`, makespan `330.2 s`
- 위 결과는 모두 MuJoCo 시뮬레이션 검증이며 실물 셀 근거가 아니다(D-947).
