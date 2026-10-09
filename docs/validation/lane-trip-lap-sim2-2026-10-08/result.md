# Fleet trip 한 바퀴 SIM 2차 (모델 PC), 2026-10-08

증거 등급: **ROS-SIM (폐루프, 한 대) + 실제 Fleet trip 루프**. 장치·현장 수용이 아니다. Gazebo·ROS는 모델 PC(OMEN)에서만 돌렸고
이 노트북에서는 기록 분석(ROS 없음)만 했다. 실물 로봇은 건드리지 않았다. 제품 코드는 바꾸지 않았다.

대상: 로컬 main `47fa82b1a`(`fix/junction-corner-hold` 착지 직후: 굽이→교차로 넘겨주기, 모서리 정지 `junction_corner_hold`와
그 liveness, D-520 단계 1 호 주행 코드 포함). 하네스는 [lap SIM](../lane-trip-lap-sim-2026-10-08/result.md)의 `lap_fleet.py`·
`lap_trip.py`·`lap_record.py`·`lap_analyze.py`를 그대로 쓰고, 격리만 바꿨다([`evidence/lap2_run.sh`](evidence/lap2_run.sh),
[`evidence/lap2_batch.sh`](evidence/lap2_batch.sh)): 작업공간 `~/rosy_lap2_ws`(main `git archive` 스냅숏, `colcon build
--symlink-install --packages-up-to gz_sim core control description`), ROS 도메인 91, `GZ_PARTITION rosy_lap2`, CORE 포트 8388,
Fleet 8389, 실행 폴더 `lap2`, world 파일 `lap2_fleet_real.world`. 다른 세션(도메인 78 `rosy_d507`, 81 `rosy_bws`)의 프로세스는
건드리지 않았고, 끝난 뒤 `GZ_PARTITION=rosy_lap2` 프로세스만 멈췄다(남은 것 0).

설정 두 가지, 각 12회. 계획은 모두 같다: 서쪽 길 출발 → `B_SW` 굽이 → SW `right` → `ring_s` → SE `straight` → `ring_e` →
NE `straight` → `ring_n` → NW `stop`.

- **출하 기본**: CORE 겹 `obstacle_mode: path`, `ir_guard_enabled: true`, `site_floor_map_id: map_v2_fleet`, 나머지 기본
  (`bridge_enabled` 끔, `recovery_local_enabled` 켬, `arc_enabled` 끔).
- **호 주행**: 같은 겹 + D-520의 문서화된 스위치 `line_follow.arc_enabled: true`(ADR D-520 「설정」, `ARC=1`). CORE 능력
  `lane_arc: true`를 확인했고 Fleet은 SW·SE·NE 지시에 `exit_segment`를 실었다(`sends_arc.jsonl`).

## 결과 (구간별)

정의는 [`evidence/lap2_segments.py`](evidence/lap2_segments.py) 머리말: 모서리 = 참값 x > −1.15, y < −0.45; 굽이 = `B_SW`가
중단·미해결 없이 SW 지시로 넘어감; SW 회전 = SW 지시가 돌고 중단 없이 차선 재획득 또는 `ring_s` 호를 엶; ring = trip이 마지막
구간 `ring_n`에 닿음(SE·NE 통과); NW 정지 = NW `stop`이 `executing`이 됨 또는 도착; 완료 = Fleet trip `arrived`.

| 구간 | lap SIM 1차 (`caa74a53c`, 20회) | 넘겨주기 SIM (12회) | **출하 기본 (12회)** | **호 주행 `arc_enabled` (12회)** |
|---|---|---|---|---|
| 서→남 모서리 | 16/20 | 11/12 | **12/12** | **12/12** |
| 굽이 `B_SW` | 16/16 | 10/11 넘김 | **12/12** | **12/12** |
| SW 회전 끝 | 0/16 | 10/11 | **12/12** | **12/12** |
| ring (SE 통과) | — | 2/10 (`ring_e`에서 정지) | **0/12** | **2/12** |
| ring (NE 통과, `ring_n`) | — | 0 | **0/12** | **1/12** |
| NW 정지 | — | 0 | **0/12** | **1/12** |
| trip 완료 (`arrived`) | 0/20 | 0/12 | **0/12** | **1/12** (arc_11) |

| 설정 | 끝난 이유 (Fleet) | 멈춘 자리 (참값) |
|---|---|---|
| 출하 기본 | `junction_corner_hold` 11, `pose` 1 (lap_12) | 모두 `ring_s`, (−0.39…−0.44, −0.30…−0.32) |
| 호 주행 | `lane_arc` (`lane_arc_edge`) 10, `pose` 1 (arc_10), `arrived` 1 (arc_11) | `lane_arc_edge` 10회 모두 `ring_s` 끝 SE 앞 (−0.156…−0.168, −0.254…−0.257); arc_10 NE 호 끝 (−0.093, 0.170) |

