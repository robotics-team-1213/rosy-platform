# core SIGINT/SIGTERM 종료 — exit 0 결정화 (2026-09-22)

판정: **PASS(조건 2건)** — main 이 제어하는 구간(`main()` 첫 문장 이후)에서 SIGTERM/SIGINT 는
종료 훅을 마치고 exit 0 으로 끝난다. 남은 조건: (1) `main()` 이 불리기 전 entry script 창의
신호, (2) 정상 상태 1건의 teardown SIGSEGV. 아래 "남은 것" 참조.

실행 시각은 WSL 기준 2026-09-23 00:05–01:00 (+09:00). 디렉터리 이름은 발견일(09-22b 재실행)을 따른다.

## 원인

`docs/validation/ros-sim-core-2026-09-22b` "종료" 항목의 후속이다.

- rclpy(Jazzy 7.1.11)는 `rclpy.init()` 때 SIGINT/SIGTERM C 처리기를 깐다. 신호가 오면 그 처리기가
  **비동기로** context 를 내리고(rcl_shutdown), 이전 Python 처리기를 이어 부른다
  (`evidence/rclpy-chain-probe.py`: `ok after False python handler hits [15]`).
- `Executor.spin()` 은 `while self._context.ok()` 를 본 뒤 매번 `_rclpy.WaitSet(...)` 을 새로 만든다.
  이 둘 사이에 context 가 내려가면 `RCLError: failed to initialize wait set` 이 spin 밖으로 나온다.
  기동 중이면 같은 경합이 `MultiThreadedExecutor()` 의 guard condition 생성
  (`failed to create guard_condition`), 노드의 publisher 생성(`Failed to create publisher`)에서 난다.
- 기존 `core/main.py` 는 `KeyboardInterrupt` 만 잡았다. finally 가 `node.shutdown()`(감사
  `system.shutdown`, API `should_exit`)을 먼저 돌리므로 종료 훅은 매번 됐지만, 예외는 그대로 올라가
  `ros2 run` exit 1 + traceback 이었다.
- `rclpy.init()` 전 기동 창에서 SIGTERM 은 기본 동작(SIG_DFL)으로 프로세스를 죽였다
  (`ros2 run` 은 `-15` 를 `sys.exit(-15)` → exit status **241**). SIGINT 는 기본 처리기가
  `KeyboardInterrupt` 를 아무 바이트코드에서나 던진다 — finally 의 종료 훅 도중에도.

## 변경 (`src/core/core/core/main.py`)

- `main()` 첫 문장에서 SIGINT/SIGTERM 을 **예외를 던지지 않는** 처리기로 바꾼다
  (`install_stop_handlers` → `threading.Event` 에 기록만). rclpy 가 나중에 깔리면 이 처리기를
  이어 부르므로 한 가지 기록으로 두 창을 덮는다.
- `rclpy.init()` 전·후에 종료 요청을 보고, 이미 요청됐으면 노드를 만들지 않고 끝낸다.
- 예외 판정은 ROS 없는 `is_orderly_shutdown(exc, stop_requested, context_was_valid, context_ok)`:
  종료 요청 뒤 예외, 또는 한 번 유효했던 context 가 지금 무효인 뒤의 예외(Python 처리기가 돌기
  전에 C 처리기가 context 를 먼저 내린 경우)는 정상 종료 → exit 0. context 가 살아 있는 채
  난 예외와 `rclpy.init()` 자체의 실패는 그대로 올라가 exit 1.
- finally 순서는 그대로: `node.shutdown()`(감사 `system.shutdown`, 포트 해제) → `rclpy.shutdown()`.
  `core/node.py`, cmd_vel 경로는 건드리지 않았다.

## 방법

- 트리: `git archive HEAD -- src` 를 WSL `/root/rosy_sigterm_ws` 에 풀고
  `colcon build --symlink-install --packages-up-to core`. 수정 전 `0a9a07a`(main), 수정 후 `c6230cc`.
- 환경: WSL2 Ubuntu 24.04, ROS 2 Jazzy, `ROS_DOMAIN_ID=43`, `ROS_LOCALHOST_ONLY=1`,
  `ROSY_ROBOT_NUMBER=1`, 실행마다 새 `HOME=/root/rosy_sigterm_home/rN`.
