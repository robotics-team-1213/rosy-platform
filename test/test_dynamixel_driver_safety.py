"""Startup safety tests for the DYNAMIXEL motor driver."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_driver(
    monkeypatch,
    events,
    fail_enable_id=None,
    fail_reboot_id=None,
    fail_bulk_id=None,
    motor_ids=None,
    max_rpm=100.0,
    fail_baud=False,
    raise_goal_tx=False,
    raise_disable_id=None,
):
    sdk = ModuleType("dynamixel_sdk")
    sdk.COMM_SUCCESS = 0
    sdk.DXL_LOBYTE = lambda value: value & 0xFF
    sdk.DXL_HIBYTE = lambda value: (value >> 8) & 0xFF
    sdk.DXL_LOWORD = lambda value: value & 0xFFFF
    sdk.DXL_HIWORD = lambda value: (value >> 16) & 0xFFFF

    class Port:
        def __init__(self, _device):
            pass

        def openPort(self):
            events.append(("open",))
            return True

        def setBaudRate(self, _baudrate):
            events.append(("baud", _baudrate))
            return not fail_baud

        def closePort(self):
            events.append(("close",))

    class Packet:
        def __init__(self, _protocol):
            pass

        def reboot(self, _port, motor_id):
            events.append(("reboot", motor_id))
            return ((-1, 0) if motor_id == fail_reboot_id else (0, 0))

        def write1ByteTxRx(self, _port, motor_id, address, value):
            events.append(("write1", motor_id, address, value))
            if address == 64 and value == 0 and motor_id == raise_disable_id:
                raise OSError(f"disable failed for {motor_id}")
            if address == 64 and value == 1 and motor_id == fail_enable_id:
                return -1, 0
            return 0, 0

        def write4ByteTxRx(self, _port, motor_id, address, value):
            events.append(("write4", motor_id, address, value))
            return 0, 0

        def read4ByteTxRx(self, _port, motor_id, address):
            events.append(("read4", motor_id, address))
            return 0, 0, 0

    class SyncWrite:
        def __init__(self, *_args):
            pass

        def clearParam(self):
            pass

        def addParam(self, motor_id, _param):
            events.append(("goal", motor_id, 0))
            return True

        def txPacket(self):
            events.append(("goal_tx",))
            if raise_goal_tx:
                raise OSError("sync write failed")
            return 0

    class BulkRead:
        def __init__(self, *_args):
            pass

        def clearParam(self):
            events.append(("bulk_clear",))

        def addParam(self, motor_id, address, length):
            events.append(("bulk_add", motor_id, address, length))
            return motor_id != fail_bulk_id

    sdk.PortHandler = Port
    sdk.PacketHandler = Packet
    sdk.GroupSyncWrite = SyncWrite
    sdk.GroupBulkRead = BulkRead
    monkeypatch.setitem(sys.modules, "dynamixel_sdk", sdk)
    monkeypatch.syspath_prepend(str(ROOT / "src" / "devices" / "pinky_pro" / "bringup"))
    sys.modules.pop("bringup.dynamixel_driver", None)
    module = importlib.import_module("bringup.dynamixel_driver")
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    return module.DynamixelDriver(
        "/dev/test",
        1_000_000,
        [1, 2] if motor_ids is None else motor_ids,
        max_rpm=max_rpm,
    )


def test_initialization_confirms_zero_before_enabling_any_torque(monkeypatch):
    events = []
    driver = _load_driver(monkeypatch, events)

    assert driver.initialize_motors() is True

    zero_tx = events.index(("goal_tx",))
    first_enable = min(
        index
        for index, event in enumerate(events)
        if event[0] == "write1" and event[2:] == (driver.ADDR_TORQUE_ENABLE, 1)
    )
    assert zero_tx < first_enable
    assert ("read4", 1, driver.ADDR_GOAL_VELOCITY) in events
    assert ("read4", 2, driver.ADDR_GOAL_VELOCITY) in events
    assert ("write4", 1, driver.ADDR_PROFILE_ACCEL, 200) in events
    assert ("write4", 2, driver.ADDR_PROFILE_ACCEL, 200) in events


def test_begin_closes_port_when_baudrate_setup_fails(monkeypatch):
    events = []
    driver = _load_driver(monkeypatch, events, fail_baud=True)

    assert driver.begin() is False
    assert events == [("open",), ("baud", 1_000_000), ("close",)]


def test_terminate_closes_port_and_attempts_every_torque_off_despite_sdk_errors(
    monkeypatch,
):
    events = []
    driver = _load_driver(
        monkeypatch,
        events,
        raise_goal_tx=True,
        raise_disable_id=1,
    )

    driver.terminate()

    assert ("write1", 1, driver.ADDR_TORQUE_ENABLE, 0) in events
    assert ("write1", 2, driver.ADDR_TORQUE_ENABLE, 0) in events
    assert events[-1] == ("close",)


@pytest.mark.parametrize("profile_accel", [0, -1, 1.5, "fast", 32768])
def test_initialization_rejects_invalid_profile_acceleration_before_io(
    monkeypatch, profile_accel
):
    events = []
    driver = _load_driver(monkeypatch, events)

    assert driver.initialize_motors(profile_accel=profile_accel) is False
    assert events == []


def test_public_profile_acceleration_validator_preserves_exact_integer(
    monkeypatch,
):
    driver = _load_driver(monkeypatch, [])
    module = sys.modules[driver.__class__.__module__]

    assert module.validate_profile_acceleration(200) == 200
    with pytest.raises(ValueError, match="integer from 1 through 32767"):
        module.validate_profile_acceleration(200.5)


def test_partial_torque_enable_failure_disables_every_motor(monkeypatch):
    events = []
    driver = _load_driver(monkeypatch, events, fail_enable_id=2)

    assert driver.initialize_motors() is False

    failure_index = events.index(("write1", 2, driver.ADDR_TORQUE_ENABLE, 1))
    cleanup = events[failure_index + 1 :]
    assert ("write1", 1, driver.ADDR_TORQUE_ENABLE, 0) in cleanup
    assert ("write1", 2, driver.ADDR_TORQUE_ENABLE, 0) in cleanup


def test_reboot_failure_stops_initialization_before_torque_enable(monkeypatch):
    events = []
    driver = _load_driver(monkeypatch, events, fail_reboot_id=1)

    assert driver.initialize_motors() is False
    assert not any(
        event[0] == "write1" and event[2:] == (driver.ADDR_TORQUE_ENABLE, 1)
        for event in events
    )


def test_driver_requires_exactly_two_distinct_motor_ids(monkeypatch):
    for motor_ids in ([1], [1, 1], [1, 2, 3]):
        with pytest.raises(ValueError, match="two distinct"):
            _load_driver(monkeypatch, [], motor_ids=motor_ids)


@pytest.mark.parametrize("motor_ids", [[1, "2"], [1, 253], [True, 2]])
def test_driver_requires_motor_ids_in_dynamixel_unicast_range(monkeypatch, motor_ids):
    with pytest.raises(ValueError, match="integers from 0 through 252"):
        _load_driver(monkeypatch, [], motor_ids=motor_ids)


def test_public_motor_id_validator_preserves_exact_integer_ids(monkeypatch):
    driver = _load_driver(monkeypatch, [])
    module = sys.modules[driver.__class__.__module__]

    assert module.validate_motor_ids([1, 2]) == (1, 2)
    with pytest.raises(ValueError, match="integers from 0 through 252"):
        module.validate_motor_ids([1.9, 2.9])


@pytest.mark.parametrize("max_rpm", [0.0, -1.0, float("nan"), float("inf")])
def test_driver_requires_positive_finite_maximum_rpm(monkeypatch, max_rpm):
    with pytest.raises(ValueError, match="max_rpm must be a positive finite number"):
        _load_driver(monkeypatch, [], max_rpm=max_rpm)


@pytest.mark.parametrize(
    ("left_rpm", "right_rpm"),
    [
        (float("nan"), 0.0),
        (0.0, float("inf")),
        ("fast", 0.0),
        (100.0001, 0.0),
        (0.0, -100.0001),
    ],
)
def test_direct_rpm_boundary_rejects_invalid_or_excessive_values(
    monkeypatch, left_rpm, right_rpm
):
    events = []
    driver = _load_driver(monkeypatch, events)

    assert driver.set_double_rpm(left_rpm, right_rpm) is False
    assert not any(event[0] == "goal" for event in events)


@pytest.mark.parametrize("left_rpm,right_rpm", [(100.0, -100.0), (-100.0, 100.0)])
def test_direct_rpm_boundary_accepts_exact_configured_limit(
    monkeypatch, left_rpm, right_rpm
):
    events = []
    driver = _load_driver(monkeypatch, events)

    assert driver.set_double_rpm(left_rpm, right_rpm) is True
    assert len([event for event in events if event[0] == "goal"]) == 2


def test_bulk_read_registration_failure_stops_feedback_transaction(monkeypatch):
    events = []
    driver = _load_driver(monkeypatch, events, fail_bulk_id=2)

    assert driver.get_feedback() == (None, None, None, None)
    assert ("bulk_add", 1, driver.ADDR_PRESENT_VELOCITY, 8) in events
    assert ("bulk_add", 2, driver.ADDR_PRESENT_VELOCITY, 8) in events


def test_signed_32_decode_handles_dynamixel_negative_values(monkeypatch):
    driver = _load_driver(monkeypatch, [])
    module = sys.modules[driver.__class__.__module__]

    assert module.decode_signed_32(0x7FFFFFFF) == 0x7FFFFFFF
    assert module.decode_signed_32(0x80000000) == -0x80000000
    assert module.decode_signed_32(0xFFFFFFFF) == -1


def test_encoder_delta_crosses_signed_32_rollover_without_odometry_jump(monkeypatch):
    driver = _load_driver(monkeypatch, [])
    module = sys.modules[driver.__class__.__module__]

    assert module.wrapped_encoder_delta(-0x80000000, 0x7FFFFFFF) == 1
    assert module.wrapped_encoder_delta(0x7FFFFFFF, -0x80000000) == -1
    assert module.wrapped_encoder_delta(110, 100) == 10


def test_no_motion_initialization_confirms_zero_and_never_enables_torque(monkeypatch):
    # D-192 no-motion mode: encoders read back, the wheels cannot be driven.
    events = []
    driver = _load_driver(monkeypatch, events)

    assert driver.initialize_motors(enable_torque=False) is True

    assert not any(
        event[0] == "write1" and event[2] in (driver.ADDR_TORQUE_ENABLE, driver.ADDR_LED_RED)
        and event[3] == 1
        for event in events
    )
    assert ("write1", 1, driver.ADDR_TORQUE_ENABLE, 0) in events
    assert ("write1", 2, driver.ADDR_TORQUE_ENABLE, 0) in events
    assert ("read4", 1, driver.ADDR_GOAL_VELOCITY) in events
    assert ("read4", 2, driver.ADDR_GOAL_VELOCITY) in events
