# D-507 B8 남서 굽이 인식 증거 (모델 PC SIM), 2026-10-07

증거 등급: **ROS-SIM (폐루프, 한 대) + 호스트 재생**. 장치·현장 수용이 아니다. Gazebo·ROS는 모델 PC(OMEN)에서만 돌렸다.
이 노트북에서는 Gazebo를 돌리지 않았고 기록 재생(ROS 없음)만 했다. 실물 로봇은 건드리지 않았다. 제품 코드는 바꾸지 않았다.

목적: D-495 SIM 발견 5(남서 굽이를 교차로로 보거나 `flipping`으로 LOST)와 발견 7(아래 길에서 차로 중심보다 약 0.05 m
왼쪽, bridge 무장 안 됨)을 카메라 프레임과 keeper 번들로 기록해 B9 `fix/keep-bend-not-fork`, B9b `fix/keep-lane-centre-bias`가
기록된 증거로 고칠 수 있게 한다(계획 B8).

## 판정 요약

| 질문 | 답 | 근거 |
|---|---|---|
| 굽이 실패는 무엇인가 | keeper에 약 63° 굽이를 읽는 규칙이 없다. 굽이 앞에서 지금 차로의 직선 경계는 시야에서 빠지고, 새 방향 선(로봇 기준 55–65°)은 steep 규칙에 버려지거나, 경로를 가로지르는 바깥 사선 하나만 한쪽 경계로 남는다 | 16회 진입 중 통과 0. `junction_fork` 먼저 7, `flipping` 뒤 `junction_fork` 2, `flipping`만 7 |
| `junction_fork`의 두 기록 | 같은 쪽(왼쪽)에 놓인 **이어진 칠 하나**: spoke 바깥 사선(61°, 경로를 몸 앞 약 0.19 m에서 가로지름)과 그 끝에 붙은 회전교차로 바깥 원호(−9°) | 103 프레임, 두 기록 끝점 사이 0.035/0.038/0.044 m (p10/50/90) |
| `flipping` | 두 한쪽 해석의 번갈음: `right_only`(바깥 사선을 오른쪽 경계로, 목표가 실제 중심보다 0.13–0.18 m 왼쪽, 오차 −1.0)와 `left_only`(옛 안쪽 직선의 남은 토막, 목표가 오른쪽) | 아래 「굽이」 표 |
| 0.05 m 왼쪽 치우침의 원인 | **인식 편향도 추종 이득도 아니다.** 가운데에서 출발하면 직선에서 +0.002 m(출발 자리 그대로)를 지킨다. 치우침은 (1) 서→남 모서리 탈출 잔여 +0.067 m가 짧은 직선(0.27 m)에서 다 줄지 않고 +0.020 m까지만 줄고, (2) x≈−0.955에서 굽이 바깥 사선이 66°로 보여 L-모서리(`corner_left`)가 13프레임 걸리고, 이어서 `right_only` 목표가 왼쪽으로 끌어 +0.057 m까지 다시 커진 것이다 | 「아래 길 중심」 표 |
| bridge가 무장되지 않는 이유 | 직선에서는 무장 조건이 선다(신뢰 0.9, \|오차\| ≤ 0.09, \|ω\| p90 0.072). 마지막 무장 가능 프레임은 x −0.87…−0.92이고, 그 뒤 굽이 오독으로 \|오차\|가 0.3–1.0이 된 채 7–11 s(sim) 지나 HOLD가 온다 | 16회 모두 |
| 기록이 제품 keeper와 같은가 | 같다. main(62ab5172a, G-16 포함) `LaneKeeper`로 재생하면 텔레포트 뒤 프레임 중 5개만 다르고(모두 시작 직후·프레임 누락 자리) 나머지는 live 번들(전략·사유·오차)과 같다 | `evidence/b8_replay.py` |

## 설정

- 하네스: D-495 SIM 하네스(`docs/validation/d495-junction-sim-2026-10-07/evidence/`)를 바꾸지 않고 썼다. 모델 PC 작업공간
  `~/rosy_d495_ws`(src = D-495 기준 `432445eed`). `evidence/b8_run.sh`가 `run_sim.sh`를 ROS 도메인 78, `GZ_PARTITION rosy_b8`,
  CORE 포트 8098, 실행 폴더 `~/rosy_d495_ws/b8`, world 파일 이름 `b8_fleet_real.world`로만 바꿔 띄운다. 시작 전 모델 PC에
  다른 Gazebo·ROS 프로세스가 없었고 GPU 0 %였다. 끝난 뒤 이 파티션의 프로세스만 멈췄다(남은 `joint_state_publisher` 하나 포함).
