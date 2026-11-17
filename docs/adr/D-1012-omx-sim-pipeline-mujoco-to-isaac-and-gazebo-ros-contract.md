## D-1012 OMX 시뮬레이션·학습 파이프라인: Stage 1(MuJoCo) → Stage 2(Isaac Sim) 직렬 2단계와 Gazebo ROS 2 실행 계약 트랙 분리

**Status:** Accepted (2026-11-10, 사용자 확인: "무조코 이후에 아이삭 처리하는 것도 각각 역할로 해서 시뮬레이션을 더 심화 있게 하는 것도 구성해", "왜 무조코 다음이 가제보야?", "그럼 그걸 명확하게 기록해주고 adr에도 기록해"). 파이프라인 코드·핸드오프·호스트 시험까지다. 실물 팔 수용(D-911)은 별도다.

잇는 결정: [D-947](D-947-omx-palletizing-sim-models-and-claim-scope.md)(시뮬레이터 역할·주장 범위), [D-969](D-969-omx-two-arm-act-from-isaac-ik-demonstrations.md)(두 팔 ACT 정책), [D-866](D-866-vla-sim-primary-and-parallel-gpu-hosts.md)(ROS 백엔드 실행 계약), [D-872](../reference/ROSY%20ADR%20Log.md)(Isaac 셀 케이스 재생), [D-911](D-911-omx-native-reviewed-operating-envelope.md)(실물 작업 범위).

### Context

1. **기존 `omx_ladder.py`·`omx_two_arm_policy.py`의 단계 표기가 물리·학습 순서와 섞여 있었다.**
   - 기존 라운드 기록(`round.json`)은 `stages`에 `mujoco`, `gazebo`, `isaac`을 나란히 두고 `isaac`에는 `"단일 팔 Isaac 케이스가 아직 없습니다. v13 작업 뒤에 연결합니다."`라는 해묵은 사유를 하드코딩해 두었다.
   - 이 때문에 마치 학습·시뮬레이션이 `MuJoCo → Gazebo → Isaac` 순서로 흐르는 것처럼 보였으나, 실제로 `Gazebo`에는 OMX 적층 접촉·카메라 학습 모델이 없다(D-947 1항: "Gazebo에는 적층 접촉·카메라 모델을 새로 만들지 않는다").
2. **다색·비정렬(틀어진) 컨테이너 비전 피킹 및 3단 적층 시나리오가 추가되었다(2026-11-10).**
   - 벨트 위 컨테이너가 정사각형이 아닌 직육면체(`90×30×30 mm`)이고 위치(`dx, dy`)나 각도(`dyaw`)가 조금씩 틀어져 들어오며 색상(`orange`, `green`, `red`, `purple`)이 다양할 때, Stage 1(MuJoCo)에서 상단 카메라 색 분할·주축 각도 추정에 측벽 투영 보정을 더해 3단 9스텝(`stack`) 피킹·적층을 검증했다.
   - 이어서 그 파지 오프셋·비전 추정 결과·최종 안착 오차를 Stage 2(Isaac Sim)의 PhysX 그리퍼 패드 슬립·스터드/포켓 안착 시험(`arm-s-cell-case` / `omx-map-container-stack`)으로 바로 넘기는 핸드오프(`rosy.omx-isaac-handoff.v1`)가 필요하다.

### Decision

OMX 적층·파지 시뮬레이션과 정책 학습 파이프라인은 **직렬 2단계 학습·물리 트랙(`Stage 1: MuJoCo → Stage 2: Isaac Sim`)**과 **별도 ROS 2 실행 계약 점검 트랙(`Gazebo`)**으로 명확히 분리한다.

