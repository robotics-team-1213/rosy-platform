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
C1 ADR 세트 ─┬─ C2 OMX 해석 IK 플래너(SOURCE) ── C3 Gazebo 단일 pick/place(ROS-SIM) ─┐
             ├─ C4 Fleet↔OMX Cell 경로(SOURCE→ROS-SIM) ─────────────────────────────┼─ C6 종단 수용
             └─ C5 Rosy Cell 서버·UI(SOURCE, 브라우저) ─────────────────────────────┘
```

### C1. ADR 세트 (Proposed, D-402·D-403·D-404)

1. **OMX 모션 플래너 v1** (D-376 개정) → [D-402](../adr/D-402-omx-motion-planner-v1-analytic-top-down-ik.md). 기존 phase 타입은 재사용하고 포즈 입력 변형 `CellTransferPlanProvider`/`CellTransferPlan`을 둔다.
   - 플래너는 장치 로컬이다. 입력은 base-frame TCP 포즈(x, y, z, yaw, 수직하향)와 `approach_z`이고, 출력은 4단계 관절 궤적(approach, grasp, transfer, release)이다.
   - 기하는 고정된 `open_manipulator` URDF 값에서 온다(D-397 규칙).
   - 도달성 검사(관절 한계, 작업 영역)를 둔다. 충돌 장면은 없고, 안전은 `approach_z` 경유와 작업 영역 경계로 확보한다.
   - 제출은 계속 owner만 한다. MoveIt은 같은 Protocol의 후속 구현이다.
2. **Fleet Cell Job 경로** → [D-403](../adr/D-403-fleet-cell-job-route-cell-transfer.md)
   - 새 Action 종류는 `CELL_TRANSFER`로 확정했다. 내용은 pick 포즈, place 포즈, `approach_z`, item, job/recipe/cell 해시다.
   - Rosy Cell은 Job을 Fleet 제안으로 제출한다. Fleet이 Step으로 풀어 승인하고 하달한다.
   - 하달기는 `simulation` 프로필에서만 켠다. D-330 §2의 개방 조건은 ROS-SIM 정지 세대 시험이고, D-336 UDS와 같은 호스트 조건은 유지한다.
3. **OMX 셋업·티칭 API (시뮬 우선)** → [D-404](../adr/D-404-omx-setup-teaching-api-simulation-first.md)
   - 티칭은 D-390 `pilot_sim_api`의 seat와 jog를 쓰고, 여기에 읽기 전용 TCP(FK) 조회를 더한다.
   - Rosy Cell 마법사는 팔로워 FK 포즈를 포인트로 저장한다. 실물 장치 API는 닫힌 채로 둔다(D-282 §5).
- 게이트: 독립 리뷰 approve, lint 0. 세 ADR을 한 브랜치에서 리뷰받고 main에 넣는다.

### C2. OMX 해석 IK 플래너 (SOURCE)
- 위치: `src/products/omx/adapter/omx_adapter/`. 새 모듈은 `kinematics.py`(FK/IK)와 `pose_plan.py`(`PickPlacePlanProvider` 구현)다.
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

### C4. Fleet↔OMX Cell 경로
- grant 스키마에 Cell Action 종류를 추가하고, Fleet 제안 resolver가 Job을 Step으로 푼다.
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

### C6. 종단 수용 (ROS-SIM)
- 레시피 2층, 슬립시트, 팔레트 2개를 정식 경로로 끝까지 실행한다.
- 증거 bundle에 남길 것: 레시피·셀 해시, Fleet 원장, OMX phase 기록, 그리퍼 readback, 카메라 영상, 최종 블록 위치 오차.

## 운영 규칙

- 단계마다 `rosy-land-on-main` 절차를 따른다. 각 단계는 자기 worktree를 쓰고, 정확한 경로만 `git add`하며, ADR 번호는 쓰기 직전에 다시 확인한다.
- 단계마다 구현 → 스펙 리뷰 → 품질 리뷰 → 로컬 main 병합 순서로 진행한다. push는 하지 않는다.
- OMX·Fleet 코드를 만지는 단계(C2–C4)는 시작 전에 `ListAgents`로 같은 영역을 만지는 세션이 있는지 확인한다.
- Gazebo 실행은 WSL Ubuntu와 Docker 이미지 `rosy-omx-workstation`을 쓴다. 이미지 재빌드가 필요하면 사용자에게 먼저 알린다.
