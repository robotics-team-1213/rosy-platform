## D-402 OMX 모션 플래너 v1은 장치 로컬 해석 IK(5축 수직하향)이며 계획만 내고 제출은 owner가 한다

**Status:** Proposed (2026-10-01, 계획 경계·인터페이스 결정; 시뮬레이션 한정 D-376 개정은 사용자 승인 2026-10-01). 대상은 D-403의 `CELL_TRANSFER` 포즈 입력과 `simulation` 프로필뿐이다. RGB-D `PICK_PLACE` 계획, 실물 OMX 프로필 활성화, 충돌 장면, MoveIt 채택, DEVICE/FIELD 수용은 포함하지 않는다.

## 배경

- **D-376(Accepted).** §2는 로컬 `PickPlacePlanProvider`를 plan-only 경계로 둔다. MoveIt Task Constructor는 평가 후보이고, 마지막 문장은 "다른 결정론적 backend는 근거 검토와 별도 결정 전에는 선택하지 않는다"이다. §3은 production provider 전에 다음을 요구하고, 그 전에는 계획을 `HOLD`로 거절한다: SRDF, planning group, IK solver, 충돌 geometry/scene, 제한값, frame/calibration identity, 재현 가능한 빌드.
- **코드 현황(main `dcad279d`).**
  - `manipulation_plan.py`: `PickPlacePlanProvider` Protocol만 있다. 입력은 `FleetActionGrant`와 `RgbdObservation`이고, 출력 `ResolvedPickPlacePlan`은 RGB/depth digest를 가진 `ResolvedObjectPose`를 필수로 요구한다. IK/FK 코드는 `src`에 없다.
  - `PickPlaceRunner`: `ResolvedPickPlacePlan`만 받고 `plan.phases`와 `plan.planner_revision`만 읽는다. start-state 허용오차는 계획된 모든 관절을 정확히 덮어야 한다(그리퍼 관절 포함).
  - `ActionRunner.submit`(`action_runner.py` 185행): `PICK_PLACE`이고 phase runner factory가 있을 때만 phase runner로 간다. 그 밖에는 `driver.submit(grant)`로 직접 제출한다.
  - `ArmCommandOwner.submit`이 최종 검사를 한다.
    - 관절 한계
    - 다점 궤적이면 점마다 속도·가속도가 있고 그 한계 안인지
    - `duration_s ≤ max_goal_duration_s`
    - 상태 sequence, `allowed_owners`
  - `pilot_sim_server.py`는 자리표시 값을 쓴다: 한계 ±3.0 rad, `max_goal_duration_s=1.0`, `allowed_owners=("pilot_sim",)`.
- **URDF.** 저장소의 생성본 `src/sim/isaac_sim/assets/open_manipulator_description/urdf/omx_f/omx_f.urdf`를 확인했다.
  - joint1 축은 +z다. joint2·3·4 축은 +y이고(91·124·157행), 영점 자세에서 팔이 +x를 향한다. joint5 축은 +x다.
  - 관절 한계는 모두 ±2π다. 보호가 되지 않는다.
  - 치수: joint2 축 높이는 베이스에서 0.0975 m, L1 = |(0.0415, 0.11315)| ≈ 0.1205 m, L2 = 0.162 m, joint4 → TCP(`end_effector_link`) ≈ 0.0287 + 0.0919 ≈ 0.12 m.
- **D-401(Proposed).** Step은 `Pose(x, y, z, yaw)`와 Step마다의 `approach_z`를 싣는다. D-399 §7 후속 3은 MoveIt과 5축 IK를 묶었다.
- **사용자 결정(2026-10-01).** 해석 IK를 먼저 만들고, MoveIt 2는 같은 인터페이스의 두 번째 구현으로 둔다. 시뮬레이션 한정으로 D-376을 개정하는 것을 승인했다.

## 결정

