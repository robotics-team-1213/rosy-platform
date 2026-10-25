## D-877 OMX 시뮬레이터 백엔드는 공통 층 하나에 붙는다: Gazebo, Isaac Sim, MuJoCo

**Status:** Accepted (2026-10-25, 사용자 결정 「ROSY 자체도 빠르게 아이삭심과 가제보나 기타 무조코까지 연결이 가능해서 파이프라인이 함께 되어야」). D-866 §1·§2를 넓힌다. 주 시뮬레이터(Isaac)와 회귀용(Gazebo) 역할은 그대로다.

**관련:** D-866 §2 · D-864 · D-854 · D-434

### Context

- D-866 §2는 백엔드 계약(관절 상태, 궤적 Action, top·front 카메라, `/clock`)을 정했다. P1(`tools/sim/omx_backend_conformance.py`)이 이 계약을 판정하고 Gazebo가 통과했다.
- Gazebo는 `gz_ros2_control`로 벤더 OMX 컨트롤러를 띄운다. Isaac과 MuJoCo는 ros2_control 하드웨어 플러그인이 없다. 각자 궤적 Action을 따로 만들면 허용 오차, 결과 코드, 취소 의미가 백엔드마다 달라진다.
- 실물 셀도 같은 벤더 `joint_trajectory_controller`를 쓴다(`dynamixel_hardware_interface`).

### Decision

1. **공통 층.** `tools/sim/omx_topic_backend.py`가 벤더 OMX-F 설명(xacro)과 벤더 컨트롤러 설정·제약을 그대로 쓰고, 하드웨어만 `topic_based_ros2_control`(고정 commit, `tools/sim/build_topic_based_ros2_control.sh`)로 바꾼다. owner가 보는 `/joint_states`와 `/arm_controller/follow_joint_trajectory`는 모든 백엔드에서 같은 컨트롤러가 낸다.
2. **백엔드 어댑터.** 새 시뮬레이터는 `/sim/joint_states`(URDF 관절 전부)를 내고 `/sim/joint_commands`를 적용하며, `/clock`과 top·front 카메라를 시뮬레이션 시각으로 낸다. 궤적 Action을 직접 만들지 않는다.
3. **연결 순서.** MuJoCo(`tools/sim/omx_mujoco_backend.py`)로 공통 층을 먼저 확인한다. 가볍고 GPU 없이도 돌고 두 PC 모두에서 쓸 수 있다. 그다음 Isaac을 같은 층에 붙인다. Gazebo는 기존 `gz_ros2_control` 경로를 유지한다.
4. **판정.** 어느 백엔드든 `tools/sim/run_omx_backend_conformance.sh <backend> <HxW> <Hz>`로 P1 적합성 시험을 통과해야 쓴다.

### Consequences

- 정책, 실행기, CORE, owner 코드는 백엔드를 바꿔도 그대로다. 데이터 수집과 평가를 백엔드 사이에서 교차할 수 있다.
- 공통 층은 `topic_based_ros2_control`과 벤더 OMX overlay에 의존한다. Jazzy 바이너리가 없어 사용자 영역에 빌드한다.
- 벤더 ros2_control 블록의 Dynamixel `<gpio>` 선언은 실물 드라이버에만 있어 공통 층에서 뺀다.
- MuJoCo 물리(서보 이득, 감쇠)는 실물에 맞춘 값이 아니다. 데이터·평가에 쓰기 전에 따로 맞춘다.
