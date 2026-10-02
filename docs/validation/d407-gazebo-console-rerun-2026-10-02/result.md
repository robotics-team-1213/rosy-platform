# D-407 Gazebo 재실행 — 관제 연결, 2026-10-02

증거 등급: **ROS-SIM (폐루프, 한 대) + 실제 Fleet 관제 서버**. 장치·필드 수용이 아니다.
코드는 `test/d407-gazebo-console-rerun`(local main 13e6d5e45: CORE 막힘 복구, FleetAgent 이벤트 루프 시작,
재막힘 이어 세기, 뒤 띠 = URDF 반폭 + 0.02, trail 유효 30 s, Fleet 판단 요청 패널·경로, API v1.79) 그대로다.
CORE·Fleet 코드는 바꾸지 않았다. 첫 실행: `../d407-gazebo-stuck-recovery-2026-10-02/result.md`.

## 무엇을 돌렸나

- WSL Ubuntu, 작업공간 `/rosy_d407_ws`(src 를 이 worktree 에서 rsync, 바뀐 fleet·pinky_pro·rosy_cell 만 다시 빌드;
  CORE 패키지는 symlink 설치라 새 파일이 없어 재빌드 불필요). 격리: `GZ_PARTITION=rosy_d407`, `ROS_DOMAIN_ID=41`,
  CORE API 8095, Fleet 8096.
- 월드·CORE overlay 는 첫 실행과 같다(`evidence/run_sim.sh`, `camera_lane_mode:=keep`, `recovery_local_enabled: true`,
  나머지 기본값) + `HUB=1`: `fleet.hub_url http://127.0.0.1:8096`, `pairing_token d407-sim-pairing`.
- 관제: **실제 `rosy_fleet console`**(`evidence/console.sh`) — robots.yaml 에 `rosy_01`(base_url 8095, CORE operator
  토큰, `fleet_pairing_token`), `--events-db`/`--tasks-db`, `--no-localization-service`. 가짜 hub 는 쓰지 않았다.
- 구동기: `tools/sim/d407_stuck_scenarios.py run --fleet-base http://127.0.0.1:8096 --robot-id rosy_01` — 답을
  **Fleet 경로** `POST /api/fleet/robots/rosy_01/line-stuck/decision` 으로 보내고, `GET /api/fleet/state`(판단 요청
  보드를 채우는 gather)와 `GET /api/fleet/line-stuck` 을 1 Hz 로 `fleet.jsonl` 에 기록한다. CORE 상태·사건은 첫
  실행처럼 10 Hz.
- RTF ≈ 0.35(ASKING `ask_remaining_s` 14.95→0.05 가 벽시계 43.1 s). 아래 `t` 는 벽시계 초, 15 s 등은 sim 시간.

## 결과 요약

