# D-866 P1: Gazebo OMX 백엔드 적합성 확인 (2026-10-25)

## 주장과 한계

D-866 §2 시뮬레이터 백엔드 계약을 `tools/sim/omx_backend_conformance.py`로 시험으로 만들었고, Gazebo 백엔드가 통과했다. 같은 도구로 Isaac 백엔드(P2)를 판정한다.

대상 Gazebo world는 D-866 P0 변형이다. 설치된 `omx_pilot_workcell`의 `workcell_camera`를 front로 쓰고, 이를 복제한 top 카메라를 덧붙였다. 카메라 크기는 P0 설치 정책과 같은 320×240, 5Hz다. 주기는 메시지 시각(시뮬레이션 시간) 기준이다. Isaac 전환 조건(640×480 두 대 10Hz, 실시간 배율 1 이상, 파지 반복, 렌더링 비교)은 이 기록의 주장이 아니다.

## 판정 항목

| 항목 | 기준 |
|---|---|
| `/joint_states` | `joint1..5`, `gripper_joint_1`이 한 번씩, 메시지마다 같은 순서, 시각 엄격 증가, 20Hz 이상 |
| 카메라 | `/top_camera/image_raw`, `/front_camera/image_raw`: rgb8, 설치 크기, 시각 엄격 증가, 지정 주기 이상 |
| `/clock` | 뒤로 가지 않고 진행 |
| 정지 응답 | `/arm_controller/follow_joint_trajectory`에 joint1 +0.3rad/4s 목표를 보내 수락, 1초 뒤 취소 확인. 취소 전 0.02rad 이상 움직이고, 1초 정착 뒤 2초 동안 0.005rad 이하로 움직임 |

## 결과

커밋 `5f3dca8a37`, AI PC `remote_sim`(D-867 12코어·10GB), NVIDIA EGL. 명령: `OMX_CELL_OVERLAY=... python3 middleware/robot_execution/local/test/omx_backend_conformance_gazebo.py`.

- `OMX_BACKEND_CONFORMANCE_PASS`, 실패 항목 없음.
- 10초 기록: 관절 상태 1401건, top·front 각 70프레임, `/clock` 7003건.
- 정지 응답: 목표 수락, 취소 확인, 취소 전 이동 0.068rad, 정착 뒤 이동 0.0rad.
- 같은 판정을 ROS 없이 확인하는 시험 `test/test_omx_backend_conformance.py`(정상 1건, 계약 위반 11종이 각각 실패로 보고됨)가 원격 시험 PC에서 통과했다.

앞선 실행(취소 전 이동 검사 없음)도 통과했지만, 이동 0.0rad만으로는 목표를 무시하는 백엔드도 통과하므로 취소 전 이동 조건을 더했다.
