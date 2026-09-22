"""core.main — 진입점: ROS 노드 기동 + API 서버 (P1-1, ADR-D-1).

프로세스 구조:
- Main Thread: rclpy 노드 "core" (MultiThreadedExecutor)
- Worker Thread: uvicorn + FastAPI

종료(SIGINT/SIGTERM): 신호 처리기는 예외를 던지지 않고 종료 요청만 기록한다.
rclpy 가 설치한 C 처리기가 context 를 내리고 이 처리기를 이어 부르므로 spin 이
돌아온다. context 가 내려가는 순간과 executor 의 다음 wait set/guard condition
생성이 겹치면 rclpy 가 `RCLError` 를 던진다 — 종료 요청 뒤에 난 예외는 정상 종료로
보고 exit 0, 요청 없이 난 예외는 그대로 올려 exit 1 (systemd Restart=on-failure).
"""

from __future__ import annotations

import os
import signal
import sys
import threading

STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)
# 두 번째 종료 신호(멈춘 종료를 운영자가 끊음)로 죽을 때의 종료 코드. systemd 가 이것을
# 실패(`Result=exit-code`, `ExecMainStatus=2`)로 보아야 정상 정지(exit 0)와 구별된다.
STUCK_SHUTDOWN_EXIT_CODE = 2


def is_orderly_shutdown(exc: BaseException, *, stop_requested: bool,
                        context_was_valid: bool, context_ok: bool) -> bool:
    """기동/spin 중 난 예외가 종료 요청의 부산물인지 판정한다 (ROS 없음).

    - `KeyboardInterrupt`: 운영자 중단.
    - `stop_requested`: SIGINT/SIGTERM 을 받았다 — 그 뒤의 예외는 종료 경합이다.
    - 한 번 유효했던 context 가 지금 무효: 이 프로세스에서 context 를 내리는 것은
      신호 처리기뿐이다(finally 의 shutdown 은 이 판정 뒤). Python 처리기가 아직
      돌기 전에 예외가 먼저 올라온 경우를 덮는다.
    초기화가 한 번도 성공하지 못한 context(`context_was_valid=False`)는 종료가 아니라
    기동 실패다.
    """
    if isinstance(exc, KeyboardInterrupt):
        return True
    if stop_requested:
        return True
    return context_was_valid and not context_ok


def install_stop_handlers(stop: threading.Event) -> None:
    """SIGINT/SIGTERM 을 `stop` 기록으로 바꾼다. 첫 신호는 예외를 던지지 않는다.

    기본 SIGTERM(SIG_DFL)은 rclpy 가 처리기를 깔기 전 기동 창에서 프로세스를 죽이고,
    기본 SIGINT 는 `KeyboardInterrupt` 를 아무 바이트코드에서나 던져 종료 훅
    (`system.shutdown` 감사 기록, API 포트 해제) 도중에도 끊을 수 있다.
    두 번째 신호는 종료가 멈췄다는 운영자 의사다 — 종료 훅도 스레드 join 도 기다리지 않고
    `os._exit(STUCK_SHUTDOWN_EXIT_CODE)` 로 끊는다(SIGINT·SIGTERM 동일).
    - `KeyboardInterrupt` 로 올리지 않는 이유: 예외가 잡혀 finally 의 `rclpy.shutdown()` 까지
      가면 rclpy 가 OS 처리기를 CPython 의 처리기로 되돌리는데, Python 쪽 표가 SIG_DFL 이라
      세 번째 SIGINT 부터는 아무 일도 하지 않는다.
    - 같은 신호로 자기 종료(`os.kill`)하지 않는 이유: `rosy-core.service` 가 `ros2 run` 래퍼
      없이 entry script 를 exec 하므로 노드가 유닛의 주 프로세스다. systemd 는 주 프로세스의
      SIGINT/SIGTERM 사망을 **깨끗한 종료**로 치므로(`is_clean_exit`), 멈춘 종료를 운영자가
      끊은 것이 정상 정지와 구별되지 않는다. 0 아닌 종료 코드만 `Result=exit-code` 로 남는다.
    - `os._exit` 인 이유: 격상의 목적이 멈춘 훅/join 을 건너뛰는 것이다 — atexit 와
      스레드 join 을 타면 다시 같은 자리에 걸린다.
    - `SIG_DFL` 복원은 `os._exit` 직전에 또 신호가 와도 이 처리기로 돌아오지 않게 한다.
    """

    def _request_stop(signum, frame) -> None:
        if not stop.is_set():
            stop.set()
            return
        signal.signal(signum, signal.SIG_DFL)
        print(f"core: second stop signal ({signum}) — shutdown looked stuck; exiting "
              f"{STUCK_SHUTDOWN_EXIT_CODE}", file=sys.stderr, flush=True)
        os._exit(STUCK_SHUTDOWN_EXIT_CODE)

    for signum in STOP_SIGNALS:
        signal.signal(signum, _request_stop)


def main() -> None:
    stop = threading.Event()
    install_stop_handlers(stop)

    from core_common.rmw import apply_cyclone_rmw

    apply_cyclone_rmw(os.environ)

    import rclpy

    from core_common.config import load_config
    from core.node import RosyCoreNode

    node = None
    context_was_valid = False
    try:
        if stop.is_set():
            return
        rclpy.init()
        context_was_valid = True
        if stop.is_set():
            return
        config = load_config()
        node = RosyCoreNode(config)
        node.run()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # 불변식: core 프로세스에서 rclpy context 를 내리는 코드는 이 main() 의 finally 뿐이다
        # (test_core_main_shutdown 이 src/core 전체를 검사). 그래서 finally 전에 context 가
        # 무효라면 신호 처리기가 내린 것이다.
        if not is_orderly_shutdown(exc, stop_requested=stop.is_set(),
                                   context_was_valid=context_was_valid,
                                   context_ok=rclpy.ok()):
            raise
        print(f"core: suppressed during shutdown: {exc!r}", file=sys.stderr, flush=True)
    finally:
        # 순서: 종료 훅(감사 system.shutdown, API 스레드 join — 상한 안에서 끝나면 포트도
        # 해제된다) → destroy_node(타이머·publisher 해제; executor 작업 스레드는 node.run()
        # 이 이미 비웠다) → rclpy.shutdown. 노드가 context 보다 먼저 내려가야 인터프리터
        # 종료 때 rclpy 객체가 무효 context 위에서 해제되지 않는다. 상한을 넘긴 스레드는
        # 여기서 막을 수 없다 — 최종 방어선은 systemd 의 TimeoutStopSec SIGKILL 이다.
        if node is not None:
            for step in (node.shutdown, node.destroy_node):
                try:
                    step()
                except Exception as exc:
                    print(f"core: suppressed during shutdown: {exc!r}", file=sys.stderr,
                          flush=True)
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
