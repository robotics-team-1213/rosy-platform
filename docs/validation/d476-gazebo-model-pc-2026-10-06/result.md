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

> 2차 실행(아래 「2차 실행: sim 센서 보강 뒤」, 브랜치 `feat/sim-sensor-fidelity`)에서 sim 공백을 sim 전용으로
> 닫았다. D-468은 이제 sim에서 움직이지만(센서 탐색 회전, Fleet 요청) 이 트랙에서는 차로 안 여유가 D-468 기준
> 0.015 m에 닿지 않아 bridge가 여전히 무장되지 않는다. A·B·C 모두 **INCONCLUSIVE**(bridge 0 틱). 남은 원인은 sim이
> 아니라 D-468 기하 조건이다.

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

## 2차 실행: sim 센서 보강 뒤 (같은 날, 브랜치 `feat/sim-sensor-fidelity`)

증거 등급은 같다: **ROS-SIM (폐루프, 한 대)**. 장치·필드 수용이 아니다. 모델 PC의 별도 clone에 이 브랜치를
git bundle로 가져와 `gz_sim core control description`만 다시 빌드했다. 실행은 `evidence/run_sim.sh`의
`SIMSENS=1`(아래 2.4)이다. run별 요약은 `evidence/runs2/summary.json`, 원시 기록은 저장소 밖 작업 디렉터리에 있다.

### 2.1 1차 발견 2의 셋째 원인: 벽시계 모드의 `obstacle_ahead` 230 틱

원인은 시계도 bridge도 아니고 **D-422 근접점 기억(`BodyStopMixin._remember_near`)의 정지 중 래치**다.

- 증거: 1차 `wall_mode_default`의 `nav.line_obstacle_hold` 사건이 `clearance_source: memory`, `body_gap_m: 0.0`을
  남겼다. `obstacle_ahead`가 시작된 틱마다 LiDAR 최소값이 0.0563 m 또는 정확히 0.05000000074 m(float32 0.05,
  `range_min`)였다. 그 자리(기본 출발)는 몸 옆면에서 벽까지 0.074 m이고, Gazebo LiDAR 잡음은 σ 0.02 m다.
  Gazebo는 `range_min` 아래로 떨어진 값을 `range_min`으로 돌려준다.
- 기제: 기억은 `range_min + 0.05` 안의 점을 저장하고, 다음 스캔에서 그 점이 `range_min`보다 가까우면 계속 둔다.
  로봇이 서 있으면 주행 거리계가 늘지 않아 저장된 점이 지평(`obstacle_path_horizon_m`)을 넘지 않는다. 정확히
  `range_min`에 놓인 점은 `(px + lidar_x) - lidar_x`의 부동소수 반올림 때문에 640 빔 방향 가운데 92개에서
  `range_min`보다 조금 작게 다시 계산된다. LiDAR 반경 0.05 m 안의 점은 언제나 몸 윤곽 안이므로 `body_gap 0`이고,
  서 있는 한 영영 풀리지 않는다.
- 호스트 재현: 실제 `LineFollowManager`(Pinky URDF 몸, path 모드)에 0.08 m 옆벽 스캔을 주고, 한 번만 그 각도의
  빔을 `range_min`으로 넣으면 그 틱은 `clearance_source lidar`, 다음 틱부터 깨끗한 스캔 40개 내내
  `HOLD obstacle_ahead`, `clearance_source memory`, `gap 0.0`, 기억 점 1개였다. 1차의 벽시계 shim과 무관하다.
  sim 시간 실행에서도 같은 값이 나오면 같은 래치가 생긴다(2차 `C_corner_*`에서 LiDAR 최소 0.050, `obstacle_ahead`
  짧게 10 틱).
- 분류: `line_follow/body_stop.py`는 `platform_parts.yaml`의 safety 모듈이라 이 브랜치에서 고치지 않았다
  (Safety-Review 필요). 장치에서도 C1이 정확히 `range_min`을 내고 로봇이 서 있으면 같은 래치가 가능하다.
  확인과 수정은 별도 작업이다.

### 2.2 sim 전용 보강 (장치 기본값 그대로)

