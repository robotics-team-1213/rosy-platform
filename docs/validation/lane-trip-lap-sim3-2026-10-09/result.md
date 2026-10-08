# Fleet trip 한 바퀴 SIM 3차, 회전교차로 둘레 (모델 PC), 2026-10-09

증거 등급: **ROS-SIM (폐루프, 한 대) + 실제 Fleet trip 루프**. 장치·현장 수용이 아니다. Gazebo·ROS·pytest는 모델 PC(OMEN)에서만
돌렸고, 이 노트북에서는 기록 분석(ROS 없음)과 착지 게이트만 돌렸다. 실물 로봇은 건드리지 않았다.

대상: 로컬 main `b23055884`. 이 SIM 앞에 아래 세 브랜치를 착지했다.

| 브랜치 | 착지 | 무엇 |
|---|---|---|
| `fix/junction-corner-hold-scope` | `7bbe093d8` | `junction_corner_hold`는 지시와 어긋나는 모서리에서만 선다. API v1.152 `lane_turn_deg` |
| `fix/fleet-advance-needs-next-lane` | `e6392f223` | Fleet `_locate`는 지시가 끝났더라도 로봇이 다음 차로에 있어야 넘어간다(lap_12 `off_lane_m` 0.276) |
| `fix/junction-turn-lane-heading` | `b23055884` | 교차로 회전각은 들어오는 차로 끝 방향에서 나가는 차로 접선까지다. 6° 추가 없음 |

하네스: lap SIM 2의 `lap2_run.sh`·`lap2_batch.sh`와 같은 lap 하네스(`lap_fleet.py`·`lap_trip.py`·`lap_record.py`)를 쓰고 격리만 바꿨다
([`evidence/ring_run.sh`](evidence/ring_run.sh), [`evidence/ring_batch.sh`](evidence/ring_batch.sh)). 작업공간은 `~/rosy_ring_ws`(main
`git archive` 스냅숏, `colcon build --symlink-install --packages-up-to gz_sim core control description`)다. 격리 값은 ROS 도메인 92,
`GZ_PARTITION rosy_ring`, CORE 포트 8488, Fleet 8489, 실행 폴더 `ring`, world `ring_fleet_real.world`다. 설정은 **출하 기본**이다.
CORE 겹은 `obstacle_mode: path`, `ir_guard_enabled: true`, `site_floor_map_id: map_v2_fleet`이고 `arc_enabled`, `bridge_enabled`는 끔이다.
다른 세션(`rosy_tturn_ws` 등)의 프로세스는 건드리지 않았다. 계획은 lap SIM 2와 같다. 서쪽 길에서 출발해 `B_SW` 굽이 → SW `right` →
`ring_s` → SE `straight` → `ring_e` → NE `straight` → `ring_n` → NW `stop`이다.

## 결과 (구간별, 12회 + 기록 2회)

정의는 lap SIM 2의 [`lap2_segments.py`](../lane-trip-lap-sim2-2026-10-08/evidence/lap2_segments.py) 그대로다.

| 구간 | lap SIM 2 출하 기본 (12회) | **이번 (12회)** | 기록 run (2회) |
|---|---|---|---|
| 서→남 모서리 | 12/12 | **12/12** | 2/2 |
| 굽이 `B_SW` | 12/12 | **12/12** | 2/2 |
| SW 회전 끝 | 12/12 | **12/12** | 2/2 |
| SW 회전 끝 방향 − ring 접선 | 약 −20° (rec_01–03, 아래 원인 2) | **−1.1…−8.0°** (중앙값 −2.4°) | −2.0°, −2.0° |
| ring (SE 통과) | 0/12 | **0/12** | 0/2 |
| ring (NE 통과, `ring_n`) | 0/12 | **0/12** | 0/2 |
| NW 정지 | 0/12 | **0/12** | 0/2 |
| trip 완료 (`arrived`) | 0/12 | **0/12** | 0/2 |

