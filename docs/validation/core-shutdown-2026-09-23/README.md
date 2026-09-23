# core 종료 후속 — teardown SIGSEGV, 세 번째 SIGINT, main 이전 창, systemd stop (2026-09-23)

판정: **PASS(조건 2건)** — `docs/validation/core-sigterm-2026-09-22` 가 남긴 후속 4건을 닫았다.
남은 조건: (1) teardown SIGSEGV 는 수정 후 600회 0건이지만 수정 전 발생률(2/600)이 낮아
**통계로 증명되지 않는다**, (2) 실기(Pi) `systemctl stop` 은 그대로 DEVICE 몫이다.

실행 시각 WSL 기준 2026-09-23 01:38–03:05 (+09:00). 대상 브랜치 `fix/core-shutdown-followups`.

## 대상 (D-172 후속 열린 항목)

| | 항목 | 결과 |
|---|---|---|
| A | 종료 훅 뒤 SIGSEGV 1/105 | 스택 확보 실패(이유 아래) + 명시적 teardown 구현. 수정 전 **2/600**, 수정 후 **0/600** |
| B | 두 번째 SIGINT 뒤 세 번째 SIGINT 무시 (LOW) | `os.kill(self, SIGINT)` 로 격상 통일. 시험 추가 |
| C | `main()` 이전 창의 신호 → `ros2 run` exit 241/254 | 유닛이 entry script 를 직접 exec. `SuccessExitStatus` 없음 |
| D | systemd 정지 경로 | WSL systemd 에서 유닛 사본으로 steady 12회 + 기동 중 정지 24회(신규 ExecStart 기준). `ExecStartPost` 가 정지를 실패로 만들던 것을 발견·수정 |

## A. teardown SIGSEGV

### 스택을 못 얻은 이유 (그리고 그 자체가 단서다)

- `PYTHONFAULTHANDLER=1` 로 전 실행을 돌렸고(수정 전 600회, 그중 2회가 SIGSEGV) 파이썬 스택은
  한 줄도 나오지 않았다. `LD_PRELOAD` 로 `backtrace_symbols_fd` 를 부르는 SIGSEGV 처리기를
  심어(`evidence/segv_bt.c`) 360회를 더 돌렸고, 그 안의 SIGSEGV 1건에서도 출력이 없었다
  (처리기 자체는 동작 확인, 같은 파일 주석 참조).
- 이유: core 프로세스의 **CycloneDDS/lttng 스레드는 SIGSEGV 를 블록한다**
  (`evidence/thread-sigmask.txt` — `recv`, `recvUC`, `dq.*`, `gc`, `tev`, `core-ust` 의
  `SigBlk` 에 비트 11 이 서 있고, 파이썬 스레드는 `SigBlk=0`). 블록된 스레드에서 난 동기
  SIGSEGV 는 커널이 처리기를 무시하고 바로 죽인다. 즉 이 crash 는 파이썬 스레드가 아니라
  네이티브(DDS) 스레드에서, 또는 `faulthandler` 가 이미 내려간 인터프리터 종료 이후
  (C atexit/정적 소멸자) 났다.
- gdb 는 이 WSL 에 없고 `core_pattern` 은 Windows 쪽 crash capture 로 파이프된다. 패키지 설치나
  WSL 설정 변경은 하지 않았다(범위 밖).

### 변경 (`src/core/core/core/node.py`, `core/main.py`)

- `node.run()` 의 finally: 어댑터 detach → `executor.remove_node()` → **`_stop_executor()`**.
  `_stop_executor` 는 `MultiThreadedExecutor` 의 `ThreadPoolExecutor` 를
  `shutdown(wait=True, cancel_futures=True)` 로 비우고(보조 스레드에서 실행, **3 s 상한**),
  그 다음에 `executor.shutdown(timeout_sec=0)` 을 부른다.
  - 왜 필요한가: rclpy 7.1.11(Jazzy)은 풀을 비우지 않는다 — `Executor.shutdown()` 은
    `_is_shutdown` 를 세운 뒤 `if not self._is_shutdown:` 을 보므로 작업 완료를 **기다리지 않고**,
    `MultiThreadedExecutor` 에는 풀을 내리는 `shutdown` 자체가 없다. spin 이 돌아온 뒤에도 타이머
    콜백이 계속 돌아 `rclpy.shutdown()` 과 인터프리터 종료에 겹쳤다.
  - 왜 이 순서인가: `Executor.shutdown()` 은 콜백이 끝날 때 트리거하는 guard condition 을
    파괴한다. 먼저 부르면 진행 중 콜백이 `cannot use Destroyable because destruction was requested`
    로 터진다(중간 커밋 `48929f7` 에서 240회 중 42회 관찰, `evidence/logs/interim-destroyable-noise.log`).
