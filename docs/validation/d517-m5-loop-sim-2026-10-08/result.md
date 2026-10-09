# D-517 M5 대신 돌린 헤드리스 고리 시험 (모델 PC), 2026-10-08

증거 등급: **Fleet 실제 trip 루프 + 운동학 가짜 로봇(호스트, sim 시간)**. Gazebo도 CORE도 아니다. [D-517](../../adr/D-517-multi-robot-lane-traffic.md)
8항 SIM 합격선(Gazebo `map_v2_fleet` 시연 고리 2대 30분, 접촉 0, 블록 중복 0, 사람 개입 0, 이어서 3대)은 **아직 시험하지 않았다.**
실물 로봇은 건드리지 않았다. 이 노트북에서는 기록 분석만 했고 실행은 모델 PC(OMEN, `~/rosy-test` venv, `systemd-run --user --scope -p MemoryMax=1G`)에서 했다.
제품 코드는 바꾸지 않았다. 대상: main `6cb6c3905`(M0–M4 포함).

## Gazebo M5를 지금 돌리지 않은 이유

- 모델 PC 환경은 된다. ROS 2 Jazzy와 Gazebo가 있고, 오늘 한 대 SIM을 여러 번 돌렸다(아래 두 기록). docker는 권한이 없다(`docker.sock` permission denied). sudo 없이 쓸 수 있는 것은 그대로 쓰면 된다.
- **한 대가 아직 한 바퀴를 돌지 못한다.** [lap SIM](../lane-trip-lap-sim-2026-10-08/result.md)은 trip 완료 0/20이었다(원인 A–E). 같은 날 21:36–21:47 `docs/lane-trip-lap-sim2` 묶음도 12/12가 멈췄다(`junction_corner_hold` 11, `pose` 1).
  [D-520 단계 1](../d520-arc-stage1-sim-2026-10-08/result.md)도 FAIL이다. 그래서 2–3대 Gazebo 30분 시험은 교통 규칙과 상관없이 첫 바퀴의 교차로·keeper 결함에서 멈춘다. 한 대 trip이 끝까지 가는 것이 M5 Gazebo의 선행 조건이다.
- 2–3대 Gazebo에는 이름공간을 나눈 CORE·keeper·참값 프로브를 로봇 수만큼 띄워야 한다. 지금 SIM 스크립트(`d495 run_sim.sh`)는 한 대용이다. 모델 PC 부하 평균은 7 이상이었다(다른 세션의 SIM).

## 시험 장치 (`evidence/m5_loop.py`, `evidence/m5_batch.sh`)

- Fleet은 진짜다. `TripRunner`(로봇별 trip, 반복 운행, 블록 표 `lane_traffic`, M2 `AuthoritySender`, M3 대열, M4 `handover`·UNKNOWN 해결기 행)와
  `SiteMapStore`에 시험의 시연 지도 `test_routing.demo_site()`(map_v2_fleet, `east`·`west` 일방, 출발 자리 `start_n`·`start_s`)를 쓴다. `authority=True`이고 로봇 능력은 `AUTH`(`line_follow_authority`, `..._required`)다.
- 로봇은 가짜다. CORE 교차로는 시험의 `FakeCore`다. 위치는 자기 trip 경로를 따라 정해진 속도로 움직이는 점이다. 통행권 문은 CORE `line_follow/authority.py`를 옮겼다: odom 길이 기록, `pose_stamp` 기준, 줄지 않음(0.02 m), `ttl_s` 만료, `derived_stop_gap_m(max_linear)` = 0.045 m에서 HOLDING, 이력 0.03 m.
  교차로는 0.35 m 앞에서 보고, 지시가 없으면 선 앞에서 기다리고, 회전은 제자리 1.5 s다. Fleet은 `--pose-lag` 초 전 자세를 그 odom 시각과 함께 읽는다(기본 0.2 s).
