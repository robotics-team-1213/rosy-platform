## D-402 OMX 모션 플래너 v1은 장치 로컬 해석 IK(5축 수직하향)이며 계획만 내고 제출은 owner가 한다

**Status:** Proposed (2026-10-01, 계획 경계·인터페이스 결정). 대상은 D-403의 `CELL_TRANSFER` 포즈 입력과 `simulation` 프로필뿐이다. RGB-D `PICK_PLACE` 계획, 실물 OMX 프로필 활성화, 충돌 장면, MoveIt 채택, DEVICE/FIELD 수용은 포함하지 않는다.

## 배경

- **D-376(Accepted).** §2는 로컬 `PickPlacePlanProvider`를 plan-only 경계로 둔다. MoveIt Task Constructor는 평가 후보이고, 마지막 문장은 "다른 결정론적 backend는 근거 검토와 별도 결정 전에는 선택하지 않는다"이다. §3은 production provider 전에 다음을 요구한다: 검토된 SRDF, planning group, IK solver, 충돌 geometry/scene, 제한값, frame/calibration identity, 재현 가능한 빌드. 그 전에는 계획을 `HOLD`로 거절한다. 이 ADR은 §2가 말하는 "별도 결정"을 한 backend에 대해 내리고, §3 HOLD는 좁은 범위에서만 연다.
- **코드 현황(main `dcad279d`).**
  - `manipulation_plan.py`에는 `PickPlacePlanProvider` Protocol만 있고 구현이 없다. IK/FK 코드는 `src` 어디에도 없다.
  - Protocol 입력은 `FleetActionGrant`와 `RgbdObservation`이다. 출력 `ResolvedPickPlacePlan`은 RGB/depth digest를 가진 `ResolvedObjectPose` 두 개를 필수로 요구한다.
  - `PickPlaceRunner`는 `isinstance(plan, ResolvedPickPlacePlan)`만 받는다. 실제로 읽는 것은 `plan.phases`와 `plan.planner_revision`뿐이다.
  - `ArmCommandOwner.submit`이 최종 검사를 한다. 관절 위치 한계를 보고, 다점 궤적이면 점마다 속도·가속도가 있어야 하며 그 한계를 넘으면 안 된다. `duration_s ≤ max_goal_duration_s`(기본 1.0 s), 상태 sequence 일치, `allowed_owners`도 확인한다.
- **D-401(Proposed).** Rosy Cell Step은 로봇 베이스 좌표 `Pose(x, y, z, yaw)`와 Step마다의 `approach_z`를 싣는다. D-401 수용 기준은 실행 전제로 "MoveIt 채택(D-399 후속 3)"을 적었다. D-399(Proposed) §7 후속 3은 MoveIt 채택과 5축 수직하향 IK를 한 ADR로 묶었다.
- **사용자 결정(2026-10-01).** 해석 IK를 먼저 Python으로 장치 쪽에 만든다. MoveIt 2는 나중에 같은 플래너 인터페이스의 두 번째 구현으로 붙인다.
- `pilot_sim_server.py`의 `position_limits`는 URDF 값이 아니라 자리표시 값이다(팔 ±3.0, 그리퍼 ±0.5 rad).

## 결정

1. **D-376 개정 범위.**
   - 이 ADR은 D-376 §2 마지막 문장이 요구한 별도 결정이다. backend 하나를 고른다: 해석 5축 수직하향 IK. 적용 범위는 `CELL_TRANSFER`(D-403)와 `simulation` 프로필로 한정한다.
   - 이 범위에서는 D-376 §3의 조건 중 SRDF, planning group, 충돌 scene을 다음으로 대신한다: 고정 URDF 기구학, 관절 한계, 작업 영역 경계, `approach_z` 경유점. 근거가 없거나 지원하지 않는 계획을 `HOLD`로 거절한다는 §3 규칙은 그대로다.
   - RGB-D `PICK_PLACE` 경로와 `simulation`이 아닌 모든 프로필에서는 D-376 §3 HOLD가 계속 유효하다.
   - D-376 §1(owner만 `FollowJointTrajectory`를 제출)과 §4–§8은 바꾸지 않는다. 이 ADR이 Accepted가 되기 전에는 D-376이 그대로 효력을 가진다.
