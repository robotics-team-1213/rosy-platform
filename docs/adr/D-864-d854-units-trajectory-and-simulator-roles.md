## D-864 D-854 보완 — 공통 행동 단위 `ros_joint_rad`, 목표 묶음은 궤적 하나, Isaac은 학습 데이터·Gazebo는 실행 확인

**Status:** Proposed (2026-10-24). D-854를 대체하지 않고 §3·§5와 구현 순서를 보완한다. 사용자는 SIM rad 데이터셋을 변환하지 않기로 했고(2026-10-24), 보완 방향과 Isaac Sim 활용 검토를 지시했다. 이 ADR은 실물 실행 관문(D-793, G4), AI PC 현장 경로, owner의 안전 검사를 열거나 바꾸지 않는다. 3b 구현과 관측 나이 한계 값은 별도 승인 대상이다.

**관련:** D-854 · D-858 · D-800 · D-794 · D-434(모델 PC) · D-795(PC 간 DDS 금지) · D-322(Isaac Sim 연동) · D-516

### Context

- D-854 1~4단계 구현과 5단계 1차 실측이 끝났다(`docs/validation/policy-latency-smolvla-2026-10-24/`).
- SmolVLA 기본 모델을 한 걸음마다 동기 추론하면 종단 p99가 208ms다(CORE와 망 제외). `act_job.py`가 만드는 설치 정책은 주기 100ms, 관측·행동 나이 한계 50ms라서 이 방식으로는 실행할 수 없다.
- D-854 §3은 목표 K개를 관측 하나에 묶어 하나씩 승인하는 방식이었다. 그런데 owner는 목표마다 **관측 당시 관절 자세**를 시작 자세로 검사한다(`TrajectoryCommand.expected_start_state_positions`). 그래서 두 번째 목표부터는 팔이 이미 움직여 항상 거부된다. 이 검사를 풀면 안전 의미가 약해진다.
- 실물 native 데이터(lerobot 정규화 값)를 CORE의 ROS 관절 rad로 바꾸려면 ROS 관절 ↔ Dynamixel 모터 대응이 필요하다. 저장소가 고정한 ROBOTIS 공식 스택(`deploy/robot/omx/stack.lock.yaml`: `open_manipulator` `0a4af6a9`, `dynamixel_hardware_interface` `3375b3d0`)을 읽은 결과는 다음과 같다.
  - `omx_f.ros2_control.xacro`에는 변환 행렬이 없어서 드라이버가 단위 행렬을 쓴다(드라이버 소스의 기본값).
  - 모든 모터의 Drive Mode는 4다. 방향 반전 비트(bit0)는 꺼져 있다.
  - `gripper_joint_1`은 회전 관절이다.
  - 모터 ID 11~16이 `joint1..5`, `gripper_joint_1` 순서이고, 이는 `omx_follower` 모터 순서와 같다.
- 모델 PC에는 Isaac Sim 5.1이 있다(D-434). 저장소의 Isaac 경로는 공식 OMX-F URDF를 USD로 가져와 관절 이름을 검사하는 데까지다(`learning/envs/isaac/import_omx.py`). 카메라, 작업 장면, 팔 제어 ROS 연결, 데이터 수집은 없다. Gazebo에는 OMX 장면, top·front 카메라, ROS owner, CORE·Fleet lease 연결, 교사 시연 수집이 있다.

### Decision

#### 1. 공통 행동 단위는 `ros_joint_rad`다

- Gazebo, Isaac Sim, 실물 ROS 경로의 정책 입출력 단위는 ROS 관절 rad(`joint1..5`, `gripper_joint_1`)다. CORE 정책 계약과 실행기 대상이 이미 이 단위를 쓴다.
- `lerobot_norm_v1`은 리더 native 녹화의 원본 단위로 남는다. 학습 전에 `ros_joint_rad`로 바꾼다.
- D-854 §5의 "정본 단위 `lerobot_norm_v1`"은 이 결정으로 바뀐다. 데이터셋의 단위 선언 구조와 "선언 없으면 거부" 규칙은 그대로다. SIM rad 데이터셋은 이미 `ros_joint_rad`다.

#### 2. ROS 관절 ↔ 모터 대응은 공식 스택 가설로 두고, 읽기 전용 대조로 확인한다

- **가설:** 몸 관절의 homing offset이 0이고 드라이버 모델 파일의 0 rad 값이 2048이면, 각 관절의 `ros_joint_rad`는 같은 순서 모터의 `dynamixel_rad_v1`과 같다.
- **확인 방법:** 실물 팔에서 움직이지 않고 읽기만 한다. 같은 순간의 `/joint_states`와 모터별 Present Position·Homing Offset·Drive Mode를 몇 번 읽어 대조한다. 그리퍼는 `guarded_native`의 homing offset 검사 대상이 아니므로 따로 본다.
- **확인 뒤:** 결과가 오차 한계 안이면 `contracts/learning` `action_space`에 `ros_joint_rad` 단위와 변환기(버전 1)를 추가한다. 실행기의 `ActionSpace`는 이 변환만 연다. 확인 기록이 없으면 변환은 계속 거부한다.
- 결과가 다르면 관절별 부호·원점을 잰 대응표를 보정 해시와 함께 산출물로 두고 변환기에 넣는다.

