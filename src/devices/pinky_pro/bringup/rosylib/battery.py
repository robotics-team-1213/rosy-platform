"""Pinky Pro battery voltage from the board's ADC MCU, without pinkylib.

The vendor's ``battery_publisher`` imports ``Battery`` from ``pinkylib``, a
closed library preinstalled on the vendor image that Rosy cannot ship. This is
a Rosy-owned ``Battery`` with the two methods the publisher calls,
``get_voltage()`` and ``battery_percentage()``, over the public ADC protocol
that ``src/devices/pinky_pro/adc/src/main_node.cpp`` already speaks:

* bus ``/dev/i2c-1``, MCU address ``0x08``, battery on channel 4 (``0xF8``);
* write the one-byte register pointer, wait about 6 ms, read two bytes;
* ``raw = (d0 << 4) + (d1 >> 4)``, ``V = raw / 4096 * 4.096 / (13 / 28)``.

Percent follows CORE's 2S Li-ion curve (``core_features.power.battery``
``DEFAULT_CURVE_2S`` / ``BatteryCurve.default()``). The table is copied, not
imported: the I/O runtime must not import CORE, whose package pulls pydantic.
``test/test_rosylib_battery_curve.py`` pins the copy equal to CORE's.

Bus ownership (D-192): other processes read the same MCU (``control``'s
``ir_adc_node``). A reading is a pointer write, a settle and a read; two
readers interleaving them read each other's channel. Every Rosy reader of
0x08 therefore holds an exclusive ``flock`` on its ``/dev/i2c-1`` descriptor
for the whole transaction, the bench-only C++ ``sensor_adc`` included. That
node still never runs beside ``ir_adc_node`` (both publish ``ir_sensor/range``;
``test_ir_source_exclusivity``).
"""

from __future__ import annotations

import os
import time
from typing import Callable, Optional, Sequence

I2C_SLAVE = 0x0703  # linux/i2c-dev.h
DEFAULT_BUS = "/dev/i2c-1"
ADC_ADDRESS = 0x08
BATTERY_REGISTER = 0xF8  # channel 4; 0x88/0xC8/0x98 IR, 0xD8 ultrasonic
SETTLE_S = 0.006
ADC_FULL_SCALE = 4096
ADC_REFERENCE_V = 4.096
DIVIDER_RATIO = 13.0 / 28.0

# Copy of core_features.power.battery.DEFAULT_CURVE_2S (pack volts, percent).
CURVE_2S: tuple[tuple[float, float], ...] = (
    (8.40, 100.0), (8.12, 90.0), (7.96, 80.0), (7.84, 70.0),
    (7.74, 60.0), (7.64, 50.0), (7.58, 40.0), (7.50, 30.0),
    (7.42, 20.0), (7.32, 10.0), (6.60, 5.0), (6.40, 0.0),
)


def decode_adc12(payload: bytes) -> int:
    """The MCU's two-byte, left-aligned 12-bit sample."""
    if len(payload) != 2:
        raise OSError(f"ADC answered {len(payload)} bytes, expected 2")
    return (payload[0] << 4) + (payload[1] >> 4)


def raw_to_voltage(raw: int) -> float:
    """Pack voltage behind the 13/28 divider (same formula as sensor_adc)."""
    return raw / ADC_FULL_SCALE * ADC_REFERENCE_V / DIVIDER_RATIO


def voltage_to_percent(voltage: float,
                       curve: Sequence[tuple[float, float]] = CURVE_2S) -> float:
    """Piecewise-linear percent, clamped at both ends (as BatteryCurve.percent)."""
    points = sorted(((float(v), float(p)) for v, p in curve), reverse=True)
    value = float(voltage)
    if value >= points[0][0]:
        return points[0][1]
    if value <= points[-1][0]:
        return points[-1][1]
    for (v_hi, p_hi), (v_lo, p_lo) in zip(points, points[1:]):
        if value >= v_lo:
            return p_lo + (value - v_lo) / (v_hi - v_lo) * (p_hi - p_lo)
    return points[-1][1]


class DeviceIO:
    """The real bus: an i2c-dev descriptor bound to the MCU, flock per transaction."""

    def open(self, bus: str, address: int) -> int:
        import fcntl

        fd = os.open(bus, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
        try:
            fcntl.ioctl(fd, I2C_SLAVE, address)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def lock(self, fd: int) -> None:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)

    def unlock(self, fd: int) -> None:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)

    def write(self, fd: int, data: bytes) -> int:
        return os.write(fd, data)

    def read(self, fd: int, size: int) -> bytes:
        return os.read(fd, size)

    def close(self, fd: int) -> None:
        os.close(fd)


class Battery:
    """``pinkylib.Battery``-compatible reader: ``get_voltage()``, ``battery_percentage()``."""

    def __init__(self, bus: str = DEFAULT_BUS, address: int = ADC_ADDRESS, *,
                 io: Optional[DeviceIO] = None,
                 sleep: Callable[[float], None] = time.sleep,
                 curve: Sequence[tuple[float, float]] = CURVE_2S) -> None:
        self._io = io if io is not None else DeviceIO()
        self._sleep = sleep
        self._curve = tuple(curve)
        self._fd: Optional[int] = self._io.open(bus, address)

    def read_raw(self) -> int:
        """One locked channel-4 transaction: pointer write, settle, 2-byte read."""
        if self._fd is None:
            raise OSError("battery ADC is closed")
        self._io.lock(self._fd)
        try:
            written = self._io.write(self._fd, bytes((BATTERY_REGISTER,)))
            if written != 1:
                raise OSError(f"ADC register write returned {written}")
            self._sleep(SETTLE_S)
            return decode_adc12(self._io.read(self._fd, 2))
        finally:
            self._io.unlock(self._fd)

    def get_voltage(self) -> float:
        return raw_to_voltage(self.read_raw())

    def battery_percentage(self) -> float:
        return voltage_to_percent(self.get_voltage(), self._curve)

    def close(self) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            self._io.close(fd)

    def __enter__(self) -> "Battery":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