- CORE 겹: D-495와 같다(`recovery_local_enabled: false`, IR 가드, `junction_turn_site_accepted`, bridge 켬). keeper:
  `camera_lane_mode keep`, `lane_corner_turning: true`, `camera_x_offset_m 0.03317`, `lane_half_width_m 0.0925`,
  GAZEBO 지면(높이 0.06343 m, pitch 8°, 320×240, fx 281.6), 카메라 8 Hz.
- 기록: `evidence/b8_record.py`가 `camera/front` 원본 프레임, `line/keep_debug` 번들 전부, `d495/gt` 참값, `/cmd_vel`을
  남긴다. `evidence/b8_go.sh`가 D-495 probe(`trip --plan left:60`)를 돌리는 동안 기록한다. probe는 run마다 교차로 기억을
  지운다(D-495 하네스 3).
- 실행: 굽이 진입 17회(서쪽 길 (−1.27, 0.24, −90°)에서 출발해 서→남 모서리, 아래 길, 남서 굽이) + 아래 길 직선
  6회((−1.15, y, 0°), y = 중심 ×3, 왼쪽 +0.03, 오른쪽 −0.03/−0.015). 굽이 진입 중 `bend_3`, `bend_13`은 서쪽 길에서
  `HOLD obstacle_ahead`(`body_gap_m 0.0`)로 서서 굽이에 닿지 못했다(D-495 발견 8의 D-422 기억 래치와 같은 모양,
  `clearance_source`는 기록하지 않음). 오른쪽 출발 `south_r`, `south_r2`도 출발 자리에서 같은 HOLD였다. 그래서 굽이 진입은
  pilot + 15 = **16회**, 아래 길은 가운데 3회와 왼쪽 1회를 쓴다.
- 참값 칠: world STL의 `PaintMap` raster(2 mm)에서 아래 길 안쪽 선 중심 y −0.4185, 바깥 선 −0.6035, 차로 중심 −0.511,
  선 중심 간격 0.185 m(= 2 × `lane_half_width_m`). lane_graph 중심 −0.509와 2 mm 차이. 굽이: 안쪽 선은 x −0.738에서,
  바깥 선은 x −0.62에서 약 63°로 꺾여 SW spoke가 되고, spoke 바깥 선은 회전교차로 바깥 원(남쪽 y ≈ −0.34)에 붙는다.

## 결과

### 아래 길 중심 (참값, 차로 중심 기준 +는 왼쪽)

x 구간별 중앙값 (오프셋 m / yaw °):

| x | −1.225 | −1.175 | −1.125 | −1.075 | −1.025 | −0.975 | −0.925 | −0.875 | −0.825 | −0.775 |
|---|---|---|---|---|---|---|---|---|---|---|
| 굽이 진입 16회 | +0.067/−20 | +0.052/−14 | +0.041/−11 | +0.032/−9 | +0.025/−6 | +0.020/−4 | +0.020/+5 | +0.027/+13 | +0.047/+21 | +0.057/+5 |
| 가운데 출발 3회 | — | +0.002 | +0.002 | +0.002 | +0.002 | +0.002 | +0.002 | +0.002 (LOST) | — | — |
| 왼쪽 +0.03 출발 | — | — | +0.031/−4 | +0.025/−7 | +0.019/−5 | +0.015/−3 | +0.017/+5 | +0.022/+11 | +0.039/+25 | +0.057/+7 |

D-495 원시 기록(`d495_runs_full.tgz`, 모든 run)의 같은 표도 +0.061(−1.25) → +0.020(−1.0, −0.95) → +0.057(−0.8) → +0.064(−0.75)로 같다.
D-495의 「참값 y −0.462, 중심 −0.509」는 굽이 앞(x ≈ −0.78)의 값이다.

직선 구간 인식. 위 두 줄은 x −1.15…−0.95의 `both` 프레임(굽이 진입 381, 가운데 출발 128), 아래 두 줄은 x −1.15…−0.80의
한쪽 프레임(run별 중앙값의 범위, `evidence/analysis.json`):

