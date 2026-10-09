# D-507 B13 Fleet trip 한 바퀴 수용 SIM (모델 PC), 2026-10-08

증거 등급: **ROS-SIM (폐루프, 한 대) + 실제 Fleet trip 루프**. 장치·현장 수용이 아니다. Gazebo·ROS는 모델 PC(OMEN)에서만 돌렸고
이 노트북에서는 기록 분석(ROS 없음)만 했다. 실물 로봇은 건드리지 않았다. 제품 코드는 바꾸지 않았다.

대상: 로컬 main `caa74a53c`(D-507 B6·B9·B10–B12, 지도 굽이 `bend`, 굽이가 hold를 따름, keeper 제자리 회전 재시작 수정
`9abbc9de7`·`223524991`, D-422 기억 규칙 포함). 질문: Fleet 지도 trip이 차선 로봇에서 실제로 끝까지 가는가.

## 판정 요약

**완료한 trip: 0/20 (0 %).** 20회 모두 Fleet이 trip을 멈추고 로봇을 세웠다. 걸린 trip(hang)은 0이다.

| 구간 (20회) | 결과 |
|---|---|
| 서→남 모서리 통과 (참값 x > −1.15, y < −0.45) | **16/20**. 4회는 모서리를 돈 직후 출구 (−1.19, −0.457)에서 D-468 차선 복귀로 섰다(원인 C) |
| 남서 굽이 통과 (`B_SW` `bending`→`reacquiring`, 중단 없음) | **16/16** (굽이에 닿은 run 기준) |
| 회전교차로 SW 우회전 시작 (`approaching`/`turning`) | **3/16** |
| 회전 끝 (`reacquiring`) | **0/16** |
| 재획득 (SW 지시가 `idle`로 끝나고 다음 구간으로) | **0/16** |
| trip 완료 (`arrived`) | **0/20** |

멈춘 이유와 자리 (원인은 아래 「원인」):

| 원인 | 횟수 | Fleet 종료 사유 | 멈춘 자리 (참값) | run |
|---|---|---|---|---|
| A. 굽이 뒤 SW 교차로를 못 봄 → keeper `corner_left`로 원형 교차로 서쪽을 역주행 | 11 | `pose`(계획 차로 밖 > 0.0925 m) 9, `junction_no_window` 2 | (−0.572…−0.584, −0.073…−0.109) 회전교차로 서쪽 | lap_01, 02, 03, 06, 07, 10, 12, rec_2, 3, 5, 8 |
| B. CORE가 SW에서 `approaching`인데 Fleet이 다음 곳(SE) `straight`를 보내 CORE가 회전을 중단 | 3 | `junction` (`aborted`) | (−0.485, −0.241), (−0.494, −0.249), (−0.506, −0.185) | lap_05, 08, 09 |
| C. 모서리 출구에서 D-468 차선 복귀 → 회전 탐색 소진 → `lane_return_fleet_required` | 4 | `stall` (20 s) | (−1.189…−1.196, −0.456…−0.458) | lap_04, 11, rec_1, 6 |
| D. 굽이가 교차로 목격으로 끝나 CORE `waiting`, Fleet은 굽이를 아직 안 끝난 것으로 봐 SW 지시를 안 보냄 | 1 | `junction` (`waiting` 10 s) | (−0.638, −0.439) spoke | rec_4 |
| E. spoke에서 차선 잃음(`no_boundary`) → D-407 후진 → 다시 본 교차로가 창 밖 | 1 | `junction_unexpected` | (−0.628, −0.412) spoke | rec_7 |

| 그 밖의 질문 | 답 |
|---|---|
| D-422 HOLD | run당 1–7회(`obstacle_ahead`) + 굽이 중 0–3회(`junction_bend_blocked`), 서쪽 길·모서리·아래 길. 모두 풀렸다. 출처를 기록한 rec 8회의 33건은 `lidar` 31, 빈 값 2(사유 전환 프레임), **`memory` 0**, `body_gap_m` 0.0–0.025 |
| `near_stop` | 0/20 (이벤트·junction 사유 모두) |
| 실패 때 Fleet이 깨끗이 끝내나 | **예, 20/20.** 매번 trip이 `stopped`로 닫히고 `stop_sent: true`, 이어 line-follow `OFF`; 3 s 뒤 CORE `OFF`, 명령 (0, 0). trip 시작부터 종료까지 37–42 s. 걸린 trip 0 |
| 안전 관찰 | 원인 A에서 로봇은 한 방향(반시계) 회전교차로의 서쪽 원을 북쪽으로(역방향) 약 0.25 m 달린 뒤 Fleet의 차로 밖 검사(폭/2 = 0.0925 m)로 섰다 |

