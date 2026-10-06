# D-476 예상 도로 bridge Gazebo 검증 (모델 PC), 2026-10-06

증거 등급: **ROS-SIM (폐루프, 한 대)**. 장치·필드 수용이 아니다. 코드는 origin/main `a05c16338`
(D-476 구현 `9455dccc0` 포함) 그대로이며 CORE·perception 코드는 바꾸지 않았다. 시뮬레이션은 모델 PC
(Ubuntu 24.04, ROS 2 Jazzy, RTX 5080)에서만 돌렸다. 이 노트북에서는 Gazebo·ROS를 돌리지 않았다.

## 판정 요약

| 시나리오 | 판정 | 한 줄 |
|---|---|---|
| A. OFF 기준 (`bridge_enabled false`, `recovery_local_enabled true`) | **INCONCLUSIVE** | 로봇이 출발하지 못한다. D-468 중재가 첫 틱부터 `HOLD lane_return_space_or_floor_unconfirmed` (25 s, 이동 0 m) |
| B. ON, 같은 자리 | **INCONCLUSIVE** | A와 같다. `TRACKING`을 한 번도 거치지 않아 bridge가 무장(`armed`)되지 않는다. `lane_bridge` 0 틱 |
| C. ON, 벽 모서리 차로 끝 | **INCONCLUSIVE** | A와 같은 이유로 모서리까지 가지 못했다 |
| D. 도색 공백 월드 | 하지 않음 | A–C가 움직이지 않아 월드 편집은 의미가 없었다 |
| 참고: D-468 전 동작 (`recovery_local_enabled false`) | 측정함 | 손실 → 즉시 HOLD → LOST 2.98 / 3.02 s (sim), 손실 뒤 이동 ≤ 0.0001 m |

bridge 자체의 거리·시간 상한, 막힘 정지, 벽 여유는 **이 sim에서 한 번도 실행되지 않았다**. 결함은 bridge 코드가
아니라 bridge가 서는 전제(D-468 동작 증명)가 sim에서 성립하지 않는다는 것이다. 아래 발견 1·2.

## 무엇을 돌렸나

- 월드: `map_v2_fleet_real.launch.py camera_lane_mode:=keep` (실물 카메라 기하, 흰 둘레 벽 4면), 로봇 한 대.
  `ROS_DOMAIN_ID 76`, `GZ_PARTITION rosy_d476`, RTF 0.99–1.02. 카메라는 `gz sim -s`(헤드리스 서버) 그대로
  렌더링됐다(7.7 Hz, 320×240). `DISPLAY`·`--headless-rendering`은 필요 없었다. 로그에 `libEGL warning: egl:
  failed to create dri2 screen`이 남지만 프레임은 정상이다(`evidence`에는 넣지 않음).
- CORE overlay (sim 전용, `evidence/run_sim.sh`): `api_port 8095`, `line_follow.recovery_local_enabled`
  (`RECOVERY`, 기본 true), `line_follow.bridge_enabled` (`BRIDGE`). 나머지 bridge 값은 기본(`lookahead 0.10`,
  `coast 0.10`, `slow 0.25`, `slow_scale 0.5`, `distance_scale 1.08`, `time_margin 0.5`, `lost_after_s 3.0`).
  몸 기하와 `obstacle_mode: path`는 `pinky_pro` 로봇 패키지 `core.yaml`(URDF 공칭)에서 장치와 같은 경로로 들어왔다.
- 기록: `evidence/d476_probe.py run` — `gz service set_pose`로 출발 자세를 놓고 `PUT /line-follow/mode
  {CAMERA_LINE, hold_s 0.5}`, `POST /hold` 10 Hz. 10 Hz로 CORE 상태(state, reason), `/odom`, Gazebo 참값 자세
  (`gz topic -e .../dynamic_pose/info --json-output`의 `rosy`), `/cmd_vel`, LiDAR 최소 거리, 사건을 남긴다.
  벽 참값 거리는 몸 footprint 네 모서리(앞 0.042, 뒤 −0.076, 반폭 0.0566)에서 둘레 벽 안쪽 면(x ±1.400,
  y ±0.625)까지의 최소값이다.
- 출발 자세: 회전교차로 서쪽 원호 (−0.585, −0.12, yaw 1.5708; D-407 B2와 같은 차선 상실 자리),
  기본 출발 (−1.26955, 0.24255, yaw −1.5708; 좌하 L 모서리 방향).
