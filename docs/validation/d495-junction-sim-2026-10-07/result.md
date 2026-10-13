# D-495/D-498 교차로 회전 SIM 수용 (모델 PC), 2026-10-07

증거 등급: **ROS-SIM (폐루프, 한 대)**. 장치·현장 수용이 아니다. Gazebo·ROS는 모델 PC(Ubuntu 24.04, ROS 2 Jazzy,
RTX 5080, 24코어)에서만 돌렸다. 이 노트북에서는 돌리지 않았다. 실물 로봇은 건드리지 않았다.

- 제품 코드: 브랜치 `test/d495-junction-sim-acceptance`의 기준 `432445eed`(그날 main). CORE·perception 코드는 바꾸지 않았다.
  모델 PC clone에 원인 확인용 `print` 세 줄(`junction.py`, `lane_return_evidence.py`, `odometry.py`)을 20:15–21:10에
  잠시 넣었다가 되돌렸다(`git status` 깨끗함 확인). 동작은 바꾸지 않는다.
- 하네스(이 폴더 `evidence/`): 커밋 `16ab771b5`, `829f563ca`, `57459adc7`, `c2a445470`, `e2d4ceaaa`와 이 기록 커밋.
- 같은 시간에 다른 세션이 같은 모델 PC에서 D-476 sim(`~/rosy_d476_ws`, 도메인 76, 포트 8095)을 돌렸다. 이 실행은
  도메인 77, `GZ_PARTITION rosy_d495`, 포트 8097, 다른 이름의 world 파일로 분리했다(아래 「하네스」 4).

## 판정 요약

| 항목 | 판정 | 한 줄 |
|---|---|---|
| 설정: 로봇 기본값(`recovery_local_enabled: true`) 그대로 | **BLOCKED** | enforce가 아니면 CAMERA_LINE이 출발하지 못한다. 60 s 동안 이동 0 m, 537틱 중 498틱 `HOLD lane_return_space_or_floor_unconfirmed` (발견 1) |
| 능력 `junction_turn` | PASS | 현장 겹(IR 가드·path·URDF 몸·`junction_turn_site_accepted`)에서 모든 run 끝에 `true`. `SITE=0`이면 `false`이고 회전은 `aborted motion_unconfirmed` |
| S1 bridge로 교차로 직진 | **FAIL** | bridge 진입 0틱(전체 run). 직진 지시는 `executing` 뒤 3 s에 LOST (발견 5, 7) |
| S2 좌·우 회전 | **FAIL** | 회전 정확도는 통과(완료된 회전 9건 오차 −4.08…+2.75°, 모두 ±5° 안). 재획득 0/9: `unresolved` 5, 벽 `near_stop` 2, 주입 중단 2. idle 뒤 재감지 항목은 회전이 끝나지 않아 시험하지 못함 (발견 5, 6) |
| S3 지시 없음 | PASS | `junction_waiting` HOLD, 3.06 s 뒤 LOST. 2 s 늦은 지시는 회전, 5 s 늦은 지시는 `aborted stuck` |
| S4 stop / bridge 없이 | PASS | `stop`(0)은 즉시 HOLD, `stop@0.3`은 참값 0.3045 m에서 멈춤, `stop@2.0`은 교차로에서 멈춤(3/4, 1건은 교차로 전 LOST). bridge 끈 직진은 LOST |
| S5 중단 뒤 재전송 / 재선택 | PASS(부분) | 회전 중 장애물 중단 뒤 같은 지시 → 진입 방향 기준 −107.68°(목표 −110°, +2.32°). 전진 중 odom 끊김 → CAMERA_LINE 재선택 → 같은 지시 409 `JUNCTION_ALREADY_DONE`. 반대 방향 지시는 200 `armed`이고 회전하지 않음(교차로가 시야 밖이라 `aborted odom` 경로까지 가지 않음) |
| S6 완료 뒤 재전송 | **INCONCLUSIVE** | 재획득으로 끝난 회전이 없어 시험 조건을 만들 수 없었다. `unresolved` 뒤 같은 지시는 200으로 받아진다 (발견 4) |
| S7 현장 근거 회전의 IR 중단 횟수 | PASS(한계) | 9개 동작(좌 60, 우 −110, 우 −150 포함)에서 IR 때문인 `turn_basis_lost`·`lane_departure` 0회. 단, 점 IR 모형에서는 선을 직각으로 넘어도 `centre`가 나오지 않는다 (발견 9) |
| S8 회전 원·전진 경로 장애물 | PASS | 3/3 `near_stop`. 마지막 비영 명령 뒤 다음 명령 주기(20 ms)에 0, 그 뒤 비영 명령 없음 |
| S9 회전 중 IR·스캔 낡음 | PASS | IR 2/2 `turn_basis_lost`(+0.27, +0.30 s), 스캔 1/1 `turn_basis_lost`(+0.48 s). 다음 주기에 0. 스캔 1건은 시작 전 발견 3으로 중단 |