| 항목 (p10 / 중앙 / p90, m) | 굽이 진입 16회 | 가운데 출발 3회 |
|---|---|---|
| 선 위치 오차 (keeper `y_at_side_x_m` − 참값, x 0.22 m) | 왼쪽 −0.004 / −0.002 / +0.008, 오른쪽 −0.004 / −0.002 / +0.001 | 왼쪽 −0.008 / −0.002 / +0.001, 오른쪽 −0.004 / −0.002 / +0.001 |
| `both` 목표 − 참 중심 (같은 앞 거리) | −0.002 / +0.003 / +0.008 | −0.001 / +0.001 / +0.007 |
| `right_only` 목표 − 참 중심 | run별 중앙 **+0.14…+0.16** | run별 중앙 −0.001…+0.001 |
| `left_only` 목표 − 참 중심 | run별 중앙 +0.07…+0.10 | (없음) |

해석:

1. 카메라 위치·차로 폭·지면 기하는 맞다. 두 선이 다 보이면 선 위치 오차가 중앙 2 mm, p10–p90 8 mm 안이고, 가운데에서 출발한 로봇은
   직선 끝까지 +0.002 m를 지킨다(출발 자리가 lane_graph 중심 −0.509라서 생긴 2 mm). 일정한 인식 편향(카메라 오프셋,
   가정한 차로 폭, 한쪽 오프셋)은 없다.
2. 서→남 모서리를 `corner_left`로 돈 뒤 로봇은 +0.067 m 왼쪽, yaw −20°로 나온다. keep 루프는 과감쇠(lane_keep.py 문서:
   극 −0.24, −1.9 1/s, 이 속도에서 거리 상수 약 0.2 m)라서 0.27 m 직선에서 +0.020 m까지만 줄어든다.
3. x ≈ −0.955(16/16회, 왼쪽 출발도 같음)에서 yaw가 아직 −3.5°인 로봇에게 굽이 바깥 사선이 65.3–66.6°로 보인다.
   `TRANSVERSE_MIN_ANGLE_RAD`(65°)를 넘어 가로선이 되고, 왼쪽이 열린 L-모서리로 읽혀 `corner_left`가 13프레임
   (`CORNER_LATCH_FRAMES` 12 + 1) 걸린다. yaw 0°로 들어오는 가운데 출발에서는 같은 선이 65° 아래라 모서리가 걸리지 않는다.
4. 그 뒤 x −0.92…−0.80에서 keeper는 `right_only`(바깥 사선을 오른쪽 경계로 보고 목표를 그 선에서 반폭 안쪽, 실제 중심보다
   0.14–0.16 m 왼쪽에 둠)와 `left_only`를 오가며 왼쪽으로 꺾는다(yaw +13…+21°). 치우침이 +0.057 m로 다시 커진다.
   IR 왼쪽 센서가 테이프를 읽는 틱은 x −0.85 앞에서 0이고 그 뒤 −0.825 구간 120/278, −0.775 구간 375/852다.

결론: B9b의 원인은 「차로 중심 편향」이 아니라 (a) 모서리 탈출 잔여와 짧은 직선, (b) 굽이 사선을 L-모서리 가로선으로
읽는 것(66° 대 65° 문턱), (c) 굽이 사선을 한쪽 경계로 받는 것이다. (b)(c)는 B9과 같은 원인이다. 카메라 오프셋·차로 폭·
추종 이득을 바꾸는 수정은 이 증거로 정당화되지 않는다.

### 굽이 (16회 진입, 첫 HOLD 사유)

| 결과 | 횟수 | run |
|---|---|---|
| `junction_fork` 먼저 | 7 | bend_2, 4, 5, 10, 12, 14, 15 |
| `flipping` 뒤 `junction_fork` | 2 | bend_1, 16 |
| `flipping`만 (→ LOST) | 7 | bend_6, 7, 8, 9, 11, 17, pilot |
| 굽이 통과 | 0 | |

첫 HOLD 자리는 참값 (−0.724…−0.759, −0.441…−0.454)이다. 마지막 처리: `LOST_between_junctions` 7, `unresolved` 6
(이 run들의 `left:60` 지시가 굽이 HOLD에서 회전으로 쓰였다), `aborted` 3. D-495(15회: `flipping`만 8, `flipping` 뒤 fork 5,
fork 먼저 2)와 섞임은 다르지만 두 기전은 같다.

굽이 앞에서 keeper가 보는 것(`frames/*.png`, 참값 위에 겹친 기록은 `evidence/b8_analyze.py`·프레임 재생으로 확인):

