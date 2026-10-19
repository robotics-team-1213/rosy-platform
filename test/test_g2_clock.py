"""Pinned TimeSource handoff and dedicated-executor scheduling, without DDS."""
from pathlib import Path
import queue
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))


class Clock:
    def __init__(self):
        self.ns = 0


class Source:
    def __init__(self, node=None):
        self._associated_clocks = set()
        self._node_weak_ref = lambda: node
        self._clock_sub = object()
        self.node = node
        node.callbacks.append(self._on_parameter_event)
        node.source = self

    def attach_clock(self, clock):
        clock.ns = 0
        self._associated_clocks.add(clock)

    def detach_node(self):
        self._node_weak_ref = None
        self._clock_sub = None

    def _on_parameter_event(self, _parameters):
        raise AssertionError("retired parameter callback must not run")

    def clock_callback(self, message):
        self.calls = getattr(self, "calls", 0) + 1
        for clock in self._associated_clocks:
            clock.ns = message.clock.sec * 10**9 + message.clock.nanosec


def message(ns):
    return SimpleNamespace(clock=SimpleNamespace(sec=ns // 10**9, nanosec=ns % 10**9))


class Node:
    def __init__(self, name, **_kwargs):
        self.name = name
        self.clock = Clock()
        self.callbacks = []
        self.frozen = False
        self.destroyed = False
        self._time_source = Source(self)
        self._time_source.attach_clock(self.clock)
        self.publishers = [SimpleNamespace(node_name="clock_bridge", node_namespace="/",
            topic_type="rosgraph_msgs/msg/Clock", endpoint_gid=bytes(range(16)),
            qos_profile=SimpleNamespace(depth=10, reliability=SimpleNamespace(name="RELIABLE"),
                durability=SimpleNamespace(name="VOLATILE"), history=SimpleNamespace(name="KEEP_LAST")))]

    def get_clock(self):
        return self.clock

    def get_parameter(self, _name):
        return SimpleNamespace(value=True)

    def remove_on_set_parameters_callback(self, callback):
        self.callbacks.remove(callback)

    def set_descriptor(self, name, descriptor):
        assert name == "use_sim_time"
        self.frozen = descriptor.read_only

    def describe_parameter(self, _name):
        return SimpleNamespace(read_only=self.frozen)

    def get_publishers_info_by_topic(self, topic):
        assert topic == "/clock"
        return self.publishers

    def destroy_node(self):
        self.destroyed = True


class Executor:
    def __init__(self):
        self.queue = queue.Queue()
        self.stopped = threading.Event()

    def add_node(self, node):
        self.node = node

    def spin(self):
        while not self.stopped.is_set():
            try:
                item = self.queue.get(timeout=.01)
            except queue.Empty:
                continue
            self.node.source.clock_callback(message(item))

    def shutdown(self, timeout_sec):
        self.stopped.set()
        return True


@pytest.fixture
def sdk(monkeypatch):
    import g2_clock
    class Parameter:
        Type = SimpleNamespace(BOOL=SimpleNamespace(value=2))
        def __init__(self, *_args, **_kwargs):
            pass
    sdk = SimpleNamespace(Node=Node, TimeSource=Source, SingleThreadedExecutor=Executor,
        Parameter=Parameter,
        ParameterDescriptor=lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(g2_clock, "_load_sdk", lambda: sdk)
    monkeypatch.setattr(g2_clock, "verify_sdk_sources", lambda: {"pinned": "test"})
    return sdk


@pytest.fixture
def rig(sdk):
    import g2_clock
    owner = Node("owner")
    clock = g2_clock.DedicatedSimClock(owner)
    yield owner, clock
    clock.close(timeout=.2)


def test_readonly_descriptor_must_explicitly_match_existing_bool_parameter(sdk, monkeypatch):
    import g2_clock
    original = Node.set_descriptor
    applied = []
    def strict_set_descriptor(node, name, descriptor):
        # Installed Jazzy set_descriptor validates declared bool against descriptor.type;
        # generated ParameterDescriptor defaults to NOT_SET=0, not BOOL=2.
        if getattr(descriptor, "type", 0) != sdk.Parameter.Type.BOOL.value:
            raise ValueError("Wrong parameter type, expected NOT_SET got BOOL")
        applied.append(descriptor.type)
        original(node, name, descriptor)
    monkeypatch.setattr(Node, "set_descriptor", strict_set_descriptor)
    clock = g2_clock.DedicatedSimClock(Node("owner"))
    try:
        assert applied == [2, 2]
        assert clock.owner.frozen and clock.node.frozen
    finally:
        clock.close(timeout=.2)


def test_handoff_retires_both_old_sources_and_freezes_parameters(rig):
    owner, clock = rig
    assert owner.frozen and clock.node.frozen
    assert owner.callbacks == []
    assert len(clock.node.callbacks) == 1
    owner._time_source.clock_callback(message(99000))
    clock.node._time_source.clock_callback(message(88000))
    assert owner.clock.ns == 0, "queued old callbacks retained ownership of owner clock"
    clock.source.clock_callback(message(12345))
    assert owner.clock.ns == clock.node.clock.ns == 12345
    assert clock.source.calls == 1


def test_dedicated_executor_keeps_clock_advancing_while_owner_is_blocked(rig):
    owner, clock = rig
    blocked, release = threading.Event(), threading.Event()
    worker = threading.Thread(target=lambda: (blocked.set(), release.wait(2)), daemon=True)
    worker.start()
    assert blocked.wait(1)
    clock.executor.queue.put(10**9)
    clock.executor.queue.put(2 * 10**9)
    try:
        record = clock.start(timeout=.5)
        assert worker.is_alive()
        assert owner.clock.ns == 2 * 10**9
        assert record["ready"] and record["thread_alive"]
        assert record["publishers"][0]["gid"] == bytes(range(16)).hex()
        assert record["publishers"][0]["qos"]["reliability"] == "RELIABLE"
    finally:
        release.set()
        worker.join(1)


@pytest.mark.parametrize("publishers", [[], ["duplicate", "duplicate"]])
def test_no_runtime_readiness_without_one_publisher(rig, publishers):
    _owner, clock = rig
    clock.node.publishers = publishers
    clock.executor.queue.put(1)
    clock.executor.queue.put(2)
    with pytest.raises(RuntimeError, match="CLOCK_NOT_READY"):
        clock.start(timeout=.03)


def test_no_progress_is_fail_closed_and_cleanup_is_bounded(rig):
    _owner, clock = rig
    with pytest.raises(RuntimeError, match="CLOCK_NOT_READY"):
        clock.start(timeout=.03)
    started = time.monotonic()
    clock.close(timeout=.2)
    assert time.monotonic() - started < .5
    assert not clock.thread.is_alive()
    assert clock.node.destroyed


def test_backward_frames_are_observed_not_filtered_and_telemetry_failure_cannot_drop_frame(rig, monkeypatch):
    owner, clock = rig
    for stamp in (100, 300, 200):
        clock.source.clock_callback(message(stamp))
    record = clock.snapshot()
    assert record["telemetry"]["backward_count"] == 1
    assert record["telemetry"]["min_delta_ns"] == -100
    assert owner.clock.ns == 200
    monkeypatch.setattr(clock, "_observe", lambda _message: (_ for _ in ()).throw(ValueError("private")))
    clock.source.clock_callback(message(400))
    assert owner.clock.ns == 400 and clock.source.calls == 4


def test_unsupported_old_ownership_rejected_before_executor(monkeypatch):
    import g2_clock
    monkeypatch.setattr(g2_clock, "verify_sdk_sources", lambda: {})
    monkeypatch.setattr(g2_clock, "_load_sdk", lambda: SimpleNamespace())
    owner = Node("owner")
    owner._time_source._associated_clocks.add(Clock())
    with pytest.raises(RuntimeError, match="CLOCK_SDK_UNSUPPORTED"):
        g2_clock.DedicatedSimClock(owner)
    assert owner._time_source._clock_sub is not None


def test_sdk_pin_reads_actual_import_origins_and_rejects_drift(tmp_path, monkeypatch):
    import g2_clock
    import hashlib
    path = tmp_path / "time_source.py"
    path.write_text("installed-source", encoding="utf-8")
    module = SimpleNamespace(__file__=str(path))
    monkeypatch.setattr(g2_clock, "SDK_PINS", {"rclpy.time_source": hashlib.sha256(path.read_bytes()).hexdigest()})
    monkeypatch.setattr(g2_clock.importlib, "import_module", lambda _name: module)
    assert g2_clock.verify_sdk_sources()["rclpy.time_source"]["sha256"] == g2_clock.SDK_PINS["rclpy.time_source"]
    path.write_text("different-source", encoding="utf-8")
    with pytest.raises(RuntimeError, match="CLOCK_SDK_UNSUPPORTED"):
        g2_clock.verify_sdk_sources()


def test_terminal_persistence_cannot_stall_clock_cleanup(rig, tmp_path, monkeypatch):
    import g2_clock
    _owner, clock = rig
    entered, release = threading.Event(), threading.Event()
    def parked_writer(*_args):
        entered.set()
        release.wait(2)
    monkeypatch.setattr(g2_clock, "_write_record", parked_writer)
    try:
        began = time.monotonic()
        assert clock.persist_terminal(tmp_path / "clock-terminal.json", timeout=.02) is False
        clock.close(timeout=.1)
        assert time.monotonic() - began < .5
        assert entered.is_set() and clock.node.destroyed
    finally:
        release.set()


def test_owner_composition_starts_clock_before_runtime_and_stops_it_after_owner():
    import ast
    path = Path(__file__).parents[1] / "deploy/robot/omx/g2_owner.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = sorted((node.lineno, ast.unparse(node.func)) for node in ast.walk(tree) if isinstance(node, ast.Call))
    def line(name):
        return next(number for number, called in calls if called == name)
    assert line("DedicatedSimClock") < line("clock.start") < line("build_cell_owner")
    assert line("executor.shutdown") < line("clock.close") < line("rclpy.shutdown")
    assert "num_threads=4" in path.read_text(encoding="utf-8")


def test_clock_timeout_preserves_source_and_can_finish_cleanup_later(rig, monkeypatch):
    _owner, clock = rig
    shutdown = clock.executor.shutdown
    clock.thread.start()
    monkeypatch.setattr(clock.executor, 'shutdown', lambda timeout_sec: False)
    try:
        assert clock.close(timeout=.01) is False
        assert clock.thread.is_alive()
        assert not clock.node.destroyed and not clock.closed
        assert clock.source._associated_clocks
    finally:
        monkeypatch.setattr(clock.executor, 'shutdown', shutdown)
        assert clock.close(timeout=1.) is True


@pytest.mark.parametrize('blocked', ['owner', 'action', 'clock'])
def test_owner_cleanup_hold_preserves_required_clock_and_context(tmp_path, blocked):
    from g2_owner import close_runtime
    events = []
    node = SimpleNamespace(destroy_timer=lambda timer: events.append('timer'),
                           destroy_node=lambda: events.append('node'))
    def destroy_action():
        events.append('action')
        if blocked == 'action':
            raise RuntimeError('action event executor did not stop')
    owner = SimpleNamespace(uds_server=SimpleNamespace(stop=lambda: events.append('uds')),
                            runtime=SimpleNamespace(destroy=destroy_action))
    def shutdown_owner(*, timeout_sec, wait_for_threads):
        assert timeout_sec == 5 and wait_for_threads is False
        events.append('owner')
        return blocked != 'owner'
    executor = SimpleNamespace(shutdown=shutdown_owner)
    clock = SimpleNamespace(persist_terminal=lambda *args, **kwargs: events.append('record'),
                            close=lambda **kwargs: events.append('clock') or blocked != 'clock')
    context = SimpleNamespace(shutdown=lambda: events.append('context'))
    lock = SimpleNamespace(close=lambda: events.append('lock'))
    with pytest.raises(RuntimeError, match='CLEANUP_HOLD'):
        close_runtime(node, owner, object(), executor, clock, tmp_path, lock, context)
    assert 'node' not in events and 'context' not in events and 'lock' not in events
    assert ('clock' in events) is (blocked == 'clock')
    assert ('action' in events) is (blocked != 'owner')
