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

- 모든 실행: 마지막 감사 이벤트 `system.shutdown`, 종료 후 API 포트 리스너 0, 잔존 core 프로세스 0,
  `core shutting down` 1회, traceback 0.
- **증명되지 않음**: 수정 전 발생률은 2/600(0.33%)이다. 수정 후 0/600(중간 커밋까지 합치면 0/840)은
  같은 발생률 가정에서 우연일 확률이 약 17–25%(Fisher 단측)다. 사건율이 낮아 이 표본으로는 수정이
  고쳤다고 말할 수 없다. 말할 수 있는 것은 (1) 수정 후 표본에서 재현되지 않았고, (2) crash 직전마다
  나오던 신호 — 종료 훅 뒤까지 살아 도는 executor 콜백 — 의 한 갈래(`Destroyable`)가 사라졌으며,
  (3) teardown 이 이제 인터프리터 종료가 아니라 `main()` 안에서 끝난다는 것이다.
- 부하: 두 팔 모두 busy loop 4개 + 레인 4개 동시. 실제 loadavg 는 수정 전 3–12, **수정 후 15–29**
  (같은 상자의 다른 세션 작업이 겹쳤다) — 수정 후가 더 가혹한 쪽이었다.
- 남은 `Failed to publish: publisher's context is invalid` 는 teardown 으로 막을 수 없다: rclpy 의
  C 신호 처리기가 파이썬이 한 줄도 돌기 전에 비동기로 context 를 내리므로, 그 순간 진행 중이던
  콜백의 publish 는 반드시 실패한다. 종료 코드·감사 기록·포트 해제에는 닿지 않는다.

## B. 세 번째 SIGINT

- 예전: 두 번째 SIGINT 는 `SIG_DFL` 복원 후 `KeyboardInterrupt` 를 던졌다. main 이 그것을 잡고
  finally 의 `rclpy.shutdown()` 까지 가면 rclpy 가 OS 처리기를 CPython 트램폴린으로 되돌리는데,
  파이썬 쪽 표는 `SIG_DFL` 이라 **세 번째 SIGINT 는 아무 일도 하지 않는다**.
- 변경: 두 번째 신호는 SIGINT·SIGTERM 모두 `signal.signal(signum, SIG_DFL)` 뒤
  `os.kill(os.getpid(), signum)` — 같은 신호로 즉시 자기 종료. 파이썬으로 돌아오지 않으므로
  트램폴린 복원 문제 자체가 사라진다.
- 시험: `test_core_main_shutdown.py::test_second_signal_restores_default_and_rekills_self`
  (두 신호 모두, `KeyboardInterrupt` 가 나면 실패).
- WSL 재확인(느린 종료 흉내 — WSL 작업 공간의 `node.shutdown()` 에만 20 s sleep, 실행 뒤 원복):
  이중 SIGINT 3회 **exit 254**(`[ros2run]: Interrupt`), 이중 SIGTERM 3회 **exit 241**, 첫 신호→종료
  1.14–1.31 s, `KeyboardInterrupt` 출력 0건, 마지막 감사 이벤트 `system.shutdown`
  (`evidence/double-signal-after.txt`). 격상 종료 코드가 실패로 남는 것은 이전 결정 그대로다.

## C. `main()` 이전 창 — `ros2 run` 래퍼 제거

`SuccessExitStatus=241 254` 와 래퍼 제거 중 **래퍼 제거**를 골랐다.

- `deploy/robot/native/rosy-core.service`:
  `exec ros2 run core core …` → `exec /opt/rosy/current/install/lib/core/core …`
  (`--merge-install` 페이로드 레이아웃, `setup.cfg` 의 `install_scripts=$base/lib/core`).