1. **직렬 학습·물리 파이프라인 (`track: "learning_and_physics"`): `Stage 1 (MuJoCo) → Stage 2 (Isaac Sim)`**

   | 단계 | 시뮬레이터 | 역할 (`role`) | 입력·산출물과 주장 범위 |
   |---|---|---|---|
   | **Stage 1** (`stage_order: 1`) | **MuJoCo** | `stage1_geometry_vision_and_act_policy` | **기하·비전·정책 학습 주력:** 두 팔 도달성·충돌·동시 이동 스케줄(`omx_two_arm_plan.py`), 4카메라(`top`, `front`, `arm_a`, `arm_b`) 다색·비정렬 컨테이너 비전 추정(`--pick-vision --belt-skew`), ACT 시연 수집·학습·1차 평가(`omx_two_arm_policy.py`), 그리고 Stage 2로 넘길 케이스 명세(`isaac-handoff.json`, `rosy.omx-isaac-handoff.v1`) 생성. 접촉 성공률을 주장하지 않는다(D-947). |
   | **Stage 2** (`stage_order: 2`) | **Isaac Sim** | `stage2_physx_contact_pad_slip_and_seating` | **PhysX 접촉·패드 슬립·안착 심화 확증:** Stage 1(MuJoCo)을 통과한 파지 오프셋·비전 추정 오차·적층 목표(`from_mujoco_handoff` / `skew_vision_cases`)를 그대로 받아 조 v2.1 패드 마찰·미끄럼, 배 판 돌기 및 2·3단 상자 위 안착, 표면 조명·노이즈 하의 접촉 결과를 판정(`cell_case_suite.py`, `judge_isaac_stage`). |

2. **별도 ROS 2 실행 계약 점검 트랙 (`track: "ros2_execution_contract"`, `stage_order: null`): `Gazebo`**
   - `Gazebo`는 MuJoCo와 Isaac Sim 사이에 끼는 물리·학습 단계가 아니다.
   - `omx_backend_conformance.py`(`judge_gazebo_contract`)를 통해 ROS 2 실행 인터페이스 계약(D-866 §2: `/joint_states` ≥ 20 Hz 및 관절 순서 불변, 카메라 토픽 프레임 규격·주기, `/clock` 단조 증가, 미접촉 물체 드리프트 ≤ 5 mm, `FollowJointTrajectory` 취소 시 정지 이동량 ≤ 0.005 rad)을 독립적으로 검증하는 **미들웨어·제어기 통신 적합성 트랙**으로만 기록한다.

3. **라운드·실행 기록(`round.json`, `run.json`)의 표현 규칙**
   - `tools/sim/omx_ladder.py`와 `tools/sim/omx_two_arm_policy.py`의 `stages` 블록은 항상 `mujoco`(Stage 1) → `isaac`(Stage 2)을 먼저 배치하고, 각 단계에 `stage_order`(`1`, `2`, `None`)와 `track`(`"learning_and_physics"` vs `"ros2_execution_contract"`)을 명시한다.
   - MuJoCo 비전·틀어짐 실행(`--pick-vision`, `--belt-skew`)과 ACT 정책 평가(`run_round`)는 자동으로 `isaac-handoff.json`을 생성해 Stage 2 Isaac Sim(`deploy/robot/omx/cell_cases.py --mujoco-handoff`)으로 연결한다.

### 검증

- 호스트·원격 시험:
  - `test/test_omx_cell_cases.py`: MuJoCo 핸드오프(`rosy.omx-isaac-handoff.v1`) 및 비정렬 다색 피킹 케이스의 Isaac Sim `arm-s-cell-case` 변환 검증.
  - `test/test_omx_ladder.py`, `test/test_omx_two_arm_policy.py`: `Stage 1 (MuJoCo) → Stage 2 (Isaac Sim)` 직렬 순서(`stage_order: 1, 2`)와 별도 `Gazebo` ROS 2 실행 계약 트랙(`track: "ros2_execution_contract"`) 판정 검증.
  - 원격 MuJoCo 실행(`model-pc`): `stack --pick-vision --belt-skew --choice container_colours=multi` 3단 9/9 통과 및 `isaac-handoff.json` 산출 확인.
