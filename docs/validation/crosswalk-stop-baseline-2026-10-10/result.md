# 횡단보도 정지 기준선 SIM (D-573 (g) 기준선, 모델 PC), 2026-10-10

증거 등급은 **ROS-SIM**이다. 폐루프 한 대에 실제 Fleet trip을 돌렸다. 장치·현장 수용이 아니다.

- Gazebo·ROS는 모델 PC(OMEN)에서만 돌렸다. 이 노트북에서는 채점 self-check와 착지 게이트만 돌렸다.
- 실물 로봇은 건드리지 않았다.
- 이 기록은 D-573 (g)의 S1–S10 실행기가 아니다. CORE 횡단보도 정지 게이트(D-573 (c))가 아직 없을 때의 **기준선**이다.

**판정: 지금 로봇은 횡단보도 앞에서 멈추고 보지 않는다.** D-573의 동작(대기 띠 앞 정지 → 보기 → 비면 건넘)은 7회 중 0회다.

- 사람이 없는 횡단보도를 보기 정지 없이 지나갔다(1/1).
- 0.60 m 다리와 0.15 m 인형 앞에서는 4/4 멈췄다. 그러나 사유는 모두 D-422 몸 기준 LiDAR 정지(`obstacle_ahead`)다. 멈춘 자리는 횡단보도 앞 0.02–0.03 m였다. 사람이 구역 안 가까운 변 쪽에 서 있었기 때문이다. 횡단보도를 알고 멈춘 것이 아니다.
- 0.10 m 인형(LiDAR 평면 0.125 m 아래)에는 2/2 부딪혔다.

## 대상과 환경

- 코드는 local main `eb9943953`의 `git archive`다. 작업공간은 `~/rosy_xwalk_ws`이고 `colcon build --symlink-install --packages-up-to gz_sim core control description`로 지었다. `pydeps`·`pyextra`·`pyfleet`은 lap SIM 4와 같은 링크다.
- 격리 값은 ROS 도메인 61, `GZ_PARTITION rosy_xwalk`, CORE 포트 8661, Fleet 8662, 실행 폴더 `xwalk`, world `xwalk_fleet_real.world`다. 시작 전에 같은 포트·도메인·gz sim이 없는 것을 확인했다. launch는 `systemd-run --user --scope -p MemoryMax=8G` 안에서 돌았다.
- 다른 세션의 pytest가 같은 시간에 돌았다(부하 5–11).
- 하네스는 lap SIM 4의 `ring4_run.sh`에서 격리 값만 바꾼 것이다([`evidence/xwalk_sim.sh`](evidence/xwalk_sim.sh)). 설정은 출하 기본 + `obstacle_mode: path`, `ir_guard_enabled: true`, `site_floor_map_id: map_v2_fleet`이다.
- 장면은 서쪽 길 남행이다.
  - 출발은 lap SIM의 출발 (−1.26955, 0.24255, −90°)이다. CAMERA_LINE을 고르고 Fleet trip `to: NW`를 시작한다(`lap_trip.py`와 같은 순서).
  - 지나는 횡단보도는 `lane_graph.yaml` `crosswalks[0]`이다. x −1.343…−1.197, y −0.086(가까운 변)…−0.206(먼 변)이다. 몸 앞(`body_front_x_m` 0.04205)에서 가까운 변까지 0.29 m다.
  - 보행자는 차로 중심 x −1.2696, 횡단보도 가운데 y −0.146에 둔다. 앞면은 가까운 변에서 0.04 m 안쪽이다.
- 보행자 모델 세 가지는 `integrations/simulation/gazebo/models/`에 있다. 모두 정적(static)이다.

| 모델 | 모양 | LiDAR 평면 0.125 m |
|---|---|---|
| `crosswalk_pedestrian_legs` | 원기둥 두 개, 반지름 0.02 m, 높이 0.60 m, 0.06 m 간격(길을 가로질러) | 지남 |
| `crosswalk_figurine_150` | 원기둥, 반지름 0.02 m, 높이 0.15 m | 지남 (현장 최소) |
| `crosswalk_figurine_100` | 원기둥, 반지름 0.02 m, 높이 0.10 m | 아래 |

