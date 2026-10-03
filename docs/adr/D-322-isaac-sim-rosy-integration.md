## D-322 Isaac Sim은 Gazebo와 별도 시뮬레이터로 연결한다

**Status:** Accepted (2026-09-29, 소스 설계·구현 범위). Isaac Sim 6.1 실제 실행과 ROS-SIM 수용은 HOLD.

**Context:** `src/sim/gz_sim`은 Gazebo Harmonic의 world·플러그인·브리지를 소유한다. ROSY는 Isaac Sim도 필요하지만 공통 `description`의 `is_sim:=true` 렌더에는 Gazebo 전용 DiffDrive·센서·램프 플러그인이 함께 들어간다. 이를 Isaac Sim에 직접 가져오면 시뮬레이터별 장치 제어와 ROS 그래프의 책임이 섞인다. D-98은 축구 게임 내부 `isaac/` 학습 환경만 FIELD 반복 뒤로 미뤘다. 일반 로봇 시뮬레이션 경로에는 적용하지 않는다.

**Decision:**

1. 공통 로봇 형상은 `src/sim/description`이 소유한다. `robot.urdf.xacro`에 `sim_backend`를 추가하고 기본값 `gz`를 유지한다. Isaac 렌더는 `is_sim:=true sim_backend:=isaac`으로 동일한 primitive collision을 쓰되 Gazebo 태그만 제외한다. 형상을 복제하지 않는다.
2. `src/sim/isaac_sim`은 Isaac Sim 6.1 전용 독립 실행 도구다. `prepare_urdf.py`는 xacro와 mesh URI를 검증해 URDF를 생성한다. `run_rosy.py`는 [공식 6.1 URDFImporter](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/py/source/extensions/isaacsim.asset.importer.urdf/docs/index.html)로 USD를 만들고 ROS 2 OmniGraph를 연결한다. URDF/USD와 로그는 소스 트리 밖의 스크래치에 둔다. 저장소에 NVIDIA 바이너리·USD 생성물은 넣지 않는다.
3. 첫 실행 범위는 한 대다. `/rosy_XX/cmd_vel`을 구독하고 바퀴 관절을 구동하며 `/rosy_XX/odom`, `/rosy_XX/joint_states`, 전역 `/tf`와 `/clock`을 발행한다. `ROS_DOMAIN_ID=40+로봇 번호`를 요구한다. 바퀴 반지름 0.028 m, 초기 바퀴 간격 0.0961 m는 현재 Gazebo 설정과 맞춘 시작값이다. 실제 Isaac Sim 변환 뒤 물리 이동량과 joint 순서를 확인해야 한다. CORE가 최종 `cmd_vel`을 발행하는 기존 경계는 유지한다.
4. `description`의 `sim_backend` 기본값과 Gazebo 경로를 보존한다. Isaac Sim 출력을 ROSY 장치·현장 수용 증거로 쓰지 않는다. LiDAR, 카메라, Nav2, 다중 로봇, Isaac Lab 학습은 첫 실제 실행의 prim·프레임·토픽·정지 측정을 통과한 후 후속 구현으로 둔다. D-98의 축구 학습 env는 열지 않는다.

**근거:** [NVIDIA 요구 사양](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/requirements.html)은 x86-64 GPU 호스트의 최소 RAM 32 GB·VRAM 16 GB를 제시한다. [ROS 2 설치 지침](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/install_ros.html)은 Ubuntu 24.04/Jazzy와 ROS 2 Bridge 설정을 설명한다. [URDF 가져오기](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/importer_exporter/import_urdf.html)와 [ROS 2 통합 예제](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/ros2_tutorials/tutorial_series/tutorial_ros2_putting_it_all_together.html)는 importer, Twist→DifferentialController→ArticulationController, 오도메트리·TF·시계 그래프의 기준이다. 자세한 자료·한계는 [조사 노트](../reference/isaac-sim-integration-research.md)에 있다.

**대안:** Gazebo world를 Isaac에서 재활용하는 안은 플러그인과 물리 엔진 차이를 숨긴다. 별도 ROSY 모델 복사본은 형상 드리프트가 생긴다. 축구 `isaac/`을 먼저 만드는 안은 D-98·D-109에 어긋난다.

