"""core 노드 teardown: spin 이 돌아온 뒤 executor 작업 스레드를 비우고, API 스레드를 기다린다.

ROS-SIM 2026-09-22: 정상 상태 SIGTERM 105회 중 1회가 종료 훅 뒤 SIGSEGV(exit 245)로 끝났다.
직전 로그 "Failed to publish: publisher's context is invalid" — spin 이 끝난 뒤에도
MultiThreadedExecutor 작업 스레드의 타이머 콜백이 돌고 있었다. rclpy 7.1.x 는 그 풀을
비우지 않으므로 node.run() 이 직접 비운다. 여기서는 rclpy 없이 가짜 모듈로 검사한다.
"""

from __future__ import annotations

import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

import pytest


class _ExternalShutdown(Exception):
    """Stand-in for rclpy.executors.ExternalShutdownException."""


@pytest.fixture
def node_module(monkeypatch):
    """rclpy 가 없어도(호스트) 있어도(ROS) 같은 가짜로 core.node 를 새로 읽는다."""
    rclpy = types.ModuleType("rclpy")
    executors = types.ModuleType("rclpy.executors")
    node = types.ModuleType("rclpy.node")
    executors.MultiThreadedExecutor = object
    executors.ExternalShutdownException = _ExternalShutdown
    node.Node = object
    rclpy.executors = executors
    rclpy.node = node
    monkeypatch.setitem(sys.modules, "rclpy", rclpy)
    monkeypatch.setitem(sys.modules, "rclpy.executors", executors)
    monkeypatch.setitem(sys.modules, "rclpy.node", node)
    import core
    monkeypatch.delitem(sys.modules, "core.node", raising=False)
    missing = object()
    saved_attr = getattr(core, "node", missing)
    import core.node as module
    yield module
    # 가짜 rclpy 로 읽은 모듈이 다른 시험(진짜 rclpy 의 test_node_wiring)에 새지 않게 한다.
    sys.modules.pop("core.node", None)
    if saved_attr is missing:
        delattr(core, "node")
    else:
        core.node = saved_attr


class _FakeExecutor:
    """Jazzy MultiThreadedExecutor 흉내: spin 이 돌아와도 풀에는 콜백이 남아 있다.

    콜백은 시간이 아니라 사건(`release`)으로 푼다 — 부하 걸린 상자에서 sleep 기반 시험은 흔들린다.
    """

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self._executor = ThreadPoolExecutor(2)
        self.release = threading.Event()
        self.running = threading.Event()
        self.finished = threading.Event()
        self.queued_ran = threading.Event()

    def add_node(self, node) -> None:
        self.calls.append("add_node")

    def remove_node(self, node) -> None:
        self.calls.append("remove_node")

    def spin(self) -> None:
        def in_flight():
            self.running.set()
            assert self.release.wait(30), "release event never set"
            self.finished.set()

        self._executor.submit(in_flight)
        self._executor.submit(in_flight)
        assert self.running.wait(30), "callback never started"
        for _ in range(20):  # 풀 스레드 2개가 바빠서 대기열에 남는 콜백
            self._executor.submit(self.queued_ran.set)
        self.calls.append("spin returned")

    def shutdown(self, timeout_sec=None) -> bool:
        # Jazzy 는 여기서 작업 스레드가 끝낼 때 부르는 guard condition 을 파괴한다 —
        # 풀이 비워진 뒤에만 불려야 한다.
        self.calls.append(f"executor.shutdown({timeout_sec})")
        self.pool_drained_at_shutdown = self._executor._shutdown and self.finished.is_set()
        return True


class _Logger:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.warnings: list[str] = []

    def info(self, msg) -> None:
        self.calls.append(str(msg))

    def warning(self, msg) -> None:
        self.warnings.append(str(msg))


def _bare_node(module, calls):
    node = module.RosyCoreNode.__new__(module.RosyCoreNode)
    node.control_adapter = types.SimpleNamespace(
        attach=lambda ex: calls.append("attach"),
        detach=lambda ex: calls.append("detach"),
        close=lambda: calls.append("adapter.close"),
    )
    logger = _Logger(calls)
    node.get_logger = lambda: logger
    return node


def test_run_drains_executor_workers_before_returning(node_module, monkeypatch):
    calls: list[str] = []
    executor = _FakeExecutor(calls)
    monkeypatch.setattr(node_module, "MultiThreadedExecutor", lambda: executor)
    node = _bare_node(node_module, calls)

    shutdown = executor._executor.shutdown

    def release_after_cancellation(wait=True, *, cancel_futures=False):
        # Keep callbacks blocked until shutdown has cancelled the queued work.
        # A timer can release them before run() reaches shutdown on a busy host.
        shutdown(wait=False, cancel_futures=cancel_futures)
        executor.release.set()
        shutdown(wait=wait, cancel_futures=cancel_futures)

    monkeypatch.setattr(executor._executor, "shutdown", release_after_cancellation)
    node.run()

    # run() 이 돌아올 때 이미 돌던 콜백은 끝났고, 대기열의 콜백은 버려졌다.
    assert executor.finished.is_set()
    assert not executor.queued_ran.is_set()
    assert calls == ["add_node", "attach", "spin returned", "detach", "remove_node",
                     "executor.shutdown(0)"]
    assert executor.pool_drained_at_shutdown
    assert node.get_logger().warnings == []