2. **인터페이스: 기존 phase 타입은 재사용하고, 포즈 입력 변형을 새로 둔다.**
   - **재사용:** `MOTION_PHASES`, `JointTrajectoryPoint`, `PlannedMotionPhase`, `ExecutionStateSnapshot`, `TrajectoryCommand`, `PickPlaceRunner`의 phase 진행·fence·취소 로직.
   - **새로 둔다:**
     - `CellTransferPlanProvider.plan_transfer(request, profile, state) -> CellTransferPlan`
     - `CellTransferPlan`: `phases`, `planner_revision`, `kinematics_revision`, `source_state_sequence`, `planned_at_monotonic_s`
     - `CellPlanningProfile`: 작업 영역 경계, 관절 이름, 그리퍼 열림·닫힘 목표, Cartesian 표본 간격, 시간 매개화 한계, 특이점 최소 반경. 모두 설정에서 받는다.
   - `ResolvedPickPlacePlan`, `ResolvedObjectPose`, `RgbdObservation`은 쓰지 않는다. RGB-D 출처 필드를 가짜 digest로 채우면 증거를 위조하는 셈이다. `ManipulationPlanningProfile`도 쓰지 않는다. 이 경로에서 의미가 없는 RGB-D 임계값을 필수로 요구하기 때문이다.
   - `PickPlaceRunner`의 타입 검사를 넓혀 두 계획 타입을 모두 받게 한다. `validate_pick_place_plan`은 `PICK_PLACE` 전용으로 남기고, `validate_cell_transfer_plan`을 따로 둔다.
   - `PlannedMotionPhase.planning_scene_revision`에는 `kin:` 접두사를 붙인 기하 revision을 싣는다. 충돌 장면이 있다고 읽히지 않게 하기 위해서다.
3. **입력.** 입력은 D-403 grant의 pick 포즈와 place 포즈(`robot_base` 프레임, x, y, z, yaw)다. 공구는 수직하향이다. 각 포즈에는 자기 `approach_z`가 붙는다. 다음 경우는 계획 전에 거절한다: `approach_z ≤ z`, 값이 유한하지 않음, 프레임이 `robot_base`가 아님.
4. **기구학과 기하 출처.**
   - 기하는 `deploy/robot/omx/stack.lock.yaml`이 고정한 `open_manipulator` 5.1.2(revision `0a4af6a9…`)의 xacro에서 온다. C2가 추출한 값을 시험 고정값으로 체크인하고, 드리프트 시험으로 묶는다. D-397(Proposed, Pinky)의 "URDF가 NOMINAL, 보정이 다듬는다" 규칙을 OMX에 그대로 적용한다. 코드에는 물리 상수를 두지 않는다.
   - TCP는 URDF의 말단 링크에 보정 레코드의 오프셋을 더한 점이다.
   - 관절 한계는 같은 URDF 한계와 owner `ArmCommandConfig.position_limits`의 교집합이다. owner 설정이 URDF보다 넓으면 시작을 거절한다.
   - 축 배치는 다음으로 가정하고 C2가 고정 URDF로 확인한다: joint1 베이스 yaw, joint2–4 수직 평면 pitch 사슬, joint5 손목 roll. 가정이 틀리면 이 ADR을 고친다.
   - 풀이 절차는 다음과 같다.
     - joint1은 `atan2(y, x)`이다.
     - 수직하향 조건(pitch 합 = −π/2)으로 손목 중심을 정하고, 2링크 평면 IK를 elbow-up 분기 하나로만 푼다. 다른 분기를 탐색하지 않는다.
     - joint5는 목표 yaw와 joint1의 차이에서 나온다. 평행 그리퍼는 180°에 대해 대칭이므로 두 후보 중 한계 안에서 현재 값에 가까운 쪽을 고른다.
5. **네 phase의 모양.** phase마다 ROS goal 하나다(D-376 §4). 그리퍼 관절은 시뮬 `arm_controller` 관절 집합에 포함된다.
   - `approach`: 현재 상태 → pick 위 `approach_z` → pick 포즈. 그리퍼는 열림 목표다.
   - `grasp`: 팔은 정지하고 그리퍼만 닫힘 목표로 간다.
   - `transfer`: 수직 상승 → 운반 높이 `max(pick approach_z, place approach_z)`에서 직선 이동 → place 포즈로 하강.
   - `release`: 그리퍼를 열고 place `approach_z`로 후퇴한다.
   - 모든 구간은 Cartesian 직선을 설정 간격으로 표본화해 표본마다 IK를 푼다. 모든 waypoint를 FK로 다시 계산해 작업 영역 안인지 확인한다.
   - 시간은 owner 설정의 속도·가속도 한계로 사다리꼴 매개화하고, 점마다 속도·가속도를 싣는다. phase 하나가 `max_goal_duration_s`를 넘으면 거절한다. phase를 더 쪼개지 않는다.
   - 첫 phase는 현재 관절 상태에서 계획한다. 이후 phase의 시작 상태는 runner의 start-state 허용오차 검사(D-386 §3)가 다시 확인한다.
