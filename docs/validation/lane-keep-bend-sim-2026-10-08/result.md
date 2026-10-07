# D-507 B9 남서 굽이 keeper 수정 SIM (모델 PC), 2026-10-08

증거 등급: **ROS-SIM (폐루프, 한 대) + 호스트 시험**. 장치·현장 수용이 아니다. Gazebo·ROS는 모델 PC(OMEN)에서만 돌렸고
이 노트북에서는 돌리지 않았다. 실물 로봇은 건드리지 않았다.

대상: `fix/keep-bend-not-fork` 05462b7d9 (위 표·아래 「결과」), 검토 반영 뒤 e192ef089 (아래 「검토 반영 뒤 재실행」). keeper: `lane_keep_bend.py`, `lane_keep_junction.py` 연속성, `lane_keep.py`).
B8(`docs/validation/lane-trip-perception-2026-10-07/result.md`)이 찾은 원인 — 약 63° 굽이를 읽는 규칙이 없음 — 을 고친 뒤 같은
하네스로 다시 돌렸다.

## 판정 요약

| 합격선 (계획 B9, B8 제안) | 결과 |
|---|---|
| 굽이 진입에서 `junction_fork` 0 | 0 (굽이에 닿은 11회) |
| `flipping` 0, 굽이에서 LOST ≤ 1/15 | `flipping` 0, 굽이 LOST 0 |
| `corner_left` 0 | 0 (모든 `corner_*` 0) |
| x −0.95…−0.78 참값 오프셋 중앙 \|·\| < 0.02 m | run별 중앙 +0.0139…+0.0157 m, 최대 \|·\| 0.0190 m |
| 굽이 통과 | 11/11이 굽이를 지나 회전교차로 입구 `junction_transverse`(진짜 교차로)에 닿았다. B8은 0/16 |

16회 진입 중 5회는 굽이에 닿지 못했다. 원인은 이 수정 밖이다(아래 「굽이에 닿지 못한 run」).

## 설정

- 작업공간 `~/rosy_b9_ws`: `~/rosy_d495_ws/src`(432445eed)를 로컬 clone한 뒤 이 브랜치를 bundle로 받아 checkout, D-495와 같은
  `colcon build --symlink-install --packages-up-to gz_sim core control description`. CORE·keeper 모두 이 브랜치(main 기준) 코드다.
- `evidence/b9_run.sh`: D-495 `run_sim.sh`를 바꾸지 않고 ROS 도메인 79, `GZ_PARTITION rosy_b9`, CORE 포트 8099, 실행 폴더
  `~/rosy_b9_ws/b9`, world 파일 이름 `b9_fleet_real.world`로만 바꿔 띄웠다. `RECOVERY=false`. 시작 전 다른 Gazebo·ROS 프로세스
  없음, GPU 0 %. 끝난 뒤 이 파티션의 프로세스만 멈췄다(남은 것 0).
- CORE 겹·keeper 설정은 B8과 같다(`camera_x_offset_m 0.03317`, `lane_half_width_m 0.0925`, `lane_corner_turning: true`).
- 실행(`evidence/batch.txt`): 굽이 진입 pilot + 15회(서쪽 길 (−1.27, 0.24, −90°)에서 `trip --plan left:60`), 아래 길 가운데
  출발 3회. 기록은 B8 `b8_record.py`, 요약은 `evidence/b9_analyze.py` → `evidence/analysis.json`.

## 결과 (굽이에 닿은 11회: pilot, bend_1, 2, 7–14)

| 항목 | 값 |
|---|---|
| x −0.95…−0.78 참값 오프셋 중앙 (run별) | +0.0139…+0.0157 m (B8 같은 구간 +0.020…+0.057) |
| 같은 구간 최대 \|오프셋\| | 0.0174…0.0190 m |
| `corner_*` / `junction_fork` / `flipping` 프레임 | 0 / 0 / 0 |
| 굽이 뒤 첫 HOLD 사유 | `junction_transverse` 5, 한 프레임 `no_boundary` 뒤 `junction_transverse` 6 |
| `junction_transverse` 첫 자리 (참값) | x −0.716…−0.723, y −0.457…−0.464, yaw 49–52° (회전교차로 바깥 원 앞) |
| 그 뒤 probe의 `left:60` | `done` 4, `aborted`(`near_stop`) 7 |

keeper 흐름(pilot 예): x −0.95까지 `both`, 굽이 사선이 보이면 `bend_ahead`(직진, 굽이 중심선이 로봇 경로와 만나는 점이
`CORNER_LOOKAHEAD_M` 0.12 m 밖), x −0.80부터 `bend_left`(굽이 중심선 추종, |오차| ≤ 0.6), 사선이 45° 아래로 오면 `right_only`/
`both`, x −0.72에서 회전교차로 `junction_transverse`.

`no_boundary` 한 프레임(6회, 참값 (−0.74, −0.487), yaw 43–45°)은 CORE 상태를 바꾸지 않았다(다음 프레임에 `junction_transverse`).
`left:60` `aborted`는 교차로 회전·접근(B11 범위)이다. 굽이를 안쪽으로 조금 끊어 들어가 교차로를 볼 때 로봇은 아래 길 중심보다
+0.05 m 왼쪽이다.

