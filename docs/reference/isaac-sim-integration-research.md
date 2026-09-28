# ROSY Isaac Sim 연동 구현 참고 자료

조사일: 2026-09-29. 구현 기준 후보는 NVIDIA Isaac Sim **6.1.0**이다. 공식 `latest` 문서의 [6.1 마이그레이션 안내](https://docs.isaacsim.omniverse.nvidia.com/latest/migration_guides/isaac_sim_6_1/index.html)와 6.1 샘플 경로를 확인했다. 아래 API 이름은 `latest` 문서에서 확인했으며 실제 6.1.0 설치에서 재검증해야 한다. 이 문서는 자료 조사이며 ROSY에서 Isaac Sim을 실행하거나 검증한 기록이 아니다.

## 저장소에 이미 있는 입력과 경계

- `src/sim/description/urdf/robot.urdf.xacro`가 공용 모델 진입점이다. `is_sim:=true`로 시뮬레이션 충돌체를 사용한다. `src/sim/description/urdf/rosy_gz.urdf.xacro`의 DiffDrive, odometry, 센서, 램프 플러그인은 Gazebo 전용이므로 Isaac Sim에 그대로 이식할 수 없다.
- `src/sim/gz_sim/`은 Gazebo 실행 경로이며 `src/sim/isaac_sim/`은 별도 Isaac Sim 경로다. ROSY의 최종 `cmd_vel` 발행 권한은 CORE에 있다(D-2, D-38). Isaac 측은 이 명령을 **구독**하고 센서·주행 상태를 **발행**하는 시뮬레이터여야 한다.
- D-98은 `src/site/games/games/isaac/`의 축구 학습 환경을 FIELD 반복 전 보류한다. 일반 로봇 시뮬레이션을 위한 `src/sim/isaac_sim/`과 분리한다.

## 공식 구현 경로

| 항목 | 확인한 공식 동작 | ROSY 적용 시 확인할 점 |
| --- | --- | --- |
| 실행 환경 | [Isaac Sim 요구 사양](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html)은 x86-64 Ubuntu 22.04/24.04 또는 Windows 11, 최소 RAM 32 GB, RTX 4080급·VRAM 16 GB, SSD 50 GB를 제시한다. NVIDIA의 aarch64 빌드는 DGX Spark만 지원한다. | Pinky/Pi 이미지에 넣지 않고 지원 GPU가 있는 개발 호스트에서 실행한다. 설치 전 GPU, 드라이버, 메모리를 점검한다. |
| ROS 2 | [ROS 2 설치 지침](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_ros.html)에 따라 Ubuntu 24.04에서 외부 ROS 환경을 source하지 않으면 내장 Jazzy 라이브러리가 선택된다. `python.sh`도 같은 방식으로 환경을 구성한다. Linux에서는 Cyclone DDS를 설정할 수 있으나 WSL2 Cyclone DDS 경로는 지원되지 않는다. | ROSY가 사용하는 Jazzy 및 `RMW_IMPLEMENTATION`을 호스트별로 명시하고, CORE와 Isaac 프로세스의 DDS 발견·토픽 교환을 실제로 시험한다. |
| 모델 반입 | [URDF 가져오기](https://docs.isaacsim.omniverse.nvidia.com/latest/importer_exporter/import_urdf.html)는 URDF→USD 변환 및 `python.sh` 단독 스크립트를 제공한다. ROS 2 노드의 `robot_description`에서 간접 xacro 가져오기도 가능하다. | `robot.urdf.xacro`를 `is_sim:=true`로 렌더해 `package://description` 메시 경로를 해석한 URDF를 반입한다. 변환 후 wheel joint, 축, 관성, collision, scale, frame을 USD에서 검사한다. USD는 생성 산출물로 버전·원본 해시와 연결한다. |
| 바퀴 구동 | [Differential Drive 튜토리얼](https://docs.isaacsim.omniverse.nvidia.com/latest/controllers/tutorial_differential_drive.html)은 선속도·각속도를 좌우 휠 속도로 바꾸는 제어기를 제공한다. [ROS 2 통합 예제](https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/tutorial_series/tutorial_ros2_putting_it_all_together.html)는 `geometry_msgs/Twist`의 `/cmd_vel` 구독을 ActionGraph로 연결한다. | ROSY의 실제 joint 이름과 휠 반경·간격을 사용한다. CORE 이외의 ROS 최종 명령 발행자를 만들지 않는다. 명령 유실 시 정지 조건과 속도 제한을 시뮬레이터 어댑터에 명시한다. |
| ROS 데이터 | 같은 [통합 예제](https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/tutorial_series/tutorial_ros2_putting_it_all_together.html)는 `JointState`, `/tf`, `/tf_static`, `nav_msgs/Odometry`, `sensor_msgs/LaserScan`, `/clock` 발행 및 `/cmd_vel` 구독을 보인다. LiDAR는 [RTX LiDAR ROS 2 예제](https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/tutorial_series/tutorial_ros2_rtx_lidar.html)를 따른다. | ROSY의 namespace, frame ID, QoS, scan 특성, odom/TF 단일 발행자를 Gazebo 및 Nav2 계약과 대조한다. 카메라가 필요한 범위라면 별도 ROS 2 Camera Helper 경로를 추가한다. |
| 시간·다중 로봇 | [ROS 2 clock 지침](https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/tutorial_series/tutorial_ros2_clock.html)은 외부 노드의 `use_sim_time`과 `/clock` 동기화를 설명한다. [통합 예제](https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/tutorial_series/tutorial_ros2_putting_it_all_together.html)는 여러 로봇의 중복 clock을 피하려고 clock 그래프를 장면에 한 번만 둔다. | 첫 단계는 단일 로봇과 clock 발행자 하나로 제한한다. `rosy_XX` namespace 및 TF prefix는 후속 다중 로봇 검증에서 확장한다. |
| 자동 실행 | [SimulationApp API](https://docs.isaacsim.omniverse.nvidia.com/latest/py/source/extensions/isaacsim.simulation_app/docs/api.html)는 `SimulationApp({"headless": True})`와 `update()/close()`를 제공한다. [ROS 2 standalone 지침](https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/bridge_configuration/tutorial_ros2_python.html)은 `python.sh` 기반 실행을 설명한다. | 변환된 USD와 ROS 그래프를 로드하는 단독 스크립트를 Isaac 전용 Python으로 실행한다. Windows host pytest는 Isaac 런타임 증거가 아니다. |
| 배포·권리 | [Python 설치 지침](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_python.html)은 Python 3.12와 Omniverse EULA 수락을 요구한다. [컨테이너 지침](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_container.html)은 Linux 컨테이너의 headless 실행을 설명한다. | Isaac 바이너리·NVIDIA 에셋을 저장소에 복사하기 전 배포 조건을 별도 검토한다. 공개 저장소에는 자체 스크립트/설정과 출처가 확인된 에셋만 둔다. |

### 6.1 OmniGraph 구현에서 확인한 노드

[NVIDIA의 전체 ROS 2 통합 예제](https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/tutorial_series/tutorial_ros2_putting_it_all_together.html)는 `omni.graph.core.Controller.edit`로 그래프를 생성하며 `isaacsim.ros2.nodes`, `isaacsim.core.nodes`, `isaacsim.robot.wheeled_robots` 확장을 켠다. 구동 체인은 `isaacsim.ros2.bridge.ROS2SubscribeTwist` → `omni.graph.nodes.BreakVector3` → `isaacsim.robot.wheeled_robots.DifferentialController` → `isaacsim.core.nodes.IsaacArticulationController`이다. 상태 체인은 `IsaacComputeOdometry` → `ROS2PublishOdometry`·`ROS2PublishRawTransformTree`, 센서는 `ROS2RtxLidarHelper`, 시간은 `IsaacReadSimulationTime` → `ROS2PublishClock`이다. 이는 예제의 **노드 타입 문자열**이고 ROSY 모델의 prim 경로나 조인트 이름은 아니다. URDF→USD 변환 CLI는 [공식 importer 예제](https://docs.isaacsim.omniverse.nvidia.com/latest/importer_exporter/import_urdf.html)의 `./python.sh standalone_examples/api/isaacsim.asset.importer.urdf/urdf_import.py --urdf <path> --usd-path <dir>`이다.

## 최소 수직 검증 순서

1. 지원 GPU 호스트에서 Isaac 버전·드라이버·ROS 2 Jazzy·RMW를 고정하고 공식 호환성 체크를 통과시킨다.
2. ROSY xacro→URDF→USD를 재현 가능하게 변환하고 joint, collision, 센서 prim을 점검한다.
3. 단일 로봇을 headless로 실행해 `/clock`, `/joint_states`, `/odom`, `/tf`, `/scan`을 읽고 CORE의 `/cmd_vel`만 받아 저속 직진·회전·명령 중단 후 정지를 관찰한다.
4. 시뮬레이션 시간, frame tree, topic 타입/QoS/namespace를 Nav2 소비자와 대조한다. Isaac 결과는 ROS-SIM 증거로만 기록하고 실물 안전·FIELD 판정으로 올리지 않는다.