- `node.shutdown()`: 기존 순서(API `should_exit` → 감사 `system.shutdown` → 어댑터 close →
  `core shutting down` 로그) 뒤에 **API 스레드 join(5 s 상한)** 을 더했다. 포트 해제가 종료 훅
  안에서 끝난다.
- `main()` 의 finally: `node.shutdown()` → **`node.destroy_node()`** → `rclpy.shutdown()`.
  노드가 context 보다 먼저 내려간다.
- 상한 합 8 s < `TimeoutStopSec=15`. cmd_vel 경로와 종료 훅 순서는 건드리지 않았다.

### 결과 (steady SIGTERM, 신호는 core 노드 PID)

| 트리 | 실행 | exit 0 | exit 245(SIGSEGV) | `never retrieved` 난 실행 |
|---|---|---|---|---|
| 수정 전 `5a4cedb` | 240 | 239 | **1** | 56 (모두 `Failed to publish: … context is invalid`) |
| 수정 전 `5a4cedb` (+`LD_PRELOAD` 진단) | 360 | 359 | **1** | 69 (같음) |
| 중간 `48929f7` (drain 순서 전) | 240 | 240 | 0 | 47 (21 publish + 42 `Destroyable`) |
| 수정 후 `7614627` | 240 | 240 | **0** | 46 (모두 publish, `Destroyable` 0) |
| 수정 후 `7614627` (+`LD_PRELOAD` 진단) | 360 | 360 | **0** | 63 (같음) |
| 리뷰 2차 `861386e` (로그·uvicorn graceful 추가) | 240 | 240 | **0** | 45 (같음) |
| 리뷰 3차 `861386e`+`os.write`/`SIG_IGN` | 240 | 240 | **0** | 32 (같음) |

- 모든 실행: 마지막 감사 이벤트 `system.shutdown`, 종료 후 API 포트 리스너 0, 잔존 core 프로세스 0,
  `core shutting down` 1회, traceback 0.
- **증명되지 않음**: 수정 전 발생률은 2/600(0.33%)이다. 수정 후 0/600(중간 커밋까지 합치면 0/840)은
  같은 발생률 가정에서 우연일 확률이 약 17–25%(Fisher 단측)다. 사건율이 낮아 이 표본으로는 수정이
  고쳤다고 말할 수 없다. 말할 수 있는 것은 (1) 수정 후 표본에서 재현되지 않았고, (2) crash 직전마다
  나오던 신호 — 종료 훅 뒤까지 살아 도는 executor 콜백 — 의 한 갈래(`Destroyable`)가 사라졌으며,
  (3) teardown 이 이제 인터프리터 종료가 아니라 `main()` 안에서 끝난다는 것이다.
- 리뷰 2차(`861386e`)에서 더한 것: 상한을 넘겼을 때·풀이 없을 때·`executor.shutdown()` 이
  던졌을 때 각각 경고를 남기고(그래서 조용한 실패가 없다), uvicorn 에
  `timeout_graceful_shutdown=3`(WS 엔드포인트가 await 에 park 해 API join 상한을 다 쓰는 것을 막음).
- 그 경고가 실제로 나지 않는지는 **리뷰 3차에서야 측정했다**: `evidence/lane.sh` 에 `warn=` 칸을
  더해(teardown 경고 4종을 실행마다 센다) 240회를 다시 돌렸고 `warn=[1-9]` 인 실행은 **0건**
  (`evidence/after4-steady-TERM-round3.txt` 꼬리 줄 "teardown-bound warning runs: 0").
  2차 표의 240회는 콘솔 로그를 전부 남기지 않아 이 주장을 뒷받침하지 못한다 — 숫자는
  리뷰 3차 실행의 것이다.
