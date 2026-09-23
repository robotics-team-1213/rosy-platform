"""rosylib.Battery over a fake i2c-dev descriptor (D-192).

The vendor's battery_publisher needs pinkylib.Battery, which is closed and only
on the vendor image. rosylib.Battery speaks the public ADC protocol that
sensor_adc/src/main_node.cpp already uses. No bus is opened here.
"""

from __future__ import annotations

import pytest

from rosylib import Battery
from rosylib import battery as battery_module


class FakeI2C:
    """Records every bus call; answers reads from a queue of 2-byte replies."""

    def __init__(self, replies=(), written=1):
        self.calls = []
        self.replies = list(replies)
        self.written = written
        self.locked = False

    def open(self, bus, address):
        self.calls.append(("open", bus, address))
        return 7

    def lock(self, fd):
        assert not self.locked
        self.locked = True
        self.calls.append(("lock", fd))

    def unlock(self, fd):
        assert self.locked
        self.locked = False
        self.calls.append(("unlock", fd))

    def write(self, fd, data):
        assert self.locked, "register pointer written outside the bus lock"
        self.calls.append(("write", fd, bytes(data)))
        return self.written

    def read(self, fd, size):
        assert self.locked, "sample read outside the bus lock"
        self.calls.append(("read", fd, size))
        return self.replies.pop(0)

    def close(self, fd):
        self.calls.append(("close", fd))


def _battery(io):
    # The settle is recorded in the same call log, so its place is asserted.
    def sleep(seconds):
        assert io.locked, "settled outside the bus lock"
        io.calls.append(("sleep", seconds))

    return Battery(io=io, sleep=sleep)


def test_opens_the_adc_mcu_on_i2c_1():
    io = FakeI2C()
    _battery(io)
    assert io.calls == [("open", "/dev/i2c-1", 0x08)]


def test_one_transaction_is_pointer_write_settle_two_byte_read_under_the_lock():
    io = FakeI2C(replies=[bytes((0x8A, 0x70))])

    raw = _battery(io).read_raw()

    assert io.calls[1:] == [("lock", 7), ("write", 7, bytes((0xF8,))), ("sleep", pytest.approx(0.006)),
                            ("read", 7, 2), ("unlock", 7)]
    assert raw == (0x8A << 4) + (0x70 >> 4)


@pytest.mark.parametrize(
    ("d0", "d1", "raw"),
    [(0x00, 0x00, 0), (0xFF, 0xF0, 4095), (0x12, 0x3F, 0x123), (0x80, 0x0F, 0x800)],
)
def test_byte_assembly_is_left_aligned_12_bit(d0, d1, raw):
    # The low nibble of d1 is not part of the sample (sensor_adc: d1 >> 4).
    assert battery_module.decode_adc12(bytes((d0, d1))) == raw


def test_voltage_uses_the_sensor_adc_formula():
    # V = raw / 4096 * 4.096 / (13 / 28)
    assert battery_module.raw_to_voltage(4096) == pytest.approx(4.096 * 28 / 13)
    assert battery_module.raw_to_voltage(0) == 0.0
    # rosy-pinky-e4us 2026-09-24 measured 8.665-8.682 V: raw 0x0FB7..0x0FBF.
    assert 8.66 < battery_module.raw_to_voltage(0xFBC) < 8.69
    io = FakeI2C(replies=[bytes((0xFB, 0xC0))])
    assert _battery(io).get_voltage() == pytest.approx(0xFBC / 4096 * 4.096 / (13 / 28))


def test_percentage_reads_the_bus_and_maps_through_the_curve():
    # 0x0DF0 -> 7.690 V, between (7.74, 60) and (7.64, 50).
    io = FakeI2C(replies=[bytes((0xDF, 0x00))])
    voltage = 0xDF0 / 4096 * 4.096 / (13 / 28)
    expected = 50.0 + (voltage - 7.64) / (7.74 - 7.64) * 10.0

    assert _battery(io).battery_percentage() == pytest.approx(expected)


def test_percent_clamps_at_both_ends():
    assert battery_module.voltage_to_percent(8.67) == 100.0
    assert battery_module.voltage_to_percent(8.40) == 100.0
    assert battery_module.voltage_to_percent(6.40) == 0.0
    assert battery_module.voltage_to_percent(5.0) == 0.0


@pytest.mark.parametrize("reply", [b"", b"\x01", b"\x01\x02\x03"])
def test_a_short_or_long_read_is_an_error_and_releases_the_lock(reply):
    io = FakeI2C(replies=[reply])
    with pytest.raises(OSError):
        _battery(io).get_voltage()
    assert io.calls[-1] == ("unlock", 7) and not io.locked


def test_a_failed_pointer_write_reads_nothing_and_releases_the_lock():
    io = FakeI2C(replies=[bytes((1, 2))], written=0)
    with pytest.raises(OSError, match="register write"):
        _battery(io).read_raw()
    assert not any(call[0] == "read" for call in io.calls)
    assert not io.locked


def test_close_is_idempotent_and_a_closed_battery_refuses_to_read():
    io = FakeI2C()
    battery = _battery(io)
    battery.close()
    battery.close()
    assert io.calls.count(("close", 7)) == 1
    with pytest.raises(OSError, match="closed"):
        battery.read_raw()


def test_led_is_not_provided_and_says_why():
    # led/led_server.py does `from rosylib import LED`; the LED is bench-only.
    with pytest.raises(ImportError, match="bench-only"):
        from rosylib import LED  # noqa: F401
