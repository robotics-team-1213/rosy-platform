# Isaac Sim 6.1 연동 구현 계획

**Goal:** 공통 ROSY xacro에서 Isaac Sim용 URDF와 USD를 만들고, 단일 Pinky 모델에 ROS 2 구동·오도메트리·시뮬레이션 시계를 연결한다.

**Architecture:** `description`이 형상 정본이다. xacro는 `sim_backend:=isaac`에서 Gazebo 플러그인만 제외한다. `isaac_sim`의 준비 도구는 xacro를 URDF로 변환하고 mesh 경로를 해석한다. Isaac Sim 6.1 Python 런너는 공식 URDFImporter로 USD를 만들고 OmniGraph를 연결한다. 출력 URDF/USD와 로그는 소스 트리 밖에 둔다.

**Tech Stack:** ROS 2 Jazzy xacro, Isaac Sim 6.1 Python API, ROS 2 Bridge, OmniGraph, pytest.

## Task 1: 모델 변환

1. `src/sim/isaac_sim/test/test_prepare_urdf.py`에 Gazebo 요소 제거와 mesh 경로 해석의 실패 테스트를 만든다.
2. 실패를 확인한 뒤 `src/sim/description/urdf/{robot,rosy}.urdf.xacro`에 backend 인자를 추가한다.
3. `src/sim/isaac_sim/prepare_urdf.py`에서 xacro 실행, URDF 검증, mesh 경로 해석, 명시적 출력 경로 쓰기를 구현한다.
4. 호스트 pytest와 Jazzy의 실제 xacro 렌더를 별도 검증한다.

## Task 2: Isaac Sim ROS 경계

1. `src/sim/isaac_sim/test/test_graph_contract.py`에 ROS topic, joint, wheel 수치, clock 단일 발행 그래프 계약 테스트를 먼저 만든다.
2. `src/sim/isaac_sim/graph_contract.py`에 플랫폼 비의존 그래프 명세를 구현한다.
3. `src/sim/isaac_sim/run_rosy.py`에 6.1 URDFImporter, USD stage, OmniGraph 설정과 명시적 prim 검증을 구현한다.
4. NVIDIA GPU 호스트에서 USD/ROS topic/실제 이동/정지/TF를 검증한다. 이 호스트에서 불가능하면 HOLD로 기록한다.

## Task 3: 기록과 수용 기준

1. 새 ADR에 버전, 모델 원천, CORE 최종 writer, 스코프, 검증 단계, 롤백을 기록한다.
2. `src/sim/isaac_sim/README.md`, `src/sim/AGENTS.md`, 문서 색인을 갱신한다.
3. `git diff --check`, 관련 pytest, harness lint를 실행한다. 런타임 검증이 없으면 ROS-SIM GO로 표기하지 않는다.

**수용 제한:** 첫 단계는 단일 로봇의 모델·구동·오도메트리·시계다. LiDAR, 카메라, Nav2, 다중 로봇, Isaac Lab 학습은 이 연결 위에서 실제 USD prim과 GPU 실행 증거를 확인한 후 별도 단계로 진행한다. D-98의 축구 학습 env는 열지 않는다.