**검증과 수용:** 호스트 pytest는 URI·namespace·초기 wheel 계약만 확인한다. Jazzy xacro 렌더, Isaac 6.1 USD import, ROS graph, 단일 CORE publisher, `/clock`·TF·odom 일관성, 제한된 직진·회전·zero-command 후 정지, 센서·Nav2 연동은 각각 실제 GPU 호스트에서 확인해야 한다. 이 세션의 Windows 호스트에는 Isaac Sim/ROS 2 도구가 없어 ROS-SIM을 HOLD로 둔다. `run_rosy.py`의 그래프에는 현재 명령 신선도 watchdog이 없으므로 지속 운전·Nav2 시연 수용 전에 timeout 동작을 증명하거나 추가해야 한다. 실기 G4/G5/DEVICE/FIELD는 별도다.

**위험·롤백:** 6.1 importer의 asset transformer가 prim 경로와 joint 이름을 바꿀 수 있고, 렌더링·접촉 물리는 Gazebo와 다르다. 가져오기 실패 시 명시적 prim 경로로 재시도하되, 검증 없이 속도 제한이나 정지 조건을 완화하지 않는다. 롤백은 Isaac 런너와 `sim_backend` 호출을 사용하지 않고 기존 기본 Gazebo 렌더만 사용하는 것이다. `gz_sim` 패키지와 장치 이미지는 변경하지 않는다.

**References:** D-2, D-4, D-83, D-98, D-109, D-315, [구현 계획](../plans/2026-09-29-isaac-sim-integration.md).

### 2026-09-29 asset decision

Isaac용 Pinky Pro 형상은 이미 `src/sim/description`에 있는 ROSY 모델을 재사용한다. 공식 `pinklab-art/pinky_pro`의 `014a09f289e6988894fbffde2624fdb1e257815b`를 받아 비교한 결과, 충돌 STL 9개와 시각 DAE 4개는 SHA-256이 같고 시각 DAE 6개는 다르다. 차이를 검토하기 전 공식 파일로 현행 모델을 덮어쓰거나 Isaac 폴더에 형상을 중복 보관하지 않는다.

OMX-AI는 구형 OpenMANIPULATOR-X나 OMY와 구분해 공식 ROBOTIS `open_manipulator`의 OMX-F/OMX-L 형상을 사용한다. `deploy/robot/omx/stack.lock.yaml`과 같은 `0a4af6a923b8b7d80b8c20506d1839c54d2e993e`에서 전개된 URDF 2개와 참조 STL 15개를 `src/sim/isaac_sim/assets/open_manipulator_description`에 보관하고, Apache-2.0 라이선스와 파일별 SHA-256을 함께 기록한다. Isaac import를 위한 URI 치환 출력은 저장소 밖에 생성한다. 이는 모델 형상 준비까지만 증명하며, OMX 관절 제어, 카메라 보정, Pinky 장착, 정책 학습, 실제 Isaac 실행은 별도 검증 대상이다.

### 2026-09-29 preflight and import amendment

Isaac 실행 전에 `model_checks.py`가 OMX 공급사 파일 해시, 양쪽 팔의 URDF 메시·관절, 준비된 Pinky URDF의 메시·바퀴 관절을 검사한다. `run_rosy.py`는 검사 실패 시 Isaac 앱을 시작하지 않는다. `import_omx.py`는 OMX-F 또는 OMX-L을 공식 6.1 URDFImporter로 USD로 변환한 뒤 articulation 하나와 필수 관절 이름을 확인한다. 이 도구는 형상과 가져오기 계약에 한정되며 arm controller나 카메라를 제공하지 않는다.

Pinky URDF의 바퀴 중심 간격은 0.0811 m이고 현재 Gazebo·Isaac 구동 설정의 유효 간격은 0.0961 m다. 값의 차이는 실제 접촉·회전 측정 없이는 오류인지 보정값인지 확정할 수 없다. GPU 호스트에서 관절 축, 바퀴 접촉, 지시 회전량과 관측 회전량을 비교하고 수치를 재판정한다. 명령 신선도 watchdog도 아직 없으므로 장시간 주행과 Nav2 수용은 HOLD다.

---

### 2026-10-03 버전 개정 — Isaac Sim 5.1 유지 (D-434)

GPU 호스트(모델 PC, D-434)에 이미 설치된 Isaac Sim 5.1과 Isaac Lab 2.3.2를 그대로 쓴다(사용자 결정). 6.1 전용 `URDFImporter`/`URDFImporterConfig`를 쓰는 `run_rosy.py`·`import_omx.py`에는 5.1 가져오기 경로(`URDFParseAndImportFile`, `_urdf.ImportConfig`)를 함께 둔다. 이 문서의 수용 항목과 Isaac Lab 학습 HOLD는 바뀌지 않는다. RAM 32 GB 전까지 headless, 작은 렌더, 센서 최소, 학습과 GPU 동시 사용 금지(D-434 §4)를 따른다. 6.1 전환은 RAM 증설 뒤 다시 정한다.