- 실행기는 [`evidence/xwalk_run.py`](evidence/xwalk_run.py)다. 끝은 몸 앞이 먼 변을 0.15 m 지난 때(`passed`), 12 sim s 동안 서 있은 때(`held`), 또는 60 sim s다. 끝나면 trip을 취소하고 모델을 지운다.
- 채점은 `score()`다. Gazebo 참값 자세(`d495/gt`)와 odom 속도로 한다.
  - 정지 = |v| < 0.005 m/s가 1 sim s 이상이다.
  - "가까운 변까지"는 몸 앞에서 가까운 변까지이고, + 가 앞이다.
  - "보행자까지 최소 간격"은 몸 앞에서 보행자 앞면까지다. 0.003 m 이하면 충돌이다.
  - 정지 사유는 그때 CORE `/line-follow`의 state/reason이다. 그래서 장애물 정지와 D-573 게이트 정지를 나눈다. 지금 CORE에는 D-573 사유가 없다.

## 결과

| 회 | 보행자 | 끝 | 첫 정지: 가까운 변까지 / 사유 / CORE `body_gap_m` / 길이 | 보행자까지 최소 간격 (참값) | 충돌 | 구역 안 최고 속도 | trip 끝 |
|---|---|---|---|---|---|---|---|
| empty_01 | 없음 | 지나감 | +0.196 m / `camera_line_not_visible` / — / 2.9 s | — | — | 0.068 m/s | running |
| legs_01 | 다리 0.60 m | 섬 | +0.028 m / `obstacle_ahead` / 0.031 m / 4.9 s | 0.067 m | 아니오 | 0 | stopped (`stall`) |
| legs_02 | 다리 0.60 m | 섬 | +0.020 m / `obstacle_ahead` / 0.021 m / 4.9 s | 0.060 m | 아니오 | 0 | stopped (`stall`) |
| fig150_01 | 인형 0.15 m | 섬 | +0.031 m / `obstacle_ahead` / 0.041 m / 4.8 s | 0.066 m | 아니오 | 0 | stopped (`stall`) |
| fig150_02 | 인형 0.15 m | 섬 | +0.022 m / `obstacle_ahead` / 0.036 m / 4.9 s | 0.062 m | 아니오 | 0 | stopped (`stall`) |
| fig100_01 | 인형 0.10 m | 섬(부딪힌 뒤) | −0.039 m / `obstacle_ahead` / 0.0 m / 13.9 s | 0.000 m | **예** | 0.068 m/s | running |
| fig100_02 | 인형 0.10 m | 섬(부딪힌 뒤) | −0.042 m / `obstacle_ahead` / 0.0 m / 13.8 s | −0.005 m | **예** | 0.068 m/s | running |

- 접근 속도는 모든 회가 0.068 m/s였다.
- D-573 "횡단보도 앞에서 멈추고 기다림"은 0/7이다. 아래 둘을 따로 적는다.
  - **장애물 정지로 횡단보도 앞에 섬:** 4/4 (다리 2, 0.15 m 인형 2). 보행자가 구역의 가까운 변 근처에 있어서 생긴 결과다. 보행자가 대기 띠(보도)에 서 있거나 구역 안 먼 쪽에 있으면 이 정지는 횡단보도 앞에서 일어나지 않는다. 이번 기준선에서는 그 배치를 돌리지 않았다.
  - **횡단보도를 알고 섬(보기 정지, 사람 기다림):** 0/7. 사람이 없는 empty_01에도 보기 정지가 없었다.

## 지금 로봇이 하는 일

1. **사람 없음:** 횡단보도를 0.068 m/s로 그대로 지난다. 가까운 변 0.2 m 앞에서 2.9 s 선 것은 카메라 선 놓침(`camera_line_not_visible` → `stuck_back_off` → `camera_reselection_required` → 다시 추종)이다. 횡단보도 게이트가 아니다.
2. **0.60 m 다리, 0.15 m 인형:** D-422 몸 정지로 선다(LiDAR, `clearance_source: lidar`). 5 s 뒤 국소 stuck 복구가 뒤로 약 0.08 m 물러났다가 다시 다가가 또 선다. 이것이 2–3번 되풀이된다. 20 s에 Fleet trip이 `stall`로 끝나고 `stop` + `HOLD(mode OFF)`를 보낸다. 사람이 비켜도 로봇은 스스로 다시 가지 않는다.
3. **0.10 m 인형:** LiDAR가 보지 못해 0.068 m/s로 부딪힌다. 부딪힌 뒤에야 `obstacle_ahead`(간격 0.0)로 선다. Fleet trip은 `running`으로 남는다.