- **모델에 없는 것:** 카메라 인식, 차선 유지 오차, 몸체 정지(D-422), IR, Wi-Fi 지연, Rosy Cam 자세 오차, 실제 가감속. 간격 지표는 몸체 정지 없이 통행권만으로 남은 간격이다.
- 간격 = 두 로봇 중심 거리 − 몸 길이(0.118 m). 곡선이나 서로 다른 차로에서는 실제 경로 간격보다 작게 나온다(보수적). 블록 중복 = 표의 `last_occupied`에서 수용(기본 1)을 넘는 블록이 있는 주기 수. 허가 충돌 = `held`가 수용을 넘는 주기 수.
- 블록 길이(표): `east` 0.665, `west` 0.716, `ring_n` 0.372, `ring_s` 0.374, `ring_e` 0.46, `ring_w` 0.374 m.

## 결과

| run | 로봇 (출발, m/s) | sim 시간 | 최소 간격 | 접촉 | 블록 중복 | 허가 충돌 | 허가 | 통행권 정지 | 바퀴 (대별) | 끝난 trip / 해결기 |
|---|---|---|---|---|---|---|---|---|---|---|
| two_30min | a start_n 0.10, b start_s 0.08 | 30 분 | 0.339 m | 0 | 0 | 0 | 434 | a 7 | 17 / 16 | 없음 / 없음 |
| three_30min | + c east@0.3 0.09 | 30 분 | 0.324 m | 0 | 0 | 0 | 653 | a 7, c 4 | 17 / 16 / 17 | 없음 / 없음 |
| four_refused | + d west@0.3 | 시작 | — | — | — | — | — | — | — | d 시작 `TRIP_LOOP_FULL` (S 11, h 3, N ≤ 3) |
| convoy_15min | a start_n 0.08, b `follow_a` 0.10 | 15 분 | 0.420 m, 대열 `gap_m` 최소 0.875 m | 0 | 34 (a·b) | 237 (a·b) | 215 | b 5 | 8 / 7 | 없음 / 없음 |
| lag_0.5 | a start_n 0.08, b east@0.3 0.10, 자세 0.5 s 늦음 | 10 분 | 0.367 m | 0 | 0 | 0 | 144 | b 13 | 5 / 4 | 없음 / 없음 |
| lag_1.0 | 같음, 1.0 s 늦음 | 10 분 | 0.389 m | 0 | 0 | 0 | 141 | a 1, b 15 | 4 / 4 | 없음 / 없음 |
| stuck_freeze | a start_n, b east@0.3; a를 20 s부터 60 s 멈춤 | 4 분 | 0.402 m | 0 | 0 | 0 | 10 | b 1 | 0 | a `stall` 40.5 s; 71 s a `unknown`→`human` |
| pose_loss | 같음; a 자세 LOST 20–65 s | 4 분 | 0.402 m | 0 | 0 | 0 | 9 | b 1 | 0 | a `pose` 20.5 s; 51 s a `unknown`→`human` |

- 바퀴 시간: 느린 로봇의 속도로 모인다. 0.08 m/s 로봇은 101–102 s, 앞이 빈 0.10 m/s 로봇의 첫 바퀴는 83 s, 따라잡은 뒤에는 96.5 s, 그다음부터 101–102 s다. 0.09 m/s는 91 s에서 101–102 s로 줄어든다. 30분 동안 trip 종료, 보류(`hold`), 해결기 행이 없다. 기준에 맞춰 보면 사람 개입은 0이다.
- 통행권 거절(`AUTHORITY_POSE_*`)은 모든 run에서 0이다. 판단 주기 한 번은 최대 23 ms(3대)다.
- 대열: 블록 중복과 허가 충돌은 리더–팔로워 쌍에서만 나왔다. M3 설계대로 팔로워는 고정 블록 대신 리더 꼬리에서 계산한 움직이는 끝을 받는다. 표의 `gap_m`(리더 꼬리에서 팔로워 앞 끝까지의 경로 거리) 최소는 0.875 m다. 중심 거리 최소 0.42 m는 리더가 `ring_n`으로 꺾일 때의 직선거리다.
- 멈춘 로봇(D-407 대신 움직임 0): M4 노트대로 20 s 정체로 trip이 끝나고, 핀이 남은 채 30 s가 지나면 `unknown`→`human` 행이 나온다. 뒤 로봇 b는 끝까지 통행권 끝에서 섰다(정체 종료 없음, `waiting_for: [a]`).
- 자세 잃음: trip은 첫 비-LOCALIZED 주기에 `pose`로 끝나고(D-494), 30 s 뒤 `unknown`→`human`이다.

