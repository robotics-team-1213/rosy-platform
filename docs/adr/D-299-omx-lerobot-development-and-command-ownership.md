## D-299 OMX LeRobot 실험 경로와 운영 팔 제어권을 분리한다

**Status:** Proposed (2026-09-27). OMX 실물 모델·리비전, 드라이버, 캘리브레이션과 DEVICE 시험 전에는 운영 모드·원격 팔 API·학습 정책을 활성화하지 않는다.

**Context:** 공식 LeRobot OMX 통합은 `omx_leader`/`omx_follower`를 시리얼 포트로 직접 연결해 teleoperation, 기록, 정책 실행에 사용한다. ROBOTIS의 ROS 2 `open_manipulator`/Cyclo 경로 역시 팔로워 하드웨어를 제어한다. 기존 OMX 보고서와 D-273은 두 경로의 동시 시리얼 점유를 금지하지만, D-296의 장치 미들웨어와 LeRobot의 역할 관계를 별도로 고정할 필요가 있다.

**Proposed decision:**

1. ROSY 운영 경로의 팔로워 actuator 최종 명령은 OMX 장치 로컬 제어기 한 곳이 소유한다(D-282). ROS 2/ros2_control 기반 경로를 첫 운영 후보로 둔다. LeRobot 학습 정책, leader teleop, MoveIt, 규칙 기반 조작은 제어기가 검증·중재할 입력 후보이며 Fleet이나 학습 서버가 시리얼 버스 또는 최종 trajectory를 직접 소유하지 않는다.
2. Native LeRobot 직접 연결은 별도 **개발·기록 모드**로 둔다. 이 모드에서 LeRobot 프로세스가 OMX-F 시리얼 버스의 유일한 owner이며 ROS 하드웨어 드라이버와 운영 OMX 제어기는 같은 버스를 열지 않는다. 모드 변경은 새 명령 차단, 현재 동작·장치 상태 확인, 이전 owner 종료와 포트 해제, 실물 포트/캘리브레이션 확인, 새 owner 시작, 재승인의 순서로 검증한다. 단순 프로세스 재시작이나 네트워크 재연결은 모드 전환 또는 자동 재개가 아니다.
3. ROS 경로에서 LeRobot 데이터셋·정책을 쓰려면 별도 어댑터를 설계한다. 데이터셋 변환은 관측/명령 시각, 카메라·관절 순서, 단위, 그리퍼 표현, 보정 revision, 성공 판정과 provenance를 검증한다. 정책 추론은 경계가 정한 유효기간·관절 제한·fresh state·취소·fault 처리에 종속된다. 변환 성공은 동작 안전이나 정책 품질의 증거가 아니다.
4. OMX-L leader는 사용자 입력 장치가 될 수 있지만 팔로워의 운영 최종 명령 owner가 아니다. Pinky 탑재 시에도 Pinky CORE는 최종 base `cmd_vel`, OMX 로컬 제어기는 최종 arm trajectory를 각각 소유한다. 복합 순서는 Fleet Mission 또는 별도 수용한 Local Transaction 계약을 따른다(D-298).

**Validation / Transition:** 실물 장치 inventory 및 영구 포트 식별 → 단일 owner/중복 점유 거부 → 모드 전환 중 정지·재시작·포트 분리 시험 → 관절·카메라·데이터 매핑 → 정책 제안 경계 → DEVICE/FIELD 수용 순서다. 현재 `omx_adapter`/disabled profile과 기존 ROS-SIM은 이 시험을 대체하지 않는다.

**Sources:** [Hugging Face LeRobot OMX](https://huggingface.co/docs/lerobot/omx), [Hugging Face LeRobot](https://huggingface.co/docs/lerobot/main/index), [ROBOTIS open_manipulator](https://github.com/ROBOTIS-GIT/open_manipulator), [ROBOTIS physical_ai_tools](https://github.com/ROBOTIS-GIT/physical_ai_tools), [OMX 조사 보고서](../reference/OMX_AI_ROS2_Camera_Report_2026-09-26.md), [D-273](D-273-omx-camera-stream-and-arm-control-order.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md).