- 부하: 두 팔 모두 busy loop 4개 + 레인 4개 동시. 실제 loadavg 는 수정 전 3–12, **수정 후 15–29**
  (같은 상자의 다른 세션 작업이 겹쳤다) — 수정 후가 더 가혹한 쪽이었다.
- 남은 `Failed to publish: publisher's context is invalid` 는 teardown 으로 막을 수 없다: rclpy 의
  C 신호 처리기가 파이썬이 한 줄도 돌기 전에 비동기로 context 를 내리므로, 그 순간 진행 중이던
  콜백의 publish 는 반드시 실패한다. 종료 코드·감사 기록·포트 해제에는 닿지 않는다.

## B. 세 번째 SIGINT — 그리고 격상이 실패로 보여야 한다는 것

- 예전: 두 번째 SIGINT 는 `SIG_DFL` 복원 후 `KeyboardInterrupt` 를 던졌다. main 이 그것을 잡고
  finally 의 `rclpy.shutdown()` 까지 가면 rclpy 가 OS 처리기를 CPython 트램폴린으로 되돌리는데,
  파이썬 쪽 표는 `SIG_DFL` 이라 **세 번째 SIGINT 는 아무 일도 하지 않는다**.
- 1차 수정은 두 신호 모두 `os.kill(self, signum)` 으로 통일했으나, C 에서 `ros2 run` 래퍼를
  걷어내면서 **그 격상이 보이지 않게 됐다**: 노드가 유닛의 주 프로세스가 되면 systemd 의
  `is_clean_exit()` 가 SIGINT/SIGTERM 사망을 깨끗한 종료로 쳐서, 멈춘 종료를 운영자가 끊은
  것이 정상 `systemctl stop` 과 구별되지 않는다(아래 표로 실측).
- 최종: 두 번째 신호는 `signal.signal(signum, SIG_IGN)` → `os.write(2, STUCK_SHUTDOWN_MESSAGE)`
  → **`os._exit(STUCK_SHUTDOWN_EXIT_CODE=2)`**. 결정적인 0 아닌 종료 코드이고, core dump 도
  남기지 않으며, 격상의 목적(멈춘 훅·join 건너뛰기)을 그대로 지킨다(atexit·스레드 join 을 타지 않는다).
  - `SIG_DFL` 이 아니라 `SIG_IGN` 인 이유: 이 세 줄 사이에 세 번째 신호가 들어오면 기본 동작은
    신호 사망이고, 그것은 systemd 가 깨끗한 종료로 치는 바로 그 경로다 — 격상이 다시 정상 정지처럼
    보인다. 무시해 두면 반드시 exit 2 로 끝난다.
  - `print` 가 아니라 `os.write` 인 이유: 신호 처리기는 인터럽트된 주 스레드가 쥐고 있을 수 있는
    버퍼 잠금을 기다리면 안 된다(async-signal-safe). 메시지는 미리 bytes 로 만들어 둔다.
    이 경로는 "이미 멈춘 상황"에서 반드시 돌아야 하므로 여기서 막히면 SIGKILL 까지 늘어진다.
    (WSL 재현의 60 s sleep 은 I/O 잠금을 쥐지 않으므로 이 위험을 재현하지 못한다 — 코드 쪽 계약으로
    막고 `test_escalation_message_is_preformatted_bytes_for_os_write` 가 붙든다.)
- 시험: `test_core_main_shutdown.py::test_second_signal_exits_non_zero_without_raising`
  (두 신호 모두: `KeyboardInterrupt` 도 `os.kill` 도 쓰면 실패),
  `test_stuck_shutdown_exit_code_is_not_a_signal_death`,
  `test/test_native_systemd_contract.py` 가 유닛 쪽에서 같은 계약을 붙든다.