## 설정

- 작업공간 `~/rosy_lapsim_ws`: `~/rosy_wscorner_ws/src`를 로컬 clone, 이 브랜치(`caa74a53c`)를 bundle로 받아 checkout,
  `colcon build --symlink-install --packages-up-to gz_sim core control description`.
- `evidence/lap_run.sh`: D-495 `run_sim.sh`를 바꾸지 않고 ROS 도메인 88, `GZ_PARTITION rosy_lapsim`, CORE 포트 8188, 실행 폴더
  `lapsim`, world 파일 이름 `lapsim_fleet_real.world`. CORE 겹은 `map_v2_fleet_core.yaml` + `line_follow` {`obstacle_mode: path`,
  `ir_guard_enabled: true`, `site_floor_map_id: map_v2_fleet`}. 나머지는 출하 기본값: `recovery_local_enabled: true`,
  **`bridge_enabled: false`**(앞선 굽이·모서리 SIM은 bridge 켬). keeper는 launch 기본 `camera_lane_mode keep`.
  CORE 능력: `junction_turn`, `junction_pivot`, `lane_bend` true, `site_floor_map_id map_v2_fleet`, `trip_max_linear 0.1`.
- 시작 전 다른 세션(도메인 81 `rosy_bws`, 83 `rosy_lfstop`, 98–101)의 프로세스를 확인했고 건드리지 않았다. 끝난 뒤
  `GZ_PARTITION=rosy_lapsim` 프로세스만 멈췄다(12개, 남은 것 0, 다른 세션의 `gz sim`은 그대로).
- **Fleet은 진짜 서버다.** `evidence/lap_fleet.py`가 `create_app`(FleetConsole, `SiteMapStore`, `TripRunner`, `HttpLaneJunction`,
  site 운영자 인증)을 uvicorn으로 띄운다(포트 8189). SIM 대역은 둘뿐이다.
  1. trip 루프의 `MapPosePort` = Gazebo 참값(`d495/gt`), LOCALIZED, 나이 = 마지막 메시지 이후. **실제 지도 자세 오차(목격 닻 +
     odom bridge)는 다루지 않았다.**
  2. `POST /trip`의 계획 자세(`console.trusted_map_pose`)를 위해 로봇 클라이언트 `state()`에 같은 참값을 `pose` +
     `localization {LOCALIZED, map}`로 넣었다. `line_follow` 등 나머지 스냅숏은 CORE 그대로다.
  지도 = lane_graph `map_v2_fleet` + bend-odom SIM의 굽이 장소 `B_SW`(꼭짓점 (−0.6924, −0.5091), 63.6°, r 0.15 m).
  Fleet의 junction 송신과 CORE 응답은 `LoggedJunction`(Fleet 클래스 상속, 기록만)으로 `sends_*.jsonl`에 남겼다.
- `evidence/lap_trip.py`(run 하나): D-495 probe로 기록(10 Hz CORE 상태+참값, keep 사유 전환, 명령, 이벤트). 출발 전 CORE junction
  기억 지우기(어두운 안쪽 블록에서 CAMERA_LINE 4 sim s + 버리는 장소에 `straight` 하나, CORE R1 끝난 장소 기억), 서쪽 길
  (−1.26955, 0.24255, −90°)으로 텔레포트, CAMERA_LINE 선택(운영자처럼), `POST /api/fleet/robots/rosy_sim/trip {to: NW}`,
  `POST /api/fleet/trips/{id}/start`, 0.5 s마다 `GET /api/fleet/trips/{id}`(trip.jsonl). 900 s 안에 끝나지 않으면 hang으로 적고 취소.