def test_run_drains_even_when_spin_raises(node_module, monkeypatch):
    calls: list[str] = []
    executor = _FakeExecutor(calls)

    def spin():
        executor.release.set()
        executor._executor.submit(executor.finished.set)
        raise RuntimeError("failed to initialize wait set")

    executor.spin = spin
    monkeypatch.setattr(node_module, "MultiThreadedExecutor", lambda: executor)
    node = _bare_node(node_module, calls)

    with pytest.raises(RuntimeError, match="wait set"):
        node.run()
    assert "executor.shutdown(0)" in calls
    assert executor._executor._shutdown


def test_drain_is_bounded_and_says_so(node_module):
    calls: list[str] = []
    executor = _FakeExecutor(calls)
    logger = _Logger(calls)
    executor._executor.submit(executor.release.wait, 30)
    t0 = time.monotonic()
    assert node_module._stop_executor(executor, 0.2, logger) is False
    assert time.monotonic() - t0 < 5.0
    assert any("still running callbacks after 0.2s" in w for w in logger.warnings), (
        logger.warnings)
    executor.release.set()


def test_an_executor_without_a_worker_pool_is_a_loud_failure(node_module):
    """rclpy 가 `_executor` 를 없애거나 이름을 바꾸면 조용히 보장을 잃지 않는다."""
    calls: list[str] = []
    logger = _Logger(calls)

    class NoPool:
        def shutdown(self, timeout_sec=None):
            calls.append("executor.shutdown")

    assert node_module._stop_executor(NoPool(), 0.1, logger) is False
    assert any("no ThreadPoolExecutor" in w and "NoPool" in w for w in logger.warnings), (
        logger.warnings)
    assert calls == ["executor.shutdown"]


def test_executor_shutdown_error_is_logged_not_swallowed(node_module):
    calls: list[str] = []
    logger = _Logger(calls)

    class WithBrokenShutdown:
        def __init__(self) -> None:
            self._executor = ThreadPoolExecutor(1)

        def shutdown(self, timeout_sec=None):
            raise RuntimeError("context is not valid")

    assert node_module._stop_executor(WithBrokenShutdown(), 1.0, logger) is True
    assert any("context is not valid" in w for w in logger.warnings), logger.warnings


def test_shutdown_joins_api_thread_after_audit_hook(node_module):
    calls: list[str] = []
    node = _bare_node(node_module, calls)
    server = types.SimpleNamespace(should_exit=False)

    def serve():
        while not server.should_exit:
            time.sleep(0.01)
        time.sleep(0.2)  # uvicorn: 연결 정리 후 소켓을 닫는다
        calls.append("api stopped")

    node._api_server = server
    node._api_thread = threading.Thread(target=serve, daemon=True)
    node._api_thread.start()
    node.core = types.SimpleNamespace(station_docking=None, events=types.SimpleNamespace(
        publish=lambda event, **kw: calls.append(event)))

    node.shutdown()

    assert not node._api_thread.is_alive()
    assert calls == ["system.shutdown", "adapter.close", "core shutting down", "api stopped"]
    assert node.get_logger().warnings == []


def test_shutdown_says_so_when_the_api_thread_outlives_the_join(node_module, monkeypatch):
    monkeypatch.setattr(node_module, "API_JOIN_TIMEOUT_S", 0.1)
    calls: list[str] = []
    node = _bare_node(node_module, calls)
    stuck = threading.Event()
    node._api_server = types.SimpleNamespace(should_exit=False)
    node._api_thread = threading.Thread(target=lambda: stuck.wait(30), daemon=True)
    node._api_thread.start()
    node.core = types.SimpleNamespace(station_docking=None, events=types.SimpleNamespace(
        publish=lambda event, **kw: calls.append(event)))
    try:
        node.shutdown()
        assert any("api thread still alive" in w for w in node.get_logger().warnings), (
            node.get_logger().warnings)
    finally:
        stuck.set()


def test_teardown_bounds_fit_inside_systemd_stop_timeout(node_module):
    # rosy-core.service TimeoutStopSec=15; 그 SIGKILL 전에 teardown 이 끝나야 한다.
    # uvicorn graceful 상한은 API join 안에서 돈다.
    assert node_module.API_GRACEFUL_TIMEOUT_S <= node_module.API_JOIN_TIMEOUT_S
    assert node_module.EXECUTOR_DRAIN_TIMEOUT_S + node_module.API_JOIN_TIMEOUT_S < 15


