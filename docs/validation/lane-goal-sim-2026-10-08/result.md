# 차선 추종 주행 목표: B9 굽이 후보와 현재 CORE의 결합 재생

2026-10-08, 모델 PC의 독립 `~/rosy_bend_window_ws`에서 시행했다. 소스는 `feat/bend-window-sim`의 `3a6586947`이다. 이 브랜치는 현재 main의 CORE 기대 창 가드와 미착지 B9 keeper를 SIM용으로만 합쳤다. B9의 `bend_expected`는 장치 기본값 `false`이며, 이 실험에서만 `sitecustomize.py`로 켰다. ROS domain 81, Gazebo partition `rosy_bws`, CORE port 8101을 썼고 종료 뒤 이 partition의 프로세스를 멈췄다.

| 재생 | 결과 | 해석 |
|---|---|---|
| `bw1`, `trip --plan left:60` | 굽이 전 x≈−0.951 m에서 첫 `no_boundary`; 33프레임 지속 뒤 x≈−0.948 m에서 `LOST_between_junctions`. 차로 중심 오프셋 중앙값 +0.0196 m(32프레임). 분기 지시는 `armed`, 소비 0 | 굽이 통과 실패. 보이지 않는 구간에 진입할 근거가 없으므로 STOP은 맞는 안전 결과다. [프로브](bw1-summary.json), [분석](analysis.json). |
| `bw2`, 같은 경로 | 굽이 평가 창 0프레임. x≈−1.271 m에서 LOST, 종료 때 프로브 Python이 core dump | 굽이 후보의 성공·실패 표본에서 제외. 재현 환경도 별도 조사 대상이다. [분석](analysis.json). |

이 프로브의 `/api/v1/line-follow/junction` 요청에는 `map_id`와 기대 창이 없다. 따라서 `bw1`의 지시 미소비를 CORE의 새 **지도 지시 기대 창 가드 검증**으로 해석할 수 없다. 그 가드는 소스 회귀 시험에서만 확인했다. 이 실험으로 확인된 것은 B9를 강제로 켜도 굽이 전 경계 공백이 남는다는 점이다. 앞선 B9 단독 SIM은 6회 중 0회 통과했고, 이번 결과는 이를 통과로 바꾸는 근거가 없다.

다음 gate는 (1) Fleet 경로의 굽이 장소·기대 창을 CORE와 keeper에 시각·지도 ID를 묶어 전달하고, (2) 앞서 검증한 같은 차로 경계와 신선한 오돔·차체 여유가 있는 짧은 구간에서만 공백 접근을 허용하며, (3) 기대 창 밖 분기·벽·오래된 오돔에서는 정지하는 것이다. 이 계약과 10/6·10/7 영상의 사람 승인 동일 경계 정답이 갖춰지기 전에는 B9 게이트를 장치에 연결하지 않는다. CORE만 최종 `cmd_vel`을 낸다. 이번 증거는 ROS-SIM이며 장치·현장 수용이 아니다.

## 기존 오돔 경계 기억기와 비교

같은 `bw1`의 원본 영상·GT odom 293프레임을 변경 없는 `LaneEdgeFollower`에 오프라인으로 넣었다. B9 keeper가 첫 굽이 공백에서 `no_boundary`가 된 프레임 260(x≈−0.951, y≈−0.491)에도 이 기억기는 목표 후보를 냈다. 이 프레임의 B9 후보에는 굽이 모양 선 하나만 남고 양쪽 차로 경계 목표는 없다. 기억기의 후보는 사람 승인 동일 경계가 아니므로 곧바로 주행 근거로 쓸 수 없다.

`camera_lane_mode=edge_left`로 바꾼 **별도** 폐루프 SIM의 결과도 분리했다. 서쪽 출발 `edge1`은 첫 모서리 전에 `obstacle_ahead`로 정지해 굽이 평가 표본이 아니다([프로브](edge1-summary.json)). 남쪽 직선 중앙 x=−1.15, y=−0.511, yaw=0에서 출발한 `edge_south1`은 굽이 구간 x=−0.95…−0.78을 지나갔다. 그 구간 23프레임의 west edge 지도 중심선 거리 중앙값 0.001 m, 최대 0.0037 m였다. 그러나 `left:60` 교차로 결과는 하나도 없고, 이후 지도 west edge 중심선 거리 최대 0.1738 m(재출발 뒤 487프레임 중 51프레임 >0.04 m, 19프레임 >0.0925 m)였다. 이 거리는 **west edge 기준**이며 다른 edge 가까이에 있을 수 있어 물리적 차선 침범 판정은 아니다. 마지막은 x≈−0.677, y≈+0.488에서 `obstacle_ahead` HOLD였다([프로브](edge-south1-summary.json)). 프로브 Python은 요약을 쓴 뒤 종료 중 core dump를 냈으므로 재현 환경도 조사해야 한다.

원본 `frames.npz`는 모델 PC `~/rosy_bend_window_ws/b9runs/{bw1,edge_south1}/rec/`와 X: `DevTemp/bend-window-sim/`에 있다. SHA-256: `bw1-frames.npz` AAF96E3B2813DE4937E47258B570F5A6EE9A4FDE7ED30679E07AEB212D6C4DDF, `edge-south1-frames.npz` 6F068DAA8184D9FDA6F6BF9F894A32AEBB07D9BB80126ADC82E77FB29122B1D4. 실험은 종료했고 전용 Gazebo 프로세스를 멈췄다.

거리 수치는 저장소 루트에서 `python docs/validation/lane-goal-sim-2026-10-08/analyze_edge.py X:/DevTemp/bend-window-sim/edge-south1-frames.npz middleware/perception/map/map_v2_fleet/lane_graph.yaml --start-index 75`로 재계산한다. 75는 마지막 남쪽 직선 텔레포트 뒤의 첫 프레임이다. 이 계산은 지도 중심선과의 거리이며 실제 페인트·장애물 검수는 아니다.

**결정:** 기억기가 한 굽이를 통과한 점은 다음 후보를 정하는 증거지만, 현재 `edge_left`를 trip 주행으로 대체하지 않는다. Fleet 지도에는 `bend` 장소 종류가 없고 굽이는 edge polyline에 있다. 지도 버전·현재 edge·굽이까지의 거리 창·신선한 odom을 결합한 단서를 만들고, 같은 경계의 검수와 벽/분기 음성 재생을 통과한 뒤에만 keeper의 `bend_expected` 및 짧은 기억 경로를 연결한다. D-476 bridge는 현재 좌회전 지시에서 거부되고 `reselection_required`를 처리하지 않으므로 설정만 켜서 이 공백을 해결했다고 보지 않는다.