## 설정

- 월드: `map_v2_fleet_real`(실물 카메라 기하) 한 대, `camera_lane_mode: keep`. `use_sim_time`, RTF 약 1, 카메라 8 Hz 320×240.
- launch: `evidence/d495_real.launch.py`. 제품 `map_v2_fleet_real.launch.py`와 다른 점은 셋이다.
  1. line_observer 파라미터는 페이로드 `line_follow.yaml` 다음에 IR 보정(`ir_calibration_enabled`, black 600, white 2600)만 더한다.
     `lane_corner_turning`(true)·`camera_x_offset_m`(0.03317)은 페이로드 값 그대로다(H1). 실행 중 `line/keep_debug`가
     `corner_turning: true`, `camera_geometry_source: GAZEBO`를 실었다.
  2. Gazebo scan/odom을 `scan_gz`/`odom_gz`로 받고 `evidence/d495_sim_aux.py`가 다시 낸다(장애 주입용 멈춤, odom 순서 보정).
  3. world 파일을 다른 이름으로 복사해 띄운다(옆 세션의 `pkill`이 맞지 않게).
- CORE 겹(`ROSY_CONFIG`, 문서화된 겹 경로) = `gz_sim config/map_v2_fleet_core.yaml`(포트만 8097) + 아래. 센서 어댑터는 없음(꺼짐, 장치와 같음).
  몸 기하와 `obstacle_mode: path`는 `pinky_pro` 로봇 패키지 `core.yaml`에서 온다.

  ```yaml
  line_follow:
    obstacle_mode: path
    recovery_local_enabled: false   # 발견 1 때문에. 첫 run(explore_rec_on)만 true
    ir_guard_enabled: true
    junction_turn_site_accepted: true   # SITE=0 run만 false
    bridge_enabled: true                # BRIDGE=0 run만 false
    bridge_site_no_dropoffs: true
  ```

- IR: `sim_ir_floor.py`는 바닥/절벽만 모형화해 IR 가드가 늘 `clear`가 된다. 그래서 `d495_sim_aux.py`가 Gazebo 참값 자세와
  지도 도색 raster(`PaintMap`, 월드와 같은 STL)로 IR 세 점(URDF IR 줄 x 0.0295 m, y +0.020/0/−0.020)을 계산해 장치 모양
  `ir_sensor/range`(20 Hz, 테이프 2600, 카펫 600)로 낸다. 점 센서·이진 반사율·잡음 없음이다.

## 하네스

`evidence/d495_sim_probe.py`는 CORE HTTP API만으로 몬다(`PUT /line-follow/mode`, `POST /line-follow/junction`,
`GET /line-follow`, `GET /system/capabilities`). 기록은 10 Hz 상태·`/odom`·참값(`d495/gt`)·IR, 모든 `/cmd_vel`,
`keep_debug` HOLD 사유 전이다. `trip`은 지시 목록을 미리 무장(완료 직후 다음 지시, 만료 30 s 전 20 s마다 다시 보냄)하거나
`--reactive --late s`로 늦게 보낸다. `fault`는 회전·전진 중에 상자(gz create, 높이 0.25 m)·odom/IR/스캔 멈춤을 넣고
재전송·재선택을 한다.

