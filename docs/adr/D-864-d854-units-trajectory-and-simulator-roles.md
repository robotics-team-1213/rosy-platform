## D-864 D-854 보완 — 공통 행동 단위 `ros_joint_rad`, 목표 묶음은 궤적 하나, Isaac은 학습 데이터·Gazebo는 실행 확인

**Status:** Proposed (2026-10-24). D-854를 대체하지 않고 §3·§5와 구현 순서를 보완한다. 사용자는 SIM rad 데이터셋을 변환하지 않기로 했고(2026-10-24), 보완 방향과 Isaac Sim 활용 검토를 지시했다. 이 ADR은 실물 실행 관문(D-793, G4), AI PC 현장 경로, owner의 안전 검사를 열거나 바꾸지 않는다. 3b 구현과 관측 나이 한계 값은 별도 승인 대상이다.

**관련:** D-854 · D-858 · D-800 · D-794 · D-434(모델 PC) · D-795(PC 간 DDS 금지) · D-322(Isaac Sim 연동) · D-516

### Context

- D-854 1~4단계 구현과 5단계 1차 실측이 끝났다. 실측 기록 `docs/validation/policy-latency-smolvla-2026-10-24/`는 실행기 브랜치 `feat/omx-policy-runner`와 함께 착지한다.
- SmolVLA 기본 모델을 한 걸음마다 동기 추론하면 종단 p99가 208ms다. 이 값은 CORE와 망을 제외한 1회 측정이고, 카메라 3대 합성 프레임으로 다른 작업과 GPU를 같이 쓰는 조건이었다. `act_job.py`가 만드는 설치 정책은 주기 100ms, 관측·행동 나이 한계 50ms라서 이 방식으로는 실행할 수 없다.
- D-854 §3은 목표 K개를 관측 하나에 묶어 하나씩 승인하는 방식이었다. 그런데 owner는 목표마다 **관측 당시 관절 자세**를 시작 자세로 검사한다(`TrajectoryCommand.expected_start_state_positions`). 그래서 두 번째 목표부터는 팔이 이미 움직여 항상 거부된다. 이 검사를 풀면 안전 의미가 약해진다.
- 실물 native 데이터(lerobot 정규화 값)를 CORE의 ROS 관절 rad로 바꾸려면 ROS 관절 ↔ Dynamixel 모터 대응이 필요하다. 저장소가 고정한 ROBOTIS 공식 스택(`deploy/robot/omx/stack.lock.yaml`: `open_manipulator` `0a4af6a9`, `dynamixel_hardware_interface` `3375b3d0`)의 소스를 읽은 결과는 다음과 같다.
  - `omx_f.ros2_control.xacro`에는 변환 행렬이 없어서 드라이버가 단위 행렬을 쓴다(드라이버 소스의 기본값). 위치는 XL330·XL430 모델 파일의 단위(약 0.00153398 rad/tick, 오프셋 −π)로 바꾸므로 2048이 0 rad다.
  - 모든 모터의 Drive Mode는 4다. 방향 반전 비트(bit0)는 꺼져 있다.
  - `gripper_joint_1`은 회전 관절이다.
  - 모터 ID 11~16이 `joint1..5`, `gripper_joint_1` 순서이고, 이는 `omx_follower` 모터 순서와 같다.
  - 이 드라이버는 시작할 때 모터 EEPROM(Operating Mode, Drive Mode, 위치 한계, 게인)을 쓰고, 활성화할 때 토크를 켠다. 그 뒤 몸 관절 12~15는 Operating Mode 3으로 남는데, native 경로(`guarded_native.py`)는 모드 4를 요구한다. 그래서 실물 확인에 이 드라이버를 쓰지 않는다.
- 모델 PC에는 Isaac Sim 5.1이 있다(D-434). 저장소의 Isaac 경로는 OMX에 대해서는 공식 OMX-F URDF를 USD로 가져와 관절 이름을 검사하는 데까지다(`learning/envs/isaac/import_omx.py`). Pinky에는 별도의 ROS 그래프가 있다(`run_rosy.py`). 카메라, 작업 장면, 팔 제어 ROS 연결, 데이터 수집은 없다. Gazebo에는 OMX 장면, top·front 카메라, ROS owner, CORE·Fleet lease 연결, 교사 시연 수집이 있다.

**정정 (2026-10-25):** 위 문단의 "top·front 카메라"는 틀렸다. 설치된 Gazebo world의 카메라는 작업대 카메라 1대(`workcell_camera`)다. D-866 P0 시험(`policy_chain_vla_gazebo.py`)이 이 카메라를 복제해 top 카메라를 덧붙이고 두 대로 실행한다.