| Fleet 끝 사유 | 횟수 | CORE 마지막 사유 |
|---|---|---|
| `junction_corner_hold` | 8 | 차선을 잃고 D-407 후진하는 중 keeper `corner_right`(왼쪽으로 도는 ring에서 어긋나는 모서리라 맞는 정지) |
| `pose` | 2 | `stuck_back_off` (후진이 차로 밖으로) |
| `stall` | 1 | `camera_reselection_required` |
| `junction_unexpected` | 1 | 후진 뒤 창 밖 감지 |

- 12회 모두 `ring_s` 위 (−0.31…−0.37, −0.30…−0.32)에서 먼저 차선을 잃었다(`camera_line_not_visible` 또는 keeper `no_boundary`).
  그 전에 ring 중심선 바깥으로 최대 +0.059…+0.070 m까지 나갔다. 차로 반폭은 0.0925 m다. 바깥선에서는 IR `lane_edge_right`가 먼저 걸렸다
  ([`evidence/ring_summary_lap3.json`](evidence/ring_summary_lap3.json)).
- lap SIM 2에서 ring을 막던 **오정지는 사라졌다.** SE `straight`에 Fleet이 `lane_turn_deg` 46–55°를 실었고, ring을 따르는
  `corner_left`에서는 서지 않았다. 남은 `junction_corner_hold` 8건은 모두 차선을 잃은 뒤 후진 중에 나온 `corner_right`에서다.
  `straight` 지시와 왼쪽으로 도는 차로에 어긋나는 모서리이므로 범위가 의도한 정지다
  ([`evidence/sends_lap3.jsonl`](evidence/sends_lap3.jsonl)).
- 걸린 trip(hang)은 0/14다. 모두 `stopped`로 닫혔다.

## 원인 (기록과 재생으로 확인)

### 1. `junction_corner_hold`가 ring 곡선에서 섰다 → 고쳤다 (`fix/junction-corner-hold-scope`)

lap SIM 2 원인 1과 같다. 지시와 어긋나는 모서리만 정지하게 했다. `left`·`right` 지시는 반대쪽 모서리만 정지한다.
`straight`는 Fleet의 `lane_turn_deg`(지도 차로가 장소까지 도는 방향 변화)가 그 모서리 쪽으로 20° 미만일 때만 정지하고,
값이 없으면 예전처럼 모든 모서리에서 정지한다. 시험에서 ring 경우(SE `straight`, `lane_turn_deg` 52, `corner_left`)는 서지 않는다.
SW 역주행 경우(`right` 지시에 `corner_left`)와 `left` 지시에 `corner_right`는 여전히 선다.

- 독립 Safety-Review(code-reviewer, opus) 1차 판정은 **REQUEST CHANGES**였다. HIGH 지적은 반대 방향 모서리 한 프레임이 2 s 래치를 풀고,
  만료 순간에는 지시를 버려 역주행 모서리로 놓아 준다는 것이었다. 모서리 방향마다 따로 래치하고 시험 두 개를 더해 고쳤다.
  2차 판정은 **APPROVE WITH NOTES**다.
- 남긴 것: 같은 방향 모서리는 `left`·`right` 지시를 `armed`로 둔다(47fa82b1a 이전 동작이다. 창·`junction_unexpected`·만료가 처리한다).
  260919 회전교차로에는 **안쪽 spoke가 없다.** 그래서 `straight`에서 차로 쪽 모서리를 따라가도 다른 차로로 들어가지 않는다.
  다른 지도에 안쪽 갈래가 있으면 다시 봐야 한다.

### 2. SW 회전이 ring 접선보다 바깥에서 끝났다 → 고쳤다 (`fix/junction-turn-lane-heading`)

lap SIM 2의 12–17°(호 주행)와 약 20°(출하 기본)는 우리 교차로 회전 목표에서 나왔다. 정확히는 Fleet `turn_target`이 보내는 `turn_deg`다.
CORE는 진입 yaw + `turn_deg`로 돈다.