- 계획(20회 모두 같음): `west:rev`(s 1.19→2.865) → SW `right` (−114.6°, CORE에는 `turn_deg −120.6`, `advance_m 0.1`) → `ring_s` →
  SE `straight` → `ring_e` → NE `straight` → `ring_n` → NW `stop`, 2.88 m. 경로상 가장 짧은 길이 회전교차로를 돌아 NW에 서는
  것이라 동쪽 큰 고리(한 바퀴 전체)는 들어가지 않는다.
- 묶음 A(lap_01–12)는 기본 기록, 묶음 rec(rec_1–8)는 `REC=1`로 카메라 프레임·keep_debug 번들·odom(`lap_record.py` =
  ws-corner `ws_record.py`)과 CORE `clearance_source`·`lane_return_containment`·`error`·`confidence`까지 기록했다
  (`lap_trip.py`의 `LapProbe`, 묶음 A 뒤에 추가).
- 요약: `evidence/lap_analyze.py` → `analysis_batch_a.json`, `analysis_batch_rec.json`.

## 원인 (모두 기록으로 확인; 다음 수정 후보이며 이 브랜치는 제품 코드를 고치지 않았다)

### A. 굽이 뒤 SW 교차로를 keeper가 L-모서리로 읽는다 (11/20) — 다음 수정 1순위

rec_2(rec_3, rec_8 같음) keep_debug 번들, 참값 기준:

| 참값 (x, y, yaw) | CORE | keeper 전략 / 사유 | `junction_ahead_m` | 가로선 |
|---|---|---|---|---|
| (−0.681…−0.639, −0.469…−0.433, 34–49°) | `B_SW` `bending` | `none` / `junction_transverse` | 0.445 → 0.388 | 1개 (−78…−90°) |
| (−0.637, −0.431, 51°) | `reacquiring` → `idle` | `right_only` | 없음 | 1개 (84–88°) |
| (−0.625…−0.577, −0.411…−0.318, 55–65°) | Fleet `SW right` `armed`(expect_in 0.23–0.29, tol 0.15–0.17) | `corner_ahead` → **`corner_left`** (약 3 s) | 없음 | 1→0개 |
| (−0.574…−0.579, −0.31…−0.10, 79–96°) | `armed` | `both` (원형 교차로 서쪽 원 두 선) | 없음 | 0 |

1. keeper는 SW 입구 가로선을 SW 노드 0.29–0.34 m 앞(로봇 앞 0.39–0.45 m)에서만 `junction_transverse`로 낸다. 그때 CORE의
   한 칸은 굽이(`bending`)가 쥐고 있다.
2. 굽이가 호 끝에 닿아 `reacquiring`으로 바뀔 때 CORE가 목격을 지운다(`junction_bend.py` `_bend_step`:
   `self._junction_seen_at = self._junction_first_seen = self._junction_anchor = None`). 굽이가 끝날 때 `_junction_done()`도 지운다.
3. 그 뒤 같은 가로선이 가까워지자 keeper는 한쪽 경계만 남은 채 가로선을 L-모서리로 읽어 `corner_left`를 걸고 왼쪽(북쪽)으로 돈다.
   이후 `both`로 원형 교차로 서쪽 원을 따라간다. SW `right`는 `armed`인 채 목격이 오지 않아 실행되지 않는다.
4. Fleet은 로봇이 계획 차로에서 0.0925 m 넘게 벗어나면 `pose`로, SW 지시를 다시 보낼 때 거리가 0 이하이면 `junction_no_window`로 멈춘다.

지도 기하: 굽이 호 끝(s 2.572)에서 SW 노드까지 0.29 m인데 keeper가 교차로를 내는 거리는 0.39–0.45 m 앞이다. 그래서 이 굽이
반지름(0.15 m)에서는 교차로 목격이 항상 굽이 안에 떨어진다. lap_05에서는 `junction_transverse`가 굽이 `reacquiring`이 끝난
뒤에도 한 프레임 남아 CORE `waiting` → Fleet `SW right` → `approaching`까지 갔다(아래 B).
수정 방향(결정은 다음 계획): (a) 굽이 끝에서 지우는 목격을 다음 지시가 쓰도록 넘기거나, (b) 지도가 교차로를 말하는 자리에서
keeper `corner_*`를 막거나, (c) 굽이와 교차로를 한 지시로 묶기. 어느 것이든 원형 교차로 역방향 진입을 막는 시험이 필요하다.