- 카메라 바닥 시야는 base_link 앞 약 0.14 m부터이고, 옆 0.09 m의 선은 약 0.2 m 앞부터 보인다. 안쪽 선이 x −0.738에서
  꺾이므로 로봇이 x −0.95를 지나면 안쪽 직선은 짧은 토막(0.07–0.14 m)만 남는다. 가운데 출발 3회는 여기서 오른쪽 선만
  남다가(0.10 → 0.06 m로 짧아짐) x −0.893에서 `no_boundary` → LOST였다(새 방향 안쪽 사선 +63–64°는 `steep_far`로 버려짐).
- 새 방향 선은 로봇 기준 55–65°다. `STEEP_MIN_ANGLE_RAD` 45°보다 가파르고 `TRANSVERSE_MIN_ANGLE_RAD` 65°보다 완만해서,
  옆으로 멀면 `steep_far`로 버려지고, 경로를 가로지르면(옆 오프셋이 작음) `steep` 규칙(`far_lateral` 필요)을 빠져나가 한쪽
  경계로 남는다. 바깥 사선은 x 0.22 m에서의 옆 오프셋 부호에 따라 매 프레임 왼쪽이나 오른쪽이 된다.
- **flipping**: `right_only`(바깥 사선, 목표 왼쪽, 오차 −0.6…−1.0)와 `left_only`(옛 안쪽 토막, 로봇이 왼쪽으로 돌면 이 토막의
  방향이 −20…−40°가 되어 목표 오른쪽, 오차 +0.3…+1.0)가 16프레임 안에 두 번 이상 뒤집힌다.
- **junction_fork**: 103개 fork 프레임 모두 왼쪽 두 기록이다. (1) spoke 바깥 사선(예 61°, 끝 (0.156, −0.073)–(0.283, 0.156))과
  (2) 그 너머 회전교차로 바깥 원 남쪽 호(예 −9°, (0.309, 0.128)–(0.432, 0.109)). 두 기록의 가까운 끝 사이는 0.035–0.044 m
  (p10–p90, 최대 0.187)이다. 지도에서 spoke 바깥 선은 원에 붙어 있으므로, 이것은 갈라지는 두 가지가 아니라 꺾인 칠 하나를
  직선 둘로 나눈 것이다. 계획 B9의 「끝–시작 연속성 검사」 가설을 지지한다. 단, 연속성으로 fork를 막아도 위 두 줄의 굽이
  읽기 문제(사선을 한쪽 경계로 받음, 안쪽 사선을 버림)는 남아 `flipping`/LOST가 된다(fork 먼저인 7회도 그 뒤 `flipping`이 나온다).
- 대조: `spoke_transverse` 클립(bend_15, 참값 (−0.69, −0.37), spoke 안)에서는 회전교차로 가로선으로 `junction_transverse`가 나온다.
  이것은 실제 교차로 입구(D-495 SW 자리)이므로 B9 수정 뒤에도 남아야 한다.

### bridge 무장

무장 조건(D-476 rev, `model.py` 175–186): 최근 3프레임 신뢰 ≥ 0.5, TRACKING, |오차| ≤ 0.1, |ω| ≤ 0.08.
x −1.15…−0.97 TRACKING 틱 383 중 370이 |ω| ≤ 0.08(중앙 0.063, p90 0.072)이고 `both` 오차는 −0.09…−0.02다.
16회 모두 마지막 무장 가능 프레임은 x −0.865…−0.920이고, 그 뒤 HOLD까지 7.1–11.3 s(sim) 동안 keeper가 굽이를 한쪽
경계로 읽어 |오차| 0.3–1.0으로 꺾었다(HOLD 직전 세 프레임 오차 예 [1.0, 1.0, 1.0], [0.59, 0.56, −0.46]). 무장이 풀리는
원인은 중심 치우침이 아니라 굽이 오독이다. 이 지도에서 굽이 앞 직선은 bridge가 쓸 자리도 아니다(교차로 입구가 아님).

## B9·B9b에 넘기는 것