- 근거:
  - 241/254 는 `ros2 run` 이 자식의 신호 사망을 `sys.exit(-N)` 으로 바꿔 만든 숫자다. 노드가 주
    프로세스가 되면 systemd 가 신호 사망을 직접 보고 **SIGINT/SIGTERM 사망을 깨끗한 종료로** 친다
    (systemd 기본). 따로 성공 코드 목록을 둘 필요가 없다 — 목록을 두면 241/254 를 만드는 **다른**
    경로(이중 신호 격상)까지 성공으로 덮는다.
  - 래퍼가 사라지면 `systemctl stop` 이 cgroup 에 보내는 SIGINT 를 두 프로세스가 각각 처리하던
    경합도 없어지고, ros2 CLI 자체의 기동 창(아래 표에서 exit 1/254 를 만든 구간)도 없어진다.
  - 파이썬 프로세스 하나가 줄어든다(Pi 메모리·기동 시간).
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
| steady start/stop 12회 | 신규(entry script) | **12/12 `Result=success`, `ExecMainStatus=0`, `NRestarts=0`**, 매회 감사 `system.boot`+`system.shutdown`, 포트 해제, 잔존 0 |
| steady start/stop 4회 | 기존(`ros2 run`) | 4/4 success |
| 기동 중 stop, 0.1–8 s 8점 (프로브 수정 **전**) | 신규 | **7×`Result=signal`**(전부 프로브 사망), 1×success |
| 기동 중 stop, 0.1–8 s 12점 (프로브 수정 **후**) | 신규 | **10×success**, 0.1 s·0.2 s 2점만 실패(프로브 인터프리터가 처리기를 깔기 전) |
| 기동 중 stop, 0.1–8 s 12점 (프로브 수정 후) | 기존(`ros2 run`) | 10×success, 1×`ExecMainStatus=254`(C 가 말하는 창), 1×`signal` |
| 기동 중 stop, 1.3–3.0 s 12점 | 신규 | **12/12 success** |
| 기동 중 stop, 1.3–3.0 s 12점 | 기존(`ros2 run`) | 10 success, **2×`Result=exit-code` `ExecMainStatus=1`** (ros2 CLI 기동 창) |

- 남은 실패 창은 `ExecStartPost` 프로브의 **인터프리터 기동 ~0.2 s**(부하 loadavg 15–25 기준)다.
  여기서 죽으면 유닛이 `failed` 로 남지만 재시작은 없고(`systemctl stop` 경로), core 는 아직 뜨지도
  않았다. 더 줄이려면 프로브를 파이썬 밖으로 내거나 `ExecStartPost=-` 로 실패를 무시해야 하는데,
  후자는 진짜 준비 실패까지 덮으므로 하지 않았다.
- 시험 유닛·상태 디렉터리·작업 공간은 실행 뒤 지웠다(`evidence/sd-cleanup.txt`: `LoadState=not-found`).
  WSL systemd 설정은 건드리지 않았다.

## 시험

- 호스트 3.14: `python -m pytest src/core/core/test/ test/ -q -p no:cacheprovider` → 2556 passed, 52 skipped
- 호스트 3.12(uv, `requirements-core.txt`): `python -m pytest src/core/core/test/ -q -p no:cacheprovider` → 1256 passed, 13 skipped
- 새 시험: `src/core/core/test/test_core_node_teardown.py`(가짜 rclpy 로 drain 순서·상한·API join),
  `test_core_main_shutdown.py` 의 두 번째 신호·`node.destroy` 순서,
  `test/test_native_systemd_contract.py` 의 주 프로세스 계약·프로브 신호 처리(POSIX 서브프로세스
  시험은 Windows 에서 skip, WSL 에서 실행 — `evidence/probe-posix-test.txt`).

## 범위와 한계

- ROS-SIM(WSL2 Ubuntu 24.04, ROS 2 Jazzy, rclpy 7.1.11) 증거다. **실기 Pi 의 `systemctl stop`,
  ARM64 이미지, 실제 `rosy-core.service`(User=rosy-core, `/etc/rosy/runtime.env`, ProtectSystem)
  확인은 DEVICE 게이트에 그대로 남는다.** 특히 entry script 경로
  `/opt/rosy/current/install/lib/core/core` 는 실기 페이로드에서 한 번 눈으로 확인할 것.
- teardown SIGSEGV 는 "수정 후 표본에서 안 났다"까지다. 실기에서 다시 보이면 이번에는
  SIGSEGV 를 블록하지 않는 스레드에서 잡아야 하므로 core dump + gdb 가 필요하다.