| 공백 | 바꾼 것 | 켜는 곳 | 장치가 그대로인 이유 |
|---|---|---|---|
| worker가 sim `/scan`을 버림 | `is_simulation_scan`이 공용 Gazebo 모델 모양(640 빔, `range_max` 12, `<ns>rplidar_link`)도 받는다. `SafetyNode`의 새 파라미터 `accept_simulation_scans`(기본 false)가 `enable_simulation_scans`를 부르고, `use_sim_time`이 아니면 시작을 거부한다 | CORE overlay `control.sensor_adapter.simulation_sensors: true` → `resolve_safety_params(simulation=True)`가 worker에 `accept_simulation_scans`, `imu_angular_velocity_unit rad_s`, `use_sim_time`을 넘긴다 | 플래그가 없으면 파라미터가 아예 없다(리비전도 같음). overlay 허용 키가 아니어서 장치 overlay로 넣을 수 없다. `use_sim_time` 없이 플래그를 쓰면 CORE가 시작을 거부한다. C1은 `range_max` 40이라 sim 모양과 겹치지 않는다 |
| 정책 시계 불일치 | `bind_lane_return_motion(..., policy_clock)`: `use_sim_time`이면 D-468 바닥 증명은 worker 정책을 `time.monotonic`(정책 창과 `SafetyManager`의 시계)으로 묻고, 몸 sweep은 line clock(sim 초)에 둔다 | `node.py`가 `use_sim_time`으로 고른다 | 장치는 `policy_clock=None`, `now`를 그대로 넘긴다(전과 같음) |
| IMU 없음 | 모델의 기존 Gazebo IMU(`imu_raw`)를 둘째 bridge로 가져온다 | `launch_sim.launch.xml sim_sensors:=true` | 기본 false. Gazebo 모델 파일만 바뀐다 |
| IR 없음 | URDF IR 링크 셋(`ir_l/ir_mid/ir_r_link`, 바닥 위 0.013 m)에 아래를 보는 한 줄 `gpu_lidar`. `scripts/sim_ir_floor.py`가 장치와 같은 `ir_sensor/range`(`UInt16MultiArray` [left, mid, right])로 바꾼다: 바닥 ≤ 0.05 m → 2000, 없음 → 100(worker가 유효로 받는 0 < v < 4000 안이고 `cliff_raw_max` 800 아래), 세 채널이 모두 들어오기 전에는 내지 않는다. 반사율(테이프·카펫)은 모델링하지 않는다 | 같은 `sim_sensors:=true` | 기본 false |
| Gazebo LiDAR 각도 | `[-π, π]` 양끝 포함 640 빔(증분 2π/639)이 D-468 `return_scan_view`의 한 바퀴 검사에 걸려 모든 스캔이 거부됐다. `max_angle = π − 2π/640` | 늘 (Gazebo 모델) | Gazebo 모델 파일만 바뀐다 |
| 차로 투영 불확실도 | `containment_payload`가 늘 `uncertainty_m None`을 보내 D-468이 `projection_uncertainty_unknown`으로 첫 프레임부터 이탈을 열었다. `GAZEBO` 지면(`allow_simulation_ground`에서만 생김)은 카메라 기하가 정확하므로 검출기 측면 오차 `GAZEBO_DETECTOR_LATERAL_PX × max_range / fx`(2 px, 0.6 m, 281.6 px → 4.3 mm)를 낸다. 2 px는 측정값이 아닌 휴리스틱이다 | GAZEBO 지면일 때만 | NOMINAL·CALIBRATED는 여전히 `None` |

`evidence/sim_wall_shims.py`, `evidence/d476_real.launch.py`(1차 벽시계 모드)와 `evidence/d476_probe.py`는 이 기록의
고정 증거다. 실행 경로가 아니다. sim 센서는 `launch_sim.launch.xml sim_sensors:=true`(단일 로봇만, bridge 토픽에 namespace가
없다)가 대신한다.

sim overlay 조각은 `gz_sim config/sim_sensors_core.yaml`(enforce, `required [lidar, imu, ir]`,
`simulation_sensors true`)이고 `run_sim.sh SIMSENS=1`이 overlay 끝에 붙인다. 장치 설정(`contracts/foundation/config`,
`middleware/apps/device`, `deploy`)에 `simulation_sensors`가 없다는 것은 시험이 고정한다.

