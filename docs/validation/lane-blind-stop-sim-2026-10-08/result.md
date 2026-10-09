# 양쪽 경계 미관측 시 정지: 독립 ROS SIM 재생

2026-10-08 모델 PC의 독립 `~/rosy_lfstop_ws`에서 시행했다. 기본 소스는 `65b15b9bb`이며, 로컬 `main`의 `lane_bev.py`, `lane_boundaries.py`, `route_camera.py` 세 파일만 덮어 `control`을 다시 빌드했다. 따라서 **전체 현재 main 이미지 검증은 아니다**. 격리값은 ROS domain 83, Gazebo partition `rosy_lfstop`, CORE port 8103이다. `camera_lane_mode=edge_left`, `RECOVERY=false`, 남쪽 출발 `(-1.15, -0.511, 0)`, 계획 `left:60`으로 `d495_sim_probe.py trip`을 실행하고 `b8_record.py`로 영상·SIM 참 자세·명령을 녹화했다. `/cmd_vel` publisher는 `/core` 하나였다.

프로브는 0.5835 m 진행 후 `camera_line_not_visible` HOLD, 이어 `reselection_required` LOST로 끝났다. 교차로 지시 소비·완료는 0건이고 종료 capability는 false다. 마지막 자세는 `(-0.61068, -0.38828, 1.02766)`이다. 226개 녹화 프레임에서 마지막 텔레포트 다음 프레임 76부터 `analyze_edge.py`로 서쪽 지도 중심선까지 거리를 계산하면 굽이 창 35프레임의 중앙값 0.0009 m, 최대 0.0041 m, 이후 전체 최대 0.0193 m이며 0.04 m 초과는 0프레임이다. 움직임이 기록된 마지막 프레임은 192이고 프레임 195 이후 명령은 `(0, 0)`이다.

녹화 영상 프레임 170에는 전방으로 굽는 흰 선이 보이고, 180에서는 그 선이 화면 아래 오른쪽으로 빠진다. 정지 뒤 프레임 195~200에서는 원형 바닥 표식이 전방에 있지만 추종할 같은 경계는 화면에서 확인되지 않는다. 이는 영상 후보 판독이며 사람 승인 동일 경계 정답이 아니다. 이전 `edge_left` SIM은 비슷한 자세를 지나 계속 진행했으나 [별도 기록](../lane-fallback-sim-2026-10-08/result.md)의 근거는 경계 기억이다. 이번 정지는 양쪽 경계 미관측에서 기억만으로 진행하지 않는 가드의 예상 안전 동작이다. **굽이 통과나 차선 추종 주행 완료 증거가 아니다.**

원본은 모델 PC `~/rosy_lfstop_ws/guard1/rec/frames.npz`와 로컬 `X:/DevTemp/lane-blind-ros-sim/guard1-frames.npz`에 있다. SHA-256 `08e8598bd0aa9736b8ba90ba8a7ec3bc8a77c44a00025f4f546bd3e73f1bfd63`. 재계산: `python docs/validation/lane-goal-sim-2026-10-08/analyze_edge.py X:/DevTemp/lane-blind-ros-sim/guard1-frames.npz middleware/perception/map/map_v2_fleet/lane_graph.yaml --start-index 76`. 요약 JSON과 CORE 시계열 로그는 같은 X: 디렉터리에 보존했다.

다음 재생은 승인된 활성 지도 edge·신선한 위치·차선 잠금·짧은 기억 목표의 지도 일치를 실제 ROS 주행 경로에 결합한 뒤, 이 영상과 벽/분기 음성 사례에서 정지 또는 재획득을 확인해야 한다. 현재 `edge_left`에는 이 지도 허가가 없으므로 완전 미관측에서 STOP을 유지한다. 사람 검수된 10/6·10/7 동일 경계 정답, R0 재생, 실물 R1/R2는 아직 없다. ROS SIM 결과를 실물 주행 수용으로 올리지 않는다.