- 부하: 실행 내내 `python3 -c 'while True: pass'` 6개(8 코어). 다른 세션 부하와 합쳐 loadavg 4–23.
- 신호는 `ros2 run` 래퍼의 자식(core 노드 PID)에만 보낸다. 스크립트: `evidence/cycles.sh`.
  - steady: `GET /api/v1` 200 확인 후 0.5–3.0 s 무작위 대기 → 신호.
  - startup: 노드 PID 가 보인 뒤 무작위 대기 → 신호. 요청 창 0.2–1.5 s 와, 부하에서 부트가
    8–30 s 걸려 노드 생성 구간을 치려고 1.5–8 s 창을 더했다. `sig@+` 는 실제 경과(부하로 늘어남).
- 판정 열: `exit`(=`ros2 run` 종료 코드 = 노드 종료 코드; 신호 사망 N 은 256−N), `shutting_down`
  (`core shutting down` 로그), `traceback`, `audit_last`(마지막 감사 이벤트), `port8080`(종료 후 리스너 수).

## 결과

| 조건 | 신호 | 수정 전 `0a9a07a` | 수정 후 `c6230cc` |
|---|---|---|---|
| steady | SIGTERM | 20회: **17×0, 3×1** (`RCLError: failed to initialize wait set`) | 20회: **19×0, 1×245** (SIGSEGV, 아래) |
| steady, faulthandler | SIGTERM | — | 25+60회: **85×0** |
| startup 0.2–1.5 s 창 | SIGTERM | 10회: **10×241** (SIGTERM 사망, 모두 core up 전) | 12회: **6×0, 6×241** (아래 "남은 것" 1) |
| startup 1.5–8 s 창 | SIGTERM | 10회: **3×0, 7×1** (guard_condition 5, wait set 1, `Failed to create publisher` 1) | 12회: **12×0** |
| steady | SIGINT | — | 6회: **6×0** |
| startup 0.2–8 s 창 | SIGINT | — | 6회: **6×0** |

- 수정 후 exit 0 인 모든 실행: traceback 으로 끝난 것 없음, API 가 떴던 실행은 `core shutting down`
  1회 + 마지막 감사 이벤트 `system.shutdown`, 종료 후 8080 리스너 0, 잔존 core 프로세스 0.
- 수정 후에도 `traceback=1` 로 찍힌 4건(startup)은 모두 rclpy 내부의
  `Exception ignored in: Executor.__del__ ... no attribute '_sigint_gc'` 이다 — guard condition 생성
  실패로 반쯤 만들어진 executor 의 소멸자 경고이며 종료 코드에 닿지 않는다
  (`logs/after-startup-run1-exit0-del-noise.log`).
- 요약 파일: `evidence/{before,after,diag,diag2}-*.txt`. 대표 콘솔 로그: `evidence/logs/`.

## systemd 영향

`deploy/robot/native/rosy-core.service`: `ExecStart=... exec ros2 run core core`(주 프로세스는
`ros2 run` 래퍼), `Restart=on-failure`, `RestartSec=2`, `KillSignal=SIGINT`, `TimeoutStopSec=15`,
`SuccessExitStatus` 없음.

- `ros2 run` 은 자식의 종료 코드를 그대로 돌려준다. 자식이 신호로 죽으면 `sys.exit(-N)` →
  exit status 256−N 이 되므로 systemd 는 이를 "깨끗한 신호 사망"이 아니라 **실패 exit code** 로 본다.
- `systemctl stop`/target 정지에서는 `Restart=` 가 돌지 않지만, exit 1 이면 유닛이 `failed`
  (Result=exit-code)로 남는다. 신호가 systemctl 밖(수동 `kill`, 다른 스크립트)에서 오면 exit 1 은
  2 s 뒤 재시작, exit 0 은 의도한 정지로 끝난다. 수정은 이 판정을 "정지 요청 = 0" 으로 고정한다.
- `deploy/robot/compose.yaml` 경로는 `restart: unless-stopped` 라 종료 코드와 무관하게 재시작 규칙이
  정해진다.

## 남은 것

