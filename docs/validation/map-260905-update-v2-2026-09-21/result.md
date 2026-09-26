# map_260905_update_v2 실제 Gazebo 매핑 검증

검증일: 2026-09-21 KST
실행 ID: `20260921T_map260905_final_22`

## 결론

설치된 `map_260905_update_v2/worlds/map_260905.world`에서 단일 Pinky Pro 모델이
52개 관측 waypoint를 모두 주행하고 live LiDAR SLAM 지도를 저장했다. 본체 반경을
반영한 spawn 연결 구성공간에서 unknown, occupied, outside-raster 표본이 모두
`0.0%`이므로 실제로 갈 수 있는 영역의 매핑은 완료로 판정한다.

왼쪽 아래 밀폐 포켓은 본체가 들어갈 수 없는 별도 free-space component다. 전체
내부 픽셀 기준 unknown `1.9241%`는 이 포켓을 포함한 값이며, 이를 숨기거나
완주 경로에 억지로 포함하지 않는다.

## 같은 실행에서 확인한 결과

| 항목 | 결과 |
|---|---:|
| Route | 52/52, complete |
| 주행 거리 | `13.754679 m` |
| 로봇 직경 | `0.172 m` |
| 최소 중심-벽 거리 | `0.107789 m` |
| 최소 표본 본체 여유 | `0.021789 m` |
| 표본 충돌 중첩 | `false` |
| 본체 접근 가능 unknown | `0.0%` |
| 본체 접근 가능 occupied | `0.0%` |
| 본체 접근 가능 outside raster | `0.0%` |
| 연결 점 공간 unknown | `0.0%` |
| 알려진 통로 순도 | `97.5183%` |
| 최소 벽 표면 recall | `85.0365%` |
| phantom occupied | `0.2469%` |
| 지도 | `141 x 69`, `0.02 m/cell` |
| Fleet | `online=true`, `map_id=occupancy:326966090e60` |
| 최종 CORE 상태 | `NAVIGATION/IDLE`, linear/angular `0/0` |
| 최종 `cmd_vel` publisher | 1개, `/rosy_01/core` |

`map_raster_complete=false`는 밀폐 포켓과 98% 벽 recall을 요구하는 정적 전체
래스터 지표다. 운용 합격은 별도 필드인 `robot_reachable_mapping_complete=true`와
`connected_mapping_complete=true`로 판단한다.

## 적응 속도와 recovery

- 이동 명령 최대값: `0.158851 m/s`
- 좁은 구간 이동 속도 median: `0.067975 m/s`
- 열린 구간 이동 속도 median: `0.122453 m/s`
- 회전 속도 최대값: `0.6 rad/s`
- accepted run recovery 발생: `0`

속도는 전후 LiDAR 여유, 본체 직경, 곡률에 따라 매 tick 줄어든다. 목표가 실제
후방에 있으면 좁은 곳에서 U-turn을 강요하지 않고 후진 방향을 선택한다. 회전
여유가 사라진 경우 후방 가용 거리와 직경으로 reposition 거리를 계산하므로
8 cm 고정 상한은 없다. 단, `final_22`에서는 주행 경로 자체가 안전해 recovery가
실제로 발동하지 않았으며, 8 cm 초과 계산과 전방위 회전 fail-close는 회귀 시험
증거다.

## SLAM 재현성 결정

Gazebo `OdometryPublisher`의 model pose를 `/odom` 권위 소스로 사용하고 wheel
적분 odom은 `/odom_wheel` 진단으로 분리했다. 반복되는 10 mm 벽에서 scan matcher가
정확한 simulation odom을 인접 벽에 잘못 맞춰 유령 벽을 만들 수 있으므로,
simulation SLAM은 `use_scan_matching=false`, `do_loop_closing=false`로 live scan을
권위 odom pose에 직접 누적한다. 실기기 설정을 이 결정으로 바꾸지 않는다.

## 경계

- 이 결과는 Gazebo Harmonic, ROS 2 Jazzy 컨테이너의 ROS-SIM 합격이다.
- 실제 Pinky Pro의 직경, 휠 slip, LiDAR/카메라 외부 파라미터, 정지거리, Pi image,
  물리 충돌과 FIELD 무인 운용을 증명하지 않는다.
- 카메라 homography 후보는 여전히 독립 사진/실측 거리/고정 마운트 검증 전에는
  활성화할 수 없다.
- 원시 rosbag과 PNG는 용량 때문에 Git에 넣지 않고 동일 worktree의
  `evidence/map-260905-live/20260921T_map260905_final_22/`에 보존한다.
