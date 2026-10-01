# Rosy Cell 완성 계획 (C1–C6)

**범위:** [D-401](../adr/D-401-rosy-cell-application.md) Rosy Cell을 **Gazebo OMX-F 종단 수용**까지 완성하는 부모 계획이다. 이 계획은 [로드맵](2026-10-01-rosy-layered-architecture-roadmap.md)의 P1·P3·P4·P5를 Rosy Cell 쪽으로 좁힌 실행판이다. 하위 단계마다 자기 계획(TDD 단계)을 쓰고, 독립 리뷰를 거친 뒤 로컬 main에 넣는다. 실물 OMX, DEVICE, FIELD, LeRobot 정책 스킬(P7), 장치 Fault 계약(P6)은 범위 밖이다.

**최종 수용:** Gazebo에서 OMX-F가 Rosy Cell 레시피(2층, 슬립시트 1장, 팔레트 2개)를 정식 경로로 끝까지 실행한다. 정식 경로는 Rosy Cell → Fleet 제안·승인 → Mission 하달기 → UDS → OMX owner다. 증거는 `docs/validation/rosy-cell-gazebo-<date>/`에 둔다.

## 사용자 결정 (2026-10-01)

| 항목 | 결정 |
|---|---|
| IK | **해석 IK 먼저.** 5축 수직하향 IK를 Python으로 구현하고 URDF 치수를 쓴다. MoveIt 2는 같은 플래너 인터페이스의 두 번째 구현으로 나중에 붙인다. |
| 실행 경로 | **정식 Fleet 경로.** D-330 §2의 Mission 하달 보류는 시뮬레이션 범위에서만 연다. 여는 조건은 정지 세대 producer/consumer 시험이다. D-336의 같은 호스트 UDS는 유지한다. |

## 현재 상태 (main `dcad279d`, 2026-10-01 조사)

- `rosy_cell` 코어: SOURCE GO(123 passed). Job = base-frame `Pose` Step 목록.
- OMX 명령 경로:
  - 관절공간뿐이다(`TrajectoryCommand`).
  - `PickPlacePlanProvider`는 Protocol만 있고 구현이 없다. IK/FK 코드는 `src` 어디에도 없다.
  - `UnixActionServer`/`LocalActionPort`의 운영 연결이 없다. 테스트에서만 생성된다.
- Fleet:
  - `mission_dispatcher.py`가 있지만 기본으로 꺼져 있다(`enable_mission_dispatcher=False`).
  - `FleetActionGrant`는 RGB-D 증거 기반 `PICK_PLACE`만 받는다. 포즈 기반 Step을 실을 종류가 없다.
- Gazebo:
  - `deploy/robot/omx/` Docker 이미지(`open_manipulator` 5.1.2 고정)와 `run_pilot_sim.sh`, `omx_pilot_workcell` 월드가 있다.
  - D-390 `pilot_sim_api`로 관절 jog가 검증됐다.
  - 그리퍼는 목표에서 약 0.011 rad 어긋난다(mimic).

## 하위 단계

```text
C1 ADR 세트 ── C2a rosy_cell cell/2 + carry_z ─┬─ C2 OMX 해석 IK 플래너(SOURCE) ── C3 Gazebo 단일 pick/place(ROS-SIM) ─┐
                                               ├─ C4 Fleet↔OMX Cell 경로(SOURCE→ROS-SIM) ─────────────────────────────┼─ C6 종단 수용
                                               └─ C5 Rosy Cell 서버·UI(SOURCE, 브라우저) ─────────────────────────────┘
```

### C1. ADR 세트 (Proposed, D-402·D-403·D-404)

1. **OMX 모션 플래너 v1** (D-376 개정) → [D-402](../adr/D-402-omx-motion-planner-v1-analytic-top-down-ik.md). 기존 phase 타입은 재사용하고 포즈 입력 변형 `CellTransferPlanProvider`/`CellTransferPlan`을 둔다.
   - 플래너는 장치 로컬이다.
     - 입력: base-frame `home`·pick·place 포즈(x, y, z, yaw, 공구 축 = −z_base), `approach_z`, `carry_z`
     - 출력: 4단계 관절 궤적(approach, grasp, transfer, release)
     - 수평 이동은 항상 상승 → `carry_z` → 하강이다.
   - 기하는 고정된 `open_manipulator` URDF 값에서 온다(D-397 규칙). 한계·시간은 `deploy/robot/omx/sim/cell_profile.yaml`에서 온다. URDF ±2π는 보호가 아니고, 실제 OMX-F 한계를 고정하기 전까지 보호는 명목상이다.
   - 충돌 장면이 없다. 이미 놓인 박스·같은 높이 이웃·들고 있는 박스·낮게 지나가는 링크는 **보호하지 않는다**. 그래서 시뮬레이션 전용이다.
   - 제출은 계속 owner만 한다. `CELL_TRANSFER`는 phase runner로만 실행한다. MoveIt은 같은 Protocol의 후속 구현이다.