- Fleet은 `theta` = 들어오는 차로 `end_tangent` → 나가는 차로 `start_tangent`를 보냈다. `end_tangent`는 5 cm lead 접선이다.
  `west:rev`의 이 값은 SW 입구 polyline의 잡음 때문에 **72.6°**다. 그 차로의 마지막 0.1–0.2 m는 62.7–63.2°이고, 로봇은 59–60°로 들어온다.
  여기에 `TURN_OVERTURN_DEG` 6°가 더해져 −120.6°를 보냈다. 회전은 −58.8°에서 끝났고, 그 자리 ring 접선 약 −40°보다 약 20° 바깥이다
  ([`evidence/ring_timelines_before.txt`](evidence/ring_timelines_before.txt) rec_01–03).
- 수정 후에는 끝 방향을 마지막 두 0.10 m 현으로 잰다. 값은 마지막 현에 두 현 차이의 절반을 더한 것이다. 원호에서는 접선과 0.1° 안이고,
  곧은 차로에서는 현과 같다. 그 방향에서 나가는 차로 시작 접선까지 회전하며, 6° 추가는 없다. 차로가 0.20 m보다 짧으면 `theta`를 쓴다.
  SW는 **−104.7°**를 보낸다. SIM 회전 끝은 −1.1…−8.0°다.
- 독립 리뷰 판정은 **APPROVE WITH NOTES**다. 짧은 차로 가드와 원호 추정 시험은 반영했다. 열린 점: NE 진입이 −108.8°에서 −97.4°로 바뀌었는데,
  이 lap 경로는 NE에서 돌지 않는다. 동쪽 길 출발로 NE 회전을 따로 4회 시도했지만, 출발 자리(0.11, 0.509)에서 `obstacle_ahead`로
  회전 전에 섰다(`runs_ne`, 원시 기록). **NE 회전의 SIM 증거는 없다.** SIM 4c에서 현 조준은 NE 재획득 0/3이었으니 다음 SIM에서 NE를 따로 본다.

### 3. lap_12 Fleet `off_lane_m` 0.276 (참값 0.07 m) → Fleet 버그, 고쳤다 (`fix/fleet-advance-needs-next-lane`)

- lap SIM 2 lap_12에서 keeper가 선을 잃었다. CORE는 SE `straight`를 `executing`으로 두고 D-407로 후진했고, 감지가 끊기자 그 직진을 닫았다(`idle`).
- Fleet `_locate`의 `done`(우리 지시가 끝남 + `pass_window_m` 0.3 안)이 SE 0.26 m 앞에서 인덱스를 `ring_e`로 넘겼다. 그래서 위치를
  `ring_e`·`ring_n`에 대고 쟀다. (−0.439, −0.305)에서 `ring_e` 시작까지는 0.278 m이고, 이것이 0.276이다. 같은 틱에 `pose`로 끝나
  보기 화면에는 `segment_index` 1이 남았다.
- 수정 후에는 `done`이 로봇이 다음 차로 반폭 안에 있을 때만 넘어간다. 새 시험은 수정 전에 실패한다.
- 독립 리뷰 판정은 **APPROVE WITH NOTES**다. 남긴 것: CORE가 후진 중에 직진을 일찍 닫는 일은 그대로이고, 이제 거짓 `pose` 대신 뒤의 `junction`·`stall`로 끝날 수 있다.
  이번 12회의 `pose` 2건은 후진이 실제로 차로 밖까지 간 경우다(`ring_s`에 대고 `off_lane_m` 0.093, 0.097 > 반폭 0.0925, 참값 dr +0.094).

### 4. ring에서 차선을 잃는 근본 원인: 카메라에 ring 차로가 보이지 않고, SE spoke가 온전한 차로로 보인다 (고치지 못함)

lap SIM 2·handoff SIM에서 SW를 지난 run이 모두 ring에서 차선을 잃은 이유다. 회전을 접선에 맞춘 뒤에도(위 2) 12/12 그대로다.
기록 run의 keeper 번들([`evidence/ring_keep_rec01.txt`](evidence/ring_keep_rec01.txt)), 프레임, 궤적
([`evidence/ring_tracks.png`](evidence/ring_tracks.png))으로 확인했다.