#### 3. 목표 묶음은 여러 점을 가진 궤적 명령 하나로 보낸다 (D-854 §3 보완)

- 관측 하나에서 나온 chunk 전체를 owner의 궤적 명령 하나로 보낸다. 승인은 한 번 받는다.
- 시작 자세 검사는 지금 owner가 하는 그대로, 명령을 보내는 순간 한 번 한다. 모든 점은 관절 한계와 속도·가속 한계를 통과해야 한다. 정지하거나 lease가 끝나면 궤적 전체를 취소한다.
- 묶음의 유효 시간은 D-854 §4 식(`L_p99 + n_action_steps/fps`)으로 정한다. 그 값이 설치 정책의 관측 나이 한계보다 길면 그 정책은 실행할 수 없다.
- 한계를 얼마로 둘지는 사람이 정한다. 반정밀도·카메라 2대·GPU 단독 조건과 CORE·망 구간을 포함한 재측정 결과를 보고 정한다.
- 구현은 owner를 바꾸므로 safety 경로 독립 검토와 `Safety-Review` 서명을 거친다. 이 ADR은 방향만 정한다.

#### 4. 시뮬레이터 역할: Gazebo는 실행 확인, Isaac Sim은 학습 데이터

- **Gazebo:** CORE·owner·정지·lease를 실제와 같은 경로로 확인하는 실행 확인 환경이다. D-854 6단계(SmolVLA를 CORE에 연결하고 정지까지 확인)는 Gazebo에서 한다.
- **Isaac Sim (모델 PC):** VLA 학습 데이터 생산 환경으로 키운다. 사실적 렌더링, Replicator의 조명·질감·물체 위치 무작위화, Isaac Lab 병렬 환경을 쓴다.
  - Gazebo와 같은 공식 URDF, 관절 이름, 카메라 역할(D-794 top·front)과 크기, 작업 장면을 쓴다.
  - 출력은 LeRobot 데이터셋이고, 단위 선언은 `ros_joint_rad`다.
- **교차 평가:** 한 시뮬레이터 데이터로 학습한 정책은 다른 시뮬레이터에서도 평가해, 렌더러 하나에 과적합하지 않았는지 본다.
- **RL 미세조정:** 강화학습 미세조정(HIL-SERL 등)이 필요해지면 Isaac Lab에서 한다.
- **호스트 제약:** Isaac Sim은 모델 PC에서 돈다(D-434). Isaac에서 CORE까지 닫힌 실행을 하려면 같은 PC에 CORE를 둔다(D-795). 추론은 AI PC가 맡는다(D-854 §2).
- Isaac 데이터 생산 경로의 장면·카메라·수집기 설계는 별도 ADR로 정한다.

#### 5. 첫 VLA는 SIM 데이터로 끝까지 연결한다

순서는 다음과 같다.

1. Gazebo 교사 시연(`ros_joint_rad`)으로 SmolVLA를 미세조정한다. 모델 PC에서 하고, D-516 역할을 따른다.
2. AI PC 실행기 → CORE(SIM) → owner로 Gazebo에서 실행하고, 정지·lease 동작을 확인한다.
3. 실물 데이터는 §2 확인 뒤에 섞는다.

### Consequences

- 실행기의 단위 거부는 §2 확인 기록이 생길 때까지 유지된다. 그전에도 SIM 경로는 단위 변환 없이 끝까지 닫힌다.
- D-854 §3의 "목표마다 승인" 방식은 쓰지 않는다. 기본값(묶음 없음, 한 걸음씩)과 현재 ACT 동작은 바뀌지 않는다.
- 데이터셋 단위 선언에 `ros_joint_rad`가 추가된다. 기존 `lerobot_norm_v1` 선언 데이터는 변환을 거쳐야 학습에 쓴다.
- Isaac Sim 쪽 새 작업(장면, 카메라, 수집기)이 생긴다. Gazebo의 실행 확인 역할은 그대로다.

### 구현 순서

1. 읽기 전용 대응 확인 도구 작성. 실행은 사람이 작업대에 있을 때 한다.
2. 재측정: 반정밀도, 카메라 2대, GPU 단독, SIM CORE를 거친 종단 지연.
3. §2 확인 결과에 따라 `ros_joint_rad` 단위와 변환기 추가.
4. 3b 궤적 묶음 구현(owner, safety 검토).
5. D-854 6단계(Gazebo SmolVLA 실행)와 §5 SIM 미세조정.
6. Isaac 데이터 생산 경로 ADR과 구현.
