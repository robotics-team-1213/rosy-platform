# D-407 차선 막힘 복구 Gazebo 검증, 2026-10-02

증거 등급: **ROS-SIM (폐루프, 한 대)**. 장치·필드 수용이 아니다. 코드는 `test/d407-gazebo-stuck-recovery`
(main 7e577452 의 D-407 CORE 구현) 그대로이며 CORE 코드는 바꾸지 않았다.

## 무엇을 돌렸나

- 월드: `map_v2_fleet_real.launch.py camera_lane_mode:=keep` (실물 카메라 기하, 흰 둘레 벽 4면). 로봇 한 대.
- CORE overlay (sim 전용, `evidence/run_sim.sh`): `api_port 8095`, `line_follow.recovery_local_enabled: true`.
  나머지는 기본값 그대로다: `obstacle_stop_m 0.20 / resume 0.28`, `recovery_ask_s 15`, `back_m 0.08`,
  `back_speed 0.03`, `rear_clear_m 0.06`, `max_attempts 2`, `settle_s 1`, `trail_s 5`, `trail_yaw_deg 10`.
  몸 기하는 `pinky_pro` 로봇 패키지 `core.yaml`(URDF 공칭 `body_lidar_x_m -0.017`, `body_rear_x_m -0.076`,
  `body_rotation_radius_m 0.08257`)에서 장치와 같은 경로로 들어왔다.
- sim LiDAR: `range_min 0.05`, 잡음 σ 0.02 m, 자기 몸 반사 없음(열린 곳에서 회전 여유 0.43 m, 몸 반경 안 점 0) →
  self-mask 비움이 URDF 와 맞다. `range_min 0.05 < LiDAR→몸 뒤끝 0.059` 라 기본 sim 의 뒤 사각은 0 이다.
  장치 C1(`range_min` ≈ 0.15)의 사각 0.091 m 를 재현하려고 `REAR_BLIND=1` 은 뒤 self-mask 창
  (±165–180°, 0.15 m)을 더한다(T1·T2).
- 주행: `tools/sim/d407_stuck_scenarios.py run` — `PUT /line-follow/mode {CAMERA_LINE, hold_s 0.5}`,
  `POST /hold` 10 Hz, 상태(`stuck` 포함)·`/robot/pose`·`/robot/velocity`·`/events` 를 ~5–10 Hz(벽시계)로 기록.
  출발 자세는 `gz service .../set_pose` 로 옮겼다(A2·C·D·E·T). 후진 거리는 `/robot/pose`(sim odom) 차이를
  `local_attempt` 시각의 진행 방향에 투영한 값이다.
- RTF 0.17–0.5(WSL 소프트웨어 렌더). CORE 차선 추종은 sim 시간으로 판단한다. 아래 `t` 는 벽시계 초.

## 결과 요약