1. **안쪽(섬) 선은 ring 위에서 시야에 들어오지 않는다.** ring 차로는 중심 반지름 0.2514 m, 반폭 0.0925 m다. 섬 선이 차로 왼쪽 경계다.
   카메라는 높이 0.063 m, pitch 8°, 수평 시야 ±29.6°이고, 바닥은 약 0.105 m 앞부터 보인다. 거기서 보이는 옆 범위는 ±0.06 m인데,
   섬 선은 0.0925 m에 왼쪽으로 휘어 나가니 더 멀다. 기록 run의 ring 위 프레임 어디에도 섬 선이 경계로 잡히지 않았다.
2. **바깥선은 SW·SE 입구에서 끊긴 짧은 현이다.** 로봇이 접선 방향(−41°)을 보면 화면 대부분은 ring 아래쪽 바깥선과
   **SE spoke의 두 경계**다. 두 경계는 0.185 m 간격으로 나란하고, 절대 방향은 약 −70°다.
3. 회전이 끝나면 D-495 `advance_m` 0.10 m를 곧게 간다. 반지름 0.25 m 원에서는 그동안 접선이 23° 돈다. 그래서 재획득 때 로봇은 이미
   접선보다 −21…−30° 바깥을 향하고, 중심선보다 +0.02 m 바깥에 있다(12/12, `reacquire_dr_dyaw`).
4. keeper는 SE spoke의 두 경계를 **`both`(쌍)**로 잡는다(rec_01 1019.375–1019.625: 왼쪽 −14°, 오른쪽 −20°, 상대 방향).
   그리고 spoke 쪽으로 오른쪽을 향해 간다. 바깥선에 닿으면 IR `lane_edge_right`가 왼쪽으로 돌린다. 그 자리(−0.36, −0.315)는 SE 입구라
   바깥선이 끊겨 있고 섬 선은 시야 밖이다. 그래서 `no_boundary` → `camera_line_not_visible` → D-407 후진으로 간다.
5. 재생: 같은 기록 프레임을 main의 `LaneKeeper`(B8 replay, `b8_replay.py`)에 넣으면 rec_01 488/553, rec_02 474/537 프레임이 live 번들과 같다.
   차이는 노드의 회전 중 재시작을 replay가 적용하지 않은 탓이다. 판단은 재현된다. 따라서 이것은 keeper 코드의 일시 오류가 아니다.
   **기하의 한계**다. 직선 경계 모델에 lookahead 0.25 m, 반지름 0.25 m 원, 시야에 없는 한쪽 경계가 겹친다.

후보 원인 중 곡률과 안쪽 선 시야 밖은 **맞다**. IR guard는 원인이 아니라 바깥선 마지막 방어다. 모서리 규칙은 1에서 고친 오정지 말고는
원인이 아니다(차선을 잃은 뒤의 정지다).

**고치지 않은 이유.** 지도 없이 keeper만으로는 "보이는 온전한 차로(SE spoke)가 내 차로가 아니다"를 알 수 없다. 고칠 길은 둘이다.

- (a) **D-520 호 주행**: ring을 odom 호로 따라간다. 다른 세션의 몫이다.
- (b) **keeper에 지도 곡률 사전을 주는 새 CORE→인식 입력**: 이번 지시가 막은 길이다.

어느 쪽이든 결정이 필요해서 keeper 코드는 바꾸지 않았다. 그래서 B9 실제 프레임 fixture
(`middleware/perception/test/fixtures/b9_real_label_frames_main.json`)는 main과 같다.

## D-520(호 주행)에 도움이 될 것 (다른 세션, D-520 코드는 바꾸지 않았다)

- lap SIM 2의 호 진입 오차 −11.8…−16.8°도 같은 근원이다. `exit_segment` 경로는 아직 `theta`를 보낸다
  (`trip_runner.py` `(theta if arc else turn_target)`). SW에서 이 값은 −114.6°이고, 72.6° lead 접선을 기준으로 잰 것이다.
  `turn_target`(이제 −104.7°, 6° 추가 없음)을 쓰면 이번 출하 기본 SIM처럼 회전 끝 방향 오차가 −1…−8°로 준다. D-520 Context 6의
  r·ε 이동(0.2514 × 0.26 rad ≈ 0.066 m)도 약 0.01 m로 줄 것으로 예상한다. SIM으로 확인하지는 않았다.
