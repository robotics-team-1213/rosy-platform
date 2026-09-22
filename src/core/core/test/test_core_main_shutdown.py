"""SIGINT/SIGTERM 에서 core 는 종료 훅을 마치고 exit 0 으로 끝난다.

ROS-SIM 2026-09-22b: SIGTERM 이 rclpy context 를 내리는 순간과 executor 의 다음
wait set 생성이 겹치면 `RCLError: failed to initialize wait set` 이 main 밖으로
새어 `ros2 run` exit 1 이 됐다(정상 상태 6회 중 1회, 기동 창에서는
`failed to create guard_condition`). exit 1 은 `rosy-core.service` 의
`Restart=on-failure` 를 건드린다. 여기서는 rclpy 없이 main 을 가짜 rclpy/노드로
돌려 판정과 순서를 고정한다.
"""

from __future__ import annotations

import signal
import sys
import types

import pytest

from core import main as core_main


# --- 판정 함수 -------------------------------------------------------------

def test_error_after_stop_request_is_orderly():
    assert core_main.is_orderly_shutdown(RuntimeError("failed to initialize wait set"),
                                         stop_requested=True, context_was_valid=True,
                                         context_ok=False)


def test_error_after_context_went_down_is_orderly_even_before_python_handler_ran():
    assert core_main.is_orderly_shutdown(RuntimeError("failed to create guard_condition"),
                                         stop_requested=False, context_was_valid=True,
                                         context_ok=False)


def test_keyboard_interrupt_is_orderly():
    assert core_main.is_orderly_shutdown(KeyboardInterrupt(), stop_requested=False,
                                         context_was_valid=True, context_ok=True)


def test_genuine_error_with_live_context_is_not_shutdown():
    assert not core_main.is_orderly_shutdown(RuntimeError("boom"), stop_requested=False,
                                             context_was_valid=True, context_ok=True)


def test_init_failure_is_not_shutdown():
    assert not core_main.is_orderly_shutdown(RuntimeError("rcl_init failed"),
                                             stop_requested=False, context_was_valid=False,
                                             context_ok=False)


# --- main 을 가짜 rclpy 로 ---------------------------------------------------

class _FakeRclpy(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("rclpy")
        self.valid = False
        self.calls: list[str] = []

    def init(self) -> None:
        self.calls.append("init")
        self.valid = True

    def ok(self) -> bool:
        return self.valid

    def shutdown(self) -> None:
        self.calls.append("rclpy.shutdown")
        if not self.valid:
            raise RuntimeError("context is already shutdown")
        self.valid = False


@pytest.fixture
def harness(monkeypatch):
    saved = {s: signal.getsignal(s) for s in core_main.STOP_SIGNALS}
    rclpy = _FakeRclpy()
    monkeypatch.setitem(sys.modules, "rclpy", rclpy)
    import core_common.config
    monkeypatch.setattr(core_common.config, "load_config", lambda: {})

    state: dict = {"run": None}

    class FakeNode:
        def __init__(self, config) -> None:
            rclpy.calls.append("node")

        def run(self) -> None:
            rclpy.calls.append("run")
            if state["run"] is not None:
                state["run"]()

        def shutdown(self) -> None:
            # 종료 훅 순서: 노드 shutdown(감사 system.shutdown, 포트 해제) 뒤 rclpy.shutdown
            rclpy.calls.append("node.shutdown")

    node_mod = types.ModuleType("core.node")
    node_mod.RosyCoreNode = FakeNode
    monkeypatch.setitem(sys.modules, "core.node", node_mod)
    yield rclpy, state
    for signum, handler in saved.items():
        signal.signal(signum, handler)


def _signal_then_race(rclpy, signum):
    """rclpy C 처리기처럼 context 를 내리고 Python 처리기를 부른 뒤, spin 이 경합으로 던진다."""
    def run():
        rclpy.valid = False
        signal.getsignal(signum)(signum, None)
        raise RuntimeError("failed to initialize wait set: the given context is not valid")
    return run


@pytest.mark.parametrize("signum", core_main.STOP_SIGNALS)
def test_rclerror_after_signal_returns_cleanly_after_shutdown_hook(harness, signum):
    rclpy, state = harness
    state["run"] = _signal_then_race(rclpy, signum)
    core_main.main()  # 예외 없음 → console_scripts exit 0
    assert rclpy.calls == ["init", "node", "run", "node.shutdown", "rclpy.shutdown"]


def test_rclerror_when_context_down_before_python_handler_ran(harness):
    rclpy, state = harness

    def run():
        rclpy.valid = False
        raise RuntimeError("failed to create guard_condition")

    state["run"] = run
    core_main.main()
    assert rclpy.calls[-2:] == ["node.shutdown", "rclpy.shutdown"]


def test_genuine_error_before_shutdown_still_propagates(harness):
    rclpy, state = harness

    def run():
        raise RuntimeError("genuine failure")

    state["run"] = run
    with pytest.raises(RuntimeError, match="genuine failure"):
        core_main.main()
    assert rclpy.calls[-2:] == ["node.shutdown", "rclpy.shutdown"]


@pytest.mark.parametrize("signum", core_main.STOP_SIGNALS)
def test_signal_before_init_skips_startup_and_exits_cleanly(harness, monkeypatch, signum):
    rclpy, _ = harness
    real_init = rclpy.init

    def init():
        # 기동 창: rclpy 처리기가 깔리기 전에 신호가 들어온다.
        signal.getsignal(signum)(signum, None)
        real_init()

    monkeypatch.setattr(rclpy, "init", init)
    core_main.main()
    assert "node" not in rclpy.calls
    assert rclpy.calls[-1] == "rclpy.shutdown"


def test_stop_handler_records_without_raising():
    import threading
    saved = {s: signal.getsignal(s) for s in core_main.STOP_SIGNALS}
    try:
        stop = threading.Event()
        core_main.install_stop_handlers(stop)
        for signum in core_main.STOP_SIGNALS:
            signal.getsignal(signum)(signum, None)  # KeyboardInterrupt 를 던지면 실패
        assert stop.is_set()
    finally:
        for signum, handler in saved.items():
            signal.signal(signum, handler)


def test_main_installs_stop_handlers_before_importing_rclpy():
    import inspect
    src = inspect.getsource(core_main.main)
    assert src.index("install_stop_handlers(stop)") < src.index("import rclpy")