확인한 것(모델 PC): `/imu_raw` 100 Hz, `/ir_sim/mid` 0.0127 m(URDF 0.013 m), `/ir_sensor/range` [2000, 2000, 2000],
`cliff clear`, worker의 `no lidar` 경고 0회, 스캔 증분 0.0098175(2π/640). 임시 진단 로그(모델 PC clone에서만, 되돌림)로
D-468 바닥 증명이 sim에서 서는 것을 봤다: 정책 창이 monotonic, `floor_observed True`, 직진·후진 후보 `sensor True`.

### 2.3 결과 (`SIMSENS=1`)

| run | 시나리오 | 출발 (gt) | 이동 / 회전 (gt) | TRACKING 틱 | bridge 틱 | 끝 사유 | LOST | 최소 벽 거리 (gt / LiDAR) |
|---|---|---|---|---|---|---|---|---|
| `A_round_1` | A. bridge 끔 | 회전교차로 (−0.585, −0.12, 1.571) | 0.009 m / 0.43 rad | 2 | 0 | 3.48 s `lane_return_sensor_search`(±0.15 rad/s) 뒤 `lane_return_fleet_required` | 없음 | 0.420 / 0.422 m |
| `B_round_1..3` | B. bridge 켬 | 같음 | 0.0075–0.0077 m / 0.42 rad | 2–4 | 0 | 3.46–3.50 s 같은 흐름 | 없음 | 0.419 / 0.406–0.420 m |
| `C_corner_1..2` | C. bridge 켬 | 기본 출발 (−1.270, 0.243, −1.571) | 0 m | 0 | 0 | 40 s 내내 `HOLD lane_return_space_or_floor_unconfirmed` | 없음 | 0.074 / 0.050–0.054 m |
| `ref_simsens_corner` | 참고: D-468 끔 | 기본 출발 | 0.570 m | 443 | 0 | 60 s 추종(`obstacle_ahead` 12 틱) | 없음 | 0.072 / 0.053 m |

A_round_1은 차로 불확실도 커밋 전 빌드, B·C·참고는 그 뒤 빌드다. 회전교차로에서는 두 빌드의 D-468 근거가 같다
(`complete_corridor_unconfirmed`, 아래).

- **A: INCONCLUSIVE.** D-468 기준선은 이제 sim에서 동작한다(±0.15 rad/s 센서 탐색 회전 뒤 3.5 s에 후보 소진으로 Fleet 요청). 하지만 차로 상실
  자리까지 추종하지 못해 손실 뒤 bridge 거리·시간을 비교할 기준선이 없다.
- **B: INCONCLUSIVE (3회).** bridge가 무장되지 않았다. 무장 조건은 직전 틱 D-468 `tracking` + `TRACKING`인데,
  D-468 근거가 run마다 search·fleet 단계 내내 `complete_corridor_unconfirmed`(run당 546–550틱)(회전교차로 원호에서 양쪽 경계가 함께 잡히지 않음)였다.
- **C: INCONCLUSIVE (2회).** D-468 근거는 `ready`였지만 몸이 차로 안에 있는 여유가 0.001 m(불확실도 4.3 mm를 뺀 값)로
  추종 단계 기준 0.015 m에 못 미쳐 첫 프레임에서 이탈이 열렸다. 그 자리에서 제자리 회전 원(0.0826 m + 여유)이 옆벽
  (중심에서 0.13 m, LiDAR 잡음으로 0.08 m까지)에 걸려 `(0, 0)` 바닥·공간 증명이 서지 않는다. 벽 접촉은 없다(움직이지
  않았다). 남쪽 차로 중심 출발(`A_south_3`, 벽 여유 0.059 m)도 여유 −0.099 m로 같은 HOLD였다.
