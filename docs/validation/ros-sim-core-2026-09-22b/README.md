# ROS-SIM core 재실행 — cmd_vel_cycle·safety.watchdog·감사 로그 compaction 이후 트리 (2026-09-22b)

판정: **PASS** — `src/core/core/progress.md` ROS-SIM HOLD→GO 근거.
종료 항목에 조건 1건(아래 "종료" 참조)을 기록한다.

## 왜 다시 돌렸나

2026-09-22 부트 스모크(`docs/validation/ros-sim-core-2026-09-22`, commit `89c1d11`) 이후
두 머지가 core 경로를 바꿨다.

- `0adbe50` port/event-catalogue-drift — ROS 없는 `core/bridge/cmd_vel.py`(`cmd_vel_cycle`) 신설,
  `ros_bridge._publish_cmd_vel` 이 그것에 위임하고 `_send_twist` 가 유일한 `cmd_vel_pub.publish` 를
  한다. CommandManager 가 워치독 만료 시 `safety.watchdog` 을 낸다.
- `11f1164` port/audit-log-write-cost — `FileAuditLog` 덧붙이기 전용 + 백그라운드 compaction,
  `/api/v1/logs/audit` 가 `{events, log}` 를 돌려주고 `/metrics` 에 `rosy_audit_*` 가 붙었다.

그래서 09-22 절차를 그대로 반복하고, 바뀐 경로를 직접 밟는 **teleop → 송신 중단 → 워치독**
프로브와 감사 로그·metrics 확인을 더했다.

## 결과 (evidence/ 파일 근거)

| 항목 | 결과 | 근거 |
|---|---|---|
| 노드 기동 | `/core` 발견 | `ros2-node-list.txt` |
| 부트 로그 | `ros_bridge ready (cmd_vel sole publisher @50Hz)` → `core up: robot_id=rosy_01 model=Pinky Pro` → `api server on 0.0.0.0:8080` | `core-boot-console.log` |
| D-2 최종 발행자 | `/cmd_vel` **Publisher count: 1**, Node name **core**(`-v`), 구독 0. teleop 뒤 재조회도 1 | `cmdvel-info.txt`, `cmdvel-info-verbose.txt`, `cmdvel-info-after-teleop.txt` |
| `/nav_cmd_vel` | publisher 0 / 구독 1 | `navcmdvel-info.txt` |
| REST/대시보드/인증 | `/api/v1` 200, `/dashboard` 200, `/robot/state` 401 | `api-health.json`, `dashboard-code.txt`, `robot-state-code.txt` |
| road 유효 payload(context 포함) | 발행 성공, NameError/traceback 없음, 이후 `/api/v1` 200 | `road-obs-valid.txt`, `core-boot-console.log`, `api-health-after-road.json` |
| road malformed payload | NameError 없음. 깨진 JSON 은 `nav.traffic_policy_reset {reason: invalid_road_observation}` 로 처리됨 | `road-obs-malformed.txt`, `audit.jsonl` seq 2 |
| teleop 수용 | `POST /mode MANUAL` 200, `POST /teleop {linear:0.1}` ×10 모두 200 `accepted` | `teleop-session.txt` |
| cmd_vel 경로 | `/cmd_vel` linear.x 가 0.0 ×62 → **0.1 ×79** → 0.0 ×95. 0 복귀 뒤 0 아닌 값 재출현 없음 | `cmdvel-echo-linear-x.csv` |
| SAF-002 워치독 | 마지막 teleop(≈14:33:37.96Z) 뒤 약 0.5 s 에 `safety.watchdog` (warning, command_manager, `timeout_ms: 500`) 1건 — 세션당 한 번 | `audit.jsonl` seq 4, `audit-log-response.json`, `events-response.json` |
| `/api/v1/logs/audit` 모양 | 최상위 키 `events`, `log`. `log.writable: true`, 실패 카운터 모두 0 | `audit-log-response.json` |
| `/metrics` `rosy_audit_*` | `write_failures_consecutive 0`, `write_failures_total 0`, `prune_failures_total 0`, `prune_skipped_total 0`, `serialize_failures_total 0` | `metrics.txt` |
| 종료 | 아래 참조 — 조건부 PASS | `core-boot-console.log`, `shutdown-repeat.txt`, `shutdown-run*-console.log` |

### 종료

- 본 실행: core 노드 PID 에 SIGTERM → `core shutting down` 기록, 프로세스 소멸, 잔존 프로세스 0.
  **그러나** 종료 직후 `executor.spin()` 에서 `RCLError: failed to initialize wait set: the given
  context is not valid` traceback 이 한 번 나고 `ros2 run` 종료 코드가 1 이었다
  (`core-boot-console.log` 말미, `context.txt`).
- 반복 확인: 정상 상태(API 200 확인 +5 s)에서 SIGTERM 5회 → **5/5** `core shutting down`,
  traceback 0, 종료 코드 0, 감사 로그 마지막 이벤트 `system.shutdown`, 8080 리스너 0
  (`shutdown-repeat.txt`). 앞선 고정 10 s 대기 시도에서도 3/3 깨끗했다.
