"""Pinky Pro hardware adapter parameter boundary.

The ROS node and the Dynamixel SDK remain the execution path for the current
robot.  This module owns the board-specific parameter contract so that launch
files and a future ``ros2_control`` backend can consume the same values without
opening a device during validation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping


DEFAULTS = {
    "wheel_radius": 0.027,
    "wheel_separation": 0.0961,
    "cmd_vel_timeout_s": 0.5,
    "frame_prefix": "",
    "motor_device": "/dev/ttyAMA4",
    "motor_baudrate": 1_000_000,
    "motor_ids": (1, 2),
    "max_linear_mps": 0.20,
    "max_angular_rps": 0.80,
    "max_wheel_rpm": 100.0,
    "motor_profile_acceleration": 200,
}


def _finite_positive(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return number


def _integer(name: str, value: Any, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _motor_ids(value: Any) -> tuple[int, int]:
    try:
        ids = tuple(value)
    except TypeError as exc:
        raise ValueError("motor_ids must contain two distinct integer IDs") from exc
    if len(ids) != 2 or any(
        isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 252
        for item in ids
    ) or ids[0] == ids[1]:
        raise ValueError("motor_ids must contain two distinct integer IDs from 0 through 252")
    return ids  # type: ignore[return-value]


@dataclass(frozen=True)
class PinkyProAdapter:
    """Validated Pinky Pro ROS parameter set.

    Validation is deliberately ROS- and SDK-free.  A successful construction
    proves only that the parameter contract is valid; it never probes UART or
    enables motor torque.
    """

    parameters: Mapping[str, Any]
    model: str = "pinky_pro"

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "PinkyProAdapter":
        merged = dict(DEFAULTS)
        merged.update(values)
        motor_device = merged["motor_device"]
        if not isinstance(motor_device, str) or not motor_device.startswith("/dev/"):
            raise ValueError("motor_device must be an absolute /dev path")
        frame_prefix = merged["frame_prefix"]
        if not isinstance(frame_prefix, str):
            raise ValueError("frame_prefix must be a string")

        normalized = {
            "wheel_radius": _finite_positive("wheel_radius", merged["wheel_radius"]),
            "wheel_separation": _finite_positive(
                "wheel_separation", merged["wheel_separation"]
            ),
            "cmd_vel_timeout_s": _finite_positive(
                "cmd_vel_timeout_s", merged["cmd_vel_timeout_s"]
            ),
            "frame_prefix": frame_prefix,
            "motor_device": motor_device,
            "motor_baudrate": _integer("motor_baudrate", merged["motor_baudrate"]),
            "motor_ids": _motor_ids(merged["motor_ids"]),
            "max_linear_mps": _finite_positive(
                "max_linear_mps", merged["max_linear_mps"]
            ),
            "max_angular_rps": _finite_positive(
                "max_angular_rps", merged["max_angular_rps"]
            ),
            "max_wheel_rpm": _finite_positive(
                "max_wheel_rpm", merged["max_wheel_rpm"]
            ),
            "motor_profile_acceleration": _integer(
                "motor_profile_acceleration", merged["motor_profile_acceleration"]
            ),
        }
        if normalized["motor_profile_acceleration"] > 32767:
            raise ValueError("motor_profile_acceleration must be <= 32767")
        return cls(parameters=normalized)

    def ros_parameters(self) -> dict[str, Any]:
        """Return a copy suitable for a ROS launch ``parameters`` mapping."""
        return dict(self.parameters)