1. **D-376 개정 범위.**
   - 이 ADR이 D-376 §2 마지막 문장의 "별도 결정"이다. backend는 해석 5축 수직하향 IK이고, 범위는 `CELL_TRANSFER`와 `simulation`이다.
   - 이 범위에서 §3의 SRDF·planning group·충돌 scene 조건을 다음으로 대신한다: URDF 기구학, 시뮬 프로필의 명시 한계, 작업 영역 경계, 운반 높이 경유.
   - 그 밖의 경로와 프로필에서는 §3 HOLD가 그대로다. §1(owner만 제출)과 §4–§8은 바꾸지 않는다.
   - D-376 머리에 시뮬레이션 한정 개정 문단을 단다.
2. **인터페이스.**
   - **재사용:** `MOTION_PHASES`, `JointTrajectoryPoint`, `PlannedMotionPhase`, `ExecutionStateSnapshot`, `TrajectoryCommand`, `PickPlaceRunner`의 진행·fence·취소 로직.
   - **새로 둔다:**
     - `CellTransferPlanProvider.plan_transfer(request, profile, state) -> CellTransferPlan`
     - `CellTransferPlan`: `phases`, `planner_revision`, `kinematics_revision`, `profile_revision`, `source_state_sequence`, `planned_at_monotonic_s`
     - `CellPlanningProfile`: §4 프로필 파일을 읽는다.
   - `ResolvedPickPlacePlan`, `ResolvedObjectPose`, `RgbdObservation`, `ManipulationPlanningProfile`은 쓰지 않는다. RGB-D 출처를 가짜 digest로 채우면 증거를 위조하는 셈이다.
   - `planning_scene_revision`에는 `kin:` 접두사를 붙인 기하 revision을 싣는다. 충돌 장면이 있다고 읽히지 않게 하기 위해서다.
3. **필요한 코드 변경(C2/C4).** 이 변경 전에는 `CELL_TRANSFER`를 열지 않는다.
   - (a) `action_runner.py` 185행의 phase runner 분기를 `CELL_TRANSFER`까지 넓힌다. `CELL_TRANSFER`는 phase runner로만 실행한다.
   - (b) 직접 `driver.submit` 경로는 기존 종류가 아니면 모두 fail closed로 막는다. 모르는 종류는 거절한다.
   - (c) `PickPlaceRunner`가 `CellTransferPlan`을 받게 한다. 새 `validate_cell_transfer_plan`을 둔다.
   - (d) `pick_place_runner.py`의 start-state 검사에서 그리퍼 관절을 제외한다. 허용오차 맵은 팔 관절만 덮는다. 집음 이후 그리퍼는 물체 폭에서 멈추므로, 관절값 비교로는 의미 있는 판정이 안 된다. 그리퍼 상태는 8항의 readback으로만 판정한다. 이는 D-386 §3을 시뮬레이션 한정으로 좁히는 것이며, D-386 머리에 개정 문단을 단다.
4. **시뮬 프로필 파일이 한계의 출처다.**
   - 경로는 `deploy/robot/omx/sim/cell_profile.yaml`(schema `rosy.omx-sim-cell-profile.v1`)이다. 내용 해시가 `profile_revision`이 된다.
   - 담는 값:
     - 팔 관절별 위치·속도·가속도 한계(보수적인 명시 값)
     - phase별 최대 시간
     - 그리퍼 열림·닫힘 목표
     - 작업 영역 경계, Cartesian 표본 간격
     - 특이점 최소 반경, 수직하향 허용오차
   - sim owner의 `ArmCommandConfig`도 같은 파일에서 만든다. `max_goal_duration_s`는 phase별 최대 시간의 최댓값이다.
   - URDF ±2π는 보호가 아니다. ROBOTIS 하드웨어 설정의 실제 OMX-F 한계를 고정하기 전까지 이 한계는 **명목상 보호**일 뿐이다.
   - 기하 값은 고정 `open_manipulator` 5.1.2(`stack.lock.yaml`)에서 추출해 시험 고정값과 드리프트 시험으로 묶는다(D-397 규칙 준용). 위 생성본이 고정 revision과 같은지는 C2가 확인한다.
