"""teardown 이 기대는 rclpy 내부 모양을 ROS 레인에서 고정한다 (rclpy 필요).

`core/node.py::_stop_executor` 는 `MultiThreadedExecutor._executor`(작업 스레드 풀)를
직접 비운다 — rclpy 7.1.x 의 `Executor.shutdown()` 은 진행 중 콜백을 기다리지 않고,
`MultiThreadedExecutor` 에는 풀을 내리는 shutdown 이 없기 때문이다(C6 판정은
`docs/plans/2026-09-06-module-split-criteria.md`). rclpy 가 이 이름을 바꾸거나 없애면
호스트 시험은 가짜 executor 로 계속 통과하므로, 여기서 진짜 rclpy 를 보고 깨뜨린다.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("rclpy")

import rclpy  # noqa: E402
from rclpy.executors import MultiThreadedExecutor  # noqa: E402

from core.node import _stop_executor  # noqa: E402


def test_multithreaded_executor_still_exposes_a_thread_pool():
    context = rclpy.context.Context()
    context.init()
    executor = MultiThreadedExecutor(context=context)
    try:
        pool = getattr(executor, "_executor", None)
        assert isinstance(pool, ThreadPoolExecutor), (
            "rclpy changed MultiThreadedExecutor's worker pool; "
            "core/node.py::_stop_executor no longer drains anything")
    finally:
        executor.shutdown(timeout_sec=0)
        context.try_shutdown()


def _spin_events_until(context, node, done, timeout=5.0):
    """CORE.run()'s events branch on a real EventsExecutor: add, spin, remove, shutdown(0)."""
    import threading
    import time

    from rclpy.experimental import EventsExecutor

    executor = EventsExecutor(context=context)
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()
    deadline = time.monotonic() + timeout
    while not done() and time.monotonic() < deadline:
        time.sleep(0.01)
    context.try_shutdown()
    spinner.join(timeout)
    assert not spinner.is_alive(), "EventsExecutor.spin() did not return on context shutdown"
    executor.remove_node(node)
    executor.shutdown(timeout_sec=0)


def test_events_executor_runs_timers_and_returns_on_shutdown():
    context = rclpy.context.Context()
    context.init()
    node = rclpy.create_node("core_events_timer", context=context)
    ticks = []
    node.create_timer(0.02, lambda: ticks.append(1))  # CORE's cmd_vel timer period
    try:
        _spin_events_until(context, node, lambda: len(ticks) >= 5)
        assert len(ticks) >= 5
    finally:
        node.destroy_node()


def test_events_executor_delivers_a_publish_from_another_thread():
    # CORE's uvicorn thread publishes on the node while the executor thread spins.
    import threading

    from std_msgs.msg import String

    context = rclpy.context.Context()
    context.init()
    node = rclpy.create_node("core_events_api_thread", context=context)
    received = []
    node.create_subscription(String, "core_events_probe", lambda m: received.append(m.data), 10)
    publisher = node.create_publisher(String, "core_events_probe", 10)
    stop = threading.Event()

    def api_thread():
        while not stop.is_set():
            publisher.publish(String(data="x"))
            stop.wait(0.02)

    sender = threading.Thread(target=api_thread, daemon=True)
    sender.start()
    try:
        _spin_events_until(context, node, lambda: len(received) >= 3)
        assert len(received) >= 3
    finally:
        stop.set()
        sender.join(1.0)
        node.destroy_node()


def test_stop_executor_drains_a_real_executor():
    context = rclpy.context.Context()
    context.init()
    executor = MultiThreadedExecutor(context=context)
    try:
        assert _stop_executor(executor, 3.0) is True
        assert executor._executor._shutdown
    finally:
        context.try_shutdown()
