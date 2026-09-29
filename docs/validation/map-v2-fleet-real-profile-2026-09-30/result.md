# map_v2_fleet real-profile Gazebo bench (D-353 §5 prerequisite), 2026-09-30

증거 등급: **ROS-SIM (렌더 외형 비교)**. 장치·필드 수용이 아니다. 주행 합격 시험도 아니다.

## 무엇을 바꿨나

기존 260919 차선 시뮬(`map_v2_fleet_lane.launch.py`)은 25° 기울기, 320x180, hfov 66°, 렌즈 높이 0.060 m,
어두운 바닥의 흰 페인트, 푸른 회색 벽이다. 실제 Pinky 카메라(`camera_nominal_pinky_pro.yaml`)와 다르다.
기존 시뮬은 그대로 두고 real-profile 변형을 추가했다.

| 항목 | 기존 lap bench | real profile | 실제 (teleop_20260919_151213) |
|---|---|---|---|
| 해상도 | 320x180 | 320x240 | 320x240 |
| hfov | 1.1519 rad (66°) | 1.0334 rad (59.2°, fx 281.6) | fx 281.6 |
| 기울기 | 25° | 8° | 8° (horizon row 80.3) |
| 렌즈 높이 (front_camera_link) | 0.0602 m | 0.0670 m | 0.067 m (추정) |
| 렌즈 x (base_link 앞) | 0.0285 m | 0.0332 m | 0.034 (sim URDF prior) |
| 바닥 | 균일 0.2 회색 | 카펫 노이즈 텍스처 (256 px / 0.5 m 타일) | 회색 카펫 |
| 테이프 | 흰색 1.0 | 0.66 회색 (렌더 ~192) | ~186 |
| 벽 | 0.155 m 푸른 회색 | 0.30 m 흰색 + 파란 이음새 테이프 | 흰 폼보드 + 파란 테이프 |
| 카메라 fps | 5 | 8 | 8 |

- `src/sim/description`: xacro 인자 `camera_hfov`(기본 1.1519), `cam_mount_z`(기본 0.0495) 추가,
  `upload_robot.launch.py`와 `gz_sim/launch/launch_sim.launch.xml`로 전달. 기본값은 기존 동작과 같다.
- `map_v2_fleet/scripts/build_world.py`: 기존 `map_v2_fleet.world`는 바이트 동일, 추가로
  `worlds/map_v2_fleet_real.world`와 `textures/carpet_grey.png`(seed 260919, 결정적)를 쓴다.
  월드 이름은 `map_v2_fleet` 그대로라 `/world/map_v2_fleet/set_pose` 등 하네스가 그대로 쓴다.
- `gz_sim/launch/map_v2_fleet_real.launch.py`: 위 카메라 + line_observer는 `line_follow.yaml` 장치 기본값
  (ROI 0.40/1.0, washed 0.40, threshold 180)에 `camera_ground_source: GAZEBO` 선언 지오메트리만 덮어쓴다.
  `camera_lane_mode`는 문자열 인자(기본 `edge_left`, `keep` 등 아무 값).

## 재현

WSL Ubuntu (ROS 2 Jazzy, Gazebo Harmonic). 9p 복사는 느리므로(121 MB tar 추출 ~16분) 한 번만 한다.

```bash
# Windows (worktree root)
git archive --format=tar HEAD src > /x/DevTemp/sim-real-profile/src.tar
# WSL, HOME=/
mkdir -p /rosy_realprof_ws && tar -xf /mnt/x/DevTemp/sim-real-profile/src.tar -C /rosy_realprof_ws
cd /rosy_realprof_ws && source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-up-to gz_sim control core description
```

헤드리스 실행 (다른 sim과 겹치지 않게 domain/partition 분리):

```bash
cd /rosy_realprof_ws && source /opt/ros/jazzy/setup.bash && source install/setup.bash
export ROS_DOMAIN_ID=53 GZ_PARTITION=rosy_realprof
ros2 launch gz_sim map_v2_fleet_real.launch.py camera_lane_mode:=edge_left   # gazebo_gui:=false 기본
```

프레임 캡처 (위 launch를 스스로 띄우고, 차로 그래프 west/east 20자세로 순간이동, 종료 시 정리):

```bash
bash docs/validation/map-v2-fleet-real-profile-2026-09-30/run_capture.sh \
  /mnt/x/DevTemp/sim-real-profile/frames v3 map_v2_fleet_real.launch.py
```

실제 프레임과 비교 시트 (Windows):

```bash
ffmpeg -i "data/teleop/learning/teleop_20260919_151213_part01.mp4" -vf fps=0.2 X:/DevTemp/sim-real-profile/real/real_%02d.png
python docs/validation/map-v2-fleet-real-profile-2026-09-30/sheet.py X:/DevTemp/sim-real-profile/frames X:/DevTemp/sim-real-profile/sheet_real_vs_sim.png
```

## 결과 (run v3)

시트: `X:\DevTemp\sim-real-profile\sheet_real_vs_sim.png` (실제 20장 | sim 20장, 노란 선 = row 80).
실내 배경이 찍힌 실제 프레임이라 저장소에는 넣지 않았다.

| 지표 (20장 중앙값) | 실제 | sim v1 | sim v3 |
|---|---|---|---|
| 하단 띠 (rows 180-240) 회색 | 66.5 | 65.0 | 65.5 |
| 흰 벽 (rows 0-70, >150) | 209 | 199 | 214 |
| 테이프 (rows 120+, >150) | 186 | 226 | 192 |
| 카펫 표준편차 (rows 120+, <120) | 13.6 | 5.4 | 10.4 |

- 수평선: 먼 벽 밑단과 차선 소실점이 두 쪽 모두 row ~80에 있다(선언값 120 - 281.6·tan 8° = 80.4).
- 차선 원근·폭: 같은 거리의 차선 폭과 수렴 각이 눈으로 비슷하다. 정량 비교는 하지 않았다.
- 벽: 흰색이고 가까우면 화면 위쪽을 채운다. 실제처럼 흰 벽이 ROI(row 96 아래)에 들어오는 장면이 생긴다.
- 노드: gz, bridge, robot_state_publisher, line_observer_node, core가 오류 없이 떴다.

판정: 외형(수평선·밝기·카펫 질감·흰 벽)은 실제와 가깝다. 기존 25° 벤치보다 장치 대리로 훨씬 낫다.

## 남은 차이

- 실제 카메라의 흐림, 녹색 색조, 센서 노이즈, 자동 노출, 모션 블러가 없다. sim은 선명하다.
- 벽 위의 방(의자·사람·조명)이 없다. sim 배경은 균일한 적회색이다.
- 파란 테이프 배치는 이음새 추정이다(0.6 m 간격, 세로 12 cm). 실제의 대각선 조각은 없다.
- 벽은 STL 외곽 링 위치다. 실제 매트와 벽 사이 간격은 재지 않았다.
- 렌즈 높이 0.067 m는 추정값이다(`camera_nominal_pinky_pro.yaml`). 줄자 측정으로 바꿔야 한다.
- 이 벤치에서 주행(CAMERA_LINE) 합격은 아직 돌리지 않았다. 차선 모드 합격은 이 월드에서 다시 받아야 한다(D-205 P5).
