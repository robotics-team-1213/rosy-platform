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
            # 종료 훅 순서: 노드 shutdown(감사 system.shutdown, 포트 해제) → destroy_node
            # → rclpy.shutdown
            rclpy.calls.append("node.shutdown")

        def destroy_node(self) -> None:
            rclpy.calls.append("node.destroy")

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
    assert rclpy.calls == ["init", "node", "run", "node.shutdown", "node.destroy",
                           "rclpy.shutdown"]


def test_rclerror_when_context_down_before_python_handler_ran(harness):
    rclpy, state = harness

    def run():
        rclpy.valid = False
        raise RuntimeError("failed to create guard_condition")

    state["run"] = run
    core_main.main()
    assert rclpy.calls[-3:] == ["node.shutdown", "node.destroy", "rclpy.shutdown"]


def test_suppressed_hook_exception_names_the_step(harness, capsys):
    rclpy, state = harness

    def run():
        rclpy.valid = False

    state["run"] = run
    import sys as _sys
    node_mod = _sys.modules["core.node"]
    original = node_mod.RosyCoreNode.shutdown

    def shutdown(self):  # 이름이 곧 메시지에 실린다
        original(self)
        raise RuntimeError("hook blew up")

    node_mod.RosyCoreNode.shutdown = shutdown
    try:
        core_main.main()
    finally:
        node_mod.RosyCoreNode.shutdown = original
    err = capsys.readouterr().err
    assert "suppressed during shutdown (shutdown): RuntimeError('hook blew up')" in err
    assert rclpy.calls[-2:] == ["node.destroy", "rclpy.shutdown"]


def test_genuine_error_before_shutdown_still_propagates(harness):
    rclpy, state = harness

    def run():
        raise RuntimeError("genuine failure")

    state["run"] = run
    with pytest.raises(RuntimeError, match="genuine failure"):
        core_main.main()
    assert rclpy.calls[-3:] == ["node.shutdown", "node.destroy", "rclpy.shutdown"]


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


@pytest.fixture
def saved_handlers():
    saved = {s: signal.getsignal(s) for s in core_main.STOP_SIGNALS}
    yield
    for signum, handler in saved.items():
        signal.signal(signum, handler)


@pytest.mark.parametrize("signum", core_main.STOP_SIGNALS)
def test_first_signal_records_without_raising(saved_handlers, signum):
    import threading
    stop = threading.Event()
    core_main.install_stop_handlers(stop)
    signal.getsignal(signum)(signum, None)  # KeyboardInterrupt 를 던지면 실패
    assert stop.is_set()