### B. Fleet이 CORE `approaching`을 모른다 (3/20) — 다음 수정 2순위, 한 줄 원인

`operations/fleet/fleet/server/trip_runner.py:44` `MANOEUVRE = ("turning", "advancing", "reacquiring", "bending")`에
`approaching`이 없다. CORE는 `junction.py:44` `MANEUVER = ('approaching', 'turning', 'advancing', 'reacquiring', 'bending')`
(D-507 4, `50656eec8`). 그래서 SW 접근 중(`approaching`, `pivot_basis map`)에 Fleet의 `_locate`가 로봇을 `ring_s`로 넘기고
`_core_busy`가 거짓이 되어 SE `straight`를 보냈다. CORE는 다른 지시를 받으면 기동을 멈춘다(`set_junction`: `aborted`,
`new_instruction`, 응답 `accepted: false`). `sends_batch_a.jsonl`의 lap_05/08/09: `straight SE` 응답 `state: aborted`, 그때 참값
(−0.486, −0.243), (−0.493, −0.248), (−0.507, −0.187). `sent["carried"]`(`_step`)도 같은 tuple을 쓴다.
이 셋은 A가 고쳐져도 회전을 끝내지 못한다.

### C. 모서리 출구에서 positive-evidence 이탈 후 국소 복귀가 다시 중심을 잡지 못한다 (4/20)

rec_1·rec_6: 직전까지 `TRACKING`, 신뢰 0.9, `lane_return_containment: unknown`(D-468 대기). 서쪽 길 직선(y 0.03…−0.01)에서
`contained`가 4–8 틱 있어 checkpoint가 그때 생긴다. 모서리를 돈 직후 (−1.196…−1.189, −0.458…−0.457, yaw −12°)에서
`lane_return_sensor_search`가 시작된다. 그 프레임의 keeper 경계: 왼쪽 y 0.089 / 오른쪽 −0.105(x 0.22 m), 선 방향 +12°.
참값으로 로봇은 차로 중심(−0.511)보다 0.054 m 왼쪽이고 yaw −12°라서 몸 왼쪽 뒤 모서리가 왼쪽 선 너머 약 0.03 m에 있다
(모서리 탈출 잔여, B8의 +0.067 m와 같은 현상). D-507 7 규칙(몸이 경계 너머 = 이탈)이 맞게 켜졌다.
국소 복귀는 제자리 회전 탐색(±0.18 rad 두 번)만 할 수 있다: 되짚기(retrace)는 checkpoint 뒤 5 s 안만, 접근(approach)은
checkpoint가 없을 때만 된다. 탐색이 소진되어 `lane_return_fleet_required`(`stuck` 열림, `console_linked: false`)로 섰고,
trip 중에는 Fleet이 stuck에 자동 답하지 않으므로 20 s 뒤 Fleet `stall`로 끝났다.
나머지 16회는 같은 자리에서 `unknown`으로 남아 계속 달렸다(몸이 경계 위인지 아닌지의 차이). 수정 방향: 모서리 탈출 잔여
줄이기(keeper/모서리 출구) 또는 checkpoint가 오래된 이탈의 복귀 방법. bridge를 켜면 달라지는지는 재지 않았다.

### D. 굽이가 목격으로 끝난 뒤 Fleet이 굽이 칸을 놓지 않는다 (1/20)

rec_4: CORE가 굽이 `reacquiring` 중 교차로 목격으로 굽이를 끝냈고(`_bend_step`), 목격이 남아 바로 `waiting`(같은 seq)이 됐다.
로봇의 Fleet 차로 위치 s 2.566은 굽이 호 끝 s_end 2.572보다 6 mm 앞이었다. Fleet `_step_bend`는 `finished`를 CORE `idle`
또는 더 큰 seq로만 판정하고(`waiting`은 아님) `next_bend`는 s < s_end라 굽이를 계속 돌려준다. `bend_fields`는 bend_in ≤ 0이라
None → 「the bend is not sent and its place waits」로 아무것도 보내지 않았다. 10 s 뒤 `junction`(`waiting`)으로 끝났다.
lap_05(s 2.580), rec_7(s 2.576)은 s_end를 넘어 같은 상황에서 SW 지시가 나갔다.