실행 중 고친 하네스 결함(제품 코드 아님):

1. 끝난 launch가 남긴 `parameter_bridge` 셋이 odom을 같은 stamp로 세 번 냈다. CORE PoseTrail이 끊겨 회전이 `odom`으로
   중단됐다. `run_sim.sh`가 같은 `GZ_PARTITION`의 프로세스를 모두 끝낸다. 오염된 `explore_1`, `x2`는 판정에 쓰지 않았다.
2. odom stamp가 CORE가 마지막으로 본 `/clock`보다 1 ms 앞서는 일이 있어 PoseTrail이 계속 리셋됐다(발견 2). aux가 odom을
   `/clock`이 stamp+10 ms를 지난 뒤 낸다. `sw_r110_5`부터 모든 회전 run이 이 보정 뒤다.
3. 교차로 정지 기록(진입 방향)은 OFF와 순간이동을 지나서도 남는다(N2 설계). `set_pose` 전에 교차로가 안 보이는 곳에서
   CAMERA_LINE을 sim 4 s 켜서 끝낸다.
4. 옆 D-476 세션이 `pkill -f "gz sim.*map_v2_fleet_real.world"`를 하므로 world를 다른 이름으로 띄우고 포트·도메인을 바꿨다.

## 결과

### 교차로 위치와 정지 거리

이 지도의 keep 모드 교차로 감지는 두 곳에서만 재현됐다.

| 자리 | keeper 사유 | 정지 위치 | 비고 |
|---|---|---|---|
| 남서 굽이 (−0.73, −0.44), 진행 방향 약 8° | `junction_fork` | 몸 앞에서 다음 도색까지 0.11–0.15 m | lane_graph에서는 분기가 아닌 굽이다(발견 5) |
| 남서 spoke → 회전교차로 (−0.655, −0.432, 64°) | `junction_transverse` | 회전교차로 가로선이 몸 앞 0.346 m | 이 자리에 놓으면 매번 바로 감지됨. S2–S9를 여기서 돌렸다 |

회전교차로 안(−0.336, −0.251)과 남쪽 길 중간(−1.10, −0.509)에서는 keeper가 `no_boundary`라 차선 주행이 안 됐다.

정지 거리(trip 루프 부록 4항): 굽이로 들어오는 속도가 0.012–0.026 m/s(곡선·IR 가드 감속)라서, keeper의 첫 사유
(`flipping` 또는 `junction_fork`)에서 odom 정지까지 참값 이동 0.000–0.0021 m, 0.08–0.34 s(15회). 교차로 정지
위치는 "첫 감지 자리"이고, 몸 앞에서 가로선까지는 굽이 0.11–0.15 m, spoke 0.346 m다. `stop_after_m` 0.3은 참값
0.3045 m에서 섰다(+4.5 mm). 순항 속도(0.08 m/s)로 곧게 들어오는 교차로가 이 지도에 없어 그 정지 거리는 재지 못했다.

### S2 회전 정확도 (현장 근거, `sw_r110_5` 이후, 참값 yaw)

| run | 지시 | 돈 각도 (참값 / odom) | 오차 | 회전 시간 | 다음 단계 결과 |
|---|---|---|---|---|---|
| sw_r110_5 | right −110 | −107.31 / −107.31 | +2.69 | 4.53 s | 전진 0.07 m에서 벽 `near_stop` |
| s6_unresolved_resend | right −110, advance 0 | −107.38 / −107.38 | +2.62 | 4.59 s | `unresolved` |
| s5_box_resend (재전송 뒤) | right −110 | −107.68 (진입 기준) | +2.32 | — | `unresolved` |
| s2_sw_r150 | right −150 | −147.25 / −147.25 | +2.75 | 5.78 s | 전진 중 벽 `near_stop` |
| s2_sw_l60 | left 60 | 57.37 / 57.37 | −2.63 | 2.82 s | `unresolved` |
| s5_odom_adv_reselect | left 60 | 57.95 | −2.05 | 2.88 s | 전진 중 주입 |
| s8_box_adv | left 60 | 57.88 | −2.12 | 2.84 s | 전진 중 주입 |
| s3_sw_late2 | left 60 (2 s 늦게) | 57.85 | −2.15 | 2.66 s | `unresolved` |
| s3_bend_late | left 60 (굽이, 3.4 s 늦게) | 55.92 / 56.33 | −4.08 | 3.48 s | `unresolved` |

