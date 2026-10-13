# 오른쪽 경계 대체 가드: 분리된 폐루프 SIM 재검증

- 대상: 로컬 `main`의 `a76bb9dad`와 동일한 `lane_bev.py` 변경을 모델 PC의 기존 B9 SIM 소스 위에 적용한 분리 체크아웃 `65b15b9bb`. ROS 2 Jazzy `control`만 새 작업공간에 빌드하고 기존 SIM 설치물을 하위 환경으로 사용했다. 실행 중 `lane_bev.__file__`은 새 작업공간의 `build/control/.../lane_bev.py`를 가리켰다. 실물 로봇 실행은 없었다.
- 격리: 별도 ROS domain 82, Gazebo partition `rosy_lfw`, CORE 로컬 포트 8102. `camera_lane_mode=edge_left`, `RECOVERY=false`, 지도 `map_v2_fleet_real`. 이전 SIM 작업공간과 출력은 보존했고, 이번 프로세스는 종료했다.
- 절차: `d495_sim_probe.py trip --x -1.15 --y -0.511 --yaw 0 --plan left:60 --duration 40`을 CORE API에 연결하고 `b8_record.py`로 원본 프레임과 SIM 참 자세를 함께 저장했다. 재계산은 `python docs/validation/lane-goal-sim-2026-10-08/analyze_edge.py <frames.npz> middleware/perception/map/map_v2_fleet/lane_graph.yaml --start-index 64`.
- 관측: 출발 후 334개 유효 프레임 중 굽이 창(x=−0.95…−0.78 m, y<−0.3 m) 21개의 west edge 중심선 거리는 중앙값 **0.0007 m**, 최대 **0.0035 m**였다. SIM 참 자세 총 경로 길이는 **1.4967 m**. 최종은 `(−0.6807, +0.4933)`에서 `obstacle_ahead` HOLD, `body_gap_m=0.0284`. `left:60` 교차로 완료는 **0건**이고 capability도 false였다. 요약은 [edge-south1-summary.json](edge-south1-summary.json).
- 원본은 모델 PC의 격리 작업공간 `~/rosy_lfw_ws/lfwruns/edge_south1/rec/frames.npz` 및 로컬 `X:/DevTemp/lane-fallback-width/edge-south1-frames.npz`에 보존했다. SHA-256 `F3960380436433C15EEBC2FA315B0C42BEA4AC67DE2CF8541B75EF987C13A1DA`.

이 실행은 새 가드를 로드한 상태의 **굽이 주행 회귀 확인**이다. 오른쪽 대체 가드가 실제 프레임에서 발동했다는 증거는 없다. [test_lane_edge.py](../../../middleware/perception/test/test_lane_edge.py)의 멀리 떨어진/가까운 잘못된 경계 회귀 시험과, 별도 [이전 SIM 분석](../lane-goal-sim-2026-10-08/result.md)의 frame 260 재생이 해당 분기를 검증한다. 이 거리값은 **west edge 기준**이며 다른 edge와의 관계 또는 차체 외곽 여유를 증명하지 않는다. B9 기본 활성화, 교차로 주행 완료, 실물 수용을 뜻하지 않는다.

다음 수용 목표는 10/6·10/7 실영상에서 사람이 동일 물리 경계의 가림·재출현을 확정하고, 직선·굽이·한쪽 선 소실·벽·분기 사례를 동일 계약으로 재생하는 것이다. 음성 사례에서 잘못된 진행 없이 STOP, 양성 사례에서는 전진 중 재획득을 확인한 뒤 R0 재생→R1 shadow→감독하 R2 실물 순으로 승인한다. CORE가 유일한 최종 `/cmd_vel` 발행자라는 경계는 유지한다.