### E. spoke에서 차선을 잃고 후진한 뒤 교차로가 창 밖 (1/20)

rec_7: SW `right` `armed`(expect_in 0.289, tol 0.149) 뒤 keeper `no_boundary`(−0.616, −0.383, yaw 68°) → `camera_line_not_visible`
HOLD 3 s → D-407 `stuck_back_off`(recovery 켬)로 0.03 m 후진 → 다시 본 `junction_transverse`는 odom 이동이 창 아래라
`unexpected` → Fleet `junction_unexpected`. 굽이 뒤 spoke 인식 몫(bend-odom SIM의 넘겨준 뒤 `flipping` 4/18과 같은 자리).

## D-422

`obstacle_ahead` HOLD는 서쪽 길과 서→남 모서리 안에서 run마다 생기고 1 s 안에 풀렸다.
rec 8회의 33건 중 31건 `clearance_source: lidar`, 2건은 사유 전환 프레임에 출처가 비었다. `memory` 0건(D-507 10 기억 규칙과
맞음). `body_gap_m` 0.0–0.025. 굽이 중 `junction_bend_blocked`도 lidar이고 모두 다시 움직였다. 이번 실패 원인은 아니다.

## 한계

- 한 대, 한 지도(260919 SIM), 한 출발 자리, 한 목적지(NW). 동쪽 큰 고리는 계획에 없었다.
- Fleet 지도 자세는 Gazebo 참값이다. 실제 지도 자세 오차는 다루지 않았다(`expect_tol_m`·`bend_tol_m`은 Fleet 계산 그대로 나갔다).
- bridge는 출하 기본(끔)으로 돌렸다. 앞선 굽이·모서리 SIM(bridge 켬)과 같은 조건이 아니다.
- Fleet 허브(웹소켓)·D-395 위치 서비스·stuck 자동 응답은 쓰지 않았다(REST 폴백). Fleet의 stuck 응답이 C를 풀 수 있는지는 재지 않았다.
- 원인 A·C의 「다른 run과의 차이」(목격이 한 프레임 남는지, 몸이 경계 위인지)는 기록된 프레임으로만 보였고 재생으로 확인하지 않았다.
- 호스트 SIM은 DEVICE가 아니다.
- SIM은 `caa74a53c`에서 돌렸다. 기록을 착지할 때 main에는 그 뒤 D-517 M2(이동 권한)와 D-520(ring 호 주행, `3b6378bae` 등)이
  들어와 있었다. 그 main에서도 `trip_runner.py`의 `MANOEUVRE`에는 `approaching`이 없고(B) `junction_bend.py:164`는 호 끝에서
  목격을 지운다(A). D-520은 SW 회전 뒤 ring 구간 몫이라 이번 run들이 닿지 못한 자리다. 새 main으로는 다시 돌리지 않았다.

## 재현

```bash
# 모델 PC: ~/rosy_lapsim_ws (위 설정). pyfleet = uv pip install --python /usr/bin/python3 --target pyfleet "cryptography>=43"
H=src/rosy-platform/docs/validation/lane-trip-lap-sim-2026-10-08/evidence
setsid nohup bash $H/lap_run.sh > sim.out 2>&1 < /dev/null &
setsid nohup bash $H/batch.sh > batch.out 2>&1 < /dev/null &                   # lap_01-12
REC=1 setsid nohup bash $H/batch.sh $H/batch_rec.txt > batch.out 2>&1 < /dev/null &   # rec_1-8 (새 runs/ 에서)
# 노트북 (ROS 없음)
python docs/validation/lane-trip-lap-sim-2026-10-08/evidence/lap_analyze.py <runs> --json analysis.json
```

원시 기록(run마다 `log/cmd/keep/actions/events/trip.jsonl`, `summary.json`, rec run은 `rec/frames.npz`·`rec/keep.jsonl`, 묶음마다
`sends.jsonl`·`fleet.sqlite3`·`batch.log`)은 저장소 밖 `X:\DevTemp\lap-sim\lap_sim_runs_full.tgz`(118,554,091 bytes,
SHA-256 `2ace91a4354a883375ff14d4e1922126022a4d9f4f3396e8a2e04ede815e5df2`)와 모델 PC `~/rosy_lapsim_ws/runs_a`, `runs`에 있다.
