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