- 판정: rclpy 의 SIGTERM 핸들러가 context 를 내리는 시점과 MultiThreadedExecutor 의 다음
  wait set 생성이 겹치는 간헐적 경합이다. 해당 경로(`core/main.py` 가 `KeyboardInterrupt` 만
  잡음, `core/node.py` `run()`)는 두 머지가 건드리지 않았다(`git show --stat 0adbe50 11f1164`).
  종료 훅·감사 기록·포트 해제는 매번 이루어지므로 게이트를 막지 않되, 종료 코드 1 은
  systemd 재시작 판정에 영향을 줄 수 있어 core `logs.md` 에 후속 항목으로 남긴다.
- 참고(증거 파일 없음, 덮어씀): 부트가 느린 시점(loadavg ≈7)에 고정 10 s 뒤 SIGTERM 을 보낸
  시도에서는 `api server on` 직후, 즉 executor 생성 전에 신호가 들어와 `failed to create
  guard_condition` traceback 이 났다. 기동 창 동안의 같은 부류 문제다.

## 실행 환경

- WSL2 Ubuntu 24.04.4, kernel 6.18.33.2-microsoft-standard-WSL2, ROS 2 Jazzy(`/opt/ros/jazzy`)
- 트리: **`git archive HEAD -- src` (commit `581741e`, 두 머지 포함)** 를 WSL
  `/root/rosy_rerun_ws/src` 에 추출. 커밋된 트리만 반영된다.
- 빌드: `colcon build --symlink-install --packages-up-to core` — 7 패키지 성공(1 min 48 s,
  stderr 는 setuptools `pytest-repeat` 경고뿐)
- 기동: `ros2 run core core`, `ROSY_ROBOT_NUMBER=1` → `rosy_01`, `ROS_DOMAIN_ID=41`,
  `ROS_LOCALHOST_ONLY=1`, `HOME=/root/rosy_rerun_home`(감사 로그·오버레이를 다른 세션과 분리).
  시작 전 8080 리스너 0 (`context.txt`).
- 인증: 패키지 기본 dev 토큰(`rosy-dev-operator` teleop/mode, `rosy-dev-admin` 감사 로그).
- 같은 디스트로에서 다른 세션이 `ROS_DOMAIN_ID=57` 로 `/odom` echo 를 돌리고 있었다.
  도메인이 달라 그래프 간섭은 없다.

## 범위와 한계

- core 부트 + ROS 출력 + API + road/observation 수신 + teleop→워치독 경로의 재증명이다.
  Gazebo 리그, Nav2/SLAM, 하드웨어는 범위 밖이다.
- `/cmd_vel` 구독자가 없는 그래프다(echo 는 teleop 창에서만 붙음). 바퀴 쪽 반응은 증명하지 않는다.
- 감사 로그 compaction 은 한 시간에 한 번이라 이 짧은 실행에서 돌지 않았다. 증명된 것은
  덧붙이기 경로와 health/metrics 노출이다.
- DEVICE 승격에는 여전히 ARTIFACT(서명 이미지)가 필요하다.

## 방법 재현

1. `git archive HEAD -- src > src.tar`, WSL 에서 `/root/rosy_rerun_ws` 에 풀고
   `colcon build --symlink-install --packages-up-to core`.
2. 위 환경변수로 `ros2 run core core &`, 14 s 대기.
3. 09-22 기본 프로브: `ros2 node list`, `ros2 topic info [-v] /cmd_vel`, `ros2 topic info /nav_cmd_vel`,
   `curl /api/v1`, `/dashboard`, `/api/v1/robot/state`.
4. road 프로브: 09-22 README 의 명령과 같다. 단 09-22 README 의 유효 payload 명령은 YAML 맵의
   닫는 `}` 가 빠져 있어(`...}}'"`) 그대로 치면 `The passed value needs to be in YAML string or a
   dictionary` 로 발행되지 않는다. 올바른 끝은 `...ctx-crosswalk-v1\"}}'}"` 이다.
5. teleop 프로브:
   - `curl -X POST -H 'Authorization: Bearer rosy-dev-operator' -d '{"mode":"MANUAL"}' /api/v1/mode`
   - 백그라운드 `timeout 6 ros2 topic echo /cmd_vel geometry_msgs/msg/Twist --csv --field linear.x`
   - 2.5 s 뒤 `POST /api/v1/teleop {"linear":0.1,"angular":0.0}` 을 100 ms 간격 10회, 이후 2.5 s 송신 중단
   - `GET /api/v1/logs/audit`(admin), `GET /api/v1/events`, `GET /metrics`
6. 종료: `ros2 run` 래퍼의 자식(core 노드) PID 에 SIGTERM. 래퍼 PID 에 보내면 노드가
   `core shutting down` 을 남기지 못하고 끝난다(첫 시도에서 관찰, 증거 교체함).
7. 종료 반복: API 200 대기 +5 s 후 SIGTERM, 5회, 회마다 새 HOME.