| run | 상황 | 사건 흐름 (벽시계 t) | 후진(odom) | 판정 |
|---|---|---|---|---|
| 시작 | HUB=1 로 CORE 시작 | CORE 정상 기동(첫 실행의 `no running event loop` 없음). 관제가 뜨기 전 `Fleet agent disconnected: Connect call failed` 를 backoff 로 반복, 관제가 뜬 뒤 연결(ESTAB 8095 core ↔ 8096) | — | **통과**(발견 1 수정 확인) |
| S1 | A2 모서리, 관제 연결, 답 없음 | 15.27 `opened obstacle_ahead` + `asked opened console_linked: true local_fallback_s 15` → ASKING 43.8 s(벽) = 15 s(sim) → 59.08 `local_attempt trigger ask_timeout` → 69.72 `still_stuck` → attempt 2 `retry` → 80.89 `still_stuck` → `asked attempts_exhausted` (WAITING_CONSOLE). Fleet 보드: ASKING 항목(`opened_event: true`, `ask_remaining_s` 감소) → WAITING_CONSOLE → 닫힌 뒤 비움 | 0.0815, 0.0808 m, Δyaw 0 | **통과**: 연결 + 무응답이면 15 s 기다린 뒤 로컬 |
| S2 | A2 모서리, Fleet 경로로 답 | `stale` → Fleet 409 `STUCK_ID_MISMATCH`(CORE 문구 그대로) · `WAIT`(ASKING 중) → 200 `hold`, `asked console_wait`, WAITING_CONSOLE · `BACK_AND_RETRY` → 200 `back`, `local_attempt trigger console attempt 1` · `still_stuck` → `retry` attempt 2 · 후진 중 `RESUME`(앞 여유 > 0.20) → 200 `resume`, `closed console_resume` · 닫힌 id `WAIT` → 409 `STUCK_ID_MISMATCH`. `GET /api/fleet/line-stuck` `answers` 에 결정·`accepted`·`outcome`·`code`·`principal_id site-console`·`audit_id`, 보드 `fleet_answer` 가 WAIT→BACK_AND_RETRY 로 바뀜 | 0.0799, 0.0525 m(RESUME 로 중단) | **통과** |
| S3 | B2 회전교차로 원호(첫 실행 6 회 반복) | 14.73 `opened lane_lost` → 43.70 attempt 1(`no_console`, 발견 A) → `recovered` → 72.39 `opened restuck_of stuck-2ccafefffb10 attempts 1` → ASKING 46.4 s(벽) → 118.77 attempt 2 `ask_timeout` → `recovered` → 151.81 `opened restuck_of stuck-d5ab48d0a794 attempts 2` + `asked attempts_exhausted` (WAITING_CONSOLE) | 0.0804, 0.0811 m | **통과**: 2 회 뒤 관제 대기로 끝남, 반복 없음 |
| S4 A1 | 기본 출발 → 좌하 L 모서리(첫 실행 `rear_blocked`, rear 0.012) | `opened obstacle_ahead` rear **0.365** front 0.011 → ASKING → attempt 1 `ask_timeout`(trail_m 0.095, trail_age_s 20.1) → `still_stuck` → attempt 2 → `recovered` | 0.0811, 0.0811 m | **통과**: 좁힌 뒤 띠로 후진이 진행된다 |
| S4 B1 | 하단 직선 동쪽 → 셰브런 굽이 LOST(첫 실행 `rear_blocked`, rear 0.035) | `opened lane_lost` rear 0.028 → ASKING → `local_result refused rear_blocked`(rear 0.032, trail_m 0.188, trail_yaw_deg 43.6, trail_age_s 18.1) → `asked local_refused` | 없음 | 규칙대로 거부. 이 자세는 좁힌 띠(±0.077 m) 안에도 벽이 있다. 거부 사건에 trail 값이 실린다(첫 실행 발견 4 수정 확인) |
| T3 | `REAR_BLIND=1` + HUB, A1 기본 출발(곧은 접근 뒤 모서리) | 55.51 `opened obstacle_ahead` rear 0.110, `rear_blind_m 0.091` → ASKING → 100.29 `local_result refused rear_blind`(trail_m **0.149** ≥ 0.08, trail_yaw_deg **14.6** > 10, trail_age_s 20.1 < 30) → `asked local_refused` | 없음 | 규칙대로 거부(yaw). 모서리 앞에서 차선 추종이 돌아 곧은 접근이 아니다 |
| T4 | `REAR_BLIND=1`, A1, 관제 WAIT 뒤 >30 s 기다렸다 BACK_AND_RETRY | 63.39 `opened` → 72.57 Fleet `WAIT` → 200 `hold` → WAITING_CONSOLE → 178.20(≈ 37 s sim 뒤) Fleet `BACK_AND_RETRY` → **409 `STUCK_DECISION_REFUSED` "BACK_AND_RETRY refused: rear_blind"**(CORE 문구 그대로) | 없음 | 거부는 확인. 거부 사유가 나이(>30 s)인지 yaw 인지 사건으로 구분할 수 없다(발견 E) |
| T5 | `REAR_BLIND=1`, A2 모서리에서 진행 방향 뒤로 0.22 m 물린 곧은 출발 | 33.37 `opened obstacle_ahead` rear 0.065 → ASKING → 76.68 `refused rear_blind`(trail_m 0.147, trail_yaw_deg **19.4**, trail_age_s 20.0) | 없음 | 규칙대로 거부(yaw). 허용 쪽은 여전히 재현 못 함 |

