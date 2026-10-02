# Rosy Cell C3 — Gazebo 단일 pick/place와 도달 범위 실측

**부모 계획:** [Rosy Cell 완성 계획](2026-10-01-rosy-cell-completion.md) C3. **결정 근거:** [D-402](../adr/D-402-omx-motion-planner-v1-analytic-top-down-ik.md)(동작 모양·보호하지 않는 것·프로필), [D-403](../adr/D-403-fleet-cell-job-route-cell-transfer.md) §5 `sim_model_pose`, §8 owner 프로세스 하나, [D-390](../adr/D-390-pilot-omx-simulation-practice-boundary.md).

**범위:** ROS-SIM 한 번. Fleet 경로(C4), Rosy Cell 서버(C5), 종단 수용(C6)은 포함하지 않는다. 실물 OMX, DEVICE, FIELD 판정은 하지 않는다.

## 목표

1. C2 해석 IK 플래너가 데모 셀의 **모든 Job Step**을 거절 없이 계획하는 배치를 호스트에서 찾는다(도달 고리 실측).
2. 같은 배치를 Gazebo 월드로 옮기고, 블록 하나를 정식 owner 경로로 옮긴다:
   `CellTransferPlanProvider` → `PickPlaceRunner` → `ArmCommandOwner` → `/arm_controller/follow_joint_trajectory`.
3. 그리퍼 readback(`gripper_contract`)과 블록 `sim_model_pose`로 결과를 판정하고 배치 오차를 잰다.

## 배치 결정

- 로봇 베이스(`link0`)는 Gazebo world 원점이다. vendor launch가 `-x 0 -y 0 -z 0`으로 spawn하고 URDF `world_fixed`가 항등이므로 **world = robot_base**다. 월드 파일에 이 변환을 적는다.
- 작업대 윗면은 z = 0(베이스 바닥면)이다.
- 데모 셀은 `cell.yaml`(schema `rosy_cell.cell/2`, `home`, 프로필과 같은 `kinematics_revision`)과 `recipe.yaml`로 `src/site/cell/examples/omx_sim/`에 둔다.
- 박스는 OMX-F 그리퍼(URDF finger mesh에서 잰 개구폭, 패드 폭) 안에 들어가는 ≤ 50 g 폼 블록으로 정한다. 2 팔레트 × 2층이 도달 고리에 맞지 않으면 박스 수·크기를 줄이고 이유를 적는다.
- Step 포즈는 `rosy_cell`이 정한 대로 "물건 윗면 TCP"다. 손가락 파지에 필요한 깊이 보정이 있다면 probe가 명시적으로 적용하고 C4 과제로 남긴다.

## 단계

1. 이 하위 계획(커밋).
2. 호스트 도달 실측 스크립트와 데모 `cell.yaml`/`recipe.yaml`. 시험: 모든 Step이 `AnalyticCellTransferPlanner`로 계획됨(omx_adapter 시험이 YAML을 경로로 읽는다. `rosy_cell` 의존이 선언되지 않았으면 import하지 않는다). 커밋.
3. Gazebo 월드 `src/sim/gz_sim/worlds/omx_cell_workcell.sdf`(작업대, 팔레트 2, 인피드 블록 1, 슬립시트 스테이션). 위치는 데모 셀과 같다. 커밋.
4. `deploy/robot/omx/probe_cell_transfer.py`: 한 프로세스 = owner 하나. 프로필로 `ArmCommandConfig`를 만들고, home 이동 → CELL_TRANSFER(인피드 → 팔레트 A 층 0 슬롯 0) → 블록 포즈 전후 측정. `pilot_sim_server`는 같이 띄우지 않는다. 마찰 파지를 먼저 시도한다. 실패하면 측정하고, 보조(DetachableJoint)는 명시 표지한 sim aid로만 쓴다. 커밋.
5. Gazebo 실행(기존 `rosy-omx-pilot:local` 이미지, 재빌드 없음, 컨테이너 `rosy-cell-c3-*`, `ROS_DOMAIN_ID=77`, 포트 publish 없음). 증거 `docs/validation/rosy-cell-gazebo-c3-2026-10-02/README.md`. 커밋.
6. 기록: omx_adapter·cell `progress.md`/`logs.md`, harness generate, lint 0, adapter·cell 시험, known_failures, architecture 시험. 커밋.

## 증거 목록

- 명령, 이미지 태그·ID, 월드 sha256, `profile_revision`, `kinematics_revision`, cell/recipe 해시
- 단계별 시간(phase별 계획 시간과 실측 wall/sim 시간)
- 그리퍼 readback 값(열림·닫힘·물체 위 정지 각도, mimic 오차)
- 블록 `sim_model_pose` 전후, 배치 오차(xy, yaw, z)
- sim aid 사용 여부와 이유
- 실행 중 발견한 플래너/owner 문제와 근거

## 판정 경계

ROS-SIM C3만 주장한다. C6 종단 수용, Fleet 경로, 실물 한계는 주장하지 않는다.