- 걸린 trip(hang) 0/24. 매번 `stopped`/`arrived`로 닫혔고 `stop_sent: true`, CORE `OFF`, 명령 (0, 0).
- **liveness 확인**: CORE가 `junction_corner_hold`를 낸 뒤 Fleet이 trip을 끝내고 CORE가 `OFF`가 되기까지 0.12–0.49 s(13건,
  기록 run 포함). 20 s stall까지 기다린 run은 없다.
- 기록 run(`REC=1`, 출하 기본, 3회, 위 표에 넣지 않음): rec_01·rec_03 `junction_corner_hold`(`ring_s`), rec_02 모서리 출구
  (−1.195, −0.455)에서 `lane_return_fleet_required` → `stall` 20 s(lap SIM 1차의 원인 C와 같음). `segments_rec.json`.

## 남은 실패의 원인 (기록으로 확인; 제품 코드는 고치지 않았다)

### 1. 출하 기본: `junction_corner_hold`가 ring의 차선 곡선을 막는다 (11/12, 기록 run 2/2)

SW 회전과 재획득은 12/12 끝났다. 그 직후 Fleet이 SE `straight`(지도 창 `expect_in_m` 0.23–0.24, `expect_tol_m` 0.17,
`pivot_past_line_m` −0.231)를 보내고, CORE는 `armed`인 채 `ring_s`를 keeper로 따른다. 1–2 s 뒤 (−0.39…−0.43, −0.30…−0.32),
yaw ≈ 0(ring 아래쪽 접선 방향)에서 HOLD `junction_corner_hold`다.

- keeper 전략(rec_01, rec_03 keep_debug 번들): `left_only` → **`corner_left`** (rec_01 stamp 105.75, 참값 (−0.417, −0.310, −0.13 rad);
  rec_03 228.62, (−0.407, −0.302, −0.10 rad)). 반시계 일방 ring에서 왼쪽으로 굽는 것은 차로 자체다. 오독된 교차로 선이 아니다.
- 그 자리의 기대선 거리: `approach._corner_at_expected_line`의 `line = expect_in − pivot − travel` ≈ 0.232 + 0.231 − 0.02 ≈ 0.44 m
  ≤ `CORNER_HOLD_AHEAD_M` 0.45 + tol 0.17 = 0.62 m. SE 지시가 `armed`인 `ring_s` 전체(호 길이 0.374 m)가 정지 범위 안이다.
- 그래서 이 정지는 「지도가 교차로를 말하는 자리 근처의 keeper 모서리 = 오독」이라는 가정이 곧은 spoke(lap SIM A의 SW 입구)에서는
  맞고, 곡선 차로(ring) 위의 `straight` 지시에는 틀린다. 지시가 `straight`이고 그 구간이 곡선인지, 모서리 방향이 지도 차로의
  굽는 방향과 같은지를 보지 않는다.
- 로봇은 그때 ring 중심선보다 +0.058…+0.085 m 바깥이었다(참값, 중심 (−0.3357, 0.0011), r 0.2514). keeper가 ring을 직선 현으로
  따른 결과(D-520 Context 3)이고, 이 정지가 없던 넘겨주기 SIM에서도 SW 회전을 끝낸 10/10이 ring에서 섰다(`ring_s` 8,
  `ring_e` 2; `pose`·`junction`·`junction_unexpected`·`stall`). 즉 정지가 ring 실패를 새로 만든 것은 아니고, 역주행 위험 대신 깨끗한 정지로 바꿨다.
- lap_12(1/12): 같은 자리에서 keeper가 선을 잃음(`camera_line_not_visible`, (−0.391, −0.303)) → SE `straight`가 `executing` →
  D-407 `stuck_back_off`로 0.048 m 후진 → Fleet `pose`(`off_lane_m` 0.276). 참값 Δr은 +0.07 m라 Fleet의 0.276은 후진 중
  위치 판정값이며, 그 계산은 추적하지 않았다.

### 2. 호 주행: ring 진입 방향이 접선보다 12–17° 바깥 → 바깥선 → `lane_arc_edge` (10/12)

- Fleet은 SW `right` `turn_deg` −114.6(지도 접선)과 `exit_segment` {κ 3.9772, 길이 0.3738, 바깥선 0.095, 끝 SE}를 보냈다.
- 호 시작(참값): Δr −0.010…+0.024 m, **yaw − 반시계 접선 = −11.8…−16.8°**(12/12). 회전 진입 yaw는 굽이 출구 방향
  1.02–1.05 rad이고, 회전 축은 SW 노드 앞(−0.48…−0.51, −0.18…−0.21)이다. D-520 단계 1 SIM은 64° 진입 자세에서 바로 시작해
  SW 진입 오차가 +1.0…+1.7°였다.