| run | 상황 | 사건 흐름 | 후진(odom) | 판정 |
|---|---|---|---|---|
| A1 | 기본 출발 → 좌하 L 모서리, 벽 앞 `obstacle_ahead` | 5.0 s 뒤 `line_obstacle_hold`+`opened`(rear 0.012, front 0.026, turn 0.005) → `asked opened` → `local_result refused rear_blocked` → `asked local_refused` (WAITING_CONSOLE) | 없음 | 규칙대로. 모서리 회전으로 뒤 오른쪽이 서쪽 벽에 1–3 cm 붙어 뒤 띠(±0.09)에 벽이 들어온다 |
| A2 | 같은 모서리, 벽에서 3 cm 띄워 놓음 | `opened obstacle_ahead`(front 0.196, rear 0.526) → attempt 1 `no_console` → 정지 1 s → `still_stuck`(lane F, front F) → attempt 2 `retry` → `still_stuck`(lane F, front T) → `asked attempts_exhausted` | 0.0800, 0.0805 m, Δyaw 0 | **통과**: 후진 → 1 s → 재판정 → 2 회 → WAITING_CONSOLE |
| B1 | 하단 직선 동쪽 → 셰브런 굽이 LOST | `lane_lost` → `opened lane_lost`(rear 0.035) → `refused rear_blocked` | 없음 | 규칙대로(남쪽 둘레 벽이 뒤 오른쪽 띠 안) |
| B2 | 회전교차로 서쪽 원호 북쪽으로 → 차선 상실 | `lane_lost` → `opened`(rear 0.43) → attempt 1 `no_console` → `recovered`(lane T, front T) → `closed recovered` → 다시 TRACKING → 같은 곳 LOST … 300 s 동안 6 회 반복 | 0.0815, 0.0778, 0.0767, 0.0772, 0.0806, 0.0810 m, Δyaw 0 | 후진·재판정·복귀는 **통과**. 반복이 끝나지 않음 → 발견 2 |
| C1 | 모서리, 관제 답 | `stale` id → 409 `STUCK_ID_MISMATCH`; SETTLING 중 `WAIT` → 200 `hold`, `asked console_wait`, WAITING_CONSOLE, 이후 후진 없음(4 s); `RESUME`(front 0.208 > 0.20) → 200 `resume`, `closed console_resume`; 닫힌 id 로 `BACK_AND_RETRY` → 409; 새 막힘(lane_lost) 뒤 `ABORT` → 200 `idle`, `mode.changed → IDLE`; 닫힌 id `WAIT` → 409 | 0.0808 m | **통과** |
| C2 | 모서리, BACKING 0.8 s 째 | `RESUME` → 409 `STUCK_DECISION_REFUSED: object_within_stop_distance`; `MANUAL` → 200 `manual`, `closed console_manual`, `mode.changed → MANUAL`, 선속도 0 | 0.016 m 에서 멈춤 | **통과** |
| D1 | 후진 시작 1.5 s 뒤 운전자 hold 끊음 | 마지막 hold 26.21 → `closed driver_released` + `line_driver_released`, 상태 OFF, velocity 0 | 끊은 뒤 0.012 m(0.03 m/s × ≈0.4 s sim, hold_s 0.5 안) | **통과**(D-344 §8 의 hold_s 안에 0) |
| D2 | 후진 시작 1.5 s 뒤 e-stop | `safety.estop` 과 같은 폴에 `closed mode_off`, 상태 OFF, velocity 0; 해제는 admin | e-stop 뒤 ≤ 0.0014 m | **통과**. 닫힘 사유가 `estop` 이 아니라 `mode_off`(발견 5) |
| E1 | C1 의 두 번째 막힘 자세 재현 + scan 기록 | `opened lane_lost`(rear 0.42) → attempt 1 → 0.028 m 에서 `local_result aborted rear_blocked` | 0.0284 m | 발견 3: 잡음 한 장으로 중단 |
| T1 | `REAR_BLIND=1`, 회전교차로 원호 | `opened lane_lost`(rear_blind 0.091) → `refused rear_blind` | 없음 | 규칙대로: 순 전진 ≈0.046 m(odom) < 0.08, 누적 yaw ≈12.3° > 10° |
| T2 | `REAR_BLIND=1`, 차선 안 보이는 곳에서 출발 | 전진 기록 없음 → `refused rear_blind` | 없음 | 규칙대로 |

원시 기록: `X:\DevTemp\d407-gz\runs\<run>\{log,events,answers}.jsonl, summary.json, stuck_open.jpg, end.jpg`,
scan 기록 `scan_D1.jsonl`·`scan_E1.jsonl`, sim 로그 `sim*.log`, `launch_last.log`,
`fleet_agent_crash_traceback.txt`.

## 시험하지 못한 것

- **ASKING 15 s 창(관제 연결 + 무응답 → 로컬)**: 관제 연결을 만들 수 없었다(발견 1). 모든 run 에서
  `console_linked: false` 라 막힘은 열리자마자 로컬 복구로 갔다(`trigger: no_console`). 관제 답은 BACKING·
  SETTLING·WAITING_CONSOLE 중에만 보냈다.
- **뒤 사각에 들어가는 후진의 허용 쪽**(순 전진 ≥ 0.08 m, yaw ≤ 10°): 이 트랙에서 막힘으로 끝나는 곧은
  접근을 찾지 못했다. 거부 쪽(T1·T2)만 확인했다.

## 발견

1. **CORE 결함(기존, D-407 밖): FleetAgent 를 켜면 CORE 가 시작하다 죽는다.** `fleet.hub_url`(또는
   discovery) + `pairing_token` 이 있으면 `CoreServices.build` 가 이벤트 루프 밖에서 `fleet_agent.start()` 를
   부르고(`src/runtime/gateway/core/services.py:528`), `asyncio.create_task`
   (`src/runtime/services/core_features/fleet_agent/agent.py:49`)가 `RuntimeError: no running event loop` 를
   낸다. 재현: `FAKE_HUB=1 bash evidence/run_sim.sh` (overlay 에 `fleet.hub_url http://127.0.0.1:8096`,
   `pairing_token`), launch.log 의 `[core-8]` traceback. 결과: CORE 노드에서 `FleetAgent.connected` 는 늘
   false 이고, D-407 §2·§3 의 "관제에 묻고 15 s 기다림" 경로는 실제로 쓰이지 않는다. 로컬 복구를 켜면
   막힘마다 즉시 후진하고, 기본(꺼짐)이면 즉시 WAITING_CONSOLE 이다.
