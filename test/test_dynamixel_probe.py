"""Unit tests for the read-only DYNAMIXEL commissioning probe."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_probe(monkeypatch):
    sdk = ModuleType("dynamixel_sdk")
    sdk.COMM_SUCCESS = 0
    sdk.PacketHandler = object
    sdk.PortHandler = object
    monkeypatch.setitem(sys.modules, "dynamixel_sdk", sdk)
    monkeypatch.syspath_prepend(str(ROOT / "src" / "devices" / "pinky_pro" / "bringup"))
    sys.modules.pop("bringup.dynamixel_probe", None)
    return importlib.import_module("bringup.dynamixel_probe")


class FakePort:
    def __init__(self, open_ok=True, baud_ok=True):
        self.open_ok = open_ok
        self.baud_ok = baud_ok
        self.closed = False
        self.baudrate = None

    def openPort(self):
        return self.open_ok

    def setBaudRate(self, baudrate):
        self.baudrate = baudrate
        return self.baud_ok

    def closePort(self):
        self.closed = True


class FakePacket:
    def __init__(self, torque_by_id=None):
        self.torque_by_id = torque_by_id or {}
        self.pinged = []
        self.reads = []

    def ping(self, _port, motor_id):
        self.pinged.append(motor_id)
        return 1234, 0, 0

    def read1ByteTxRx(self, _port, motor_id, address):
        self.reads.append((motor_id, address))
        return self.torque_by_id.get(motor_id, 0), 0, 0


def test_probe_pings_each_motor_and_reads_disabled_state(monkeypatch, capsys):
    module = _load_probe(monkeypatch)
    port = FakePort()
    packet = FakePacket()
    monkeypatch.setattr(module, "PortHandler", lambda _device: port)
    monkeypatch.setattr(module, "PacketHandler", lambda _protocol: packet)

    assert module.probe("/dev/rosy-motor", 1_000_000, [1, 2]) is True
    assert port.baudrate == 1_000_000
    assert port.closed is True
    assert packet.pinged == [1, 2]
    assert packet.reads == [(1, module.ADDR_TORQUE_ENABLE), (2, module.ADDR_TORQUE_ENABLE)]
    assert "PASS DXL id=1" in capsys.readouterr().out


def test_probe_fails_closed_when_a_motor_is_already_enabled(monkeypatch, capsys):
    module = _load_probe(monkeypatch)
    port = FakePort()
    packet = FakePacket(torque_by_id={2: 1})
    monkeypatch.setattr(module, "PortHandler", lambda _device: port)
    monkeypatch.setattr(module, "PacketHandler", lambda _protocol: packet)

    assert module.probe("/dev/rosy-motor", 1_000_000, [1, 2]) is False
    assert port.closed is True
    assert "torque is already enabled" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ["--device", "relative"],
        ["--baudrate", "0"],
        ["--ids", "1", "1"],
        ["--ids", "253"],
    ],
)
def test_probe_rejects_unsafe_transport_arguments(monkeypatch, arguments):
    module = _load_probe(monkeypatch)

    with pytest.raises(SystemExit):
        module.parse_args(arguments)