- 고정 자료: `fixtures/b8_keeper_clips.npz` (89 프레임, 3,412,799 bytes,
  SHA-256 `35bc08e1a859a8d8033c0d31cddb5717cf497665d28309ead7724d222e6504bb`). `frames` uint8 (N, 240, 320, 3) BGR, `meta` JSON
  (clip, run, stamp, 참값 gt, event, live strategy/reason/error). 클립 7개를 `LaneKeeper.reset()`에서 위 keeper 설정
  (`evidence/b8_replay.py`의 `ground`)으로 재생하면 각 클립의 event 프레임이 live와 같은 전략·사유를 낸다.

  | clip | 프레임 | event (live) | B9/B9b에서 기대 |
  |---|---|---|---|
  | `south_centre_straight` | 13 | `both` | 그대로 |
  | `south_centre_lost` | 11 | `no_boundary` (x −0.893) | 굽이를 따라감(HOLD·LOST 아님) |
  | `corner_exit_offset` | 13 | `both`, 참값 +0.05 m | 그대로(인식은 맞음) |
  | `premature_corner_left` | 13 | `corner_left` (66° 사선) | 굽이 사선을 L-모서리로 읽지 않음 |
  | `bend_flipping` | 21 | `flipping` | `flipping` 없음 |
  | `bend_fork` | 11 | `junction_fork` | 교차로 사유 없음 |
  | `spoke_transverse` | 7 | `junction_transverse` | 그대로(진짜 교차로 입구) |

- B9b 범위 제안: 카메라·차로 폭·이득은 그대로 둔다. 「굽이 사선을 경계·모서리로 읽는 규칙」은 B9과 한 원인이므로 B9에서
  다루고, B9b는 (a) 모서리 탈출 잔여(`corner_*` 뒤 `both`로 돌아올 때 +0.067 m, 거리 상수 약 0.2 m)를 다룰지 B9 SIM 뒤 다시
  정한다. B9 SIM 합격선에 「x −0.95…−0.78 참값 오프셋 중앙 |·| < 0.02 m, `corner_left` 0회」를 더할 것을 제안한다.
- 남은 의문: `bend_3`, `bend_13`, `south_r`, `south_r2`의 출발 직후 `obstacle_ahead`(`body_gap_m 0.0`)는 B4(D-422 기억) 증거로
  넘긴다. 이 기록에는 `clearance_source`가 없다.

## 한계

- 호스트 SIM은 DEVICE가 아니다. Gazebo 바닥은 고르고 칠은 이진이며, 실물 카메라의 노출·블러·렌즈 왜곡이 없다.
- 한 지도의 한 굽이(약 63°)다. 다른 각도의 굽이와 실물 260919 트랙 프레임으로는 확인하지 않았다.
- SIM 빌드는 D-495 기준 `432445eed`이다. 같은 프레임을 main `62ab5172a`(G-16 포함) keeper로 재생해도 결과가 같았으므로
  (위 재생) 결론은 main keeper에도 해당한다. 폐루프 경로 자체는 main으로 다시 돌리지 않았다.

## 재현

```bash
# 모델 PC (~/rosy_d495_ws, D-495 하네스 그대로). b8_*.sh/py를 ~/rosy_d495_ws/b8 에, b8_run.sh를 evidence/ 에 둔다
RECOVERY=false setsid nohup bash evidence/b8_run.sh > b8_sim.out 2>&1 < /dev/null &
bash b8/b8_go.sh bend_1 trip --plan left:60 --duration 90 --tag B8B1_
bash b8/b8_go.sh south_c1 trip --plan left:60 --duration 60 --x -1.15 --y -0.509 --yaw 0 --tag B8S1_
# 노트북 (ROS 없음), rosy-platform 루트에서
PYTHONPATH="middleware/perception;contracts/foundation" python docs/validation/lane-trip-perception-2026-10-07/evidence/b8_replay.py <run>
python docs/validation/lane-trip-perception-2026-10-07/evidence/b8_analyze.py <runs> --json analysis.json
PYTHONPATH="middleware/perception;contracts/foundation" python docs/validation/lane-trip-perception-2026-10-07/evidence/b8_fixtures.py <runs> fixtures/b8_keeper_clips.npz
```

`evidence/analysis.json`은 run별 요약이다. 원시 기록(run마다 `rec/frames.npz` 전 프레임, `rec/keep.jsonl` 전 번들, probe의
`log.jsonl`·`cmd.jsonl`·`events.jsonl`·`summary.json`, 24 run)은 저장소 밖 `X:\DevTemp\lane-trip-perception\b8_runs_full.tgz`
(344,582,425 bytes, sha256 `c501cea48df793feb2a3d10df4fc93763edc7d7325d886324f0813c80dd60f05`)와 모델 PC
`~/rosy_d495_ws/b8runs`에 있다.