- 작업공간: 모델 PC의 별도 clone + colcon 작업공간. CORE의 Python 의존성(fastapi, pydantic, uvicorn,
  websockets; `deploy/robot/pinky_pro/requirements-core.txt`)은 시스템 python에 pip가 없어 작업공간 안
  `--target` 디렉터리에 두고, `rosy.*` 네임스페이스 패키지(`contracts/*/src`)는 `PYTHONPATH`로 넣었다
  (`run_sim.sh` 주석).

## 결과

### 1. 기본 sim (`ENFORCE=0`, 장치와 같은 `control.sensor_adapter` 꺼짐)

| run | overlay | 결과 |
|---|---|---|
| `stock_bridge_off` | recovery true, bridge false | 216 틱 / 24.9 s: `HOLD lane_return_space_or_floor_unconfirmed` 208, `lane_return_pose_stale` 6, `containment_unconfirmed` 1. 참값 이동 0.0 m, 0이 아닌 `cmd_vel` 0 |
| `stock_bridge_on` | recovery true, bridge true | 217 틱 / 24.9 s: `space_or_floor_unconfirmed` 205, `pose_stale` 10. 이동 0.0 m, `lane_bridge` 0 틱 |

차선은 보이고 containment 증거도 들어온다(`containment_unconfirmed`는 첫 틱뿐). 그런데 D-468
`ReturnController`가 정상 추종 단계에서도 바닥 증명(`floor_safe`)을 요구하고(`lane_return.py:287`), 그 증명
`bind_lane_return_motion` → `ControlSensorAdapter.return_sensor_allowed`는 `mode != 'enforce'`이면 늘
false다(`control_sensor_adapter.py:325`). 그래서 `TRACKING`이 한 번도 나오지 않고, bridge 무장 조건
(직전 틱 D-468 `tracking` + `TRACKING`)도 성립하지 않는다.

### 2. enforce 시도 (`ENFORCE=1`, 벽시계 모드)

enforce를 켜도 기본 sim에서는 증명이 서지 않는다. 막는 것이 셋이었다.

1. CORE 안의 safety worker는 sim `/scan`을 버린다(`is_robot_scan`: sim 시각 stamp, 640빔, `range_max 12`;
   로그 `drop remote /scan`, `no lidar — motion disabled until scan`). CORE에는 `enable_simulation_scans`를
   부르는 곳이 없다.
2. Gazebo에는 IR·IMU가 없다(`required: [lidar, imu, ir]`).
3. 시계 영역이 다르다. `use_sim_time`이면 CORE line clock은 sim 초(`traffic_gate.line_clock`)인데 worker의
   정책 snapshot은 `time.monotonic`이다(`command_gate.evaluate`: `observed_at <= now <= expires_at`). 장치에서는
   둘 다 monotonic이다.

`d476_real.launch.py`(sim 전용 launch 사본)와 `sim_wall_shims.py`로 CORE만 벽시계에 두고, Gazebo의
scan/odom/camera를 `*_gz`로 받아 벽시계 stamp로 다시 내보내고(scan `range_max` 40), IR [2000×3]·정지 IMU를
합성했다. 그 뒤 worker는 LiDAR를 받고(`no lidar` 경고가 멈춤), 별도 프로세스로 띄운 같은 worker의
`sensor_state`는 `profile_valid True`, `observation_failure None`, `floor_observed True`, `obstacle False`,
`can_rotate False`였다. 그래도 CORE 결과는 `wall_mode_default`(기본 출발, 275 틱 / 30 s):
`HOLD obstacle_ahead` 230, `lane_return_space_or_floor_unconfirmed` 43, 이동 0 m 였다. 앞 벽까지 0.87 m인
자리에서 나온 `obstacle_ahead`의 원인과 CORE 안 증명이 왜 서지 않는지는 시간 상한(90분)까지 확인하지 못했다.
`can_rotate False`는 회전 후보(`turn_clear`)를 막지만, `space_or_floor_unconfirmed`는 `(0,0)` 증명
(`floor_safe`) 쪽이라 이것만으로 설명되지 않는다. 중간 시도(line_observer도 벽시계)에서는 `simulation_ground_plane`이
`use_sim_time` 없이 GAZEBO 바닥을 거부해 차선이 안 보였다(`camera_line_not_visible` → D-407 후진 2회, 참값 0.157 m).
그래서 line_observer는 sim 시간에 두었다.

### 3. 참고: D-468 전 동작 (`RECOVERY=false`, 기본 sim)