6. **도달성 거절.** 다음 중 하나라도 해당하면 부분 계획 없이 전체를 거절하고 `HOLD`로 둔다.
   - IK 해 없음
   - 관절 한계 초과
   - 손목 중심 반경이 특이점 최소 반경 미만
   - waypoint가 작업 영역 밖
   - yaw를 맞출 수 없음
   - phase 시간 초과
7. **보호하지 않는 것.** 충돌 장면이 없으므로 다음은 막지 못한다.
   - 이미 놓인 박스와 손가락의 간섭(D-401 §5가 계획기 몫으로 넘긴 것)
   - 운반 높이보다 높은 다른 팔레트 적재물, 팔레트 모서리
   - TCP보다 낮게 내려가는 팔꿈치 등 링크의 쓸림, 자기 충돌
   - 케이블, 사람, 예상하지 못한 물체
   - 물체가 티칭 위치에 없거나 어긋난 경우(인식이 없는 블라인드 집기)
   - 그리퍼 힘

   이런 이유로 이 backend는 `simulation`에만 쓴다. 실물에 쓰려면 충돌 장면(MoveIt 또는 동등한 것)과 별도 ADR이 필요하다.
8. **그리퍼.** 집음 판정은 `gripper_contract` readback으로 한다. `grasp` 뒤에는 `verify_held_object`, `release` 뒤에는 `verify_released_object`를 쓴다. 계획기는 물체가 있는지 판정하지 않는다.
   - 시뮬 그리퍼의 약 0.011 rad mimic 오차 때문에, `object_present`를 무엇으로 증명할지 C3에서 측정해 정한다. 그 생산자와 `sensor_revision`을 명시해야 한다. 증명할 수 없으면 `transfer`는 gate에서 막힌다(HOLD).
   - `PickPlaceTransaction`은 RGB-D `TargetEvidence`에 묶여 있다. 그래서 `CELL_TRANSFER`용 transaction 변형이 필요하다. 이 변형은 job·step·item을 식별자로 쓴다.
9. **owner만 제출한다.** 계획기는 `ActionPort`를 호출하지 않고 계획만 반환한다. 명령의 owner 표지는 기존 `KNOWN_OWNERS`의 `rule_based`를 쓴다. MoveIt 구현은 `moveit`을 쓴다. 새 표지는 만들지 않는다.
10. **MoveIt 2는 두 번째 구현이다.** 같은 `CellTransferPlanProvider`의 입력과 출력을 구현하고, 어느 구현을 쓸지는 프로필 설정으로 고른다. 채택하려면 D-376 §3 조건(SRDF, scene, 재현 빌드)을 충족하는 별도 ADR이 필요하다.

## 검토한 대안

| 대안 | 판단 |
|---|---|
| MoveIt 2 먼저 | 잠금 이미지에 MoveIt, SRDF, kinematics 설정이 없다(D-376 배경). 사용자가 해석 IK를 먼저 하기로 했다. 두 번째 구현으로 미룬다. |
| 수치 IK(Jacobian 반복) | 초기값에 따라 해의 분기가 달라져 결정론적이지 않다. 5축 수직하향은 닫힌 해가 있다. 채택하지 않는다. |
| Rosy Cell이 IK와 도달성을 판정 | D-399 §5, D-401 §4와 어긋난다. 채택하지 않는다. |
| `ResolvedPickPlacePlan`에 합성 RGB-D digest를 넣어 재사용 | 출처 증거를 위조하게 된다. 채택하지 않는다. |

## 결과

- 포즈 입력 계획기는 ROS 없이 시험할 수 있다. owner·runner·journal 경로는 바뀌지 않는다.
- 실물 프로필의 계획 HOLD는 그대로다. 이 계획기만으로는 충돌로부터 보호되지 않는다는 점이 문서와 코드에 남는다.

## 수용 기준과 증거 경계

- **SOURCE:**
  - FK∘IK 왕복
  - 관절 한계·작업 영역·특이점·yaw 거절
  - 네 phase의 모양
  - 생성된 명령을 실제 `ArmCommandOwner`가 수락함(속도·가속도·시간 포함)
  - URDF 드리프트 시험
- **ROS-SIM:** C3에서 고정 이미지 Gazebo로 블록 하나를 옮긴다. 그리퍼 readback과 위치 오차를 측정한다.
- **DEVICE / FIELD:** 이 결정으로 승격하지 않는다. 실물 프로필은 `enabled: false`로 둔다.

**관련 결정:** [D-376](D-376-omx-pick-place-planning-and-execution-boundary.md), [D-386](D-386-omx-async-goal-acceptance-and-phase-state.md), [D-397](D-397-pinky-geometry-urdf-nominal-calibration-refines.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-401](D-401-rosy-cell-application.md), [D-403](D-403-fleet-cell-job-route-cell-transfer.md), [D-404](D-404-omx-setup-teaching-api-simulation-first.md)
