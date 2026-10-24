"""Dynamixel bus layer for the D-858 S1 port: registers, OMX-F IDs, one-writer claims,
and the real exclusive SDK bus. Moved out of ``dynamixel_port.py`` (D-766 size limit)."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

ADDR_MODEL, ADDR_OPERATING_MODE, ADDR_HW_ERROR = 0, 11, 70
ADDR_TORQUE, ADDR_GOAL, ADDR_PRESENT_CURRENT, ADDR_PRESENT = 64, 116, 126, 132
WRITABLE = frozenset({ADDR_TORQUE, ADDR_GOAL})  # RAM only; EEPROM is below 64
TICKS = 4096


def to_raw(rad: float) -> int:
    return int(round((rad + math.pi) * TICKS / (2 * math.pi)))


def to_rad(raw: int) -> float:
    return raw * 2 * math.pi / TICKS - math.pi


def _signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value >= 1 << (bits - 1) else value



class Bus(Protocol):
    def read(self, dxl_id: int, addr: int, size: int) -> int: ...
    def write(self, dxl_id: int, addr: int, size: int, value: int) -> None: ...
    def sync_read(self, ids: Sequence[int], addr: int, size: int) -> dict[int, int]: ...
    def sync_write(self, addr: int, size: int, values: Mapping[int, int]) -> None: ...
    def close(self) -> None: ...


class HardwareMismatch(Exception):
    pass


class BusBusy(RuntimeError):
    """Another port in this process already writes this arm instance or serial device."""


@dataclass(frozen=True)
class Hardware:
    """OMX-F follower facts (rosy-platform 8be38f1b94 table, via device-core)."""

    joint_ids: tuple[int, ...] = (11, 12, 13, 14, 15)
    gripper_id: int = 16
    models: Mapping[int, int] = field(default_factory=lambda: {
        11: 1060, 12: 1060, 13: 1060, 14: 1200, 15: 1200, 16: 1200})
    operating_modes: Mapping[int, int] = field(default_factory=lambda: {
        11: 4, 12: 4, 13: 4, 14: 4, 15: 4, 16: 5})

    @property
    def all_ids(self) -> tuple[int, ...]:
        return tuple(self.joint_ids) + (self.gripper_id,)


class _BusClaims:
    """Process-wide single writer per arm instance and per serial device."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._instances: set[tuple[str, str]] = set()
        self._devices: set[str] = set()

    def acquire(self, instance: tuple[str, str], device: str) -> None:
        with self._lock:
            if instance in self._instances:
                raise BusBusy(f"arm instance {instance[0]}/{instance[1]} already has a bus writer")
            if device in self._devices:
                raise BusBusy("serial device already has a bus writer")
            self._instances.add(instance)
            self._devices.add(device)

    def release(self, instance: tuple[str, str], device: str) -> None:
        with self._lock:
            self._instances.discard(instance)
            self._devices.discard(device)


BUS_CLAIMS = _BusClaims()


class SdkBus:
    """Real bus: exclusive pyserial open + dynamixel_sdk Protocol 2.0. Arm PC (Linux) only."""

    def __init__(self, device: str, baud: int = 1_000_000) -> None:
        if not device.startswith("/dev/serial/by-id/"):
            raise HardwareMismatch("device must be a /dev/serial/by-id/ path")
        import fcntl
        import termios
        import serial
        from dynamixel_sdk import GroupSyncRead, GroupSyncWrite, PacketHandler, PortHandler
        s = serial.Serial()
        s.port, s.baudrate, s.timeout = device, baud, 0
        s.dtr = s.rts = False  # do not reset the OpenRB on open (same order as register_probe)
        s.exclusive = True     # another process (owner, collection, LeRobot) cannot open it
        s.open()
        try:
            fcntl.ioctl(s.fileno(), termios.TIOCEXCL)
            s.reset_input_buffer()
        except BaseException:
            s.close()  # never keep a non-exclusive handle
            raise
        self._serial = s
        self.ph = PortHandler(device)
        self.ph.ser, self.ph.is_open, self.ph.baudrate = s, True, baud
        self.ph.tx_time_per_byte = (1000.0 / baud) * 10.0
        self.ph.setupPort = lambda *_: True  # the SDK must not reopen the port
        self.pk = PacketHandler(2.0)
        self._groups = (GroupSyncRead, GroupSyncWrite)

    def _ok(self, comm: int, err: int, what: str) -> None:
        if comm != 0 or err != 0:
            detail = self.pk.getTxRxResult(comm) if comm else self.pk.getRxPacketError(err)
            raise IOError(f"{what}: {detail}")

    def read(self, dxl_id, addr, size):
        fn = {1: self.pk.read1ByteTxRx, 2: self.pk.read2ByteTxRx, 4: self.pk.read4ByteTxRx}[size]
        value, comm, err = fn(self.ph, dxl_id, addr)
        self._ok(comm, err, f"read id {dxl_id} @{addr}")
        return value

    def write(self, dxl_id, addr, size, value):
        if addr not in WRITABLE:
            raise HardwareMismatch(f"refusing write to register {addr}")
        fn = {1: self.pk.write1ByteTxRx, 2: self.pk.write2ByteTxRx, 4: self.pk.write4ByteTxRx}[size]
        comm, err = fn(self.ph, dxl_id, addr, value)
        self._ok(comm, err, f"write id {dxl_id} @{addr}")

    def sync_read(self, ids, addr, size):
        group = self._groups[0](self.ph, self.pk, addr, size)
        for i in ids:
            group.addParam(i)
        self._ok(group.txRxPacket(), 0, f"sync_read @{addr}")
        out = {}
        for i in ids:
            if not group.isAvailable(i, addr, size):
                raise IOError(f"sync_read id {i} no reply")
            value = group.getData(i, addr, size)
            out[i] = _signed(value, 32) if size == 4 else value
        return out

    def sync_write(self, addr, size, values):
        if addr not in WRITABLE:
            raise HardwareMismatch(f"refusing write to register {addr}")
        group = self._groups[1](self.ph, self.pk, addr, size)
        for i, value in values.items():
            group.addParam(i, list((value & ((1 << (8 * size)) - 1)).to_bytes(size, "little")))
        self._ok(group.txPacket(), 0, f"sync_write @{addr}")

    def close(self):
        self._serial.close()
