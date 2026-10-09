# 정적 차선 경로 끝 정지: 독립 ROS-SIM 폐루프

증거 등급: **모델 PC ROS-SIM 폐루프, 한 대**. 실물·현장·현재 `main` 전체 이미지 수용이 아니다. `route_a`는 정적 실험 경로 `west:r → ring_s:f`를 썼다. 승인된 Fleet 활성 trip이나 다음 경로 조각을 받지 않았다.

## 재현 조건

- 전용 작업공간 `~/rosy_lfstop_ws`: 기본 소스 `65b15b9bb`에 로컬 `main`의 `lane_bev.py`, `lane_boundaries.py`, `route_camera.py`만 반영한 `control` 빌드. 두 실행의 앞 두 파일은 동일하다. 두 번째 실행에서만 `route_camera.py`를 `23d20fd03`의 버전으로 바꿨다. 두 번째 파일의 모델 PC SHA-256은 `356a7e0451f593fbe492a34cbfbf526b4efecdd626b628d813bdd599c6cc7c9d`로 로컬 파일과 일치했다.
- 같은 `map_v2_fleet_real` 월드, 카메라 320×240·8 Hz, 시작 `(-1.15, -0.511, 0)`, `camera_lane_mode=route_a`, `route_start=(-1.15,-0.511,0)`, `route=[west:r,ring_s:f]`, CORE `left:60`, `recovery_local_enabled=false`. [실행 파일](evidence/run_route_a_sim.sh)은 [D-495 하네스](../d495-junction-sim-2026-10-07/evidence/d495_real.launch.py)를 [정적 경로가 추가된 launch](evidence/d495_real.launch.py)로 실행하고, [녹화 파일](evidence/record_trip.sh)은 원본 영상·SIM 참 자세·명령과 CORE 시계열을 수집한다.
- 첫 실행 domain 98 / Gazebo partition `rosy_lane_route98` / CORE 8108, 두 번째 실행 domain 99 / `rosy_lane_route99` / 8109. 다른 세션의 Gazebo 인스턴스는 건드리지 않았다. 두 번째 실행 중 `ros2 topic info /cmd_vel -v`는 publisher **`/core` 하나**를 보였다. 두 실행 후 전용 launch·월드·포트가 종료된 것을 확인했다.
- 로컬 원본은 `X:/DevTemp/lane-route-ros-sim/first-trip-frames.npz`(SHA-256 `0da9e7b3dbdab67d69ebb5d3b5ccf9b7d1dc5b210e7bbe7116fc8acddfebf097`)와 `second-trip-frames.npz`(SHA-256 `866e02b1690b1aac55efb57dd9a5f3da24f5f809a5d0fc94ee6aa606dc2990ab`). 각 실행의 `*-trip-log.jsonl`·`*-trip-summary.json`도 같은 X: 폴더에 있다. 원본은 크기가 커서 저장소에 넣지 않았다.

두 번째 실행 재현(모델 PC의 위 전용 작업공간): 이 폴더의 `evidence/` 세 파일을 `~/rosy_lfstop_ws/route_a_sim/`에 복사하고, `control`의 `route_camera.py`를 `23d20fd03` 버전으로 둔다. 기존 D-495 보조 파일과 ROS 2 Jazzy 설치가 필요하다. 터미널 하나에서 `bash ~/rosy_lfstop_ws/route_a_sim/run_route_a_sim.sh camera_lane_mode:=route_a spawn_x:=-1.15 spawn_y:=-0.511 spawn_yaw:=0`으로 격리 SIM을 시작하고, CORE `/api/v1`이 응답한 뒤 다른 터미널에서 `bash ~/rosy_lfstop_ws/route_a_sim/record_trip.sh`을 실행한다. 재실행 시 `second_trip/` 출력은 먼저 별도 이름으로 보존한다. 두 스크립트는 다른 partition의 프로세스를 종료하지 않는다.

| 관측 | 수정 전 | 끝점 정지 수정 후 |
| --- | ---: | ---: |
| 마지막 텔레포트 후 영상 프레임 | 332 | 311 |
| CORE 기록의 이동 거리 | 1.1910 m | 1.0945 m |
| 최종 SIM 참 자세 (x, y, yaw) | (−0.1429, −0.1377, 1.6587) | (−0.2004, −0.2016, 0.1546) |
| 정적 경로 마지막 점 `(−0.1826, −0.1983)`까지 최종 거리 | 0.0725 m | 0.0181 m |
| 모든 지도 segment 중 가장 가까운 중심선 최대 거리 | 0.0477 m | 0.0478 m |
| 위 거리 > 0.040 m 프레임 | 28 | 28 |
| 교차로 지시 완료 | 0 | 0 |
| 종료 | `camera_reselection_required` LOST | `camera_reselection_required` LOST |

지도 거리 계산은 `analyze_network.py <frames.npz> middleware/perception/map/map_v2_fleet/lane_graph.yaml --start-index 83`(첫 실행), `--start-index 89`(둘째 실행)로 재현한다. 두 지표의 시작 인덱스는 각 녹화에서 마지막 텔레포트 직후다. 마지막 점 거리는 지도 `ring_s` 끝점과 각 `summary.json`의 최종 참 위치 사이 유클리드 거리다.

수정 전 저장 프레임의 오프라인 재판독에서는 끝점 뒤 카메라 tier가 `STOP`이어도 `MANOEUVRE` 후보가 남아 움직이는 프레임이 있었다. 수정 전 단위 재현은 마지막 점과 15 mm 앞에서 모두 실패했고, 수정 후 둘 다 `STOP`/후보 없음으로 통과했다. 두 번째 ROS-SIM의 마지막 `camera_line_not_visible` HOLD는 참 자세 `(−0.2004, −0.2016)`에서 시작해 LOST 때까지 위치가 유지됐다. 전체 실행은 독립적인 Gazebo run이라 경로 편차의 미세한 차이를 수정 효과로 귀속하지 않는다. 끝점 정지 효과는 단위 반례와 두 번째 폐루프 정지 위치로 제한해 판정한다.

호스트 검증: `test_route_camera.py` **29 passed**, `test_route_hybrid.py`·`test_line_observer_wiring.py`·`test_lane_tour.py` **74 passed, 10 skipped**; 각각 `test/known_failures.py` 결과 신규 실패 0. 이 수정은 경로 끝에서 관측 후보를 없애며 CORE의 명령 발행 경계는 바꾸지 않는다.

**판정: 끝점 초과 방지 PASS, 차선 추종 전체 HOLD.** 굽이와 ring 입구의 최대 중심선 편차 약 48 mm는 기존 호스트 시나리오의 40 mm 문턱을 넘고, 교차로 완료는 0건이다. 이 지도 경로는 실험자가 고정했고 10/6·10/7 원본의 동일 물리 경계 사람 승인 정답은 없다. Fleet 경로·지도 버전 권한, 벽/분기 음성 재생, 현장 위치·차체 외곽 여유, R1/R2 실물 수용을 별도로 확보해야 한다. D-520 지도 호 주행 설계의 구현·수용 결과로 취급하지 않는다.
