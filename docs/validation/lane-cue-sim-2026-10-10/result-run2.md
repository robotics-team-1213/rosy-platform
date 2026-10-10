# D-511 CORE Fleet lane cue SIM 2차 (회전 자리, rev 4/5), 2026-10-10

증거 등급: **ROS-SIM (폐루프, 한 대)**. 모델 PC(rosy@100.98.162.71)에서만 돌렸고 노트북과 실물 로봇은 쓰지 않았다.

- 시험한 코드: `feat/core-fleet-lane-cue` `62c674c05`를 `test/lane-cue-sim-harness`에 머지(`bb7e637cf`). CORE 코드는 바꾸지 않았다.
- 하네스: `evidence/lane_cue_sim.py` 시나리오 `s5`(회전 자리 피벗, 카메라 끊김), `s6`(회전 자리 밖 WRONG_WAY), `s3 --box`,
  `s4`, 회귀 `s1`(OFF_MAP), `s2`(Fleet 끊김). 설정은 1차(`result.md`)와 같다. 단, 2–5번은 회전 자리에서 돌렸다.
  LiDAR σ 3.4 mm, CORE 8671, 도메인 67, RTF 0.95–0.97.
- 회전 자리: `X:\DevTemp\steer-review\deadlock\turn_spots.json`의 링 진입 네 곳. 지도 방향은 가까운 링 구간의 접선이다
  (0: ring_n 153°, 1: ring_n −136°, 2·3: ring_s −38°/25°). 로봇은 그 반대(+180°)를 보고 놓았다.
- 가짜 Fleet: 1차와 같다(2 Hz, ttl 1.0, 지연 0.4–0.8 s, 참값 = MapPose). 추가한 것은 두 가지다.
  - `turn_spot`은 Fleet처럼 보고 상태 = raw이고 MapPose가 자리에서 0.018 m(`turn_spot_tolerance_m`) 안일 때만 싣는다.
  - `--prejudged`: Fleet이 첫 cue부터 WRONG_WAY다. 로봇을 놓기 전부터 보고 있었다는 가정이고, Fleet의 1 s 유지 동안
    keep가 자리를 떠나는 것을 막는다. `--exact180`: |turn| > 170°이면 ±180/179.5/179를 무작위 부호로 보낸다.
- 카메라 끊김: 피벗이 60–90° 돌았을 때 Gazebo `image_bridge`를 2.5 s SIGSTOP한다. 프레임만 끊기고 IR은 살아 있다.
  `line_observer_node`를 멈춘 run(`camloss_*`)은 IR 가드 관측까지 끊긴 경우로 따로 적었다.