모든 회전이 목표보다 2–4° 덜 돈다(±5° 안에서 멈추고 머무름). Gazebo는 −0.6 rad/s 명령에 −0.515 rad/s로 돈다.

### S5–S9 장애 주입 (명령 0까지)

| run | 주입 (때) | 중단 사유 | 주입 → 첫 0 명령 | 마지막 비영 → 0 | 뒤 비영 명령 |
|---|---|---|---|---|---|
| s5_box_resend | 회전 원 상자 (20°) | `near_stop` | 0.125 s | 0.022 s | 0 |
| s8_box_turn_2 | 회전 원 상자 (21.9°) | `near_stop` | 0.106 s | 0.023 s | 0 |
| s8_box_adv | 전진 경로 0.13 m 앞 상자 | `near_stop` | 0.081 s | 0.019 s | 0 |
| s9_ir_turn | IR 멈춤 (20.7°) | `turn_basis_lost` | 0.295 s | 0.024 s | 0 |
| s9_ir_turn_2 | IR 멈춤 (22.2°) | `turn_basis_lost` | 0.268 s | 0.020 s | 0 |
| s9_scan_turn_3 | 스캔 멈춤 (22.5°) | `turn_basis_lost` | 0.480 s | 0.020 s | 0 |
| s5_odom_adv_reselect | 전진 중 odom 멈춤 | `odom` | 0.316 s | 0.019 s | 0 |

명령 주기는 20 ms다. 지연은 근거의 낡음 한도(IR 0.3 s, 스캔 0.5 s, odom 0.3 s)와 LiDAR 주기(상자)에서 온다.
중단 뒤 로봇은 관성으로 3–5° 더 돈다.

### S7 IR 판정 (동작 중 10 Hz 표본)

`s2_sw_l60` 전진·재획득에서 IR이 left → left+mid → 세 개 → mid+right → right로 안쪽 선을 직각으로 넘었다. 판정은
left, left, clear, right, right였고 `centre`는 한 번도 없었다. `s3_bend_late` 회전 중 left 17표본, `sw_r110_5` 전진 중
left·세 개 각 2표본. 9개 동작 모두 IR 때문인 중단 0회.

## 발견 (결함 후보, 이 브랜치에서 고치지 않음)

1. **로봇 기본값으로는 차선 주행이 출발하지 않는다 (결정/설정, 장치에도 해당).** `rosy_default.yaml:157`
   `recovery_local_enabled: true`(D-495 결정 개정 2)이고 센서 어댑터가 enforce가 아니면, D-468이 첫 프레임에 이탈을 열고
   (이 트랙에서 차로 안 여유 부족, D-476 기록 2.4-1) 그 뒤 단계가 바닥 증명을 요구한다
   (`lane_return.py:326-327` `space_or_floor_unconfirmed`, 증명은 `control_sensor_adapter.py:330-333`에서 enforce가 아니면 false).
   재현: `RECOVERY=true bash evidence/run_sim.sh` 뒤 `d495_sim_probe.py trip --plan ""` (`explore_rec_on`: 60 s, 0 m).
   D-498 현장 근거는 enforce 없이 회전을 열지만, 같은 로봇 기본값에서는 차선 주행 자체가 서 있다. 이 SIM의 나머지는
   `recovery_local_enabled: false`로 돌렸다. 기본값과 D-498 순서를 다시 정해야 한다.
