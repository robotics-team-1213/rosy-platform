# D-476 rev 1 Gazebo 검증과 G-16 원인 (모델 PC), 2026-10-07

증거 등급: **ROS-SIM (폐루프, 한 대)**. 장치·필드 수용이 아니다. 코드는 로컬 main commit `6c1e9855d`(D-476 개정 1,
D-468 containment 안쪽 가장자리 producer, `sim_sensors` 포함) 그대로이고 제품 코드는 바꾸지 않았다. 시뮬레이션은
모델 PC(Ubuntu 24.04, ROS 2 Jazzy)에서만 돌렸다. 이 노트북에서는 Gazebo·ROS를 돌리지 않았다(G-16 프레임 재생
`evidence/g16_fit_trace.py`는 ROS 없는 Python이다). 앞선 기록은 [`d476-gazebo-model-pc-2026-10-06`](../d476-gazebo-model-pc-2026-10-06/result.md)이다.

## 판정 요약

| 항목 | 판정 | 한 줄 |
|---|---|---|
| G-16 (차로 여유 약 5 mm 대 STL 23.4 mm) | **원인 확인 (제품 코드)** | 마스크·투영·카메라 자세는 맞다. 경계선 **기울기** 오차를 D-468이 몸 뒤끝까지 0.25–0.3 m 외삽해서 생긴다. 기울기 오차는 화면 아래 모서리의 도색 잘림과 횡단보도 blob 제거 띠가 만든다 |
| A. bridge 끔 기준선 | 기록함 | 회전교차로: `HOLD junction_waiting` → 3.0 s 뒤 `LOST`. 모서리: 대각선 진입 회전 중 손실 → 3.0 s 뒤 `LOST` |
| B. 회전교차로, bridge 켬 (4회) | **INCONCLUSIVE** | 무장 안 됨. 원호 추종 `|angular|` 0.147 > `bridge_arm_max_angular` 0.08. `straight` 지시(3회)도 `LOST`로 끝남 |
| C. 벽 모서리, bridge 켬 (6회) | **INCONCLUSIVE** | 무장 안 됨(손실 직전 회전 0.5–0.6 rad/s, 또는 0.082–0.086). 2회는 `obstacle_ahead` 래치로 정지. 접촉 없음 |
| C'. 차로 끝 벽 앞 (D 월드 `Db_on_2`, 1회) | **PASS (1회)** | bridge 0.118 m(gt) 1.78 s 뒤 D-422 `obstacle_ahead`로 정지, 몸 앞–북쪽 벽 약 0.146 m, LOST 시계 그대로(손실부터 2.97 s) |
| D. 도색 공백 0.15 m, enforce (3회) | **INCONCLUSIVE** | 1회 무장 → `HOLD lane_bridge_motion_unconfirmed`(워커 바닥 증명 거절) → `LOST`. 2회는 무장 안 됨 |
| D. 도색 공백 0.15 m, 경로 (b) (3회 + `straight` 2회) | **PASS** | 공백이 만든 손실마다 bridge 0.024–0.028 m(0.35 s) → `TRACKING` 재획득(5/5). OFF는 같은 자리에서 `LOST`(3.1 s) |

RTF는 모든 run에서 0.997–1.003이다. 다른 세션의 D-495 sim이 같은 모델 PC에서 다른 domain·partition으로 함께 돌았다.

## 무엇을 돌렸나

- 월드: `map_v2_fleet_real.launch.py camera_lane_mode:=keep sim_sensors:=true`(260919 실물 프로필), 로봇 한 대.
  `ROS_DOMAIN_ID 76`, `GZ_PARTITION rosy_d476`. 실행은 `evidence/run_sim.sh`(설치된 launch를 작업 디렉터리에 복사해
  고친다. 소스는 그대로).
- CORE overlay(sim 전용): `recovery_local_enabled false`(rev 1은 D-468 없이 무장한다), `bridge_enabled`,
  `ir_guard_enabled true`, `bridge_site_no_dropoffs true`(벽으로 둘러싼 sim 매트에는 바닥 끝이 없다).
  `ENFORCE=1`(기본)이면 `gz_sim config/sim_sensors_core.yaml`(enforce, lidar/imu/ir)을 붙여 rev 1 경로 (a)
  (bridge 명령마다 워커 바닥 증명)를 탄다. `ENFORCE=0`은 그 조각을 빼서 sensor adapter 꺼짐(오늘 장치와 같음),
  경로 (b)(사이트 수용만, 바닥 증명 없음)를 탄다.