# --- ROSY_CORE_EXECUTOR (D-953): opt-in C++ EventsExecutor for CORE -------------------------
# Why swapping is allowed: CORE and its sensor node make every subscription/timer in the
# default (mutually exclusive) callback group, so MultiThreadedExecutor never ran two callbacks
# of one node at once; the only overlap is core node vs safety_node. Callbacks that wait for a
# service reply (wait=True) run on API threads, never on an executor thread.

def test_core_callbacks_never_rely_on_a_reentrant_group():
    # Everything that shares CORE's executor: the core package, its services and API, and the
    # safety_node control_adapter attaches (middleware/drive/motion_limits/adapter).
    import pathlib
    middleware = pathlib.Path(__file__).resolve().parents[3]
    roots = [middleware / "core", middleware / "drive" / "motion_limits" / "adapter"]
    offenders = [str(p) for root in roots for p in root.rglob("*.py")
                 if "/test/" not in p.as_posix()
                 and ("callback_group" in p.read_text(encoding="utf-8")
                      or "ReentrantCallbackGroup" in p.read_text(encoding="utf-8"))]
    assert all(root.is_dir() for root in roots), roots
    assert offenders == [], offenders


def test_events_executor_shutdown_error_is_logged_not_raised(node_module, monkeypatch):
    calls: list[str] = []

    class Failing(_EventsExecutor):
        def shutdown(self, timeout_sec=None) -> bool:
            raise RuntimeError("boom")

    experimental = types.ModuleType("rclpy.experimental")
    experimental.EventsExecutor = lambda: Failing(calls)
    monkeypatch.setitem(sys.modules, "rclpy.experimental", experimental)
    monkeypatch.setenv("ROSY_CORE_EXECUTOR", "events")
    node = _bare_node(node_module, calls)
    node.run()
    assert any("executor shutdown raised during teardown" in w
               for w in node.get_logger().warnings)


class _EventsExecutor:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def add_node(self, node) -> None:
        self.calls.append("add_node")

    def remove_node(self, node) -> None:
        self.calls.append("remove_node")

    def spin(self) -> None:
        self.calls.append("spin returned")

    def shutdown(self, timeout_sec=None) -> bool:
        self.calls.append(f"executor.shutdown({timeout_sec})")
        return True


def test_default_stays_multithreaded_and_unknown_value_is_refused(node_module, monkeypatch):
    monkeypatch.delenv("ROSY_CORE_EXECUTOR", raising=False)
    assert node_module.core_executor_kind() == "threaded"
    monkeypatch.setenv("ROSY_CORE_EXECUTOR", "turbo")
    with pytest.raises(ValueError, match="ROSY_CORE_EXECUTOR"):
        node_module.core_executor_kind()


def test_events_executor_is_spun_natively_and_needs_no_pool_drain(node_module, monkeypatch):
    calls: list[str] = []
    experimental = types.ModuleType("rclpy.experimental")
    experimental.EventsExecutor = lambda: _EventsExecutor(calls)
    monkeypatch.setitem(sys.modules, "rclpy.experimental", experimental)
    monkeypatch.setenv("ROSY_CORE_EXECUTOR", "events")
    node = _bare_node(node_module, calls)
    node.run()
    assert calls == ["add_node", "attach", "spin returned", "detach", "remove_node",
                     "executor.shutdown(0)"]
    assert node.get_logger().warnings == []


def test_events_spin_ending_on_context_shutdown_returns_like_threaded(node_module, monkeypatch):
    # Real EventsExecutor.spin() raises ExternalShutdownException when the context goes down.
    calls: list[str] = []

    class Raising(_EventsExecutor):
        def spin(self) -> None:
            calls.append("spin raised")
            raise _ExternalShutdown()

    experimental = types.ModuleType("rclpy.experimental")
    experimental.EventsExecutor = lambda: Raising(calls)
    monkeypatch.setitem(sys.modules, "rclpy.experimental", experimental)
    monkeypatch.setenv("ROSY_CORE_EXECUTOR", "events")
    node = _bare_node(node_module, calls)
    node.run()
    assert calls == ["add_node", "attach", "spin raised", "detach", "remove_node",
                     "executor.shutdown(0)"]


def test_threaded_spin_still_propagates_errors(node_module, monkeypatch):
    monkeypatch.delenv("ROSY_CORE_EXECUTOR", raising=False)
    calls: list[str] = []
    node = _bare_node(node_module, calls)
    executor = _FakeExecutor(calls)
    executor.release.set()

    def spin():
        raise _ExternalShutdown()

    executor.spin = spin
    monkeypatch.setattr(node_module, "MultiThreadedExecutor", lambda: executor)
    with pytest.raises(_ExternalShutdown):
        node.run()