### Decision

#### 1. 공통 행동 단위는 `ros_joint_rad`다

- Gazebo, Isaac Sim, 실물 ROS 경로의 정책 입출력 단위는 ROS 관절 rad(`joint1..5`, `gripper_joint_1`)다. CORE 정책 계약과 실행기 대상이 이미 이 단위를 쓴다.
- `lerobot_norm_v1`은 리더 native 녹화의 원본 단위로 남는다. 학습 전에 `ros_joint_rad`로 바꾼다.
- D-854 §5의 "정본 단위 `lerobot_norm_v1`"과 "기존 rad 데이터셋은 `dynamixel_rad_v1 → lerobot_norm_v1` 변환기로 새 데이터셋을 만든다"는 이 결정으로 대체된다. 데이터셋의 단위 선언 구조와 "선언 없으면 거부" 규칙은 그대로다.
- SIM rad 데이터셋은 ROS 관절 rad이므로 `ros_joint_rad`로 선언한다. `dynamixel_rad_v1`로 선언하지 않는다. `ros_joint_rad`는 아직 `action_space.UNITS`에 없고, §2 확인 뒤에 추가한다.

#### 2. ROS 관절 ↔ 모터 대응은 공식 스택 가설로 두고, 모터 레지스터만 읽어 확인한다

- **가설:** 몸 관절과 그리퍼 모터의 homing offset이 0이고 Drive Mode 반전 비트가 꺼져 있으면, 각 관절의 `ros_joint_rad`는 같은 순서 모터의 `dynamixel_rad_v1`과 같다. 드라이버 쪽 변환(단위 행렬, 모델 파일 단위)은 소스로 확인했으므로 실물에서 다시 재지 않는다.
- **확인 방법:** 드라이버를 띄우지 않고, 쉬는 자세의 팔에서 기존 읽기 전용 도구 `deploy/robot/omx/register_probe.py`(ID 11~16에 PING과 READ만 허용)로 레지스터를 두 번 이상 읽는다. `deploy/robot/omx/joint_map_check.py`가 측정 사이에 레지스터나 위치가 바뀌지 않았는지, homing offset과 반전 비트가 맞는지를 판정한다. 그리퍼도 같은 기준으로 본다.
- **증명하지 않는 것:** 실물의 기계적 0점이 URDF의 0점과 맞는지는 이 확인으로 알 수 없다. 이 차이는 단위 변환 문제가 아니라 시뮬레이터와 실물 사이의 보정 문제다. ACT를 포함한 모든 정책에 똑같이 걸리며, 별도 승인된 실물 절차로 다룬다.
- **확인 뒤:** 판정이 통과하면 `contracts/learning` `action_space`에 `ros_joint_rad` 단위와 `lerobot_norm_v1` ↔ `ros_joint_rad` 변환기(버전 1)를 추가한다. 실행기의 `ActionSpace`는 이 변환만 연다. 판정 기록이 없으면 변환은 계속 거부한다.
- **판정의 범위:** 판정 기록에는 측정한 팔(그 팔의 데이터셋 검수에 쓰는 `rig_revision`), 보정 range digest, 측정 파일마다의 sha256이 들어간다. 2026-10-24 실측에서 이 PC의 팔로워 보정은 모두 range가 0~4095로 같아, digest만으로는 팔을 구분할 수 없음을 확인했다. 그래서 변환은 데이터의 팔 정체가 판정의 팔과 같을 때만 열린다. 팔 정체는 한 팔이면 `rig_revision`, 두 팔이면 `rig_revision/arm_a`처럼 팔 키를 붙인 값이다(`action_space.arm_identity`). 이 정체는 운영자가 정하는 이름이며 하드웨어가 증명하지 않는다. 배선을 바꾸거나 팔을 교체하면 새 rig revision과 새 판정이 필요하다. 변환은 데이터가 녹화된 그 팔·그 보정의 판정에만 쓸 수 있다. 녹화 때 `guarded_native`가 몸 관절 레지스터는 검사하지만 그리퍼는 검사하지 않고, 보정 digest도 range만 담는다. 그래서 다른 팔이나 이전 날짜의 판정으로 변환을 열지 않는다.
- 판정이 실패하면 어느 레지스터가 다른지 기록하고, 그 모터를 다시 커미셔닝할지 관절별 부호·원점 보정을 둘지는 따로 정한다.

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