- D-520 Context 6의 예측(처음 방향 오차 ε가 원 중심을 r·ε 옮김: 0.2514 × 0.26 rad ≈ 0.066 m)과 맞게, Δr은 +0.053…+0.057 m에서
  오른쪽 IR이 바깥선을 보고(`lane_arc_correcting`, (−0.28…−0.40, −0.30…−0.31)) 최대 +0.061…+0.068 m까지 갔다.
- 10회는 IR 보정 중 SE spoke 입구 앞에서 `lane_arc_edge` HOLD(IR level > `ARC_IR_LEVEL_MAX_M`)로 섰고 Fleet이 `lane_arc`로
  끝냈다. arc_10·arc_11은 같은 보정을 넘겨 SE에 닿았다.
- arc_10: `ring_e` 호까지 끝낸 뒤 NE 호 끝 (−0.093, 0.170)에서 Fleet `pose`(`off_lane_m` 0.098 > 폭/2 0.0925).
- arc_11: SE·NE 호를 끝내고 NW에서 `stop`, **trip 완료**. 이 SIM 계열에서 처음 완료한 trip이다.
- 이것은 D-520 단계 1 판정 FAIL(흐름 33 mm, NE 진입 −14…−21°)의 같은 원인이 Fleet 한 바퀴에서도 나온 것이다. D-520은
  여전히 장치에서 켜지 않는다.

### 3. 모서리 출구 D-468 복귀 소진 (기록 run 1/3, 표의 24회에서는 0)

rec_02: lap SIM 1차 원인 C와 같은 자리 (−1.195, −0.455)에서 `lane_return_sensor_search` → `lane_return_fleet_required` →
Fleet `stall` 20 s. 아직 남아 있다.

## 다음 수정 후보 (결정은 다음 계획)

1. `junction_corner_hold`: `straight` 지시나 곡선 구간(지도 `exit_segment`·차로 곡률이 있는 자리)에서는 정지하지 않거나,
   keeper 모서리 방향이 지도 차로가 굽는 방향과 같으면 정지하지 않는다. lap SIM A(곧은 spoke의 SW 입구에서 `corner_left`)를
   다시 막는지 같이 시험한다.
2. D-520: 회전 각을 지도 접선이 아니라 회전 축 자리의 ring 접선과 측정된 진입 yaw로 정하거나, 단계 2 첫 카메라 맞춤의
   `lane_arc_entry` 문을 붙인다.
3. Fleet 위치 판정이 D-407 후진 중 0.276 m를 낸 이유(lap_12)를 확인한다.

## 한계

한 대, 한 지도(260919 SIM), 한 출발, 한 목적지(NW). Fleet 지도 자세는 Gazebo 참값이다. 호스트 SIM은 DEVICE가 아니다.
기록 run 3회는 모델 PC 부하가 다른 세션과 겹친 상태에서 돌렸다(load 3–4, 24코어).

## 재현

```bash
# 모델 PC: ~/rosy_lap2_ws (main git archive + colcon build, pydeps/pyextra/pyfleet은 lap SIM 것의 링크)
H=src/rosy-platform/docs/validation/lane-trip-lap-sim2-2026-10-08/evidence
setsid nohup bash $H/lap2_run.sh > sim_def.out 2>&1 < /dev/null &               # ARC=1 이면 arc_enabled: true
OUTD=runs_def setsid nohup bash $H/lap2_batch.sh $H/lap2_batch.txt > batch_def.out 2>&1 < /dev/null &
# 노트북 (ROS 없음)
python docs/validation/lane-trip-lap-sim2-2026-10-08/evidence/lap2_segments.py <runs> --json segments.json
```

증거: `evidence/segments_default.json`, `segments_arc.json`, `segments_rec.json`(run마다 구간, CORE 사유 전환, Fleet 송신),
`sends_default.jsonl`, `sends_arc.jsonl`, `batch_default.log`, `batch_arc.log`. 원시 기록(run마다 `log/cmd/keep/actions/events/
trip.jsonl`, `summary.json`, 기록 run의 `rec/keep.jsonl`·`frames.npz`)은 저장소 밖 `X:\DevTemp\lap-sim2\lap2_runs_full.tgz`
(50,882,716 bytes, SHA-256 `dbe07bde89a5e04a9b70093f19655c1f2d36f42c7bbce2c8ba4c9c98477a5a77`)와 모델 PC `~/rosy_lap2_ws`에 있다.
