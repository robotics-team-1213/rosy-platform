"""A transfer that raised must not leave the port 'in use' for the torque-off that follows (2026-11-18 arm_s)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import guarded_device  # noqa: E402


class Port:
    def __init__(self):
        self.is_using, self.events = True, []

    def getBaudRate(self):
        return 1_000_000

    def closePort(self):
        self.events.append("close")

    def openPort(self):
        self.events.append("open")
        return True

    def setBaudRate(self, baud):
        self.events.append(("baud", baud))


class Bus:
    motors = ("shoulder_pan", "gripper")

    def __init__(self, healthy_after_reset=True):
        self.port_handler, self.healthy_after_reset, self.off = Port(), healthy_after_reset, []

    def disable_torque(self, name, num_retry=0):
        if self.port_handler.is_using or not self.healthy_after_reset:
            raise ConnectionError(f"Failed to write 'Torque_Enable' on {name}. [TxRxResult] Port is in use!")
        self.off.append(name)


def test_stuck_port_is_freed_reopened_and_torque_goes_off():
    bus = Bus()
    guarded_device.torque_off(bus)
    assert bus.off == ["shoulder_pan", "gripper"]
    assert bus.port_handler.events == ["close", "open", ("baud", 1_000_000)]


def test_still_failing_after_the_reset_is_reported():
    bus = Bus(healthy_after_reset=False)
    with pytest.raises(RuntimeError, match="torque OFF not confirmed"):
        guarded_device.torque_off(bus)


def test_healthy_bus_needs_no_reset():
    bus = Bus()
    bus.port_handler.is_using = False
    guarded_device.torque_off(bus)
    assert bus.port_handler.events == []