화면: 판단 요청 패널(S4 A1 ASKING 중, Windows 호스트 headless chromium → localhost:8096) —
`X:\DevTemp\d407-gz2\console_line_stuck.png`. `rosy_01 · 앞 물체로 멈춤 · 관제 답 기다림 · 시간이 지나면 로컬 복구`,
앞 여유 0.01 m · 뒤 여유 0.37 m · 회전 여유 −0.01 m · 후진 시도 0/2 · 카메라 미리보기 #2374, 단추 대기/재개…/후진 후 재시도…/수동/중단.

원시 기록: `X:\DevTemp\d407-gz2\runs\<run>\{log,events,answers,fleet}.jsonl, summary.json, stuck_open.jpg, end.jpg`,
`console.log`(Fleet), `launch_hub.log`(CORE+sim, S1–S4), `launch_blind.log`(T3–T5), `core_overlay_{hub,blind}.yaml`, `T.console`·`T5.console`.

## 발견

A. **관제 연결이 ASKING 중 끊겨 15 s 를 다 기다리지 않았다(S3 첫 막힘).** `asked console_linked: true` 로 열린 뒤
   29 s(벽, ≈10 s sim) 만에 `local_attempt trigger no_console`. 같은 때 Fleet `console.log` 에
   `ws error: Unexpected ASGI message 'websocket.send', after sending 'websocket.close'.`
   (`src/site/fleet/fleet/hub/server.py:59`)가 남고, 에이전트는 재연결했다(두 번째 막힘은 15 s 를 다 기다림).
   CORE 쪽 로그에는 끊김 경고가 없다 — `agent.py:135-140` 은 heartbeat/event 태스크 하나가 끝나면 조용히
   `async with` 를 빠져나가고 `connected` 를 내린다. 원인은 확정하지 못했다. 가설: `_heartbeat_loop` 의
   `ws.recv()`(`agent.py:176`)가 heartbeat ack 를 기다리지만 hub 는 사건마다 ERROR 응답도 같은 소켓에 보낸다
   (발견 B), 그래서 수신 짝이 어긋나 한쪽 태스크가 끝날 수 있다. 재현: 이 폴더의 `run_sim.sh`(HUB=1) +
   `console.sh`, 답을 보내 `nav.line_stuck_answered` 를 만든 뒤(S2) 다음 막힘을 열어 둔다(S3).
   영향: 관제가 붙어 있어도 막힘이 15 s 보다 일찍 로컬 후진으로 갈 수 있다(안전 쪽 규칙은 그대로 적용).
B. **CORE 결함: `nav.line_stuck_answered` 사건이 Fleet 감사에 거부된다.** 사건 data 에 `token_id` 가 있다
   (`src/runtime/services/core_features/line_follow/stuck_recovery.py:387`). Fleet 사건 저장소는 키 이름이
   자격 증명처럼 보이면 거부한다(`src/site/fleet/fleet/server/core_event_store.py:70-71`
   `_contains_sensitive_field`) → hub 가 `EVENT_NOT_AUDITABLE` 로 답한다(`fleet/hub/hub.py:226-227`).
   이 실행에서 8 회(`console.log`), CORE `/api/v1/events` 의 `nav.line_stuck_answered` seq 25·26·28·37·38… 전부.
   결과: 누가 어떤 답을 했는지가 Fleet 사건 기록(`--events-db`)에 남지 않는다. Fleet 자체 답 기록
   (`fleet_line_stuck_answers`, `GET /api/fleet/line-stuck` `answers`)은 남는다. 재현: S2 와 같은 답 하나 →
   Fleet 로그 `hub rejected event: EVENT_NOT_AUDITABLE`.
C. 관측성: `nav.line_stuck_opened` 의 `rear_clearance_m` 이 `null` 이다(S1·S2 모서리, `rear_blind_m 0.0`).
   좁힌 뒤 띠에 점이 하나도 없으면 null 로 낸다. 후진은 진행됐다(S1 0.0815 m). 관제 패널은 이 경우 `뒤 여유`
   를 비운다. "띠가 비었다" 와 "모른다" 가 같은 값이다.
D. 관측성: 관제 BACK_AND_RETRY 는 시도 1 을 쓰고, 그 뒤 `still_stuck` 이면 CORE 가 묻지 않고 곧바로 시도 2
   (`trigger retry`)를 한다(S2). ADR §4 "최대 2 번" 과 맞지만 관제는 "한 번 물러나 다시 본다" 로 읽을 수 있다.