2. **Fleet Cell Job 경로** → [D-403](../adr/D-403-fleet-cell-job-route-cell-transfer.md)
   - 새 Action 종류는 `CELL_TRANSFER`로 확정했다. 내용은 다음과 같다: `home`·pick·place 포즈, `approach_z`, `carry_z`, item, job/recipe/cell 해시, step index.
   - Rosy Cell은 자기 서비스 principal로 Job을 Fleet 제안으로 제출한다. Fleet이 재컴파일해 Step으로 풀고, 이름 있는 사람 운영자가 승인하면 하달한다. 목표 증거는 `sim_model_pose`와 그리퍼 readback이다.
   - 하달기는 `simulation` 프로필에서만 켠다. D-330 §2의 개방 조건은 ROS-SIM 정지 세대 시험이고, D-336 UDS와 같은 호스트 조건은 유지한다.
3. **OMX 셋업·티칭 API (시뮬 우선)** → [D-404](../adr/D-404-omx-setup-teaching-api-simulation-first.md)
   - 티칭은 D-390 `pilot_sim_api`의 seat와 jog를 쓰고, 여기에 읽기 전용 TCP(FK) 조회를 더한다.
   - Rosy Cell 마법사는 팔로워 FK 포즈를 포인트로 저장한다. 실물 장치 API는 닫힌 채로 둔다(D-282 §5).
- 게이트: 독립 리뷰 approve, lint 0. 세 ADR을 한 브랜치에서 리뷰받고 main에 넣는다.

### C2a. `rosy_cell` cell/2와 carry_z (SOURCE, C2 안에서 가장 먼저)
- `rosy_cell.cell/2` 로더를 만든다.
  - 필수 값: `home` 포즈(수직하향), `kinematics_revision`(D-404 §5).
  - `/1`은 실행용으로 받지 않는다.
- `rosy_cell.compiler.carry_z(recipe, cell)` 함수 하나를 만든다.
  - 값: Job 전체에서 가장 높은 적재물·팔레트·스테이션 윗면 + 박스 높이 + `approach_clearance_m`.
  - Fleet(C4)은 이 함수를 호출하고, 계산을 다시 구현하지 않는다(D-402 §6, D-403 §2).
- 시험:
  - `/2` 필수 필드 누락 거절
  - `carry_z` 손 계산 재현
  - 해시가 `home`·`kinematics_revision`에 반응함

### C2. OMX 해석 IK 플래너 (SOURCE)
- `deploy/robot/omx/sim/cell_profile.yaml`(schema `rosy.omx-sim-cell-profile.v1`)을 만든다. 담는 값:
  - 보수적인 명시 관절 위치·속도·가속도 한계
  - phase별 최대 시간
  - 그리퍼 열림·닫힘 목표
  - 작업 영역, Cartesian 간격, 특이점 반경
  - 실제 OMX-F 한계를 고정하기 전까지 보호는 명목상이다(D-402 §4).
- 위치: `src/products/omx/adapter/omx_adapter/`.
  - 새 모듈은 `kinematics.py`(FK/IK)와 `pose_plan.py`다.
  - `pose_plan.py`는 `CellTransferPlanProvider`와 `CellTransferPlan`을 구현하고, `CellPlanningProfile`이 `deploy/robot/omx/sim/cell_profile.yaml`을 읽는다.
  - 기존 `PickPlacePlanProvider`는 RGB-D 전용으로 그대로 둔다.
- 같은 단계의 코드 변경(D-402 §3):
  - `action_runner.py`의 phase runner 분기를 `CELL_TRANSFER`까지 넓힌다.
  - 직접 제출은 모르는 종류를 거절한다.
  - `pick_place_runner.py`가 `CellTransferPlan`을 받고, start-state 검사에서 그리퍼 관절을 제외한다.