- IR 가드: launch 사본이 line_observer에 IR 보정(black 100, white 4000)을 준다. 없으면 IR_LINE이 보정 없는 관측이라
  가드가 `stale`(= `HOLD lane_guard_stale`)이다. `sim_ir_floor`는 바닥 유무만 모델링해서 매트 위에서 늘 2000이다.
  그래서 이 sim에서 IR 가드는 언제나 `clear`다. 이탈을 잡는지도, D-491 횡단보도 오작동도 시험할 수 없다
  (이번 run 어디에도 `lane_guard_*`·`lane_departure` 틱이 없다).
- 기록: `evidence/d476_probe.py`(앞 기록 probe의 복사본. 요약에 RTF, (state, reason)별 틱 수, `stuck_id`별
  `nav.line_stuck_asked` 수, bridge 구간별 거리·시간·끝 사유를 더했고, 선택으로 첫 `junction_waiting`에 D-494 지시를
  한 번 보낸다). 10 Hz로 CORE 상태, `/odom`, Gazebo 참값 자세, LiDAR 최소, 사건을 남긴다.
- 도색 공백 월드: `evidence/make_gap_world.py`가 `map_v2_fleet_real.world` 사본에 카펫 재질의 시각 전용 판(z 0.0016 m)을
  x [−1.39, −1.15], y [0.20, 0.35]에 깐다. 왼쪽 세로 차로(북쪽으로 주행)의 두 차선이 0.15 m 끊긴다. 충돌은 바꾸지 않았다.
  공백 뒤 직선은 모서리(y 약 0.42–0.55)까지 0.07–0.10 m뿐이다(260919의 직선은 모두 약 0.5 m라 더 긴 자리가 없다).
- run별 요약은 `evidence/runs/summary.json`, G-16 요약은 `evidence/runs/g16_summary.json`이다. 원시 기록
  (`log.jsonl`, `events.jsonl`, `capture.json`, 프레임)은 모델 PC 작업 디렉터리에 있다.

## G-16: 원인

참값은 `meshes/road_lines.stl`(월드가 그리는 메시)을 Gazebo 참값 자세로 몸 좌표에 옮겨 얻었다(`evidence/g16_probe.py`).
로봇을 차로 가운데 직선에 세우고 producer payload 30개를 받았다(정지 상태라 프레임마다 같다).

| 자리 (gt) | STL 여유 | payload 여유 (침식 전) | 불확실도 | 왼쪽 기울기 | 오른쪽 기울기 | 몸 뒤끝(x −0.076)의 안쪽 가장자리 오차, 안쪽으로 (L / R) |
|---|---|---|---|---|---|---|
| C 출발 (−1.270, 0.243, 남쪽) | 0.0234 m | **−0.0075 m** | 0.0089 m | +0.027 | **−0.107** (−6.1°) | 8.4 / **31.5** mm |
| 같은 자리 재측정 | 0.0234 | −0.0075 | 0.0089 | 같음 | 같음 | 같음 |
| 같은 차로 북쪽 (−1.270, 0.0, 북쪽) | 0.0234 | 0.0104 | 0.0076 | +0.016 | −0.038 | 4.0 / 13.0 |
| 아래 직선 (0.47, −0.51, 동쪽) | 0.0189 (로봇이 5 mm 치우침) | 0.0095 | 0.0076 | +0.016 | −0.046 | 4.5 / 14.4 |

증거는 단계별로 이렇다.

1. **카메라 자세·BEV 축척은 원인이 아니다.** Gazebo 카메라 센서 자세는 `base_footprint`에서 x 0.03317, z 0.06343,
   pitch 0.139626 rad(8°)로 line_observer의 GAZEBO 지면과 같고, 로봇은 바닥에 평평히 서 있다(z −1e−7, roll·pitch 0).
   흰 벽 마스크 병합도 없다. STL 도색을 지면 모델로 영상에 투영한 열과 `floor_white_mask`의 밝은 구간이 x 0.25–0.40 m에서
   1–4 px 안에서 맞는다(BEV에서 바깥쪽으로 1–4 mm).