- WSL 실측 — **래퍼 없이**(=출하 유닛과 같은 실행 형태) 기동 후 `node.shutdown()` 에 60 s sleep 을
  넣어 종료를 막고 신호를 두 번 보냈다(`evidence/double-direct-*.txt`, 패치 잔존 0):

  | 격상 방식 | SIGINT ×3 | SIGTERM ×3 | 첫 신호→종료 |
  |---|---|---|---|
  | `os._exit(2)` + `SIG_IGN`/`os.write` (출하, 리뷰 3차) | **exit 2** ×3 | **exit 2** ×3 | 1.13–1.15 s |
  | `os._exit(2)` + `SIG_DFL`/`print` (리뷰 2차) | exit 2 ×3 | exit 2 ×3 | 1.14–1.26 s |
  | `os.kill(self, signum)` (1차 수정) | 130(=신호 사망) ×3 | 143(=신호 사망) ×3 | 1.05–1.15 s |

  세 방식 모두 마지막 감사 이벤트는 `system.shutdown`(sleep 앞에서 기록됨), 잔존 프로세스 0.
  출하 형태 6회 모두 `core: second stop signal - shutdown looked stuck; exiting 2` 가
  stderr 에 찍혔다(`evidence/double-direct-round3.txt`). systemd 에서 이 차이가 어떻게 보이는지는
  D 의 "멈춘 종료" 표에 있다.
- **격상은 감사 기록을 보장하지 않는다.** 위 실험은 `system.shutdown` 이 기록된 **뒤** 멈춘 경우라
  마지막 감사 이벤트가 남았다. 감사 publish 전에 종료가 멈춰 있었다면 격상은 그 기록 없이 끝난다 —
  의도된 것이다(격상의 정의가 "남은 훅을 포기한다"이다).
- 참고: 이전 증거(`core-sigterm-2026-09-22`)의 이중 신호 실행은 `ros2 run` 래퍼 아래에서 241/254 로
  관찰한 것이다. 출하 형태(래퍼 없음)에서의 값은 위 표가 대체한다.

## C. `main()` 이전 창 — `ros2 run` 래퍼 제거

`SuccessExitStatus=241 254` 와 래퍼 제거 중 **래퍼 제거**를 골랐다.

- `deploy/robot/native/rosy-core.service`:
  `exec ros2 run core core …` → `exec /opt/rosy/current/install/lib/core/core …`
  (`--merge-install` 페이로드 레이아웃, `setup.cfg` 의 `install_scripts=$base/lib/core`).
- 근거(요약: systemd 가 노드를 직접 감독하게 만든다):
  - 241/254 는 `ros2 run` 이 자식의 신호 사망을 `sys.exit(-N)` 으로 바꿔 만든 숫자다. 래퍼가 없으면
    그 재인코딩 자체가 없어진다 — `main()` 이전 창의 기본 신호 사망을 systemd 가 신호 사망으로
    본다(주 프로세스의 SIGINT/SIGTERM 사망 = 깨끗한 종료). 성공 코드 목록으로 숫자를 덮는 것과
    달리, 정지의 의미가 exit code 표가 아니라 실제 신호로 정해진다.
  - ros2 CLI 자체의 기동 창이 없어진다 — 아래 표에서 `ros2 run` 쪽만 만들어낸 `ExecMainStatus=1`
    2건과 `=254` 1건이 그 구간이다.
  - `systemctl stop` 이 cgroup 에 보내는 SIGINT 를 래퍼와 노드가 각각 처리하던 경합이 없어지고,
    파이썬 프로세스 하나가 줄어든다(Pi 메모리·기동 시간).
  - **대가**: 주 프로세스의 신호 사망이 깨끗한 종료가 되므로, 멈춘 종료를 끊는 격상은 더 이상
    신호 사망이면 안 된다. B 의 `os._exit(2)` 가 그 대가를 치른 자리다. 두 선택지(성공 코드 목록 vs
    래퍼 제거)의 차이는 "격상을 덮느냐"가 아니라 여기에 있다.
- 계약 시험: `test/test_native_systemd_contract.py::test_core_is_the_service_main_process_so_stop_signals_stay_clean`
  — ExecStart 에 `ros2 run` 이 없을 것, 유닛에 `SuccessExitStatus` 가 없을 것, 하드코딩한 경로가
  실제 페이로드 레이아웃(`--merge-install` + `install_scripts`)과 맞을 것.
- 건드리지 않은 것: `src/core/core/deploy/rosy-core.service` 는 `ros2 run rosy_core rosy_core` 를
  부르는 **오래된 비운영 유닛**이다(패키지 이름부터 현재 트리에 없다). 그 폴더 `AGENTS.md` 가
  ADR 없이 바꾸지 말라고 한다 — 이번 범위 밖으로 남긴다.

## D. systemd 정지 경로 (WSL)