2. **설계 공백: 복귀한 뒤 같은 자리의 다음 막힘은 새 막힘이라 시도 수가 되살아난다.** B2 에서 회전교차로
   원호의 같은 지점(y ≈ −0.07)에서 lane_lost → 후진 → `recovered` → 전진 → lane_lost 가 300 s 동안 6 회
   반복됐고 WAITING_CONSOLE 로 가지 않았다. `_settling` 이 `recovered` 로 닫고
   (`stuck_recovery.py:297-300`), 다음 `_open` 이 `_clear()` 로 시도 수를 0 으로 둔다(`stuck_recovery.py:306`).
   ADR §4 "같은 막힘에서 최대 2 번" 이 복귀 직후 다시 막힌 경우를 같은 막힘으로 볼지 정하지 않는다.
   ADR 결정이 필요하다(예: 복귀 뒤 N s/M m 안의 재막힘은 같은 막힘으로 이어 세기).
3. **뒤 띠가 옆 벽을 잡는다(규칙대로, 견고성 문제).** 뒤 여유는 ±`obstacle_corridor_half_width_m`(0.09)
   띠라서 몸 옆 1–4 cm 의 평행 벽이 들어온다. A1(rear 0.012)·B1(0.035)은 이 때문에 거부됐고, E1 은 후진 중
   σ 0.02 잡음의 scan 한 장(−134°, 0.119 m → 몸 뒤끝 기준 0.024 m)으로 0.028 m 만에 중단됐다. 같은 자세 정지
   60 장에서는 뒤 여유 0.43–0.52 m 였다. 몸 반폭 0.06 밖이라 직진 후진의 쓸고 가는 자리는 아니다. 규칙을
   느슨하게 하지 않았다. 장치에서도 벽 옆 모서리 막힘은 대부분 `rear_blocked` 로 관제 대기가 될 것이다.
4. 관측성: `local_result refused rear_blind` 사건에 `trail_m`·`trail_yaw_deg` 가 없다(`stuck_recovery.py:258`,
   시도 사건에만 `trail_m`). 장치에서 거부 이유(거리 부족인지 yaw 초과인지)를 알 수 없다.
5. 관측성: e-stop 으로 닫힌 막힘의 사유가 `mode_off` 다(e-stop listener 가 `line_follow.stop()` 을 부른다).
   같은 틱의 `safety.estop` 사건으로만 구분된다.
6. 참고: BACKING·SETTLING 중에도 기본 틱이 돌아 `nav.lane_lost` 가 복구 중에 latch 된다(A2 t=25.8).
   `recovered`·`RESUME` 은 `_release_stuck` 으로 latch 를 푼다. 동작 문제는 보지 못했다.

## 재현

```bash
# WSL Ubuntu, 작업공간 /rosy_d407_ws (src/ 를 이 worktree 에서 rsync, colcon build --symlink-install)
bash docs/validation/d407-gazebo-stuck-recovery-2026-10-02/evidence/run_sim.sh      # 전경, CORE 127.0.0.1:8095
# (REAR_BLIND=1: 장치 사각 재현, FAKE_HUB=1: 발견 1 재현)
# 다른 셸: 출발 자세 옮기기 (A2·C·D 모서리)
GZ_PARTITION=rosy_d407 gz service -s /world/map_v2_fleet/set_pose --reqtype gz.msgs.Pose \
  --reptype gz.msgs.Boolean --timeout 3000 \
  --req 'name: "rosy", position: {x: -1.235, y: -0.40, z: 0.01}, orientation: {z: -0.6629, w: 0.7487}'
python3 tools/sim/d407_stuck_scenarios.py run --out runs/A2
python3 tools/sim/d407_stuck_scenarios.py run --out runs/C1 \
  --answers stale,WAIT,RESUME,BACK_AND_RETRY,pause,pause,pause,pause,pause,ABORT,old
python3 tools/sim/d407_stuck_scenarios.py run --out runs/D1 --on-attempt release --act-delay 1.5
python3 tools/sim/d407_stuck_scenarios.py run --out runs/D2 --on-attempt estop --act-delay 1.5
# B2: (-0.585, -0.12, yaw 1.5708). 요약 다시 만들기: d407_stuck_scenarios.py summary runs/B2
```