아래 길 가운데 출발: `south_c3` x −0.95…−0.78 중앙 +0.0022 m. `south_c1`, `south_c2`는 출발 직후 CORE `obstacle_ahead`로 섰다.

## 굽이에 닿지 못한 run (이 수정 밖)

| run | 자리 | 원인 |
|---|---|---|
| bend_3, bend_6 | 아래 길 x −0.82, −0.90 | CORE `obstacle_ahead`, 사건 `clearance_source: memory`, `body_gap_m 0.0` (D-422 기억 래치, B8의 bend_3/13과 같음 → B4) |
| bend_4 | 굽이 안 (−0.75, −0.494) | 같은 CORE `obstacle_ahead` |
| bend_5 | 서쪽 길 (−1.27, 0.06) | 같은 CORE `obstacle_ahead` |
| bend_15 | 서쪽 길 횡단보도 (−1.27, 0.15), yaw −92.6° | keeper `no_boundary` → LOST. 같은 프레임을 432445eed keeper로 재생해도 `no_boundary`: 기존 결함(횡단보도와 T자 입구) |

## 검토 반영 뒤 재실행 (e192ef089)

독립 검토(CHANGES REQUESTED) 반영: 닫힌 쪽에 근거 평행선이 사선의 가까운 끝을 넘어 이어지면 굽이가 아님(정지선·횡단보도·
교차로 입구), 교차로 규칙을 굽이보다 먼저 판단, 65°를 넘는 굽이 선도 교차로 규칙에는 가로선으로 넘김(교차로는 닫힌 쪽으로
실패), 가파른 선의 가까운 끝 편 정하기·편 상속·가까운 순서는 corner turning에서만. 같은 하네스로 굽이 진입 8회
(`evidence/analysis_e192ef089.json`; 중간 커밋 d3f72e17c로 6회도 돌렸고 같은 모양이었다):

| 항목 | 값 |
|---|---|
| 굽이에 닿음 | 5/8 (f_2, 3, 4, 5, 7). 나머지 3회는 CORE `obstacle_ahead`(`clearance_source: memory`): 아래 길 x −0.835, 서쪽 길, 굽이 안 (−0.745, −0.489) |
| x −0.95…−0.78 오프셋 중앙 (run별, 8회 모두) | +0.0125…+0.0147 m, 최대 \|·\| 0.0199 m |
| `corner_*` / `junction_fork` / `flipping` | 0 / 0 / 0 |
| 첫 HOLD | 5회 모두 회전교차로 `junction_transverse` (x −0.716…−0.728) |
| `left:60` | `done` 3, `aborted`(`near_stop`) 2 |

남은 대가: B8 `premature_corner_left` 사건 프레임(yaw −3.5°에서 66°로 보인 바깥 사선 옆에 안쪽 경계가 바깥으로 꺾임)은 한 프레임
`junction_transverse`로 선다. 한 프레임에서는 교차로 입구와 구별되지 않는다. 이번 SIM 8회에서는 굽이 앞에서 이 HOLD가 나오지
않았다. 경로 문맥(B11 expect window)이 정할 몫이다.

실물 프레임(라벨 세션 124745Z·133221Z 434장, NOMINAL 지면, 열린 고리) 재생: corner turning 끔은 main과 0프레임 다름.
corner turning 켬(장치 payload 기본)은 e192ef089에서도 119프레임이 다르다(HOLD → 주행 29, 주행 → HOLD 0, `bend_*` 69, HOLD 0.237 → 0.171). 이
트랙에는 63° 굽이가 없어 운영자 검토가 필요하다(아래 한계).

## 한계

- 한 지도의 한 굽이(약 63°)다. 다른 각도의 굽이와 실물 260919 프레임으로는 확인하지 않았다.
- B9은 굽이 읽기만 고쳤다. 교차로 회전(`near_stop` 7/11)과 D-422 기억 래치는 B11·B4다.
- 호스트 SIM은 DEVICE가 아니다.
- **착지 전 운영자 검토 필요**: 실물 프레임에서 corner turning 켬일 때 바뀐 프레임(특히 HOLD → 주행, `bend_*`)이 따라가도
  되는 차로인지 사람이 확인하지 않았다. 굽이 규칙은 corner turning(장치 기본 켬)에서 실물에 닿는다.

## 재현

```bash
# 모델 PC: ~/rosy_b9_ws (위 설정), evidence/* 를 ~/rosy_b9_ws/b9/ 에
RECOVERY=false setsid nohup bash b9/b9_run.sh > b9_sim.out 2>&1 < /dev/null &
setsid nohup bash b9/batch.sh > /dev/null 2>&1 < /dev/null &
python3 b9/b9_analyze.py b9runs --json b9runs/analysis.json
# 노트북 (ROS 없음): B8 고정 자료 회귀
python -m pytest middleware/perception/test/test_lane_keep_bend.py -q
```

원시 기록(run마다 `rec/frames.npz`, `rec/keep.jsonl`, probe `log.jsonl`·`summary.json`·`events.jsonl`)은 모델 PC
`~/rosy_b9_ws/b9runs`에 있다.
