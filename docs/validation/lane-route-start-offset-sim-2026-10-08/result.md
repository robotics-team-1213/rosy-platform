# 정적 차선 경로의 잘못된 시작 위치: ROS-SIM 음성 재생

증거 등급: **모델 PC ROS-SIM 폐루프, 한 대**. 사람 승인 차선 정답·Fleet 위치 권한·실물 수용이 아니다. [앞선 정적 경로 끝점 시험](../lane-route-terminal-ros-sim-2026-10-08/result.md)의 `route_a`에 같은 `west:r → ring_s:f`와 선언 시작점 `(-1.15,-0.511,0)`을 주고, 실제 Gazebo 시작점과 D-495 trip 재배치 위치의 y만 북쪽으로 옮겼다. `route_start` 파라미터가 원래 좌표임을 ROS 파라미터 readback으로 확인했다.

| 실제 시작 y / 선언과의 차이 | 격리값 | CORE 기록의 이동 | 종료 상태·사유 | 마지막 SIM 참 위치 |
| --- | --- | ---: | --- | --- |
| −0.431 m / 80 mm | domain 100, partition `rosy_lane_route100`, CORE 8110 | 0.0 m | LOST, `camera_reselection_required` | (−1.15, −0.431) |
| −0.461 m / 50 mm | domain 101, partition `rosy_lane_route101`, CORE 8111 | 0.0 m | LOST, `reselection_required` | (−1.15, −0.461) |

두 경우 모두 출발 후 `camera_line_not_visible` HOLD가 이어졌다. 50 mm 실행에는 LOST 직전 `reselection_required` 전이가 한 번 있었지만 이동은 없었다. 두 번째 실행의 `ros2 topic info /cmd_vel -v`는 publisher **`/core` 하나**를 보였다. 전용 SIM 종료 뒤 launch·월드·포트가 남지 않았고, 다른 세션의 Gazebo는 그대로였다.

실행 소스는 전용 `~/rosy_lfstop_ws`의 기존 base `65b15b9bb`와 현재 `main`의 차선 세 모듈이며, `route_camera.py`에는 [끝점 정지 수정](../lane-route-terminal-ros-sim-2026-10-08/result.md)의 `23d20fd03`이 들어 있었다. 이는 현재 전체 `main` 이미지 시험이 아니다. 같은 지도·출발 방향의 선언 위치 일치 실행은 앞선 기록에서 1.0945 m 진행했지만, 세 Gazebo run은 동일 프레임 입력의 통제 A/B가 아니다.

재현: 앞선 기록의 `run_route_a_sim.sh`와 정적 경로 launch를 전용 작업공간 `~/rosy_lfstop_ws/route_a_sim/`에 둔다. 80 mm 사례는 `env PORT=8110 ROS_DOMAIN_ID=100 GZ_PARTITION=rosy_lane_route100 bash ~/rosy_lfstop_ws/route_a_sim/run_route_a_sim.sh camera_lane_mode:=route_a spawn_x:=-1.15 spawn_y:=-0.431 spawn_yaw:=0`으로 시작하고 다른 터미널에서 [80 mm 녹화 스크립트](evidence/record_offroute80.sh)를 같은 작업공간에 복사해 실행한다. 50 mm 사례는 포트 8111, domain 101, partition `rosy_lane_route101`, `spawn_y:=-0.461`과 [50 mm 녹화 스크립트](evidence/record_offroute50.sh)를 사용한다. CORE `/api/v1` 응답 후 녹화를 시작했다. 두 녹화 스크립트는 결과 폴더에 파일을 쓰므로 재실행 전에 기존 폴더를 별도 보존한다.

원본은 `X:/DevTemp/lane-route-ros-sim/offroute80-frames.npz`(SHA-256 `c99fa6bb0f54b339f33d0eefb12fda47cf80494c0beafa7ee2a36bb110660711`)와 `offroute50-frames.npz`(SHA-256 `5e853dc8fa6c7e5d169d2fb945583bbc19577dbf351d55b1121777e6c7f8760f`)이며, 같은 폴더의 `offroute{80,50}-summary.json`과 `-log.jsonl`에 시계열·최종 상태가 있다. 원본 대용량 영상은 저장소에 넣지 않았다.

**판정: 이 두 시작 오차 장면에서는 정지 PASS, 위치 권한은 미검증.** 카메라가 경계를 인정하지 않아 정지했을 뿐, 정적 `route_start`가 실제 로봇의 절대 위치를 검증했다는 증거는 아니다. 다른 조명·카메라 높이·보이는 한쪽 선·벽/분기에서는 결과가 달라질 수 있다. 활성 Fleet 지도와 신선한 절대 위치를 결합하기 전 `route_a`를 운영 주행 허가로 쓰지 않는다. 10/6·10/7 동일 물리 경계 사람 검수, 40 mm 곡선 편차 개선, 실물 R1/R2도 계속 HOLD다.