5. **기구학.**
   - "수직하향"은 공구 축 = −z_base라는 뜻이다. 관절 조건으로는 q2 + q3 + q4 = +π/2다(+y 축 회전이 +x를 −z로 돌린다).
   - joint1 = atan2(y, x)로 정한다.
   - 손목 중심은 TCP 위 약 0.12 m다. 여기서 L1/L2 2링크 평면 IK를 elbow-up 분기 하나로만 푼다.
   - joint5는 목표 yaw와 joint1의 차이에서 나온다. 180° 대칭 후보 중 한계 안에서 현재 값에 가까운 쪽을 고른다.
   - 도달 범위 추정: 작업대 높이에서 joint2 축으로부터 반경 약 0.28 m 이하의 고리다. C3가 실측하고 데모 배치를 맞춘다.
6. **동작 모양.**
   - **입력:** grant의 다음 값을 받는다.
     - `home` 포즈와 pick·place 포즈(`robot_base`, x, y, z, yaw, 수직하향)
     - 각 `approach_z`
     - 운반 높이 `carry_z`
   - **`carry_z`:** Action이 명시적으로 싣는다.
     - 값: Job 전체에서 가장 높은 적재물·팔레트·스테이션 윗면 + 박스 높이 + `cell.yaml`의 `approach_clearance_m`(TCP 높이).
     - 계산은 `rosy_cell` 함수 하나 `rosy_cell.compiler.carry_z(recipe, cell)`만 한다. Fleet은 재컴파일할 때 이 함수를 호출하고, 다시 구현하지 않는다(D-403 §2). 계획기는 `carry_z ≥ max(approach_z)`인지와 작업 영역 안인지만 확인한다.
   - **home:** 모든 transfer는 셀에 티칭된 `home`(수직하향)에서 시작한다. 시작 상태가 home의 IK 해에서 허용오차 밖이면 거절한다.
   - **이동 규칙:** 수평 이동은 항상 수직 상승 → `carry_z`에서 이동 → 수직 하강이다. 현재 자세에서 대각선 직선으로 가지 않는다.
   - 네 phase(phase마다 ROS goal 하나):
     - `approach`: home → `carry_z` → pick 위 → pick `approach_z` → pick. 그리퍼는 열림이다.
     - `grasp`: 그리퍼만 닫는다.
     - `transfer`: `carry_z`로 상승 → place 위 → place `approach_z` → place.
     - `release`: 그리퍼를 열고 → `carry_z` → home.
   - 모든 구간은 Cartesian으로 표본화하고 표본마다 IK를 푼다. 모든 waypoint는 FK로 작업 영역 안인지 확인한다.
   - 시간은 프로필 한계로 사다리꼴 매개화하고 점마다 속도·가속도를 싣는다.
   - phase가 자기 최대 시간을 넘으면 **거절한다**(HOLD). 쪼개지 않는다. phase 수는 journal 계약상 네 개로 고정이고, 한계는 프로필에서 조정한다.
7. **거절 조건과 보호하지 않는 것.**
   - **거절한다(부분 계획 없이 HOLD):**
     - IK 해 없음
     - 한계 초과
     - 특이점 반경 미만
     - 작업 영역 밖
     - yaw를 맞출 수 없음
     - 시간 초과
     - home 이탈
     - `carry_z` 부족
     - grant `cell_sha256`이 owner가 수락한 셀 해시와 다름. 계획 직전에 두 번째로 확인한다(D-403 §9).
   - **보호하지 않는다(충돌 장면 없음):**
     - 이미 놓인 박스와 손가락의 간섭
     - 높이가 같은 이웃 박스
     - 들고 있는 박스가 TCP 아래로 쓸고 지나가는 영역
     - 팔꿈치 등 링크가 낮게 지나가는 경로, 자기 충돌
     - `carry_z` 계산 밖의 물체, 사람, 케이블
     - 티칭 위치에 물체가 없거나 어긋난 경우(블라인드 집기)
     - 그리퍼 힘
   - 그래서 이 backend는 `simulation`에만 쓴다. 실물은 충돌 장면과 별도 ADR이 필요하다.