`systemctl is-system-running` = `degraded` (systemd 동작 중). 유닛 사본을 `/run/systemd/system/`
에 두고(`evidence/unit-under-test.service`, 생성 규칙은 `evidence/sd.sh`) 돌렸다. 워크스페이스는
`git archive` → `/opt/rosy_sdtest/current`, `colcon build --merge-install`, `ROS_DOMAIN_ID=44`,
`ROS_LOCALHOST_ONLY=1`, API 18490, `HOME=/var/lib/rosy-sdtest`. `User=`/`EnvironmentFile=` 등
실기 전용 지시자만 걷어냈고 `ExecStart`/`KillSignal=SIGINT`/`Restart=on-failure`/`TimeoutStopSec=15`
는 커밋된 유닛 그대로다. 부하 busy loop 4개.

### 발견: 정지 실패를 만들던 것은 core 가 아니라 `ExecStartPost` 였다

기동 중(`activating`) `systemctl stop` 은 cgroup 전체에 SIGINT 를 보낸다 — 준비 프로브
`wait-core-ready.py` 도 맞는다. 프로브가 `KeyboardInterrupt` 로 죽으면 systemd 는
`Control process exited, code=killed, status=2/INT` → **`Failed with result 'signal'`**, 유닛은
`failed` 로 남는다(`evidence/logs/sd-new-probe-before-fix-journal.txt`). ExecStart 를 어느 쪽으로
두든 마찬가지였다. `SuccessExitStatus=` 는 주 프로세스에만 적용되므로 이 경로를 덮지 못한다.

변경: `wait-core-ready.py` 가 SIGINT/SIGTERM 에 stderr 한 줄을 남기고 **exit 0** 으로 기다림을
접는다. 정지 요청은 준비 실패가 아니다.

### 결과 (`evidence/sd-*.txt`, 저널 `evidence/logs/`)

| 조건 | ExecStart | 결과 |
|---|---|---|
| steady start/stop 12회 | 신규(entry script) | **12/12 `Result=success`, `ExecMainStatus=0`, `NRestarts=0`**, 매회 감사 `system.boot`+`system.shutdown`, 포트 해제, 잔존 0 (리뷰 2차 `861386e` 재실행도 steady 12 + 기동 중 5 = **17/17 success**) |
| steady start/stop 4회 | 기존(`ros2 run`) | 4/4 success |
| 기동 중 stop, 0.1–8 s 8점 (프로브 수정 **전**) | 신규 | **7×`Result=signal`**(전부 프로브 사망), 1×success |
| 기동 중 stop, 0.1–8 s 12점 (프로브 수정 **후**) | 신규 | **10×success**, 0.1 s·0.2 s 2점만 실패(프로브 인터프리터가 처리기를 깔기 전) |
| 기동 중 stop, 0.1–8 s 12점 (프로브 수정 후) | 기존(`ros2 run`) | 10×success, 1×`ExecMainStatus=254`(C 가 말하는 창), 1×`signal` |
| 기동 중 stop, 1.3–3.0 s 12점 | 신규 | **12/12 success** |
| 기동 중 stop, 1.3–3.0 s 12점 | 기존(`ros2 run`) | 10 success, **2×`Result=exit-code` `ExecMainStatus=1`** (ros2 CLI 기동 창) |

### 멈춘 종료를 운영자가 끊었을 때 (B 의 격상이 systemd 에서 어떻게 보이나)

설치된 `node.shutdown()` 에 60 s sleep(>`TimeoutStopSec=15`)을 넣어 정지를 막고,
`systemctl stop` 이 도는 동안 `systemctl kill -s SIGINT` 로 두 번째 신호를 보냈다
(`evidence/sd-stuck-*.txt`, 저널 `evidence/logs/`, 패치 잔존 0):

| 격상 방식 | 결과 (2회씩) |
|---|---|
| `os._exit(2)` (출하) | **`Result=exit-code`, `ExecMainCode=1`, `ExecMainStatus=2`, `ActiveState=failed`**, 정지까지 1.1 s |
| `os.kill(self, signum)` (1차 수정) | `Result=success`, `ExecMainStatus=0`, `ActiveState=inactive` — **정상 정지와 구별 불가** |

