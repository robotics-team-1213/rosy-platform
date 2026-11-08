"""battery_publisher survives a missing bus and stays fail-closed (D-192 review)."""

from __future__ import annotations

import importlib
import sys

import pytest

import ros_stubs


@pytest.fixture
def module(monkeypatch):
    ros_stubs.install(monkeypatch, ros_stubs.World())
    monkeypatch.delitem(sys.modules, "bringup.battery_publisher", raising=False)
    yield importlib.import_module("bringup.battery_publisher")
    sys.modules.pop("bringup.battery_publisher", None)


class FlakyBus:
    """Battery factory: the first `missing` opens fail like a missing /dev/i2c-1."""

    def __init__(self, missing, voltage=8.67):
        self.missing = missing
        self.opens = 0
        self.voltage = voltage
        self.fail_reads = 0

    def __call__(self):
        self.opens += 1
        if self.opens <= self.missing:
            raise FileNotFoundError(2, "No such file or directory", "/dev/i2c-1")
        bus = self

        class _Battery:
            closed = False

            def get_voltage(self):
                if bus.fail_reads:
                    bus.fail_reads -= 1
                    raise OSError(121, "Remote I/O error")
                return bus.voltage

            def battery_percentage(self):
                return 100.0

            def close(self):
                self.closed = True

        return _Battery()


def _published(node):
    return ([m.data for m in node.voltage_publisher.messages],
            [m.data for m in node.percentage_publisher.messages])


def test_a_missing_bus_at_start_is_retried_and_nothing_is_published_meanwhile(module):
    bus = FlakyBus(missing=2)
    node = module.BatteryPublisher(battery_factory=bus)  # open 1 fails, node stays up

    node.voltage_callback()                              # open 2 fails
    assert _published(node) == ([], [])

    node.voltage_callback()                              # open 3 succeeds
    node.percentage_callback()
    assert _published(node) == ([8.67], [100.0])
    assert bus.opens == 3


def test_a_failed_read_publishes_nothing_and_reopens(module):
    bus = FlakyBus(missing=0)
    node = module.BatteryPublisher(battery_factory=bus)
    bus.fail_reads = 1

    node.voltage_callback()
    assert _published(node) == ([], [])
    assert node.battery is None

    node.voltage_callback()
    assert _published(node) == ([8.67], [])
    assert bus.opens == 2


def test_a_hung_bus_is_probed_with_growing_gaps_and_recovers(module):
    now = [0.0]
    bus = FlakyBus(missing=0)
    node = module.BatteryPublisher(battery_factory=bus, clock=lambda: now[0])
    bus.fail_reads = 10**6                      # kernel i2c timeouts, every transaction

    node.voltage_callback()                     # 1st failure: reopen at once
    node.voltage_callback()                     # reopened, 2nd failure: now 10 s quiet
    assert bus.opens == 2
    for _ in range(3):
        node.voltage_callback()
    assert bus.opens == 2                       # not touched while backing off

    now[0] = 10.0
    node.voltage_callback()                     # 3rd failure: 20 s quiet
    now[0] = 29.0
    node.voltage_callback()
    assert bus.opens == 3

    bus.fail_reads = 0
    now[0] = 30.0
    node.voltage_callback()
    assert _published(node)[0] == [8.67]
    node.voltage_callback()                     # healthy again: no gap
    assert _published(node)[0] == [8.67, 8.67]


def test_the_injected_clock_does_not_replace_the_rclpy_node_clock(module):
    """Release 175 died at start on the robot: ``self._clock = time.monotonic`` hid rclpy Node's own
    ``_clock`` and ``create_timer`` read ``.handle`` from it. The stub Node has no clock, so check the name."""
    def sentinel():
        return 0.0
    node = module.BatteryPublisher(battery_factory=FlakyBus(missing=0), clock=sentinel)
    assert getattr(node, "_clock", None) is not sentinel
