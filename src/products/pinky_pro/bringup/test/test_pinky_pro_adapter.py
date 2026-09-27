"""Pinky Pro adapter parameter contracts."""

import math

import pytest

from bringup.pinky_pro_adapter import PinkyProAdapter


def valid_mapping():
    return {
        "wheel_radius": 0.027,
        "wheel_separation": 0.0961,
        "cmd_vel_timeout_s": 0.5,
        "frame_prefix": "rosy_01/",
        "motor_device": "/dev/ttyAMA4",
        "motor_baudrate": 1_000_000,
        "motor_ids": [1, 2],
        "max_linear_mps": 0.20,
        "max_angular_rps": 0.80,
        "max_wheel_rpm": 100.0,
        "motor_profile_acceleration": 200,
    }


def test_adapter_emits_standard_ros_parameter_names_without_opening_device():
    adapter = PinkyProAdapter.from_mapping(valid_mapping())

    assert adapter.model == "pinky_pro"
    assert adapter.parameters["wheel_radius"] == pytest.approx(0.027)
    assert adapter.parameters["motor_ids"] == (1, 2)
    assert adapter.parameters["max_angular_rps"] == pytest.approx(0.80)
    assert adapter.parameters["motor_device"] == "/dev/ttyAMA4"


@pytest.mark.parametrize(
    "key,value",
    [
        ("wheel_radius", 0.0),
        ("wheel_separation", -0.1),
        ("cmd_vel_timeout_s", math.nan),
        ("max_linear_mps", math.inf),
        ("max_angular_rps", -1.0),
        ("max_wheel_rpm", 0.0),
        ("motor_profile_acceleration", 0),
        ("wheel_radius", True),
    ],
)
def test_adapter_rejects_invalid_numeric_parameters(key, value):
    values = valid_mapping()
    values[key] = value

    with pytest.raises(ValueError):
        PinkyProAdapter.from_mapping(values)


@pytest.mark.parametrize("motor_ids", ([1], [1, 1], [1, "2"], [True, 2]))
def test_adapter_rejects_invalid_motor_identity(motor_ids):
    values = valid_mapping()
    values["motor_ids"] = motor_ids

    with pytest.raises(ValueError):
        PinkyProAdapter.from_mapping(values)