| run | 손실 | 흐름 (sim 시각) | LOST | 손실 뒤 이동 (참값) | 최소 벽 거리 (참값 / LiDAR) |
|---|---|---|---|---|---|
| `ref_round_1` | (−0.580, −0.072), `camera_line_not_visible` | 15.431 HOLD → 18.413 LOST | 2.982 s | 0.0000 m | 0.467 / 0.467 m |
| `ref_round_2` | (−0.580, −0.072), 같은 사유 | 28.839 HOLD → 31.863 LOST | 3.024 s | 0.0001 m | 0.467 / 0.458 m |
| `ref_corner_1` | 기본 출발 → L 모서리 `obstacle_ahead` 3회(각 0.3–0.4 s) 뒤 통과, (−0.77, −0.44)에서 `camera_line_not_visible` | 186.211 HOLD → 189.223 LOST | 3.012 s (손실 뒤) | — | 모서리 회전 중 0.049 / 0.058 m (TRACKING 중, 접촉 없음) |

회전교차로 차선 상실은 두 번 모두 같은 자리에서 났고, 손실 틱에 영 twist, `lost_after_s` 3.0 s에 맞춰
`LOST camera_reselection_required` 다. bridge가 동작한다면 이 자리가 B의 진입 후보다.

## 발견

1. **배포 전제 (장치에도 해당): D-476은 지금 장치 설정에서 켤 수 없다.** D-476은 D-468 중재 안에서만 돌고
   (`recovery_local_enabled: true`), D-468은 정상 추종까지 `return_sensor_allowed`를 요구하며, 그 값은
   `control.sensor_adapter.mode: enforce`에서만 true가 될 수 있다. 장치 기본은 꺼짐(`rosy_default.yaml`에
   mode 없음)이고 D-400은 plan 3 전에는 enforce를 하지 않는다. 따라서 장치에서 `recovery_local_enabled`를 켜면
   CAMERA_LINE이 출발하지 못하고(이 sim의 `stock_*`와 같은 `HOLD lane_return_space_or_floor_unconfirmed`),
   `bridge_enabled`는 효과가 없다. D-476 결정 7의 장치 단계는 D-400 enforce 뒤에만 의미가 있다.
2. **sim 공백: D-468/D-476 동작 증명은 이 Gazebo 구성에서 성립할 수 없다(코드 변경 없이).** 위 2절의 세 가지
   (sim scan 거부, IR·IMU 없음, sim 시간 line clock 대 monotonic 정책 snapshot). 셋째는 `use_sim_time`일 때만의
   시계 불일치로, 장치 동작과는 무관하지만 D-476 결정 7 2단계(시뮬)를 막는다. 해결은 코드 쪽 결정이다(예: sim에서
   worker가 sim scan을 받게 하고 정책 시계를 line clock과 맞추기, Gazebo IR/IMU 센서). 이 검증에서는 고치지 않았다.
3. **bridge 코드 결함은 찾지 못했다.** bridge가 한 번도 진입하지 않았으므로 결함이 없다는 증거도 아니다.

## 시험하지 못한 것

- bridge 진입·거리(≤ 0.25 m × 1.08)·시간(≤ 2.5 s) 상한, `lane_bridge_blocked`, `lane_bridge_motion_unconfirmed`,
  재획득 → FOLLOW, D-468 인계, 벽 접촉 여부. 모두 발견 2 해결 뒤 다시 돌린다.
- 도색 공백 월드(D).

## 재현

```bash
# 모델 PC. 작업공간 ~/rosy_d476_ws (src/rosy-platform -> clone, colcon build --symlink-install
#   --packages-up-to gz_sim core control --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3)
# evidence/ 를 $WS/evidence 로 복사. tmux 안에서:
RECOVERY=false ENFORCE=0 BRIDGE=0 bash evidence/run_sim.sh   # 참고 (D-468 전)
ENFORCE=0 BRIDGE=1 bash evidence/run_sim.sh                  # 기본 sim, bridge 켬 (발견 1)
ENFORCE=1 BRIDGE=1 bash evidence/run_sim.sh                  # 벽시계 모드 (발견 2)
# 다른 셸 (ROS_DOMAIN_ID=76 GZ_PARTITION=rosy_d476, ROS 환경 source):
python3 evidence/d476_probe.py run --x -0.585 --y -0.12 --yaw 1.5708 --out runs/ref_round_1 --duration 40
python3 evidence/d476_probe.py run --x -1.26955 --y 0.24255 --yaw -1.5708 --out runs/ref_corner_1 --duration 60
python3 evidence/d476_probe.py summary runs/ref_round_1
```

`evidence/runs/`에는 run별 `summary.json`과 overlay 두 개만 두었다. 원시 기록(`log.jsonl`, `events.jsonl`,
`launch.log`)은 저장소 밖 작업 디렉터리에 있다. 모델 PC의 sim 프로세스는 모두 멈췄다.
