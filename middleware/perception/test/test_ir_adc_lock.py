"""ir_adc_node holds the I2C-1 bus lock for the whole IR cycle (D-192).

bringup's rosylib.Battery reads channel 4 of the same ADC MCU (0x08) from
another process; the MCU keeps one register pointer. Every pointer write,
settle and read of a cycle must happen inside one exclusive flock.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
from types import ModuleType

import pytest

CONTROL_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def reader(monkeypatch):
    calls = []
    state = {"locked": False}

    def module(name, **attributes):
        mod = ModuleType(name)
        mod.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    class Node:  # never constructed here
        pass

    module("rclpy", init=lambda: None, spin=lambda _n: None, ok=lambda: True, shutdown=lambda: None)
    module("rclpy.node", Node=Node)
    module("std_msgs")
    module("std_msgs.msg", UInt16MultiArray=object)

    def flock(fd, operation):
        if operation == fcntl.LOCK_EX:
            assert not state["locked"]
            state["locked"] = True
            calls.append(("lock", fd))
        else:
            assert state["locked"]
            state["locked"] = False
            calls.append(("unlock", fd))

    fcntl = module("fcntl", LOCK_EX=2, LOCK_UN=8, flock=flock)
    monkeypatch.syspath_prepend(str(CONTROL_ROOT))
    monkeypatch.delitem(sys.modules, "control.ir_adc_node", raising=False)
    node_module = importlib.import_module("control.ir_adc_node")

    replies = {0x88: b"\x10\x00", 0xC8: b"\x20\x00", 0x98: b"\x30\x00"}
    last = {}

    def write(fd, data):
        assert state["locked"], "register pointer written outside the bus lock"
        last["register"] = data[0]
        calls.append(("write", fd, data[0]))
        return 1

    def sleep(seconds):
        assert state["locked"], "settled outside the bus lock"
        calls.append(("sleep", seconds))

    def read(fd, size):
        assert state["locked"], "sample read outside the bus lock"
        calls.append(("read", fd, size))
        return replies[last["register"]]

    monkeypatch.setattr(node_module.os, "write", write)
    monkeypatch.setattr(node_module.os, "read", read)
    monkeypatch.setattr(node_module.time, "sleep", sleep)
    adc = object.__new__(node_module._ADCReader)
    adc._fd = 5
    yield adc, calls, state
    sys.modules.pop("control.ir_adc_node", None)


def test_one_lock_spans_every_write_settle_and_read_of_the_cycle(reader):
    adc, calls, state = reader

    sample = adc.read_channels()

    assert sample == [0x300, 0x200, 0x100]
    assert calls[0] == ("lock", 5) and calls[-1] == ("unlock", 5)
    body = calls[1:-1]
    assert [call[0] for call in body] == ["write", "sleep", "read"] * 3
    assert [call[2] for call in body if call[0] == "write"] == [0x88, 0xC8, 0x98]
    assert not state["locked"]


def test_the_lock_is_released_when_the_bus_fails(reader, monkeypatch):
    adc, calls, state = reader
    node_module = sys.modules["control.ir_adc_node"]

    def broken_read(_fd, _size):
        raise OSError(121, "Remote I/O error")

    monkeypatch.setattr(node_module.os, "read", broken_read)
    with pytest.raises(OSError):
        adc.read_channels()
    assert calls[-1] == ("unlock", 5) and not state["locked"]


def test_a_hung_bus_backs_off_instead_of_reopening_every_tick(reader, monkeypatch):
    _adc, _calls, _state = reader
    mod = sys.modules["control.ir_adc_node"]
    opens = []

    class Dead:
        def __init__(self, *_):
            opens.append(1)

        def read_channels(self):
            raise OSError(110, "Connection timed out")

        def close(self):
            pass

    now = [0.0]
    monkeypatch.setattr(mod, "_ADCReader", Dead)
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    node = object.__new__(mod.IRADCNode)
    node._reader, node._failures, node._retry_at = None, 0, 0.0
    node.get_parameter = lambda _n: type("P", (), {"value": "8"})()
    node.get_logger = lambda: type("L", (), {
        "warning": staticmethod(lambda *a, **k: None), "info": staticmethod(lambda *a: None)})()

    node._tick()
    node._tick()                      # first failure reopens at once, second one backs off 2 s
    assert len(opens) == 2
    for _ in range(20):
        node._tick()
    assert len(opens) == 2
    now[0] = 2.0
    node._tick()
    assert len(opens) == 3