1. **entry script 창.** `main()` 이전 — 인터프리터 기동과 setuptools entry script 의
   `importlib.metadata.distribution('core')` 조회(한가할 때 0.3–0.5 s, 부하에서 수 초) — 에 온
   SIGTERM 은 여전히 기본 동작으로 프로세스를 죽인다(exit 241; SIGINT 면 `KeyboardInterrupt` 로 254 가 될 것으로 추정 — 관찰하지 않음).
   `install_stop_handlers` 가 돈 뒤에는 SIGTERM 이 프로세스를 죽일 수 없으므로(처리기가 다시 던지지
   않음) 수정 후 241 6건은 모두 이 창이다. 이 창에서는 rclpy context·API 포트·감사 기록이 아직
   없어 정리할 것도 없다. 코드로는 닫을 수 없다(생성된 스크립트). 필요하면 유닛에
   `SuccessExitStatus=241 254` 를 두는 것을 따로 결정할 것 — 이번 변경은 유닛을 바꾸지 않았다.
2. **teardown SIGSEGV 1건.** 수정 후 steady 20회 중 run 11 이 종료 훅(`core shutting down`)을
   마친 뒤 `[ros2run]: Segmentation fault`(exit 245)로 끝났다. 직전에
   `The following exception was never retrieved: Failed to publish: publisher's context is invalid`
   — context 가 내려간 뒤 executor 작업 스레드의 타이머 콜백이 publish 하다 실패한 흔적이다.
   `PYTHONFAULTHANDLER=1` 로 85회 더 돌렸으나 재현되지 않아 스택이 없다(발생률 1/105).
   수정 전 20회에서는 보지 못했지만 표본이 작아 기존 결함인지 가를 수 없다. 이 변경이 바꾼 것은
   Python 처리기 설치뿐이고 teardown 순서는 같다. 후속: 스택 확보(`faulthandler`/core dump) 후
   interpreter 종료 전 명시적 teardown(`destroy_node`, API 스레드 join) 여부를 판단.
   `logs/after-steady-run11-segv-at-teardown.log`.

## 범위와 한계

- ROS-SIM(WSL) 증거다. Pi/ARM64 이미지·systemd 실유닛 정지 경로(`systemctl stop` 의 cgroup SIGINT
  동시 전달)는 DEVICE 에서 따로 확인해야 한다.
- 호스트 시험: `src/core/core/test/test_core_main_shutdown.py` — 판정 함수, 가짜 rclpy 로 main 의
  종료 경합·기동 창·진짜 오류 전파·훅 순서, 처리기가 예외를 던지지 않음, rclpy import 전 설치.

## 리뷰 반영 재확인 (`a545d55`, main `e8b2976` 병합 후)

변경: 두 번째 SIGINT/SIGTERM 은 기본 동작을 되돌리고 격상(SIGINT → `KeyboardInterrupt`,
SIGTERM → 같은 신호로 자기 종료), 종료로 삼킨 예외는 stderr 에
`core: suppressed during shutdown: ...` 로 남김, "core 프로세스에서 rclpy context 를 내리는 것은
main() 뿐" 불변식 주석 + src/core 전수 grep 시험. teardown 명시화(`executor.shutdown()`/
`destroy_node()`)는 executor 가 `node.run()` 지역이라 main 의 finally 에서 닿지 않고, 1/105 사건을
검증할 수단이 없어 하지 않았다 — "남은 것" 2 그대로.

| 조건 | 결과 | 근거 |
|---|---|---|
| steady SIGTERM ×10 | **10×0**, 모두 `system.shutdown`, 8080 해제 | `review-steady-TERM.txt` |
| startup 1.5–8 s SIGTERM ×6 | **6×0** (`__del__` 경고 1건, 종료 코드 무관) | `review-startup-TERM-1.5-8.txt` |
| 이중 SIGINT, 느린 종료 ×3 | 첫 신호 뒤 종료 훅 안에서 살아 있음 → 두 번째 신호 뒤 즉시 종료, **exit 254**(`[ros2run]: Interrupt`), 첫 신호→종료 1.7–2.0 s | `review-double-signal.txt` |
| 이중 SIGTERM, 느린 종료 ×3 | 같은 형태, **exit 241**(`[ros2run]: Terminated`), 1.1 s | 같은 파일 |

느린 종료는 WSL 작업 공간의 `node.py` 에만 `shutdown()` 끝 20 s sleep 을 넣어 흉내 냈고 실행 뒤
원복했다(`evidence/double-signal.sh`, 패치 잔존 0). 이중 신호 실행에서도 마지막 감사 이벤트는
`system.shutdown`(sleep 전에 기록됨). 격상 종료 코드(241/254)는 의도한 것이다 — 멈춘 종료를
운영자가 끊은 경우이므로 실패로 남는 것이 맞다.