2. **odom 음수 나이에 PoseTrail 리셋 (코드, sim에서 드러남).** `lane_return_evidence.py:52` `if not 0 <= age <= .3: self.reset()`은
   stamp가 CORE 시계보다 1 ms만 앞서도 궤적을 지우고 epoch를 올린다. 그러면 회전·전진이 `odom`으로 중단된다
   (`junction.py:343-345`, 시작은 `318-320`·`331-332`). 진단 출력에서 `pose age -0.001`이 약 2분에 4번, epoch가 25분에 330이었다.
   관측 경로(`manager.py:159-161`)는 −0.1 s까지 받는다. 같은 호스트 장치 시계에서는 드물지만, sim 시계나 다른 호스트의
   odom에서는 회전을 막는다. 하네스는 odom을 10 ms 늦춰 우회했다.
3. **CAMERA_LINE 선택 직후의 회전 지시가 `odom`으로 중단된다 (코드, 장치에도 해당).** `set_mode`가 `_reset_lane_return()`
   (`manager.py:115`)으로 PoseTrail을 비운다. 교차로가 이미 보이는 자리에서 첫 odom 표본(30 Hz면 최대 33 ms)이 오기 전에
   무장된 회전이 감지되면 `_start_turn`이 기다리지 않고 `aborted odom`이다(`junction.py:318-320`). 재현: 교차로 앞에 선
   로봇에 `PUT mode CAMERA_LINE` 뒤 곧바로 `POST junction right turn_deg −110`. odom 보정 뒤 SW 자리에서 3번
   (`s2_sw_r110_a0`, `s9_scan_turn`, `s9_scan_turn_2`). Fleet trip 루프는 CAMERA_LINE을 확인한 뒤 바로 지시를 보낸다.
4. **`unresolved`는 실행된 지시로 기록되지 않는다 (코드 읽기, sim 재현 안 됨).** `_mark_done`은 `_abort`, `straight` 통과,
   재획득 완료에서만 불린다. 재획득 단계의 `unresolved`(`junction.py:347-352`, `363-366`, `397-400`)는 부르지 않는다.
   그리고 진입 방향은 재획득에 들어갈 때 지운다(`junction.py:390`). 그래서 회전을 마치고 재획득에 실패한 뒤 같은
   (`place_id`, `action`)을 다시 보내면 200으로 받아진다(`s6_unresolved_resend`). 교차로가 다시 보이면 새 방향에서 또
   돈다. 이번에는 교차로가 시야 밖이라 돌지 않았다. R1의 "회전 뒤 단계에서 끊긴 회전"에 `unresolved`를 넣을지 정해야 한다.
5. **keep keeper의 굽이 오감지와 `flipping` (인식, S1·S2를 막음).** 남서 굽이(lane_graph에서는 분기 아님)에 15번 들어갔다.
   8번은 `flipping`만 내고 LOST였다. 5번은 `flipping` 0.49–0.62 s 뒤 `junction_fork`였고, 그래서 회전이
   `lane_lost_before_junction`(M8, `junction.py:321-326`)으로 중단됐다. `junction_fork`가 곧바로 나온 것은 2번이다.
   `lane_corner_turning` 기본 켜짐이면 Fleet이 장소로 모르는 굽이에서 `junction_waiting` 뒤 3 s에 LOST다.
6. **교차로 정지 자리와 회전 축의 기하 (S2를 막음).** 로봇은 교차로를 처음 본 자리(가로선 0.11–0.35 m 앞)에서 서고 그 자리에서
   돈다. 전진은 최대 0.30 m다. 회전교차로 쪽 우회전은 벽을 향해 `near_stop`, 좌회전과 0 전진 우회전은 차선을 다시 잡지 못한다
   (`camera_line_not_visible` 3 s 뒤 `unresolved`). 굽이 회전 뒤에는 다음 교차로(회전교차로)가 바로 보여 keeper가 다시 HOLD한다.
   재획득 성공 0/9.
7. **bridge가 무장되지 않는다.** 모든 run에서 `lane_bridge` 0틱이다. 아래 길에서 로봇이 차로 중심보다 약 0.05 m 왼쪽(참값 y −0.462,
   중심 −0.509)으로 달리고, IR 가드 `lane_edge_left`(전체 504틱)로 좌우로 흔들려 rev 1 무장 조건(|error| ≤ 0.1,
   |ω| ≤ 0.08, `tracking` 3프레임)이 굽이 전에 서지 않는다. 교차로 앞에 놓은 run은 추종 이력이 없다.