- **D: 하지 않음.** bridge가 어디서도 무장되지 않으므로 도색 공백 월드는 의미가 없다.
- **참고:** sim 센서와 enforce를 켠 채 D-468을 끄면 추종은 된다(60 s에 0.57 m). 1차 참고 run(정책 꺼짐)보다 느리다.
  enforce 정책의 제한(벽 옆에서 `can_rotate False` → 회전 성분 `motion_limited`)으로 보이며 이 실행에서는 따로
  나누지 않았다.

### 2.4 발견 (2차)

1. **D-468 기하 조건 (장치에도 해당):** D-468 추종 단계는 몸이 차로 경계 안쪽으로 양쪽 0.015 m(체크포인트는
   0.025 m) 여유를 요구한다. 260919 트랙(이 월드는 그 STL)에서 Pinky(폭 0.113 m)가 차로 중심에 있을 때 측정된 여유는
   불확실도 전 0.005 m 수준이다. 따라서 이 트랙에서는 D-468이 첫 프레임에 이탈을 열고, D-476 bridge는 무장될 수 없다.
   불확실도를 0으로 둬도 기준에 닿지 않는다. sim 충실도 문제가 아니다. 결정은 D-468/D-476 쪽이다(차로 폭 기준 또는
   몸 기준 재검토). 이 브랜치는 bridge·D-468 논리를 고치지 않았다.
2. **D-468 투영 불확실도 (장치에도 해당):** 생산 쪽 `containment_payload`는 NOMINAL·CALIBRATED에서 늘
   `uncertainty_m None`을 보내고 D-468은 그것을 `projection_uncertainty_unknown`으로 거부한다. 측정된 투영 오차 한계가
   생기기 전에는 장치에서 `recovery_local_enabled`를 켜면 CAMERA_LINE이 첫 프레임부터 이탈 HOLD다(1차 발견 1과 같은
   결론, 다른 원인).
3. **D-422 근접점 기억 래치 (2.1, safety 모듈):** 서 있는 로봇에서 `range_min`에 걸린 빔 하나가 `obstacle_ahead`를
   영구히 만든다. Safety-Review가 필요한 별도 수정이다.
4. **사건 홍수:** D-468이 `lane_return_fleet_required`로 서 있는 동안 같은 `stuck_id`의 `nav.line_stuck_asked`
   (`reason opened`)가 틱마다 나온다. `A_round_1` 36 s에 711건, `B_round_1` 26 s에 516건(약 20 건/s). 콘솔이 없는
   sim이지만 장치에서도 같은 경로다.
5. **bridge 코드 결함은 이번에도 찾지 못했다.** bridge가 진입하지 않았으므로 결함이 없다는 증거도 아니다.

### 2.5 재현 (2차)

```bash
# 모델 PC, 작업공간 ~/rosy_d476_ws (src/rosy-platform -> 이 브랜치 clone). 빌드:
colcon build --symlink-install --packages-select gz_sim core control description \
  --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
SIMSENS=1 BRIDGE=0 bash evidence/run_sim.sh                  # A
SIMSENS=1 BRIDGE=1 bash evidence/run_sim.sh                  # B, C
RECOVERY=false SIMSENS=1 BRIDGE=0 bash evidence/run_sim.sh   # 참고
python3 evidence/d476_probe.py run --x -0.585 --y -0.12 --yaw 1.5708 --out runs2/B_round_1 --duration 30
python3 evidence/d476_probe.py run --x -1.26955 --y 0.24255 --yaw -1.5708 --out runs2/C_corner_1 --duration 40
```

모델 PC의 sim 프로세스는 모두 멈췄고 임시 진단 패치는 되돌렸다. GPU 학습은 돌고 있지 않았다(사용률 0 %).

> 리뷰 반영(2차 실행 뒤, 시뮬 재실행 없음): `CLIFF_RAW` 0 → 100(0은 worker에서 무효 IR이라 절벽 분기를 시험하지
> 못했다), 세 채널이 모두 들어온 뒤에만 프레임 발행, 채널 순서를 장치(`ir_adc_node.py` [ch2, ch1, ch0] = 좌·중·우)에
> 고정, `GAZEBO_DETECTOR_LATERAL_PX` 이름. 2.3의 run은 바닥 위에서만 돌아 IR 값이 늘 2000이었으므로 결과는 그대로다.