8. **그리퍼.**
   - `grasp` 뒤에는 `verify_held_object`, `release` 뒤에는 `verify_released_object`로 판정한다(`gripper_contract`).
   - 시뮬의 `object_present`를 무엇으로 증명할지와 그 `sensor_revision`은 C3가 정한다. 0.011 rad mimic 오차를 측정해 반영한다. 증명하지 못하면 다음 phase는 gate에서 막힌다.
   - `PickPlaceTransaction`은 RGB-D `TargetEvidence`에 묶여 있으므로, job·step·item을 식별자로 쓰는 변형을 둔다.
9. **owner만 제출한다.** 계획기는 `ActionPort`를 호출하지 않는다. 명령의 owner 표지는 `rule_based`다. `KNOWN_OWNERS`에 있는 값이고, Fleet ROS actionserver 시험이 쓰는 값이다. 시뮬 owner의 `allowed_owners`는 `("pilot_sim", "rule_based")`가 된다(D-403 §8).
10. **MoveIt 2는 두 번째 구현이다.** 같은 `CellTransferPlanProvider`를 구현하고 프로필 설정으로 고른다. 채택에는 D-376 §3 조건을 충족하는 별도 ADR이 필요하다.

## 검토한 대안

| 대안 | 판단 |
|---|---|
| MoveIt 2 먼저 | 잠금 이미지에 MoveIt과 SRDF가 없다(D-376 배경). 사용자가 해석 IK를 먼저 하기로 했다. 두 번째 구현으로 미룬다. |
| 수치 IK | 해의 분기가 초기값에 좌우된다. 5축 수직하향은 닫힌 해가 있다. 채택하지 않는다. |
| 시간 초과 phase를 여러 goal로 분할 | phase journal과 Fleet receipt(네 phase 고정)를 바꿔야 한다. 채택하지 않는다. |
| 합성 RGB-D digest로 `ResolvedPickPlacePlan` 재사용 | 출처 위조다. 채택하지 않는다. |

## 결과

- 포즈 입력 계획기는 ROS 없이 시험할 수 있다. owner·journal 경로는 유지되고 실행은 phase runner로만 한다.
- 충돌 보호가 없다는 사실과 한계가 명목상이라는 사실이 문서와 프로필에 남는다.

## 수용 기준과 증거 경계

- **SOURCE:**
  - FK∘IK 왕복
  - q2+q3+q4 = +π/2 수직하향 검사
  - 한계·작업 영역·특이점·yaw·home·`carry_z` 거절
  - 네 phase의 모양(대각선 없음)
  - 생성된 명령을 실제 `ArmCommandOwner`가 수락함
  - 모르는 종류의 직접 제출 거절
  - 그리퍼 제외 start-state
  - URDF 드리프트 시험
- **ROS-SIM:** C3 Gazebo에서 블록 하나를 옮긴다. 도달 고리 실측, 그리퍼 readback, 위치 오차를 기록한다.
- **DEVICE / FIELD:** 이 결정으로 승격하지 않는다.

**관련 결정:** [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-376](D-376-omx-pick-place-planning-and-execution-boundary.md), [D-386](D-386-omx-async-goal-acceptance-and-phase-state.md), [D-390](D-390-pilot-omx-simulation-practice-boundary.md), [D-397](D-397-pinky-geometry-urdf-nominal-calibration-refines.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-401](D-401-rosy-cell-application.md), [D-403](D-403-fleet-cell-job-route-cell-transfer.md), [D-404](D-404-omx-setup-teaching-api-simulation-first.md)