- 증거: `X:\DevTemp\lane-cue-sim\run2\runs\<run>\`(cmd_vel, 10 Hz 상태 + `lane_cue`, 이벤트, cue, plot.png),
  요약 `X:\DevTemp\lane-cue-sim\run2\summary.txt`, 사본 `runs-run2/<run>/summary.json`.
  `runs_b2_superseded`는 래치를 reason으로만 읽던 판정식의 Fleet 끊김 run이다(발견 4). 재판정 전 결과라 쓰지 않았다.

## 판정 요약

| 시나리오 | 판정 | run | 한 줄 |
|---|---|---|---|
| 1 회전 자리 WRONG_WAY 175–180° → ≤10° 완료, 재획득 | **FAIL** | 2/6 | 피벗이 시작된 4건 모두 한 부호로 끝까지 돌았다(즉시 완료 0, 부호 바뀜 0, 자리 이탈 ≤ 2 mm). 끝 오차는 −8.6°, −1.1°(PASS)와 +33.8°, +13.3°(FAIL)다. FAIL 둘은 부호 유지 결함이다(발견 1). 나머지 2건은 시작하지 못했다. 카메라가 시작 조건을 못 채우고 자리를 떠나 `fleet_wrong_way` 래치(발견 3), 한 cue만 자리 안이라 `fleet_wrong_way`(발견 2) |
| 2 피벗 중 카메라 끊김 | **계속: PASS 3/3, 완료: FAIL 1/3** | camimg_spot0–2 | 프레임 2.5 s 끊김 동안 회전이 멈추지 않았다(이유 `fleet_wrong_way_turn`뿐, 6.3–7.1 s). 끝 오차 −6.8°(PASS), −31.9°, +21.4°. 두 FAIL은 발견 1이다. IR까지 끊긴 경우(camloss_spot0)는 `lane_guard_stale` HOLD로 멈췄다가 기한을 넘겨 `fleet_turn_unconfirmed` 래치였다(안전 측) |
| 3 회전 원 안 상자 | **PASS** | 2/2 | 상자가 있는 동안 회전 명령 틱 0(`pivot.ticks` 0), `obstacle_ahead`, yaw는 keep 관성 ≤ 3.2°. 5 s 뒤 stuck이 열려 물러남, 자리 이탈 후 `fleet_wrong_way` 래치. box_spot0의 summary FAIL은 피벗을 버린 뒤 keep 조향까지 센 판정식 탓이다. 위 근거로 PASS로 판정했다 |
| 4 피벗 중 stuck | **PASS** | 1/1 유효 | stuck_spot1: stuck(`obstacle_ahead`) 31행 동안 피벗·래치·cue 사유 0, side cue 30행 무시, 닫힌 뒤에야 `fleet_cue_left`. stuck_spot3는 피벗이 시작조차 안 돼(자리 3, 발견 3) 판정 불가 |
| 5 회전 자리 밖 WRONG_WAY | **PASS** | 2/2 | 첫 WRONG_WAY cue(turn_spot 없음) 0.03–0.06 s 뒤 `fleet_wrong_way` 래치. 이동 0.000 m, cmd 0건, 10 s 유지, 피벗 이벤트 0 |
| 회귀 OFF_MAP | **PASS(안전)** | 2/3 + 1 | r2·r3 1차와 같음(래치 0.04–0.13 s, 이동 0, 풀림·재래치·모드 변경). r1은 래치 동안 열린 no_motion stuck이 풀린 뒤에도 남아(로봇 LOST) 두 번째 OFF_MAP이 래치되지 않았다(발견 5). 로봇은 정지 상태 |
| 회귀 Fleet 끊김 | **PASS** | 3/3 | 회전 자리에서 120° 피벗을 51–53°에서 끊으면 마지막 cue 뒤 0.97–1.05 s에 `fleet_cue_lost` 래치. 최대 76–83°(예산 150°), 이후 이동·cmd 0, 끝까지 래치 |

재획득(rev 5): 끝난 피벗 7건 모두 끝난 틱에 카메라가 이미 차선을 따랐다(`fleet_turn_reacquire` 0.0 s, 래치 없음).
시운전 run(`runs_trial_run2/t_spot1_real`, 끝 오차 −35°)에서는 2.03 s 뒤 `fleet_turn_no_lane` 래치가 걸렸다. 설계대로다.
다만 +34°로 끝난 run도 카메라가 어떤 선이든 잡아서 재획득을 통과했다. 재획득은 방향을 확인하지 않는다.

## 발견

1. [HIGH] **±180 근처 부호 유지가 회전 방향을 뒤집는다.** `lane_cue.py` `_cue_count`: |angle| ≥ `SIGN_FREE_DEG`(150°)이면
   이전 streak의 부호를 유지하고, `_pivot_start(streak[0] * abs(angle))`로 시작한다. 첫 cue가 ±180 잡음(또는 keep가 debounce
   동안 180°를 넘겨 조향)으로 반대 부호였으면 |angle|만 남고 부호가 틀린다. 예: 실제 −161°인데 +168.2°로 돈다.
   그 결과 같은 목표 방향이 아니라 2·(180−|angle|)만큼 어긋난 방향에서 "완료"된다.

   | run | 처음 받아들인 WRONG_WAY cue | 피벗 각 | 끝 오차 |
   |---|---|---|---|
   | spot0_x180 | −179.0, +166.6, +154.9 | −166.6 | +33.8° |
   | spot2_x180 | −179.5, +179.0, +167.0 | −179.0 | +13.3° |
   | camimg_spot0 | +178.5, −168.2, −165.4 | +168.2 | −31.5° (잡음 주입 없음, keep 조향만) |
   | camimg_spot2 | −179.1, +172.9, +165.2 | −172.8 | +20.9° |

   CORE는 자기 odom 목표에 대해 ≤ 10°로 끝났다고 판단한다. 조치 후보: 유지한 부호가 cue 부호와 다르면
   `angle = kept_sign * (360 − |angle|)`(같은 목표 방향, 예산은 그 각 + 30°). 또는 유지 구간을 잡음 폭(예: ≥ 172°)으로 좁힌다.
   단위 시험: cue −179 → +167 → +160이 +167 쪽 목표로 끝나는지.
2. [MEDIUM, 통합] **turn_spot 허용 0.018 m와 달리는 keep.** CORE는 turn_spot 없는 WRONG_WAY를 debounce 없이 바로
   `fleet_wrong_way`로 래치한다. Fleet은 MapPose가 자리 1.8 cm 안일 때만 turn_spot을 싣는다. keep는 0.07 m/s로 달려
   0.3 s 안에 자리를 벗어난다. 그래서 피벗에 필요한 같은 부호 cue 둘(0.5 s 간격)이 모두 자리 안이기 어렵다.
   spot2_n3는 자리 안 cue 하나 뒤 래치됐다(cue 44건 중 turn_spot 3건). 안전 측이지만 기능이 잘 서지 않는다. 시험의
   `--prejudged`도 이를 줄일 뿐이다. 조치 후보: 첫 WRONG_WAY에서 keep를 비래치 HOLD로 세우고 turn_spot을 기다린다.
   또는 Fleet이 자리 근접(예: 몸 반경)을 넉넉히 본다.
3. [MEDIUM] **시작에 카메라 FOLLOW 요구 + 링 진입에서 역방향으로 놓인 keep.** 자리 3에서는 4건 중 3건이 처음부터
   `junction_waiting`→LOST(`camera_reselection_required`)라 피벗이 시작하지 못했다(stuck_spot3, camloss_spot3, drop 시운전).
   spot0_n3는 `camera_line_not_visible`로 시작 못 함 → lane_lost stuck 후진 → 자리 이탈 → `fleet_wrong_way`. 모두 안전 측이다.
4. [LOW] **래치 이유가 status `reason`에서 가려진다.** 래치 HOLD는 `_cue_spot_turning`이 아니라 junction 게이트를 지난다.
   그래서 `reason`이 `junction_waiting`이 되고 래치는 `lane_cue.latch`에서만 보인다(b2 drop_spot0: `fleet_cue_lost`가
   `junction_waiting`으로 보임). `line_observer`가 멈춘 경우의 `lane_guard_stale`도 같은 식으로 `junction_waiting`이 됐다.
   Fleet·대시보드가 reason만 보면 원인을 놓친다. 하네스는 `lane_cue.latch`를 먼저 읽도록 고쳤다.
5. [LOW] **열린 stuck 동안 OFF_MAP이 래치되지 않는다.** `_lane_cue_plan`은 stuck이 열려 있으면 OFF_MAP을 보기 전에 물러난다.
   OFF_MAP 래치가 5 s 넘으면 그 정지 자체가 no_motion stuck을 연다. ON_LANE으로 래치가 풀린 뒤 로봇이 LOST라 stuck이
   남았고, 이어 온 OFF_MAP(606.6 s)은 받아들여졌지만 래치되지 않았다(offmap_r1). 로봇은 stuck과 LOST로 정지 상태였다.
   stuck이 닫히면 Fleet이 다시 보내는 OFF_MAP이 다음 틱에 래치되므로 틈은 한 cue 주기 정도다. 그 사이 stuck 답
   (RESUME, BACK_AND_RETRY)은 Fleet이 로봇을 못 보는 채로 움직일 수 있다.
6. [해소] 1차 발견 2(`GET /line-follow`에 `lane_cue` 없음)는 `62c674c05`에서 `LineFollowStatus.lane_cue`로 고쳐졌다.
   이번 run의 피벗 진행·래치·재획득은 그 필드로 읽었다.

## 한계

- 회전 자리의 지도 방향은 lane_graph 링 접선으로 정했다(Fleet `build_lap`의 방향과 같은지 확인하지 않음).
- `--prejudged`와 `--exact180`은 시험용 가정이다. 실제 Fleet은 1 s 유지와 wrong_way_min_m 0.10 m를 거친다.
- 자리 3은 시작 조건 때문에 2·4번 표본이 없다. 카메라 끊김은 프레임 정지로만 흉내 냈다(흐림·오검출 없음).
- STUCK_DECIDE 풀림, D-517/D-573 게이트, 교차로 지시(armed)로 인한 `fleet_turn_interrupted`는 이번에도 SIM에서 돌리지 않았다.

## 재현

```bash
# model PC, ~/rosy_lcsim_ws = 이 커밋 archive + colcon build (1차 result.md 재현 절)
python3 .../evidence/lane_cue_sim.py s5 --out runs/spot0_x180 --spot 0 --prejudged --exact180 \
  --site-token lcsim/site_token --token "$(cat lcsim/op_token)"
#   카메라 끊김: s5 --spot 1 --prejudged --camloss 2.5 --camloss-at 60   (image_bridge SIGSTOP)
#   상자 / stuck / 자리 밖: s3 --spot 0 --prejudged --box | s4 --spot 1 --prejudged | s6 --prejudged
#   회귀: s1 | s2 --spot 0
```