8. **D-422 근접점 기억 래치 (알려진 것, safety 모듈).** `x8`(117 s), `bend_left_1`, `bs_b`에서 서 있는 로봇이
   `obstacle_ahead`, `clearance_source: memory`, `body_gap_m 0.0`, `stop_gap_m 0.0347`로 묶였다. D-476 기록 2.1과 같다.
   교차로 정지는 서 있는 정지라 회전·출발을 막을 수 있다.
9. **IR 울타리는 직각으로 넘는 선을 못 본다 (sim 모형 기준).** 센서 간격 20 mm, 테이프 25 mm인 점 센서에서는 직각으로
   넘을 때 `centre`(가운데만)가 나오지 않는다. 판정은 left → clear(세 개) → right다(`s2_sw_l60`). D-498 검토 M2의 약점을
   SIM에서 확인했다. 실기 IR 점 크기에서는 다를 수 있으므로 DEVICE D9에서 잰다.

## 한계

- 호스트 SIM은 DEVICE가 아니다. IR은 점·이진 모형, LiDAR 잡음 σ 0.02 m, Gazebo 회전 응답(−0.6 → −0.515 rad/s)이 실기와 다르다.
- 판정에 쓴 회전 run은 같은 SW 자리에서 순간이동으로 시작했다. 교차로까지 주행해 들어온 회전은 굽이 한 곳뿐이다.
- 회전교차로 안, 순항 속도 직진 교차로, 여러 교차로 trip 한 바퀴(ADR S1 원문)는 이 지도와 keep 모드에서 만들 수 없었다.
- S5의 "반대 방향 지시 → `aborted odom`"은 교차로가 시야 밖이라 `armed`로 남았다. 회전하지 않은 것만 확인했다.

## 재현

```bash
# 모델 PC. 작업공간 ~/rosy_d495_ws (src/rosy-platform = 이 브랜치 git bundle clone)
colcon build --symlink-install --packages-up-to gz_sim core control description \
  --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
# CORE Python 의존성은 작업공간 pydeps (D-476 작업공간에서 복사), evidence/ 를 ~/rosy_d495_ws/evidence 로 복사
RECOVERY=false nohup bash evidence/run_sim.sh &          # BRIDGE=0, SITE=0, RECOVERY=true 변형
# 다른 셸: source ROS + install, ROS_DOMAIN_ID=77 GZ_PARTITION=rosy_d495
python3 evidence/d495_sim_probe.py trip --plan left:60 --out runs/bl --duration 100            # 굽이
python3 evidence/d495_sim_probe.py trip --plan right:-110 --x -0.655 --y -0.432 --yaw 1.12 --out runs/sw
python3 evidence/d495_sim_probe.py fault --plan right:-110/0.0 --inject box_turn --then resend \
  --x -0.655 --y -0.432 --yaw 1.12 --out runs/s5
python3 evidence/d495_sim_probe.py fault --plan left:60 --inject odom_advance --then reselect ...
python3 evidence/d495_sim_probe.py fault --plan right:-110/0.0 --inject ir_turn|scan_turn ...
python3 evidence/d495_sim_probe.py trip --plan left:60 --reactive --late 5.0 ...                # S3
```

`evidence/runs/<run>/summary.json`에 판정에 쓴 run 40개의 요약만 두었다. 원시 기록(`log.jsonl`, `cmd.jsonl`,
`keep.jsonl`, `actions.jsonl`, `events.jsonl`, 모든 run)은 저장소 밖 `X:\DevTemp\d495-sim\d495_runs_full.tgz`
(1,400,139 bytes, sha256 `aa0cf90fe53c707d31570cd92d886ae76ab2f1347bd143d98056e26bba37a379`)와 모델 PC
`~/rosy_d495_ws/runs`에 있다. 모델 PC의 이 sim 프로세스는 모두 멈췄고 GPU 사용률은 0 %였다.