@pytest.mark.parametrize("signum", core_main.STOP_SIGNALS)
def test_second_signal_exits_non_zero_without_raising(saved_handlers, monkeypatch, signum):
    """두 번째 신호는 예외 없이 `os._exit(2)` 로 끊는다 — 정상 정지(exit 0)와 구별돼야 한다.

    - `KeyboardInterrupt` 로 올리면(예전 SIGINT 경로) main 이 잡고 finally 의
      `rclpy.shutdown()` 까지 가며, rclpy 가 CPython 트램폴린을 되돌려 세 번째 SIGINT 가
      무시된다.
    - 같은 신호로 자기 종료하면(`os.kill`) 노드가 유닛의 주 프로세스라 systemd 가
      SIGINT/SIGTERM 사망을 깨끗한 종료로 쳐서, 멈춘 종료를 끊은 것이 정상 정지와
      같아 보인다.
    """
    import threading
    exits = []
    written = []
    monkeypatch.setattr(core_main.os, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(core_main.os, "kill",
                        lambda pid, sig: pytest.fail("escalation must not re-signal itself"))
    monkeypatch.setattr(core_main.os, "write",
                        lambda fd, data: written.append((fd, data)) or len(data))
    stop = threading.Event()
    core_main.install_stop_handlers(stop)
    handler = signal.getsignal(signum)
    handler(signum, None)
    assert exits == []
    handler(signum, None)  # KeyboardInterrupt 를 던지면 실패
    assert exits == [core_main.STUCK_SHUTDOWN_EXIT_CODE]
    assert core_main.STUCK_SHUTDOWN_EXIT_CODE != 0
    # 세 번째 신호가 이 몇 줄 사이에 와도 기본 동작(신호 사망 = systemd 가 보기에 정상 정지)으로
    # 빠지지 않는다.
    assert signal.getsignal(signum) is signal.SIG_IGN
    assert written == [(2, core_main.STUCK_SHUTDOWN_MESSAGE)]


def test_escalation_message_is_preformatted_bytes_for_os_write():
    """신호 처리기 안에서는 버퍼 잠금을 기다릴 수 없다 — 문자열 포매팅도 미리 해 둔다."""
    import inspect
    assert isinstance(core_main.STUCK_SHUTDOWN_MESSAGE, bytes)
    assert core_main.STUCK_SHUTDOWN_MESSAGE.endswith(b"\n")
    assert str(core_main.STUCK_SHUTDOWN_EXIT_CODE).encode() in core_main.STUCK_SHUTDOWN_MESSAGE
    handler_src = inspect.getsource(core_main.install_stop_handlers)
    body = handler_src[handler_src.index("def _request_stop"):]
    assert "print(" not in body
    assert "os.write(2, STUCK_SHUTDOWN_MESSAGE)" in body


def test_stuck_shutdown_exit_code_is_not_a_signal_death():
    """systemd 는 주 프로세스의 SIGINT/SIGTERM 사망을 성공으로 친다 — 격상은 종료 코드여야 한다."""
    assert core_main.STUCK_SHUTDOWN_EXIT_CODE not in (0, 128 + signal.SIGINT,
                                                      128 + signal.SIGTERM)


def test_suppressed_exception_is_logged(harness, capsys):
    rclpy, state = harness
    state["run"] = _signal_then_race(rclpy, signal.SIGTERM)
    core_main.main()
    assert "core: suppressed during shutdown: RuntimeError('failed to initialize wait set"         in capsys.readouterr().err


def test_signal_during_rmw_step_skips_init(harness, monkeypatch):
    rclpy, _ = harness
    import core_common.rmw

    def apply(env):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

    monkeypatch.setattr(core_common.rmw, "apply_cyclone_rmw", apply)
    core_main.main()
    assert "init" not in rclpy.calls
    assert "node" not in rclpy.calls


def test_signal_during_load_config_skips_node(harness, monkeypatch):
    rclpy, _ = harness
    import core_common.config

    def load():
        # rclpy 처리기가 깔린 뒤: C 처리기처럼 context 를 내리고 Python 처리기를 부른다.
        rclpy.valid = False
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        raise RuntimeError("context is not valid")

    monkeypatch.setattr(core_common.config, "load_config", load)
    core_main.main()
    assert "node" not in rclpy.calls
    assert rclpy.calls[-1] == "rclpy.shutdown"


def test_rclpy_init_failure_propagates(harness, monkeypatch):
    rclpy, _ = harness

    def init():
        rclpy.calls.append("init")
        raise RuntimeError("rcl_init failed")

    monkeypatch.setattr(rclpy, "init", init)
    with pytest.raises(RuntimeError, match="rcl_init failed"):
        core_main.main()
    assert "node" not in rclpy.calls


def _entry_point_spans(source: str) -> list[tuple[int, int]]:
    """모듈 최상위 `main()` 과 `if __name__ == "__main__":` 의 줄 범위."""
    import ast
    spans = []
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
            spans.append((node.lineno, node.end_lineno))
        elif isinstance(node, ast.If) and "__main__" in ast.unparse(node.test):
            spans.append((node.lineno, node.end_lineno))
    return spans


def test_only_main_shuts_rclpy_down_in_core_production_code():
    """main 의 context-무효 판정은 다른 코드가 context 를 내리지 않는다는 불변식에 기댄다.

    `control` 은 src/core 아래로 옮겨졌고(a93d5188) 지금은 src/runtime/sensing 아래다.
    노드마다 자기 프로세스로 뜬다.
    그 노드의 `main()` 은 CORE 프로세스에서 불리지 않으므로 자기 context 를 내려도 된다.
    CORE 가 `control.sensor_provider` 로 import 하는 모듈 본문은 여전히 막는다.
    `sensing/tools/` 는 설치되지 않는 시뮬레이션 스크립트다.
    """
    import re
    from pathlib import Path
    src_core = Path(__file__).resolve().parents[2]
    pattern = re.compile(
        r"rclpy\.(try_)?shutdown\b|\btry_shutdown\(|from rclpy(\.utilities)? import[^\n]*\bshutdown\b")
    offenders = []
    for path in src_core.rglob("*.py"):
        rel = path.relative_to(src_core).as_posix()
        if "/test/" in f"/{rel}" or rel == "gateway/core/main.py" or rel.startswith("sensing/tools/"):
            continue
        source = path.read_text(encoding="utf-8-sig")
        spans = _entry_point_spans(source) if rel.startswith("sensing/control/") else []
        for lineno, line in enumerate(source.splitlines(), 1):
            if pattern.search(line) and not any(a <= lineno <= b for a, b in spans):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert offenders == []


def test_the_control_shutdown_exemption_still_catches_module_level_calls():
    """면제는 진입점 안쪽뿐이다. 노드 클래스나 모듈 본문의 shutdown 은 걸린다."""
    source = (
        "import rclpy\n"
        "class Node:\n"
        "    def stop(self):\n"
        "        rclpy.shutdown()\n"
        "def main():\n"
        "    rclpy.shutdown()\n"
    )
    spans = _entry_point_spans(source)
    assert not any(a <= 4 <= b for a, b in spans)
    assert any(a <= 6 <= b for a, b in spans)


def test_main_installs_stop_handlers_before_importing_rclpy():
    import inspect
    src = inspect.getsource(core_main.main)
    assert src.index("install_stop_handlers(stop)") < src.index("import rclpy")
