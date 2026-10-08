# 시작 위치 오차: 오프라인 차로 이탈 후보와 ROS-SIM 정지

2026-10-08의 고정 소스 `08d932fc1`로 기존 10/6·10/7 영상과 `route_a`의 시작 위치 오차를 다시 조사했다. [앞선 ROS-SIM 오차 기록](../lane-route-start-offset-sim-2026-10-08/result.md)에 이어 40 mm 상대 오차를 추가한 **후보 분석**이다. 오프라인 렌더러와 Gazebo의 장면은 다르며, 사람 승인 물리 경계나 실물 주행 정답은 없다.

## 녹화 영상 재생

원본 MCAP은 [10/7 출처 기록](../lane-1007-source-proof-2026-10-08/result.md) 및 [차선 논문 계약 검토](../../plans/2026-10-08-lane-papers-contract-fit.md)의 10/6 출처를 따른다. `road_replay.py --compare-boundary --pitch-deg 11.8`을 `20261006T091340Z_rosy_26` 642프레임과 `20261007T143038Z_rosy_60` 124프레임에 실행했다. 출력은 각각 `X:/DevTemp/lane-goal-20261008/pitch118-08d932fc1-1006-short/`와 `pitch118-08d932fc1-1007-first/`에 있다. `metrics.json` SHA-256은 순서대로 `06ade777871855c8ff80f88a25c02dcec6184087c001e252013b53f7fce02c73`, `9aba1d48356b580e56762796faf25b6ad82cf21f51d572f4d473dce4aebb7ac6`이다.

10/6은 `BOTH 0, ONE 7, MEMORY 100, STOP 535`; 처음 `BOTH`가 없는 107개 ONE/MEMORY 후보를 오프라인 게이트가 보류했다. RoadState는 642/642 STOP이었다. 10/7은 `BOTH 20, ONE 104, STOP 0`; RoadState는 13–123번 111프레임 TRACK이었다. 10/7의 `on_line_le_keep`, `on_paint_le_keep`, 직선 오차, NIS, coast 게이트는 여전히 실패한다. 두 결과 모두 `validated=false`다. 촬영 당시 보정 revision이 없어서 11.8°는 후보 가정이다. `--recorded-ground`는 첫 10/6 프레임에서 `missing or invalid ground projection`으로 거절됐다. 옛 영상에 없는 투영값을 소급해서 채우지 않았다.

## 동일 지도에서 시작 위치 오차 스윕

[오프라인 재현 스크립트](evidence/route_start_offset_offline.py)는 `SCENARIOS[11]`의 실제 시작 자세 `(-1.15,-0.511,0)`와 `west:r → ring_s:f`를 고정하고, `OdomError.start_offset_lateral_m`와 follower의 선언 시작 자세만 ±20/40/80 mm로 바꾼다. 원본 지도 페인트 렌더러와 기존 `run_scenario`/CORE 명령 법칙을 사용한다. 출력 `X:/DevTemp/lane-goal-20261008/route-start-offset-offline.json` SHA-256은 `5e5fd4d1b5c1aed70045bbda55b9ef08366169f4c55978a39ffce88bdbbb8591`이다.

| 선언 위치의 상대 횡오차 | 참 이동 거리 | 최대 지도 중심선 편차 | 결과 |
| ---: | ---: | ---: | --- |
| 0 mm | 1.0012 m | 35.6 mm | 경로 끝 도달 |
| +20 mm | 0.9877 m | 28.2 mm | 경로 끝 도달 |
| −20 mm | 1.0064 m | **40.1 mm** | 경로 끝 도달, 40 mm 목표 초과 |
| +40 mm | 0.9563 m | 24.8 mm | LOST |
| −40 mm | 1.0468 m | **60.0 mm** | 경로 끝 도달, 40 mm 목표 초과 |
| ±80 mm | 0 m | 1.1 mm | 출발 전 LOST |

이 수치는 **지도 중심선과 SIM 참 자세**의 거리다. 물리적 테이프 침범이나 실제 차체 여유의 판정이 아니다. ±80 mm에서 정지했다는 사실로 더 작은 오차의 안전성을 보간할 수 없다. 특히 −40 mm는 기존 오프라인 40 mm 경로 목표를 넘으면서 이동했다.

## +40 mm 실제 시작 ROS-SIM

상대 횡오차 −40 mm에 대응하도록 선언 `route_start=(-1.15,-0.511,0)`을 유지하고 Gazebo 참 시작을 북쪽 `(-1.15,-0.471,0)`으로 옮겼다. [앞선 끝점 시험](../lane-route-terminal-ros-sim-2026-10-08/result.md)과 같은 전용 `~/rosy_lfstop_ws`, 정적 경로, 지도 월드, CORE `left:60`, `recovery=false`를 사용했다. ROS domain 102, Gazebo partition `rosy_lane_route102`, CORE port 8112였다. 실행 명령은 `env PORT=8112 ROS_DOMAIN_ID=102 GZ_PARTITION=rosy_lane_route102 bash ~/rosy_lfstop_ws/route_a_sim/run_route_a_sim.sh camera_lane_mode:=route_a spawn_x:=-1.15 spawn_y:=-0.471 spawn_yaw:=0`이며, API 응답 후 [녹화 스크립트](evidence/record_offroute40_trip.sh)를 실행했다. ROS readback은 `route_start=[-1.15,-0.511,0]`, `camera_lane_mode=route_a`; `/cmd_vel` publisher는 `/core` 하나였다.

CORE 기록의 이동은 **0.0 m**, 최종 참 자세는 `(-1.15,-0.471)`, 결과는 `camera_reselection_required` LOST였다. 출발 후 `camera_line_not_visible` HOLD가 이어졌다. 원본 `X:/DevTemp/lane-route-ros-sim/offroute40-frames.npz` SHA-256은 `d5df2eb2d2154800b73f8667142f5fa9be47afa43e86af495b9c8d1b815c9e58`이며 같은 폴더에 `offroute40-summary.json`과 `offroute40-log.jsonl`을 보존했다. 실행 뒤 전용 launch PID와 포트 8112가 사라진 것을 확인했다. 이 전용 작업공간은 현재 전체 `main` 이미지가 아니다.

**판정:** 오프라인 −40 mm는 40 mm 중심선 목표를 넘는 반례이고, 별도 ROS-SIM +40 mm 실제 시작은 카메라 미검출로 정지했다. 두 장면은 같은 물리 입력의 통제 A/B가 아니므로 어느 결과도 다른 결과를 무효화하지 않는다. 정적 `route_start`만으로 실제 지도 위치의 권한을 증명할 수 없다. 활성 Fleet 지도·신선한 독립 위치·차체 여유와 10/6·10/7 사람 검수 동일 경계가 확보되기 전 운영 주행 허가는 계속 HOLD다. CORE 단일 명령 경계는 ROS-SIM에서 유지됐다.