## 본 결함·관찰

- **D-573 게이트 없음(예상대로).** 사람이 없는 횡단보도에서 보기 정지가 없고, 정지 사유에 횡단보도가 없다.
- **사람 앞 stuck 복구가 사람에게 다시 다가간다.** 장애물 정지 5 s 뒤 `stuck_back_off` → `stuck_resumed` → TRACKING으로 같은 사람 앞까지 다시 간다(회당 2–3번). 횡단보도에 선 사람에게는 위협으로 보이는 동작이다. D-573 게이트는 이 자리에서 stuck 복구 대신 기다림이어야 한다.
- **0.10 m 인형 충돌 2/2.** D-573 현장 규칙 "인형 ≥ 0.15 m"의 근거와 같다. 카메라 사람 모델(D-573 10항) 전에는 막을 길이 없다.
- **짧은 0.0 m `obstacle_ahead`.** 사람이 없는 구간과 empty_01에서도 0.3 s짜리 `obstacle_ahead`(`body_gap_m` 0.0~0.013)가 나왔다(empty_01은 몸 앞 y 0.128과 −0.084). 출발 직후와 횡단보도 가까운 변에서다. 원인은 보지 않았다. SIM LiDAR `<min>`은 0.05 m이고, 장치 `range_min`(약 0.15 m)과 다르다.
- **간격 두 값의 차이.** 정지할 때 CORE `body_gap_m`은 0.02–0.04 m이고, 참값 기하로 잰 몸 앞–보행자 앞면은 0.06–0.07 m다. 약 0.03–0.04 m 차이가 일정하다. `d495/gt`는 `rosy` 모델 원점이다. 이 차이의 원인은 보지 않았다.
- **Fleet trip 끝 상태가 다르다.** 장애물 앞에서 선 회는 `stall`로 끝났지만, 부딪힌 회(0.10 m)는 `running`으로 남았다. 실행기가 12 s 정지에서 회를 끝내서 Fleet `stall` 문턱 20 s 전이었다. 부딪힌 채 서 있는 로봇을 Fleet이 언제 알리는지는 이번에 보지 않았다.

## 한계

- 한 대, 한 지도(260919 SIM), 한 횡단보도, 한 방향(남행), 보행자 자리 하나(구역 가운데, 차로 중심), 정적 보행자다. 대기 띠(보도)의 사람, 움직이는 사람, 구역 먼 쪽 사람은 돌리지 않았다.
- 변형마다 2회다. 반복성 판정이 아니다.
- gz `actor`가 SIM LiDAR에 보이는지는 확인하지 않았다(정적 충돌 모델만 썼다).
- Fleet 지도 자세는 Gazebo 참값이다. 호스트 SIM은 DEVICE가 아니다.

## 재현

```bash
# 모델 PC: ~/rosy_xwalk_ws (local main git archive + 이 브랜치의 evidence·models, colcon build)
E=src/rosy-platform/docs/validation/crosswalk-stop-baseline-2026-10-10/evidence
setsid nohup bash $E/xwalk_sim.sh > sim.out 2>&1 < /dev/null &
OUTD=runs setsid nohup bash $E/xwalk_batch.sh $E/xwalk_batch.txt > batch.out 2>&1 < /dev/null &
python3 $E/xwalk_run.py --self-check   # 채점만, ROS 없음
```

원시 기록(각 회의 `log.jsonl`·`cmd.jsonl`·`events.jsonl`·`actions.jsonl`·`summary.json`, `rescore.json`, Fleet `sends.jsonl`)은 `X:\DevTemp\crosswalk-gazebo\runs\`와 모델 PC `~/rosy_xwalk_ws/runs/`에 있다. 표의 값은 지금의 `score()`로 다시 매긴 [`evidence/rescore.json`](evidence/rescore.json)이다. 실행 때의 `summary.json`은 empty_01의 판정만 다르다(고치기 전에는 정지가 하나라도 있으면 `stopped_before`였다).
