# OMX 실물↔시뮬 루프 두 번째 바퀴: 2026-11-10 위 카메라 재측량 및 v11 임시 판·스냅샷 검증

다룬 행: sim2real G-17(임시 칸 판 v11 + 다리 v7), G-18(본선 r08), G-19(위 카메라 D435 재측량), G-30(벨트). 루프 절차는 [omx-real-sim-loop](../../reference/omx-real-sim-loop.md)다. 모든 시뮬레이션 결과는 MuJoCo 기하 근거이며 실물 근거가 아니다(D-947).

## 1. 위 카메라(D435) 재측량 (G-19, `top-camera-moved-20261110`)

- **원인**: 2026-11-10 USB3 재연결 과정에서 상단 RealSense D435 카메라가 이동해 고정 영역(먼 작업대·벨트·바닥)에서 `(-56 px, -17 px, 2.8°, +1.6 %)` 변위가 발생했고 `omx_cell_anchor`가 이를 감지해 `top-camera-moved-20261110` 요청을 열었다.
- **측량 방법**: 2026-11-08/09 측량 기준 프레임과 2026-11-10 캡처 프레임(`sha256:6b2e92c27893045b9be0fc34bf296b1f8498eb5e30d58ac517b6ab28a0d2f078`) 사이에서 움직이지 않은 다중 평면 정적 특징점 61개(벨트 상면 `z=0.017 m`, 작업대 `z=0.072 m`, 양팔 받침 판 삼각 탭·모서리 `z=0.084 m`, 접안 본선 상면 `z=0.112 m`)를 대응시켜 6-DoF PnP(`cv2.solvePnPRansac` + 반복 정밀화)로 풀었다.
- **수용 기준 대조**:
  - 전체 인라이어(61점) 재투영 잔차: **중앙값 `0.74 px`**(기준 `<= 1.0 px`), **p90 `1.39 px`**(기준 `<= 2.0 px`), RMS `0.95 px`.
  - 독립 보류(hold-out 1/3 분할, 21점) 재투영 잔차: **중앙값 `0.92 px`**, **p90 `1.51 px`**, **최대 `1.84 px`**(기준 `<= 3.0 px`).
  - 판 패드 폭 대조(`camera_check`): 3개 패드(`a-1`, `b-1`, `b-3`) 오차 **`[0.0, 1.9] mm`**(기준 `90×30 mm` 대비 `<= 3.0 mm`).
- **갱신된 자세(fixture 좌표)**:
  - `eye: [-0.0334, 0.0493, 0.6613]`, `focus: [0.0804, 0.0086, 0.1762]`, `up: [0.9737, 0.0296, 0.226]`, `f_px: 615.0`
  - 연직 소실점(`top_camera_parallax_centre_px`): `[265, 383]`(기존 `[322, 383]`)
  - 관제 PC(`robttt@100.82.51.8`)의 `top-camera-moved-20261110` 요청을 `pass`로 응답 완료(`2026-11-10T04:12:24+00:00`).

## 2. 2026-11-10 셀 스냅샷 측정 (`deploy/robot/omx/sim/cell_snapshots/20261110-1231.json`)

| 항목 | 설계(fixture / SCAD v11) | 2026-11-08 스냅샷 | 2026-11-10 스냅샷 (`20261110-1231.json`) | 근거 |
|---|---|---|---|---|
| 임시 칸 판 모양 | 단계 `17.3°`, 반지름 `200.0 mm` | 단계 `13.57°`, 반지름 `217.3 mm` | 단계 **`17.0°`**, 반지름 **`203.4 mm`** | `plate b`의 두 패드(`b-1`, `b-3`) 맞춤 |
| 판 `a` (칸 1·2·3) | 다리 v7 (`x ≈ -0.084, y = -0.164`) | `x = -0.029..-0.037, y = -0.106..-0.219` | `(-0.0842, -0.2271) +17.2°`, `(-0.0933, -0.1676) +0.2°`, `(-0.0846, -0.1081) -16.8°` | `a-1` 패드, `a-2` 노란 컨테이너, `a-3` 주황 컨테이너(3/3 검출, 잔차 `1.9~2.1 mm`) |
| 판 `b` (칸 1·2·3) | 다리 v7 (`x ≈ -0.096, y = +0.153`) | `x = -0.027..-0.033, y = +0.098..+0.200` | `(-0.0818, +0.1073) +16.9°`, `(-0.0906, +0.1668) -0.1°`, `(-0.0817, +0.2263) -17.1°` | `b-1` 패드, `b-2` 노란 컨테이너, `b-3` 패드(3/3 검출, 잔차 `0.2~1.4 mm`) |
| 배(r08) | 선미 `x = 0.155`, 중심 `y = -0.014` | 선미 `x = 0.1705`, 중심 `y = -0.014` | 선미 **`x = 0.1780`**, 중심 **`y = -0.0010`**, `yaw = 0.0°` | 선체 윤곽 IoU `0.83` |
| 벨트 | 멈춤 `x = 0.158`, 중심 `y = 0.007` | 끝 `x = 0.2055`, 중심 `y = -0.0375` | 끝 **`x = 0.2115`**, 중심 **`y = -0.0226`**, 폭 **`81.8 mm`** | 위 카메라 어두운 벨트 띠 되투영 |

