# 굽이 공백의 지도 경계 기억: 녹화 프레임 후보 재생

2026-10-08, `fix/lane-one-side-reacquire`의 `26c2aa8f8`에서 앞선 [독립 ROS SIM 녹화](../lane-blind-stop-sim-2026-10-08/result.md)를 `RouteCameraFollower`(`route_a`)로 오프라인 재생했다. 마지막 텔레포트 직후 frame 76부터 첫 무관측 frame 192까지 동일한 320×240 영상·SIM 참 자세·Gazebo 지면 기하를 넣었다. 경로는 지도 `west:r → ring_s:f`, 시작은 녹화 frame 76 자세다. 이 경로와 자세는 실험자가 지정했으며 활성 Fleet trip·지도 버전·현장 위치 확인을 통과한 값이 아니다.

frame 192에서 지도 없는 `edge_left`는 후보가 없고, 지도 경로 시제품은 기존 잠금·정렬 상태에서 `MEMORY` 후보를 냈다. 그 프레임의 지도 중심선 측면 오차는 −0.0191 m였다. 같은 영상과 기억에 자세만 경로 왼쪽으로 0.080 m 옮기면 지도 측면 오차는 +0.0609 m다. 수정 전에는 경계 기억 게이트가 거절한 뒤 분기 `MANOEUVRE`가 주행 후보를 냈고, `26c2aa8f8` 이후에는 `STOP`으로 후보가 없다. 별도 호스트 회귀는 분기 진입·진행 이탈을 검증했고 관련 시험은 77 passed, 10 skipped였다.

재현: `python docs/validation/lane-route-gap-replay-2026-10-08/evidence/replay.py X:/DevTemp/lane-blind-ros-sim/guard1-frames.npz`. 원본 SHA-256은 `08e8598bd0aa9736b8ba90ba8a7ec3bc8a77c44a00025f4f546bd3e73f1bfd63`이고 모델 PC의 `~/rosy_lfstop_ws/guard1/rec/frames.npz`에도 있다. 원본 대용량 파일은 저장소에 넣지 않았다.

녹화 로봇은 frame 192 직후 정지했으므로 `MEMORY` 후보가 실제 전진 중 같은 선을 재획득할지는 **검증되지 않았다**. 이 결과는 저장된 SIM 프레임의 SOURCE/LOCAL 반례이며 `route_a`의 ROS 폐루프, Fleet 활성 경로·지도 버전 결합, 벽/분기 음성 재생, 10/6·10/7 영상의 사람 승인 동일 경계 정답 및 실물 R1/R2 수용을 대신하지 않는다. 그 전에는 현재 `edge_left`의 완전 미관측 STOP을 유지한다.