2. **지지 구간 안의 위치도 원인이 아니다.** 관측 x 구간(약 0.18–0.33 m) 안에서 맞춘 도색 중심의 오차는 중앙값 왼쪽
   −0.7 mm, 오른쪽 −4.3 mm(최대 12 mm, 먼 끝)이다.
3. **기울기 오차를 D-468이 몸까지 외삽한다.** 지지 구간이 몸 앞 0.18 m부터라서 몸 뒤끝(−0.076 m)까지 0.25–0.3 m를
   늘린다(`RECEIVER_EXTRAPOLATION_M` 0.3 안이라 받아들인다). 오른쪽 −6.1°는 그 거리에서 31.5 mm다. 이것이 여유
   23.4 mm를 −7.5 mm로 만든다. 앞선 기록의 "약 5 mm"는 같은 자리, 안쪽 가장자리 이동(12.5 mm) 전 값이다
   (5 − 12.5 = −7.5).
4. **기울기 오차의 출처 둘** (`evidence/g16_fit_trace.py`, 저장한 프레임을 제품 `extract_lines`로 다시 돌림):
   - **화면 모서리 잘림.** 320×240, 59.2° 화면은 x 0.18 m에서 |y| ≤ 0.086, 0.20 m에서 0.099, 0.22 m에서 0.109만 본다.
     테이프는 |y| 0.080–0.105라 x < 약 0.23 m에서는 안쪽 일부만 보인다. 가까운 끝의 셀이 안쪽으로 치우쳐 PCA 축이
     가까운 쪽에서 안쪽으로 기운다. 북쪽 자리(횡단보도 없음)의 −2.2°·+0.9°는 대부분 이것이다(x > 0.235 셀만 쓰면 −0.7°·+0.3°. 남은 오른쪽 기울기는 먼 끝 모서리 셀).
   - **횡단보도 blob 제거 띠.** C 출발에서는 횡단보도(중심 x 0.382, 헤딩 76.8°, 폭 ±0.115 m)가 blob으로 먼저
     제거되며 축에서 `FLANK_OUTER_M` 0.08 m 안의 셀을 함께 지운다. 그 띠가 오른쪽 테이프의 x 0.28–0.33 구간에서 안쪽
     |y| 0.081–0.101 셀 35개를 깎아 먼 끝에는 바깥쪽 셀만 남는다. 가까운 끝은 잘림으로 안쪽만 남아, 둘이 합쳐 −5.8°가
     된다. 같은 테이프의 셀 전체로 맞추면 −1.7°, x > 0.235만이면 −0.5°다.
5. **불확실도가 덮지 않는다.** GAZEBO 불확실도(7.6–8.9 mm)는 읽은 양 끝의 검출기 2 px와 카메라 기하 오차만 담고,
   이 맞춤 기울기 오차는 담지 않는다. 침식 뒤 여유는 C −16.4 mm, 북쪽 +2.8 mm로 D-468 추종 기준 15 mm에 못 미친다.

**분류: 제품 코드(perception keep-mode 맞춤 + D-468 수신 외삽).** sim 충실도 문제가 아니라 sim이 정확해서 드러난
문제다. 실제 카메라도 화각이 같아 화면 모서리 잘림은 장치에서도 같다(장치의 투영 불확실도 26–134 mm 문제, G-15와는
별개로 더해진다). 이 브랜치는 제품 코드를 고치지 않았다. 선택지(결정은 perception·D-468 소유자): 잘린 가까운 셀이나
blob 띠가 깎은 셀을 맞춤에서 빼기, 맞춤 기울기 불확실도를 `uncertainty_m`에 넣기, 수신 외삽 거리를 줄이기.

## D-476 rev 1 결과

### A. bridge 끔 (`ENFORCE=1`)