- **측정기 보강(`tools/sim/omx_real2sim.py`)**:
  1. `blobs(frame)`: 주황 컨테이너(`H < 22`)뿐 아니라 밝은 하늘색 v11 판 위의 노란 컨테이너(`22 <= H < 29, S > 140, V > 140`)를 노란 작업대(`H ≈ 20..22, S < 120` 또는 합성 배경 `H = 30`)와 합쳐지지 않게 분리 검출.
  2. `lane_blobs`: 다리 v7(`200 mm`)에 장착된 v11 판의 칸들이 640×480 영상 하단 경계(`y = 479`)에 걸릴 때, 화면 안에 완전히 들어오는 `+x` 끝단(팔 쪽 끝)을 기준으로 중심과 길이를 복원하고 사선 시야의 컨테이너 옆면 두께 번짐을 보정.
  3. `measure_temp_plates`: 현재 프레임에서 두 패드가 보이는 판이 있으면 이전 스냅샷의 구형 판 모양(`13.57°, 217.3 mm`) 대신 현재 판 모양(`17.0°, 203.4 mm`)을 우선 맞춤.

## 3. 시뮬레이션 검증 결과 (`20261110-1231.json`)

선택지: `cell_snapshot=deploy/robot/omx/sim/cell_snapshots/20261110-1231.json temp_lanes=snapshot ship_pose=snapshot belt_pose=snapshot`.

- **기하·관절 한계 검증 (`omx_two_arm_tasks.py validate`)**:
  - `stack` (9단계), `stack-t1`·`stack-t2`·`stack-t3` (각 3단계): 모두 통과, `roll_below_floor = False`.
  - `cell-stack` (9단계), `cell-stack-t1`·`cell-stack-t2`·`cell-stack-t3` (각 3단계): 모두 통과, `roll_below_floor = False`.
  - `rehandle` (12단계): 모두 통과, `roll_below_floor = False`.
- **일정·모드 비교 (`omx_two_arm_plan.py compare --scenario all`)**:
  - `two-arm stack`: `132.4 s`, `{'arm_a': 5, 'arm_b': 4}`, overlap `4.5 s`, extra `0`, holds `[]`.
  - `two-arm outbound`: `162.8 s`, `{'arm_a': 5, 'arm_b': 5}`, overlap `13.3 s`, extra `0`, holds `[]`.
  - `two-arm rearrange`: `179.4 s`, `{'arm_a': 6, 'arm_b': 6}`, overlap `26.6 s`, extra `0`, holds `[]`.
- **원격 MuJoCo 동역학 시뮬레이션 (`tools/remote/remote_sim.py` on `ai@100.108.76.123`)**:
  - `stack`: `steps pass 9/9`, `final poses ok 9/9`, `completed True`, `makespan 169.0 s`.
  - `cell-stack`: `steps pass 9/9`, `final poses ok 9/9`, `completed True`, `makespan 168.9 s`, `roll below floor: []`.
  - `rehandle`: `steps pass 12/12`, `final poses ok 6/6`, `completed True`, `makespan 232.7 s`, `roll below floor: []`.
  - `outbound`: `steps pass 10/10`, `final poses ok 4/4`, `completed True`, `makespan 192.9 s`, `roll below floor: []`.
- **원격 단위·회귀 시험 (`tools/remote/remote_pytest.py` on `ai@100.108.76.123`)**:
  - `test/test_omx_real2sim.py`, `test/test_omx_two_arm_tasks.py`, `test/test_omx_two_arm_plan.py`, `test/test_omx_cell_auto_pick.py`, `test/test_omx_cell_place_fit.py`, `test/test_omx_cell_task_runner.py`, `learning/envs/isaac/test/test_container_stack.py` → **`161 passed in 315.96s`**.