E. 관측성: 관제 BACK_AND_RETRY 가 `rear_blind` 로 거부될 때 `nav.line_stuck_answered` 에 `reason` 만 있고
   `trail_m`·`trail_yaw_deg`·`trail_age_s` 가 없다(`stuck_recovery.py:205-210` → `_answered`, 387). 로컬 거부
   사건(`local_result refused`)에는 있다. 관제는 왜 거부됐는지(나이 >30 s 인지 yaw 인지) 알 수 없다.
F. 구동기(제품 아님): 첫 S2 시도에서 Fleet 경로 BACK_AND_RETRY 응답이 구동기 timeout 3 s 를 넘겨 구동기가
   죽었다(답은 CORE 에 적용됨 — Fleet 보드 `answers` 에 accepted). timeout 을 10 s 로, 전송 오류는 기록 후 계속으로
   고쳤다. 원시 기록 `runs/S2_driver_crash`. 또 구동기 `answers.jsonl` 의 `error` 칸은 성공 응답에서 CORE line-follow
   상태의 `error`(조향 오차 숫자)를 집어 온다(T4 WAIT 행 −0.545) — 표시만의 문제.

## 시험하지 못한 것

- **뒤 사각 띠 후진의 허용 쪽**(순 전진 ≥ 0.08 m 이면서 yaw ≤ 10°, 30 s 안): T3·T5 모두 trail 거리는 넘었지만
  (0.147–0.149 m) 모서리 앞 차선 추종이 14.6–19.4° 돌아 거부됐다. 이 트랙에서 막힘으로 끝나는 진짜 곧은 접근을
  찾지 못했다(시간 제한으로 더 찾지 않음). 거부 쪽(yaw, 그리고 T4 의 >30 s)만 확인했다.
- T4 의 거부가 나이 규칙 때문인지 yaw 규칙 때문인지는 사건으로 판별할 수 없다(발견 E). 로컬 거부와 같은 판정
  함수라면 yaw 가 먼저 걸렸을 수 있다.
- 첫 실행의 D1·D2(hold 끊김·e-stop)·C2(MANUAL)는 다시 돌리지 않았다(관제 경로와 무관, 시간 우선순위).

## 멈춤

모든 sim·CORE·Fleet 프로세스(rosy_d407 / domain 41 / 8095·8096) 정지: **2026-10-02 17:11:24 KST** (`stop_all.sh` 뒤 `ps`·환경 변수 `ROS_DOMAIN_ID=41`/`GZ_PARTITION=rosy_d407` 검사 0 건, 8095·8096 LISTEN 없음, 17:12:12 재확인).

## 재현

```bash
# WSL Ubuntu, /rosy_d407_ws (src rsync, colcon build --symlink-install --packages-select fleet pinky_pro rosy_cell)
HUB=1 ROS_DOMAIN_ID=41 bash docs/validation/d407-gazebo-console-rerun-2026-10-02/evidence/run_sim.sh   # CORE :8095
ROBOT_ID=rosy_01 bash docs/validation/d407-gazebo-console-rerun-2026-10-02/evidence/console.sh        # Fleet :8096
# 출발 자세는 첫 실행 result.md 의 gz set_pose (GZ_PARTITION=rosy_d407). A2 (-1.235,-0.40, qz -0.6629 qw 0.7487),
# B2 (-0.585,-0.12, yaw 90°), A1 기본 출발 (-1.26955, 0.24255, yaw -90°), B1 (-1.05,-0.509, yaw 0)
F="--fleet-base http://127.0.0.1:8096 --robot-id rosy_01"
python3 tools/sim/d407_stuck_scenarios.py run --out runs/S1 $F
python3 tools/sim/d407_stuck_scenarios.py run --out runs/S2 $F \
  --answers stale,WAIT,BACK_AND_RETRY,pause,pause,pause,RESUME,old --first-answer-after 3
python3 tools/sim/d407_stuck_scenarios.py run --out runs/S3_B2 $F --duration 240
# REAR_BLIND=1 HUB=1 run_sim.sh 로 다시 띄운 뒤 A1 출발:
python3 tools/sim/d407_stuck_scenarios.py run --out runs/T3 $F
python3 tools/sim/d407_stuck_scenarios.py run --out runs/T4 $F --answers WAIT,pause,BACK_AND_RETRY --first-answer-after 3 --gap 50
```