| run | 출발 | 결과 |
|---|---|---|
| `A_round_1` | 회전교차로 서쪽 (−0.585, −0.12, 북쪽) | 13틱 추종 뒤 (−0.580, −0.073)에서 `HOLD junction_waiting`(D-495 keeper 교차로 정지) → 3.06 s 뒤 `LOST camera_reselection_required`. 이동 0.047 m |
| `A_corner_1` | 기본 출발 (−1.270, 0.243, 남쪽) | 모서리를 돌아 아래 직선, (−0.760, −0.433, yaw 0.53)에서 `camera_line_not_visible` → 3.00 s 뒤 `LOST`. 이동 1.185 m, 손실 뒤 최소 벽 0.104 / LiDAR 0.115 m |

### B. 회전교차로, bridge 켬 (`ENFORCE=1`)

| run | 지시 | 결과 |
|---|---|---|
| `B_round_1` | 없음 | A와 같다. `junction_waiting` → `LOST`. bridge 0틱 |
| `B_straight_1..3` | 첫 `junction_waiting`에 `straight` (200, `armed`) | 지시 다음 틱 `camera_line_not_visible` → 2.75–2.85 s 뒤 `LOST`. bridge 0틱. 손실 뒤 이동 0, 최소 벽 0.466 m |

무장 조건(rev 1 개정 8.2): 손실 직전 추종의 `angular`가 −0.147 rad/s로 0.08을 넘는다(원호 추종). 그래서 무장 연속 수가
0으로 돌아가 bridge가 없다. 설계대로다. 다만 D-495 결정 2("`straight` 통과는 bridge가 필요")는 이 진입처럼 원호에서
교차로에 닿는 자리에서는 bridge로 이어지지 않는다.

### C. 벽 모서리, bridge 켬

| run | 경로 | 결과 |
|---|---|---|
| `C_corner_1` | (a) enforce | 횡단보도 앞 (−1.269, 0.157)에서 회전 중(−0.18 rad/s) 0.3 s 손실 뒤 재획득, 대각선 진입 (−0.768, −0.437)에서 회전 중(0.33–0.49 rad/s) 손실 → `LOST`. bridge 0틱. 모서리 회전 중 최소 벽 0.042 / LiDAR 0.058 m(추종 중, 접촉 없음) |
| `C_corner_2` | (a) | 횡단보도 앞 (−1.270, 0.154)에서 손실. 직전 두 틱 `angular` 0.082·0.086 > 0.08 → 무장 안 됨 → 3.06 s 뒤 `LOST` |
| `C_corner_3` | (a) | (−1.270, 0.170)에서 `HOLD obstacle_ahead` 1420틱(190 s, 옆벽 0.072 m). 손실 없음 |
| `Cb_corner_1`, `_3` | (b) | 대각선 진입 (−0.765, −0.434)에서 손실. 직전 네 틱 `angular` 0.51–0.60, `error` −0.64…−0.89 → 무장 안 됨 → 2.96·2.98 s 뒤 `LOST` |
| `Cb_corner_2` | (b) | 아래 모서리 (−1.270, −0.370)에서 `HOLD obstacle_ahead` 1150틱(약 115 s). 손실 없음 |

이 트랙에서 저절로 나는 차선 손실(회전교차로 원호, 대각선 진입, 횡단보도 앞)은 모두 회전 중이라 bridge가 무장되지 않는다.
`lane_bridge_blocked`(몸 sweep)는 한 번도 나오지 않았다. 벽 앞 정지는 아래 C'처럼 틱 단위 D-422가 했다.

### C'. 차로 끝 벽 앞 (`Db_on_2`, 경로 (b), 공백 월드)

공백을 지난 뒤 왼쪽 위 모서리(차로가 동쪽으로 꺾임) 앞, (−1.271, 0.318, 북쪽)에서 곧은 추종(`error` 0, `angular` 0) 뒤
손실 → bridge 15틱, 1.782 s, odom 0.1176 m / gt 0.1184 m(상한 0.25/1.08 = 0.231 m 안), 0.08 m/s로 가다 0.10 m 뒤
0.04 m/s(COAST → SLOW) → `HOLD obstacle_ahead`(전방 LiDAR 0.148 m) → `camera_line_not_visible` → 손실부터 2.97 s에
`LOST`(LOST 시계 그대로). 끝 자세 (−1.272, 0.437): 몸 앞(0.042 m)에서 북쪽 벽 안쪽 면까지 0.146 m, 옆벽 최소 0.0707 m,
LiDAR 최소 0.050 m(`range_min`). 접촉 없음. 1회뿐이고 몸 sweep(`lane_bridge_blocked`)이 아니라 틱 단위 D-422가 멈췄다.