## 결함·발견

1. **(낮음, 설정 불일치) 사이트 `fleet.traffic.authority: false`인데 로봇 CORE가 `authority_required: true`이면 Fleet이 trip을 연다. 그런데 로봇은 움직이지 않는다.**
   `m1_only` run에서 두 trip이 20.5 s에 `stall`(진행 0 m)로 끝났다. `_caps_checks`는 깃발이 켜졌을 때만 `TRIP_AUTHORITY_NOT_REQUIRED`를 본다. 깃발이 꺼졌을 때 능력 `line_follow_authority_required`가 참이면 시작에서 분명한 코드로 거절하는 것이 맞다. 고치지 않았다.
2. (장치 메모) `TrafficService`는 자기 시계(벽시계)를 쓰고 `TripRunner`의 `clock`을 받지 않는다. 운영에서는 둘 다 벽시계라 결함이 아니다. sim 시간으로 돌리는 시험은 `runner.traffic._clock`을 직접 바꿔야 한다(이 장치와 `test_lane_traffic` 모두).
3. 이 범위에서 교통 결함은 찾지 못했다: 고정 블록 run에서 중복·허가 충돌 0, 수용 한도 거절 동작, 자세 지연 1 s까지 통행권 안에서 정지.

## 한계

- 운동학 장치다. 카메라·keeper·교차로 인식·몸체 정지·Wi-Fi가 없다. ADR 8항 SIM(Gazebo) 수용을 대신하지 않는다. DEVICE도 아니다.
- 교착 순환은 한 방향 고리의 수용 안에서는 생기지 않는다(M0 증명). 그래서 이 run들에서 `replan` 행은 나오지 않았다. 순환 처리는 `test_lane_traffic`의 강제 순환 시험에만 있다.
- 3대 대열(리더 + 팔로워 2)은 돌리지 않았다.

## 사람이 할 일 / 다음

1. 한 대 lap SIM의 원인(A·C·D·E, `junction_corner_hold`)이 고쳐져 한 대 trip이 반복해서 끝나야 Gazebo M5를 시작할 수 있다.
2. 그다음 2–3대 Gazebo: 모델 PC에서 sudo는 필요 없다. 로봇마다 이름공간과 포트가 다른 CORE·keeper·참값 프로브 launch를 만들고, 이 `m5_loop.py`의 지표(간격, 중복, 허가, 통행권 정지, 바퀴 시간)를 Gazebo 참값으로 다시 잰다.
   GPU·메모리가 넉넉하지 않다(15 GB, 다른 세션의 SIM과 함께 씀). 관제 PC(robttt)는 docker 설치가 아직이고 ROS/Gazebo는 확인하지 않았다.
3. 발견 1의 시작 거절 코드는 별도 브랜치에서 결정한다.

## 재현

```bash
# 모델 PC: git archive 스냅숏 ~/rosy-test/src/d517-m5, venv ~/rosy-test/venv
bash evidence/m5_batch.sh          # two_30min, three_30min, four_refused, convoy_15min, stuck_freeze, pose_loss
python m5_loop.py --robots a:start_n:0.08 b:east@0.3:0.10 --pose-lag 1.0 --minutes 10 --out runs/lag_1.0
python m5_loop.py --robots a:start_n:0.08 b:east@0.3:0.10 --authority 0 --minutes 1 --out runs/m1_only
```

`evidence/runs/<run>/`에 `summary.json`·`events.jsonl`·`stdout.txt`가 있다. 0.5 s 자취(`trace.jsonl`)까지 들어 있는 전체 기록은 저장소 밖
`X:\DevTemp\d517-m5\d517_m5_runs_full.tgz`(210,085 bytes, SHA-256 `41de20670f81b6f45f59d39d99df6955ed301f6937f2510bc7e3f01ed0d5c576`)와 모델 PC `~/d517m5/runs`에 있다.
