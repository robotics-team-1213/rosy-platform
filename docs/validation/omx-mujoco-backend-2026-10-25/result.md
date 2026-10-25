# D-877: MuJoCo OMX 백엔드가 공통 층으로 적합성 통과 (2026-10-25)

## 주장과 한계

D-877 공통 층(`tools/sim/omx_topic_backend.py`, 벤더 OMX-F 설명·컨트롤러 + `topic_based_ros2_control`)에 MuJoCo 어댑터(`tools/sim/omx_mujoco_backend.py`)를 붙였고, P1 적합성 시험(`tools/sim/omx_backend_conformance.py`)을 통과했다. owner가 보는 `/joint_states`와 `/arm_controller/follow_joint_trajectory`는 Gazebo와 같은 벤더 `joint_trajectory_controller`가 냈다.

MuJoCo 물리(서보 이득 40, 감쇠 0.3, 관성 보정)는 실물에 맞춘 값이 아니다. 카메라 영상 내용, 파지, 물체, 실시간 배율 1 이상 조건은 이 기록의 주장이 아니다.

## 조건

- 커밋 `ab837d6514`, AI PC `remote_sim`(12코어·10GB), MuJoCo 3.3.7(`~/rosy-test/venvs/sim-mujoco`, `--system-site-packages`), `topic_based_ros2_control` `aa9f9ef952`(`tools/sim/build_topic_based_ros2_control.sh`), 벤더 OMX overlay.
- 명령: `OMX_CELL_OVERLAY=... tools/sim/run_omx_backend_conformance.sh mujoco 240x320 5`.

## 결과

- `OMX_BACKEND_CONFORMANCE_PASS`, 실패 항목 없음.
- 10초 기록: 관절 상태 1400건, top·front 각 70프레임(320×240 rgb8), `/clock` 1401건.
- 정지 응답: 목표 수락, 취소 확인, 취소 전 joint1 0.051rad 이동, 정착 뒤 0.00007rad.
- 원격 pytest: `test/test_omx_sim_backends.py`, `test/test_omx_backend_conformance.py` 통과.

## 통과까지 고친 것

1. 벤더 ros2_control 블록의 Dynamixel `<gpio>`(dxl11~16)는 실물 드라이버만 내보낸다. 남겨 두면 controller_manager가 하드웨어를 거부하고 이어서 segfault가 났다. 공통 층에서 뺀다.
2. 처음 세 번은 joint1이 0.0014rad만 움직였다. `/sim/joint_commands` 기록을 보니 공통 층 명령은 1초 동안 0.076rad까지 올랐고, MuJoCo 관절만 따라가지 못했다. 원인은 벤더 메시 겹침이다. link0과 link1이 8mm 겹쳐 접촉이 joint1을 막았다. URDF 부모·자식 링크 쌍과 두 손가락 사이 접촉을 뺐다(Gazebo도 자기 충돌을 계산하지 않는다).
3. 그 전에 컨트롤러마다 `use_sim_time`을 매개변수 파일로 넣었다. 이 변경은 2의 원인이 아니었다(같은 실패가 반복됨). 컨트롤러가 시뮬레이션 시각을 쓰는 것이 맞아 유지한다.

원시 기록(`conformance.json`, `sim-joint_commands.csv`, `sim-joint_states.csv`, 공통 층 로그)은 저장소 밖 작업 공간 `Rosy/docs/workspace-records/2026-10-25/omx-mujoco-backend/`에 있다.
