# D-877: 공통 작업 장면과 실시간 배율 보고 (2026-10-26)

## 주장과 한계

`tools/sim/omx_cell_world.py`가 Gazebo `omx_cell_workcell.sdf`의 상자(작업대, 팔레트 2, 시트 받침, 슬립 시트, 투입 블록)를 읽고, MuJoCo와 Isaac 어댑터가 같은 장면을 만든다. 움직이는 상자 2개(슬립 시트 5g, 투입 블록 20g)는 SDF 질량으로 자유 물체가 된다. 이 장면에서 두 백엔드가 P1 적합성을 다시 통과했다. 적합성 도구는 이제 기록 구간의 실시간 배율(시뮬 초/벽시계 초)을 함께 보고한다(판정하지 않음).

장면이 카메라에 어떻게 보이는지, 움직이는 상자가 놓인 자리에 가만히 있는지는 확인하지 않았다. Isaac 마찰은 SDF 값이 아니라 기본 재질이다(코드에 shortcut 표시).

## 결과

커밋 `b630f2be42`, `tools/sim/run_omx_backend_conformance.sh <backend> 240x320 10`, 한 번에 시험 PC 한 대.

| 백엔드 | PC | 판정 | 카메라 프레임 top/front | 실시간 배율 | 취소 전/뒤 joint1 |
|---|---|---|---|---|---|
| MuJoCo 3.3.7 | AI PC | 통과 | 140 / 140 | 0.999 | 0.051 / 0.00006 rad |
| Isaac Sim 5.1 | 모델 PC | 통과 | 126 / 127 | 0.936 | 0.065 / 0.0 rad |

- 원격 pytest(`test/test_omx_sim_backends.py`, `test/test_omx_backend_conformance.py`) 통과.
- 단일 카메라 Gazebo 탐침(`policy_chain_gazebo.py`)도 제품 owner 실행기로 바꿨다(D-866 P0 교훈). 같은 커밋에서 AI PC로 다시 돌려 `OMX_POLICY_CHAIN_GAZEBO_PASS`와 `OMX_POLICY_CHAIN_EXIT_OK`를 확인했다.
