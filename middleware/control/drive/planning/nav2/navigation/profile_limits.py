"""Device-profile motion limits shared by hardware launch and Nav2.

The profile is data owned by the Device deployment.  This module keeps the
launch-time check ROS-free so a malformed profile or an unsafe Nav2 parameter
cannot reach the hardware graph.  It does not change limits dynamically or
touch a device.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


def _positive(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return number


@dataclass(frozen=True)
class MotionLimits:
    """Measured profile ceilings used by the base and Nav2."""

    max_linear_mps: float
    max_angular_rps: float

    @classmethod
    def from_mapping(cls, profile: Mapping[str, Any]) -> "MotionLimits":
        try:
            linear = profile["max_linear_velocity"]
            angular = profile["max_angular_velocity"]
        except KeyError as exc:
            raise ValueError(f"profile is missing {exc.args[0]}") from exc
        return cls(
            max_linear_mps=_positive("max_linear_velocity", linear),
            max_angular_rps=_positive("max_angular_velocity", angular),
        )


def load_motion_limits(path: str | Path) -> MotionLimits:
    """Load ``profile.max_*_velocity`` from a Device profile YAML file."""

    profile_path = Path(path)
    try:
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ValueError(f"cannot read Device profile: {profile_path}") from exc
    if not isinstance(data, Mapping):
        raise ValueError("Device profile must be a YAML mapping")
    profile = data.get("profile", data)
    if not isinstance(profile, Mapping):
        raise ValueError("Device profile.profile must be a YAML mapping")
    return MotionLimits.from_mapping(profile)


def validate_requested_limits(
    limits: MotionLimits,
    *,
    max_linear_mps: Any,
    max_angular_rps: Any,
) -> None:
    """Reject launch overrides above the selected Device profile ceiling."""

    requested_linear = _positive("max_linear_mps", max_linear_mps)
    requested_angular = _positive("max_angular_rps", max_angular_rps)
    if requested_linear > limits.max_linear_mps:
        raise ValueError(
            "max_linear_mps exceeds Device profile ceiling "
            f"{limits.max_linear_mps:g}"
        )
    if requested_angular > limits.max_angular_rps:
        raise ValueError(
            "max_angular_rps exceeds Device profile ceiling "
            f"{limits.max_angular_rps:g}"
        )


def _params(data: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    current: Any = data
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return {}
        current = current[key]
    return current if isinstance(current, Mapping) else {}


def _bounded(name: str, value: Any, ceiling: float) -> None:
    number = _positive(name, value)
    if number > ceiling:
        raise ValueError(f"{name} exceeds Device profile ceiling {ceiling:g}")


def _bounded_vector(
    name: str,
    value: Any,
    indexes: tuple[int, ...],
    ceilings: tuple[float, ...],
) -> None:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a numeric vector")
    for index, ceiling in zip(indexes, ceilings):
        if index >= len(value):
            raise ValueError(f"{name} is missing index {index}")
        number = value[index]
        if isinstance(number, bool):
            raise ValueError(f"{name}[{index}] must be numeric")
        try:
            magnitude = abs(float(number))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}[{index}] must be numeric") from exc
        if not math.isfinite(magnitude) or magnitude > ceiling:
            raise ValueError(f"{name}[{index}] exceeds Device profile ceiling {ceiling:g}")


def validate_nav2_parameters(path: str | Path, limits: MotionLimits) -> None:
    """Validate velocity-bearing Nav2 parameters against profile ceilings."""

    params_path = Path(path)
    try:
        data = yaml.safe_load(params_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ValueError(f"cannot read Nav2 parameter file: {params_path}") from exc
    if not isinstance(data, Mapping):
        raise ValueError("Nav2 parameters must be a YAML mapping")

    controller = _params(data, "controller_server", "ros__parameters", "FollowPath")
    if controller:
        _bounded(
            "FollowPath.desired_linear_vel",
            controller.get("desired_linear_vel", limits.max_linear_mps),
            limits.max_linear_mps,
        )
        _bounded(
            "FollowPath.rotate_to_heading_angular_vel",
            controller.get("rotate_to_heading_angular_vel", limits.max_angular_rps),
            limits.max_angular_rps,
        )
        _bounded(
            "FollowPath.min_approach_linear_velocity",
            controller.get("min_approach_linear_velocity", limits.max_linear_mps),
            limits.max_linear_mps,
        )

    behavior = _params(data, "behavior_server", "ros__parameters")
    if behavior:
        _bounded(
            "behavior_server.max_rotational_vel",
            behavior.get("max_rotational_vel", limits.max_angular_rps),
            limits.max_angular_rps,
        )

    smoother = _params(data, "velocity_smoother", "ros__parameters")
    if smoother:
        _bounded_vector(
            "velocity_smoother.max_velocity",
            smoother.get("max_velocity", [limits.max_linear_mps, 0.0, limits.max_angular_rps]),
            (0, 2),
            (limits.max_linear_mps, limits.max_angular_rps),
        )
        _bounded_vector(
            "velocity_smoother.min_velocity",
            smoother.get("min_velocity", [-limits.max_linear_mps, 0.0, -limits.max_angular_rps]),
            (0, 2),
            (limits.max_linear_mps, limits.max_angular_rps),
        )
