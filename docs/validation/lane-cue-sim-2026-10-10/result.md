# D-511 CORE Fleet lane cue SIM 안전 시험 (모델 PC), 2026-10-10

증거 등급: **ROS-SIM (폐루프, 한 대)**. 장치·현장 수용이 아니다. Gazebo·ROS는 모델 PC(rosy@100.98.162.71)에서만
돌렸다. 노트북에서는 돌리지 않았다. 실물 로봇에는 명령하지 않았다.

- 시험한 코드: `feat/core-fleet-lane-cue` `3b263c62e`(stuck이 열려 있으면 cue가 물러남). CORE 코드는 바꾸지 않았다.
- 하네스: 이 브랜치 `test/lane-cue-sim-harness`의 `evidence/run_sim.sh`, `evidence/lane_cue_sim.py`.
  launch·IR·참값 aux는 `docs/validation/d495-junction-sim-2026-10-07/evidence`를 그대로 쓴다.
- 격리: 작업공간 `~/rosy_lcsim_ws`, ROS 도메인 67, `GZ_PARTITION rosy_lcsim`, CORE 포트 8671. RTF 0.96–0.98.
- 전체 로그(cmd_vel, 상태 10 Hz, 이벤트, cue 송신, plot.png): `X:\DevTemp\lane-cue-sim\final\runs\<run>\`.
  이 폴더의 `runs/<run>/summary.json`은 그 사본이다. `X:\DevTemp\lane-cue-sim\batch1`은 LiDAR 잡음과 판정식을
  고치기 전 첫 묶음이며 판정에 쓰지 않았다.

## 판정 요약

| 시나리오 | 판정 | run | 한 줄 |
|---|---|---|---|
| 1 Fleet NO_POSE ≥ 3 s → OFF_MAP | **PASS** | 3/3 | 4.5–4.9 s 묵은 stamp의 OFF_MAP을 받고 0.04–0.09 s 뒤 `fleet_off_map` 래치. 래치 동안 cmd 0건, 이동 0.000 m. 다른 epoch(`epoch_busy`), 옛 seq(`stale`), OFF_LANE은 래치를 못 풂. 새 같은 epoch ON_LANE이 풀고 0.00–0.04 s 안에 주행 재개. 모드 변경도 풂 |
| 2 회전 중 Fleet 끊김 | **PASS** | 3/3 안전 (2/3이 끊김 경로) | 120° 피벗을 51–53°에서 끊음. 마지막 cue 뒤 1.01–1.09 s(sim)에 `fleet_cue_lost` 래치. 최대 회전 70–71°(예산 150°). 래치 뒤 cmd 0건, yaw 변화 0.0°, 끝까지 래치 유지. r2는 끊기 전 34°에서 교차로 감지로 `fleet_turn_interrupted` 래치, 21 s 정지 |
| 3 WRONG_WAY 175–180° 피벗 완료 | **FAIL** | 0/4 완료 | 피벗이 한 번도 끝나지 않았다. 14–57° 돈 뒤 카메라가 차선을 놓쳐(`camera_line_not_visible`) 멈추거나 회전 중 교차로 감지로 `fleet_turn_interrupted` 래치. lat 0.8 run은 debounce 전에 `junction_waiting`/LOST라 시작도 못 함. 안전 측 실패다. 즉시 완료 0건, 부호 뒤집힘 0건 (cue 부호 +40/−17 섞인 run 포함) |
| 3 변형: 회전 원 안 상자 | **PASS** | 2/2 | 상자가 회전 원 + 여유(0.1026 m) 안(0.083–0.085 m)에 있는 동안 피벗 명령 0건, `obstacle_ahead`. 회전은 D-407 후진으로 상자가 0.117 m 밖으로 나간 뒤에만 다시 시작(측정 gap 0.026–0.031 m) |
| 4 피벗 중 D-407 stuck | **PASS** | 2/2 | 상자에 막힌 피벗 5 s 뒤 stuck(`obstacle_ahead`)이 열림. stuck 동안 피벗 행 0, 래치 0, `nav.lane_cue latched` 이벤트 0. stuck 동안 보낸 ON_LINE side cue 29건에도 `fleet_cue_*` 사유 0. stuck이 닫힌 뒤에야 `fleet_cue_left` |

켜기 판단: 1·2·4와 상자 변형은 안전 요구를 만족한다. 3은 피벗 기능이 이 맵에서 끝나지 않는다는 뜻이다.
멈추는 쪽으로 실패하므로 위험은 아니지만, Fleet `wrong_way`를 켜도 로봇이 돌아서지 않는다(아래 발견 1).

## 설정

- 월드 `map_v2_fleet_real`, Pinky 한 대, `camera_lane_mode: keep`, 카메라 8 Hz 320×240, `use_sim_time`(D-495 launch).
- CORE 겹 = `gz_sim config/map_v2_fleet_core.yaml`(포트 8671) +
  ```yaml
  line_follow:
    obstacle_mode: path
    ir_guard_enabled: true
    fleet_lane_cue_enabled: true
  auth:
    tokens: [site 자리 토큰(operator, source pair-physical, label "site:lane-cue-sim"), probe operator 토큰]
  ```
  토큰 원문은 run마다 `~/rosy_lcsim_ws/lcsim/`에 새로 만든다. 저장소에는 없다. 겹의 token 목록이 개발 토큰을
  대신하므로 probe용 operator 토큰도 같이 만든다. `rosy-dev-operator`로 lane-cue를 보내면 401이다.
- LiDAR 잡음: 작업공간 사본 `rosy_gz.urdf.xacro`의 σ를 C1 측정값 0.0034 m, 분해능 0.001 m로 바꿨다(D-573 SIM과 같다).
  기본 σ 0.02 m·분해능 0.03 m로 돌린 첫 묶음에서는 바깥 도로 벽이 회전 원 안으로 보여 피벗이 늘 `obstacle_ahead`였다.
- 가짜 Fleet: 2 Hz, `ttl_s` 1.0, 참값 자세를 MapPose로 쓴다. 각 cue는 latency(0.4–0.8 s 균등, run마다 0.4·0.8 고정도 돌림)
  전에 표본한 자세로 판정한다. `pose_stamp`는 그 표본 시각의 CORE `GET /robot/state` `odom_pose.stamp`다.
  시나리오 3·4의 WRONG_WAY는 Fleet ReturnTracker를 줄인 것이다. |turn| > 135°면 raw WRONG_WAY, 1.0 s 유지 뒤
  보고, raw와 보고가 다르면 `turn_deg` None. 노이즈 ±3°, `--exact180`은 |turn| > 170°에서 ±180/179.5/179를 무작위 부호로 보낸다.
  OFF_MAP의 stamp는 Fleet처럼 마지막으로 받아들여진 stamp다.
- 자세: 시나리오 1은 west 도로 (−1.2696, 0.40, −90°). 2·3·4는 안쪽 east 직선 (0.327, 0.20–0.27). 차선 방향은 −90°로
  두고 로봇은 +90°를 본다. 3 perimeter는 west (−1.2696, 0.243, −90°)에 차선 +90°(west:f). 시나리오 2의 차선은
  시작 yaw + 120°로 Fleet이 주장한다.
- 상자: 0.24 × 0.01 × 0.25 m 벽을 몸 왼쪽에 진행 방향으로 둔다. 면은 base_link에서 0.092 m다. 회전 원 + 여유는 0.1026 m,
  직진 몸 통로는 0.0766 m다.

## 결과

### 1 (s1_r1–r3, latency 0.4–0.8 / 0.8 / 0.4)

| run | OFF_MAP stamp 나이 | 래치까지 | NO_POSE 동안 주행 | 래치 동안 이동·cmd | 재개 cmd |
|---|---|---|---|---|---|
| s1_r1 | 4.67 s | 0.04 s | 0.175 m | 0.000 m · 0건 | 0.00 s |
| s1_r2 | 4.86 s | 0.04 s | 0.123 m | 0.000 m · 0건 | 0.01 s |
| s1_r3 | 4.49 s | 0.09 s | 0.147 m | 0.000 m · 0건 | 0.04 s |

NO_POSE 3.3 s 동안은 cue가 만료되어 오늘의 keep으로 달렸다. 설계대로다(ADR 개정 3, 3항 기준선).
래치는 이후 3 s OFF_MAP 반복, 3 s 침묵(ttl 초과), OFF_LANE, 다른 epoch, 옛 seq 동안 유지됐다.

### 2 (s2_r1–r3)

| run | 끊을 때 회전 | 마지막 cue → 래치 (sim) | 최대 회전 | 래치 뒤 |
|---|---|---|---|---|
| s2_r1 | 51.2° | 1.01 s `fleet_cue_lost` | 69.8° | cmd 0, yaw 0.0°, 래치 유지 |
| s2_r2 | (34.4°에서 끊기 전 래치) | `fleet_turn_interrupted` (교차로 감지) | 34.4° | 21 s 정지, cmd 0 |
| s2_r3 | 52.8° | 1.09 s `fleet_cue_lost` | 71.2° | cmd 0, yaw 0.0°, 래치 유지 |

래치 5 s 뒤 D-407 `no_motion` stuck이 열린다. 그 답(STUCK_DECIDE)이 래치를 푸는 경로다. 이 시험에서는 답하지 않았다.

### 3 (s3_*)

| run | 첫 피벗 회전 (odom) | 멈춘 이유 | 끝 오차 (odom / 참값) | 부호 바뀜 |
|---|---|---|---|---|
| s3_inner_lat04 | 47.8° | 카메라 상실 뒤 stuck 후진, 재피벗 중 `fleet_turn_interrupted` | −124° / −124° | 0 |
| s3_inner_lat08 | 시작 못 함 | debounce 전 `junction_waiting` → LOST | — | — |
| s3_inner_exact180 | 14.5° | `junction_waiting` → `fleet_turn_interrupted` | −170° / −170° | 0 (cue 부호 +40/−17) |
| s3_perimeter | 52.3° | `camera_line_not_visible` → LOST `camera_reselection_required` | −118° / −118° | 0 |

odom과 참값은 0.1° 안에서 같다. 그러니 오차는 측정 문제가 아니다. 피벗이 실제로 멈췄다.

### 3 상자, 4

- s3_box_r1/r2: 피벗 이벤트 뒤 첫 `obstacle_ahead` 행부터 상자가 0.083–0.085 m에 있는 동안 회전 명령 0건이었다.
  보이는 2.5–3.3° yaw는 그 전 keep 조향의 관성이다. 5 s 뒤 stuck → 피벗 버림(래치 없음) → 후진 0.08 m → 회복 →
  상자 0.117 m(gap 0.026–0.031 m)에서 새 피벗 → 교차로 감지로 `fleet_turn_interrupted`. 하네스 판정식은 회복 뒤의 정당한
  회전까지 세어 FAIL을 찍었다. 위 수치로 PASS로 판정했다(summary.json `verdict`는 FAIL 그대로 둠).
- s4_r1/r2: stuck(`obstacle_ahead`, 국소 후진) 30행 동안 피벗·래치·cue 사유가 없었다. 닫힌 뒤 side cue가 다시 조향했다.

## 발견

1. [HIGH, 기능] WRONG_WAY 피벗은 차선 위에서 끝날 수 없다. 피벗은 매 틱 `lane_recovery_rule FOLLOW`(보이는 신선한
   카메라 차선)를 통과해야 나간다(manager.py:598–638, D-430 review 3). 0.185 m 차선에서 카메라는 45–57° 돌면 선을 잃는다.
   그러면 `camera_line_not_visible` HOLD → lane_lost stuck → 국소 후진 → keep가 원래(역)방향으로 다시 달리거나 LOST로 끝난다.
   돌아가는 카메라가 교차로를 보면 `junction` 상태가 바뀌고 `fleet_turn_interrupted`로 래치된다. Fleet WRONG_WAY는 정의상
   |turn| > 135°라서 이 기능은 사실상 작동하지 않는다. 멈추는 쪽이라 위험은 아니다. 조치 후보(설계 결정 필요): 시작할 때만
   FOLLOW를 요구하고 회전 중에는 카메라 상실을 허용한다(IR·D-422·예산·기한·cue 신선은 그대로). 또는 WRONG_WAY 피벗을 버리고
   HOLD + stuck로 Fleet REALIGN에 맡긴다.
2. [MEDIUM] `GET /api/v1/line-follow`에 `lane_cue`가 없다. manager.status()는 `model_copy(update={'lane_cue': ...})`로
   넣지만 `LineFollowStatus`(contracts/foundation/core_common/protocol/schemas.py:1048)에 그 필드가 없어 `model_dump()`에서
   빠진다. 계약 문서(protocol/lane_cue.py docstring, API reference)는 보인다고 한다. 래치 이유는 `reason`으로 보이지만,
   피벗 진행·만료·래치 종류는 Fleet·대시보드에서 볼 수 없다. 단위 시험은 `status().lane_cue`(파이썬 객체)만 봐서 놓쳤다.
   API 시험 하나(`client.get('/api/v1/line-follow').json()['lane_cue']`)로 잡힌다.
3. [LOW] 피벗 → 막힘 → stuck(5 s) → 피벗 버림 → 국소 후진 0.08 m → 회복 → 같은 WRONG_WAY cue로 새 피벗의 순환이 있다
   (s3_box, batch1 perimeter에서 30 s에 4회). 회전은 매번 D-422 아래이고 국소 시도는 `recovery_max_attempts` 2로 끝나므로
   끝은 있다. 3b263c62e가 stuck 동안은 막지만 stuck이 `recovered`로 닫히면 streak가 다시 찬다.
4. [참고] 기본 SIM LiDAR(σ 0.02 m, 분해능 0.03 m)로는 바깥 도로 벽이 회전 원 안으로 보여 모든 피벗이 막힌다.
   C1 측정 σ로는 gap 0.04 m다. 실물 C1에서의 바깥 도로 회전 여유는 장치에서 따로 재야 한다.

## 한계

- SIM 카메라·차선 모형이다. 실물 카메라(피치 ≈11.8°)는 시야가 다르니 발견 1의 각도(45–57°)는 장치에서 다시 재야 한다.
  구조(회전 중 FOLLOW 요구)는 같다.
- 가짜 Fleet은 참값 자세를 쓴다(Rosy Cam 잡음 없음, NO_POSE는 송신 중단으로 흉내). 실제 `lane_compliance_service`는 돌리지 않았다.
- STUCK_DECIDE로 래치를 푸는 경로와 IR 우선 변형은 SIM에서 돌리지 않았다(단위 시험 몫).
- RTF 0.96–0.98이라 CORE의 sim 시계와 Fleet의 벽시계가 거의 같다. 부하가 큰 호스트에서는 ttl 판정이 sim 초로 늘어난다.

## 재현

```bash
# model PC (rosy@100.98.162.71), 작업공간 = 이 커밋의 git archive + colcon build --symlink-install --packages-up-to gz_sim core control description
WS=~/rosy_lcsim_ws nohup bash src/rosy-platform/docs/validation/lane-cue-sim-2026-10-10/evidence/run_sim.sh > sim.out 2>&1 &
python3 src/rosy-platform/docs/validation/lane-cue-sim-2026-10-10/evidence/lane_cue_sim.py s1 --out runs/s1_r1 \
  --site-token lcsim/site_token --token "$(cat lcsim/op_token)"     # s2 | s3 [--box] [--exact180] [--pose x,y,deg --lane deg] | s4
```
