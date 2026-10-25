# D-877: Isaac Sim OMX 백엔드가 공통 층으로 적합성 통과 (2026-10-25)

## 주장과 한계

Isaac Sim 5.1 어댑터(`learning/envs/isaac/run_omx_backend.py`)를 D-877 공통 층(`tools/sim/omx_topic_backend.py`)에 붙였고, P1 적합성 시험을 통과했다. Gazebo([P1 기록](../omx-backend-conformance-2026-10-25/result.md)), MuJoCo([기록](../omx-mujoco-backend-2026-10-25/result.md))에 이어 세 백엔드가 같은 계약을 통과했다. owner가 보는 궤적 Action은 세 경우 모두 같은 벤더 `joint_trajectory_controller`가 냈다(Gazebo는 `gz_ros2_control`, 나머지는 `topic_based_ros2_control`).

D-866 §2의 Isaac 전환 조건은 아직 주장하지 않는다. 카메라 640×480 두 대 10Hz, 실시간 배율 1 이상, 파지 반복, 실물 렌더링 비교는 따로 잰다. 장면에는 작업대·물체가 없고 바닥만 있다. 조인트 구동은 URDF 가져오기 기본값이다.

## 조건

- 커밋 `fecd0c57fa`, 모델 PC `remote_sim`(16코어·10GB), Isaac Sim 5.1 SDK venv(Python 3.11, 번들 Jazzy 라이브러리, `rmw_fastrtps_cpp`, 시스템 ROS 환경 없이 실행), `topic_based_ros2_control` `aa9f9ef952`.
- OMX-F는 저장소에 고정한 `learning/envs/isaac/assets` URDF를 `prepare_omx_urdf.py`로 준비해 `Manipulator`로 가져왔다. top 카메라는 (0.12, 0, 0.65)m에서 아래, front 카메라는 link5에 붙였다. 그래프는 `/clock`, `/sim/joint_states`, `/sim/joint_commands`→관절 제어기, 카메라 2대를 시뮬레이션 시각으로 낸다. 메인 루프는 60Hz로 제한해 시뮬레이션 시각이 벽시계와 같이 간다.
- 명령: `OMX_CELL_OVERLAY=... tools/sim/run_omx_backend_conformance.sh isaac 240x320 5`.

## 결과

- `OMX_BACKEND_CONFORMANCE_PASS`, 실패 항목 없음.
- 10초 기록: 관절 상태 807건, top·front 각 67프레임(320×240 rgb8), `/clock` 807건.
- 정지 응답: 목표 수락, 취소 확인, 취소 전 joint1 0.066rad 이동, 정착 뒤 0.0rad.
- 같은 최종 커밋에서 MuJoCo도 다시 통과했다(AI PC, 취소 전 0.052rad, 뒤 0.00006rad).

## 통과까지 고친 것

첫 실행에서 `joint_state_broadcaster` 활성화가 5초 만에 시간 초과됐다. 컨트롤러 관리자가 시뮬레이션 시각으로 도는데, Isaac은 시작에 약 20초가 걸려 `/clock`이 나오기 전에 spawner가 돌았다. MuJoCo는 빨리 떠서 드러나지 않았다. 공통 층이 첫 `/clock`을 받은 뒤 컨트롤러를 띄우게 고쳤다.

원시 기록은 저장소 밖 `Rosy/docs/workspace-records/2026-10-25/omx-isaac-backend/`에 있다.