같은 유닛에서 평범한 `systemctl stop` 은 그대로 `Result=success` 다(위 steady 12/12,
startup 5/5). 즉 "정상 정지 = success, 멈춘 종료를 끊음 = failure" 가 실측으로 갈린다.
리뷰 3차의 최종 코드(`SIG_IGN`+`os.write`)로 다시 돌린 결과도 같다: steady 12 + 기동 중 5 =
**17/17 success**(`evidence/sd-new-round3.txt`), 멈춘 종료 2회 모두 `Result=exit-code`
`ExecMainStatus=2` `failed`(`evidence/sd-stuck-round3.txt`, 저널에 격상 메시지 기록).

**재시작 계약**: 유닛은 `Restart=on-failure`, `RestartSec=2` 다. `systemctl stop` 안에서 난 격상은
재시작을 부르지 않지만, systemctl 밖에서(수동 `kill` 두 번) 격상이 나면 exit 2 = 실패이므로
core 가 2 s 뒤 다시 뜬다. `ros2 run` 래퍼 시절의 241/254 와 같은 동작이며, 이번에는 의도된 계약으로
적어 둔다 — 멈춘 core 를 끊으면 운영 중 로봇은 다시 살아난다.

- 남은 실패 창은 `ExecStartPost` 프로브의 **인터프리터 기동 ~0.2 s**(부하 loadavg 15–25 기준)다.
  여기서 죽으면 유닛이 `failed` 로 남지만 재시작은 없고(`systemctl stop` 경로), core 는 아직 뜨지도
  않았다. 더 줄이려면 프로브를 파이썬 밖으로 내거나 `ExecStartPost=-` 로 실패를 무시해야 하는데,
  후자는 진짜 준비 실패까지 덮으므로 하지 않았다.
- 시험 유닛·상태 디렉터리·작업 공간은 실행 뒤 지웠다(`evidence/sd-cleanup.txt`: `LoadState=not-found`).
  WSL systemd 설정은 건드리지 않았다.

## 시험

- 호스트 3.14: `python -m pytest src/core/core/test/ test/ -q -p no:cacheprovider` → 2561 passed, 53 skipped (리뷰 3차)
- 호스트 3.12(uv, `requirements-core.txt`): `python -m pytest src/core/core/test/ -q -p no:cacheprovider` → 1261 passed, 14 skipped (리뷰 3차)
- ROS 레인(WSL, 진짜 rclpy): `test_core_node_teardown_ros.py` + teardown/main 시험 32 passed
  (`evidence/ros-canary-test.txt`). 이 canary 는 `MultiThreadedExecutor._executor` 가
  `ThreadPoolExecutor` 라는 것을 붙든다 — rclpy 가 바꾸면 호스트 가짜 시험은 계속 통과하므로
  여기서 깨져야 한다.
- 새 시험: `src/core/core/test/test_core_node_teardown.py`(가짜 rclpy 로 drain 순서·상한·경고·API join),
  `test_core_main_shutdown.py` 의 두 번째 신호·`node.destroy` 순서,
  `test/test_native_systemd_contract.py` 의 주 프로세스 계약·프로브 신호 처리(POSIX 서브프로세스
  시험은 Windows 에서 skip, WSL 에서 실행 — `evidence/probe-posix-test.txt`).

## 범위와 한계

- ROS-SIM(WSL2 Ubuntu 24.04, ROS 2 Jazzy, rclpy 7.1.11) 증거다. **실기 Pi 의 `systemctl stop`,
  ARM64 이미지, 실제 `rosy-core.service`(User=rosy-core, `/etc/rosy/runtime.env`, ProtectSystem)
  확인은 DEVICE 게이트에 그대로 남는다.** 특히 entry script 경로
  `/opt/rosy/current/install/lib/core/core` 는 실기 페이로드에서 한 번 눈으로 확인할 것.
- DEVICE 로 미룬 것(여기서 확인할 수 없음): 실제 ARM64 페이로드에서
  `test -x /opt/rosy/current/install/lib/core/core`, 그리고 "`ExecStartPost` 가 도는 동안 core 가
  죽는" systemd 사례(여기서는 core 를 고의로 죽이는 유닛 사례를 만들지 않았다).
- teardown SIGSEGV 는 "수정 후 표본에서 안 났다"까지다. 실기에서 다시 보이면 이번에는
  SIGSEGV 를 블록하지 않는 스레드에서 잡아야 하므로 core dump + gdb 가 필요하다.