- `test_trip_d520.py`의 주석 "tangent − 6 deg"(54행)는 이제 틀리다. 46행의 `turns != round(turn_target)` 검사는 이제 6° 추가가 아니라
  lead 접선과 현 방향의 차이 때문에 통과한다. ADR D-520 47행의 "접선 + 6°(잠정 규칙)"도 D-507 4항 개정(이번 브랜치)으로 낡았다.
- 4의 원인은 호 주행이 풀려는 문제 그 자체다. 출하 기본(keeper)으로는 260919 ring을 지나갈 수 없다는 것이 이번 SIM의 결론이다.

## 한계

한 대, 한 지도(260919 SIM), 한 출발, 한 목적지(NW)다. Fleet 지도 자세는 Gazebo 참값이다. 호스트 SIM은 DEVICE가 아니다.
NE 회전은 SIM으로 보지 못했다(위 2). 회전 수정 직후의 기록 run 4회(rec_05–08)는 프레임이 겹쳐 쓰였다. 앞 batch가 늦게 돌아 같은 폴더에
두 번째 batch가 돌았기 때문이고, 그 뒤 run은 두 batch가 겹친 것이라 표에 넣지 않았다. 겹치기 전에 받아 둔 CORE 기록(`log.jsonl`)만
`ring_timelines_before.txt`에 썼다.

## 재현

```bash
# 모델 PC: ~/rosy_ring_ws (main git archive + colcon build; pydeps·pyextra·pyfleet은 lap2 것의 링크)
setsid nohup bash ring_run.sh > sim.out 2>&1 < /dev/null &
OUTD=runs_lap3 setsid nohup bash ring_batch.sh lap3_batch.txt > batch.out 2>&1 < /dev/null &
REC=1 OUTD=runs_lap3rec setsid nohup bash ring_batch.sh lap3_batch_rec.txt > batch_rec.out 2>&1 < /dev/null &
python3 src/rosy-platform/docs/validation/lane-trip-lap-sim2-2026-10-08/evidence/lap2_segments.py runs_lap3 --json segments_lap3.json
python3 ring_summary.py runs_lap3 --json ring_summary_lap3.json      # 회전 끝, 재획득, 처음 잃은 자리
python3 ring_keep.py runs_lap3rec/rec_01                              # ring 위 keeper 번들 vs 참값
PYTHONPATH=middleware/perception:contracts/foundation python3 \
  docs/validation/lane-trip-perception-2026-10-07/evidence/b8_replay.py runs_lap3rec/rec_01
# 노트북 (ROS 없음): python ring_plot.py out.png <run>/log.jsonl ...  (저장소 루트에서)
```

증거 파일:

- `evidence/segments_lap3.json`, `segments_rec.json`
- `ring_summary_lap3.json`, `ring_summary_rec.json`
- `sends_lap3.jsonl`, `batch_lap3.log`, `batch_rec.log`
- `ring_timelines_before.txt`, `ring_keep_rec01.txt`, `ring_tracks.png`

`ring_tracks.png`의 빨강은 회전 수정 전(rec_02)이고, 보라·파랑·주황은 수정 후다.

원시 기록(run마다 `log/cmd/keep/actions/events/trip.jsonl`, `summary.json`, 기록 run의 `rec/keep.jsonl`·`frames.npz`, `runs_ne`, 수정 전
`runs_rec`)은 저장소 밖에 있다. `X:\DevTemp\lap-sim3\lap3_runs_full.tgz`(120,601,379 bytes, SHA-256 `ff5495e63c0f81982f4aed98c93b80a7b4d3fb9c27388953fd3d3d2976dc4657`)와 모델 PC `~/rosy_ring_ws`다.