- URDF 치수는 고정 버전의 xacro에서 추출한 값을 시험 고정값으로 둔다. 고정 버전이 바뀌면 드리프트 시험이 깨진다.
- 시험:
  - FK∘IK 왕복
  - 관절 한계 거부
  - 작업 영역 밖 거부
  - yaw → wrist_roll 매핑
  - 4단계 궤적 형태

### C3. Gazebo 단일 pick/place (ROS-SIM)
- `omx_pilot_workcell` 월드에 팔레트, 블록 스테이션, 슬립시트 스테이션을 추가한다.
- C2 플래너 → owner → `/arm_controller` 경로로 블록 하나를 옮긴다. 그리퍼 readback은 `gripper_contract`를 따른다.
- 그리퍼가 0.011 rad 어긋나는 영향을 측정한다. 폼 블록 파지가 성공하는지 본다.
- **도달 범위 실측.**
  - 추정값: 작업대 높이에서 joint2 축으로부터 반경 약 0.28 m 이하의 고리다. 근거는 L1 ≈ 0.1205, L2 = 0.162 m, 손목이 TCP 위 약 0.12 m라는 점이다.
  - 팔레트 2개, 2층, 스테이션이 이 고리 안에 들어가는지 Gazebo에서 측정한다.
  - 들어가지 않으면 데모 배치(팔레트·박스 크기, 층수)를 줄인다.

### C4. Fleet↔OMX Cell 경로 (C2a 이후)
- grant 스키마에 Cell Action 종류를 추가하고, Fleet 제안 resolver가 Job을 Step으로 푼다.
  - 재컴파일은 C2a의 `cell/2` 로더와 `rosy_cell.compiler.carry_z`를 그대로 호출한다.
- 하달기를 `simulation` 프로필에서 켠다.
- OMX 쪽 `UnixActionServer` + `LocalActionPort` 운영 연결이 `PickPlaceRunner`를 C2 플래너로 구동하게 한다.
- 정지 세대 producer/consumer 시험을 만든다. D-330 §2의 개방 조건이다.

### C5. Rosy Cell 서버·UI
- `rosy_cell` 안에 FastAPI 서버를 둔다. Fleet의 정적 자산 allowlist, CSP, `/common` 패턴을 따르고, `surfaces.yaml`에 등록한다(D-329).
- 화면:
  - 셋업 마법사: 셀 연결 → 프레임 3점 티칭(jog + FK 저장) → 스테이션 → 공통 포즈
  - 레시피 편집기: 2D 층 미리보기, 검증 결과
  - 실행: Fleet 제안 제출, 진행·HOLD 표시
- Step 순서는 Rosy Cell 서버가 정하지 않는다. 순서와 하달은 Fleet이 한다(D-12).
- 마법사에 `home` 티칭 단계를 둔다. 저장은 C2a의 `cell/2` 형식으로 한다(schema 변경은 C2a 몫).
- seat 갱신은 브라우저 생존 신호가 있을 때만 한다(D-404 §3).

### C6. 종단 수용 (ROS-SIM)
- 레시피 2층, 슬립시트, 팔레트 2개를 정식 경로로 끝까지 실행한다. 배치는 C3에서 실측한 도달 고리(약 ≤ 0.28 m) 안에 맞춘다. 맞지 않아 데모 배치를 줄였으면 줄인 배치로 수용하고 그 사실을 증거에 적는다.
- 증거 bundle에 남길 것: 레시피·셀 해시, Fleet 원장, OMX phase 기록, 그리퍼 readback, 카메라 영상, 최종 블록 위치 오차.

## 운영 규칙

- 단계마다 `rosy-land-on-main` 절차를 따른다. 각 단계는 자기 worktree를 쓰고, 정확한 경로만 `git add`하며, ADR 번호는 쓰기 직전에 다시 확인한다.
- 단계마다 구현 → 스펙 리뷰 → 품질 리뷰 → 로컬 main 병합 순서로 진행한다. push는 하지 않는다.
- OMX·Fleet 코드를 만지는 단계(C2–C4)는 시작 전에 `ListAgents`로 같은 영역을 만지는 세션이 있는지 확인한다.
- Gazebo 실행은 WSL Ubuntu와 Docker 이미지 `rosy-omx-workstation`을 쓴다. 이미지 재빌드가 필요하면 사용자에게 먼저 알린다.