### D. 도색 공백 0.15 m

| run | 경로 | 결과 |
|---|---|---|
| `D_off_1` | bridge 끔, (a) | (−1.269, −0.024)에서 손실(추정: 화면 창 안에 가까운 도색 약 0.08 m, 먼 도색 약 0.06 m만 남음) → 3.12 s 뒤 `LOST`. 이동 0.026 m |
| `D_on_1` | (a) | 같은 자리에서 무장 → 첫 bridge 틱 `HOLD lane_bridge_motion_unconfirmed`(워커 바닥 증명 거절) → `camera_line_not_visible` → 2.85 s 뒤 `LOST` |
| `D_on_2` | (a) | 손실 직전 곧은 추종(`|angular|` ≤ 0.041)인데 bridge 없음 → `LOST`. 이 run은 `error`·`confidence`를 기록하기 전이라 무장이 안 된 이유(신뢰도 또는 오차)를 나누지 못했다 |
| `D_on_3` | (a) | 손실 직전 `obstacle_ahead` 3틱 → 무장 안 됨 → `LOST` |
| `Db_on_1..3` | (b) | 손실 자리(y −0.026…−0.013)에서 bridge 3틱, 0.36 s, gt 0.024–0.029 m → `TRACKING` 재획득. 그 뒤 run 1·3은 y 0.10–0.11에서 `HOLD junction_waiting`(공백 너머 모서리를 keeper가 교차로로 본다), run 2는 y 0.318까지 추종해 공백을 지나갔다(위 C') |
| `Db_straight_2..3` | (b), 첫 `junction_waiting`에 `straight` | 같은 bridge(3·2틱, 0.027·0.017 m) → `TRACKING`. 다음 `junction_waiting`(y 0.095)에서 멈춤. 3번째 run의 지시는 같은 `place_id`라 409 `JUNCTION_ALREADY_DONE`(D-495 R1 그대로) |
| `Db_straight_1` | (b) | 7틱 추종 뒤 손실, 무장 안 됨 → `LOST` |

판정: 경로 (b)에서 공백이 만든 손실은 bridge가 2–3 cm 밀어 먼 도색이 보이게 하고 `TRACKING`으로 돌아왔다(5/5).
OFF는 같은 자리에서 멈췄다. 0.15 m 공백은 카메라 창(몸 앞 약 0.14–0.43 m)보다 짧아 bridge가 공백 전체를 건너지는
않았다. 공백 위를 실제로 지나간 run은 1회(`Db_on_2`, 추종으로)다. enforce(경로 (a))에서는 1/1 무장이 바닥 증명에서 거절됐다.

## 발견

1. **G-16은 제품 코드 원인이다(위).** sim containment가 차로 안을 증명하지 못하는 것은 sim 탓이 아니다. 같은 맞춤·외삽은
   장치에서도 같다.
2. **이 트랙에서 rev 1 bridge는 회전 중 손실에서 무장되지 않는다.** 회전교차로·대각선 진입·횡단보도 앞 손실 8회 모두
   `|angular|` > 0.08이었다. 무장 관문은 설계대로 동작했다. 그 결과 D-495 `straight` 지시(회전교차로 서쪽)는 bridge 없이
   `LOST`로 끝난다.
3. **enforce 바닥 증명은 벽 옆 차로에서 bridge 전진을 거절했다(1/1, `D_on_1`, 옆벽 0.074 m).** 2차 실행의 `(0, 0)` 증명
   실패(옆벽에 걸리는 회전 원)와 같은 자리다. 경로 (b)에서는 같은 자리에서 bridge가 움직였다.
4. **`nav.line_stuck_asked`는 `stuck_id`마다 2건이다(모든 run).** 같은 틱에 `reason opened`와 `local_disabled`
   (`recovery_local_enabled false`)가 나온다. 2차 실행의 홍수(약 20 건/s, D-468 `fleet_required`)는 이 설정에서는 없다.
   기대치 1건과는 다르다.
5. **`junction_waiting`과 LOST.** 회전교차로에서는 `junction_waiting` 3 s 뒤 `LOST`가 됐지만 공백 월드에서는
   `junction_waiting`이 약 55 s 동안 `LOST` 없이 이어졌다(`Db_on_1`, `_3`). `Db_straight_2`·`_3`에서는 `LOST` 뒤에 상태가
   `LOST camera_reselection_required`와 `HOLD junction_waiting` 사이를 0.2–1.2 s마다 오갔다(LOST 래치가 사유 표시에서
   유지되지 않음). D-494/D-495 소유자 확인이 필요하다.
6. **D-422 `obstacle_ahead` 래치(2차 발견 3)는 그대로다.** 벽 옆에서 115–190 s 정지(`C_corner_3`, `Cb_corner_2`).
7. **IR 가드는 sim에서 시험되지 않는다.** IR 바닥 광선에 반사율이 없어 가드는 늘 `clear`다.

## 시험하지 못한 것

- `lane_bridge_blocked`(몸 sweep 막힘), bridge 시간 상한, 거리 상한 도달, 공백 0.05·0.10 m, 공백 뒤 직선이 긴 자리
  (260919에는 없다), `recovery_local_enabled true`에서 bridge 뒤 D-468 인계(G-16 때문에 D-468은 첫 프레임에 이탈을 연다).
- 장치. 이 기록은 ROS-SIM이다.

## 재현

```bash
# 모델 PC, 작업공간 ~/rosy_d476_ws (src/rosy-platform -> clone, 로컬 main commit 6c1e9855d를 git bundle로 가져옴).
colcon build --symlink-install --packages-select gz_sim core control description \
  --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
# evidence/ 를 $WS/ev3 로 복사. 모델 PC는 공유라 tmux 소켓을 따로 쓴다.
tmux -L d476 new -d -s d476 "BRIDGE=1 ENFORCE=0 bash ev3/run_sim.sh"
python3 ev3/d476_probe.py run --x -1.26955 --y 0.24255 --yaw -1.5708 --out runs3/Cb_corner_1 --duration 150
python3 ev3/d476_probe.py run --x -0.585 --y -0.12 --yaw 1.5708 --out runs3/B_straight_1 --duration 40 \
  --junction straight --place-id roundabout-west
# 공백 월드 (D)
python3 ev3/make_gap_world.py "$(ros2 pkg prefix control)/share/control/map/map_v2_fleet/worlds/map_v2_fleet_real.world" \
  worlds/gap15.world -1.39 -1.15 0.20 0.35
tmux -L d476 new -d -s d476 "BRIDGE=1 ENFORCE=0 WORLD=$HOME/rosy_d476_ws/worlds/gap15.world bash ev3/run_sim.sh"
python3 ev3/d476_probe.py run --x -1.26955 --y -0.05 --yaw 1.5708 --out runs3/Db_on_1 --duration 60
# G-16 (sim이 떠 있을 때)
python3 ev3/g16_probe.py capture --x -1.26955 --y 0.24255 --yaw -1.5708 --out runs3/g16_C
python3 ev3/g16_probe.py analyze runs3/g16_C --stl src/rosy-platform/middleware/perception/map/map_v2_fleet/meshes/road_lines.stl
# ROS 없이 (어디서든)
PYTHONPATH="contracts/foundation:middleware/perception" \
  python docs/validation/d476-gazebo-rev1-2026-10-07/evidence/g16_fit_trace.py \
  docs/validation/d476-gazebo-rev1-2026-10-07/evidence/runs/g16_C_frame0.png
```

모델 PC의 이 작업 프로세스는 모두 멈췄다. GPU 학습은 돌고 있지 않았다(사용률 0–2 %). 다른 세션의 sim은 건드리지 않았다
(`run_sim.sh`의 `pkill`은 이 작업공간 경로로만 고른다).
