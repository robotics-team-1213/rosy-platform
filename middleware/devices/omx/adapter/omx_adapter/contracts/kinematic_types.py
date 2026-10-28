"""Kinematic value declarations; geometry loading and the solver remain device-owned."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping


ARM_JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5")

IK_OK = "OK"
IK_OUTSIDE_WORKSPACE = "OUTSIDE_WORKSPACE"
IK_SINGULAR = "SINGULAR"
IK_UNREACHABLE = "UNREACHABLE"
IK_JOINT_LIMIT = "JOINT_LIMIT"
IK_YAW_LIMIT = "YAW_LIMIT"

Matrix = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]


def _finite(name: str, value: object) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _triple(name: str, value: object) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must contain 3 values")
    return tuple(_finite(name, item) for item in value)  # type: ignore[return-value]


@dataclass(frozen=True)
class ChainJoint:
    name: str
    joint_type: str
    xyz: tuple[float, float, float]
    rpy: tuple[float, float, float]
    axis: tuple[float, float, float] | None


@dataclass(frozen=True)
class TopDownPose:
    """Base-frame TCP target with the tool axis along -z_base."""

    x: float
    y: float
    z: float
    yaw: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "z", "yaw"):
            object.__setattr__(self, name, _finite(name, getattr(self, name)))


@dataclass(frozen=True)
class TcpPose:
    """FK result: TCP position, top-down yaw, and the tool-axis deviation from -z_base."""

    x: float
    y: float
    z: float
    yaw: float
    tool_down_error_rad: float
    rotation: Matrix


@dataclass(frozen=True)
class IkLimits:
    """Protective constraints supplied by the planning profile (never the URDF)."""

    position_limits: Mapping[str, tuple[float, float]]
    workspace_min_m: tuple[float, float, float]
    workspace_max_m: tuple[float, float, float]
    singularity_radius_m: float

    def __post_init__(self) -> None:
        if set(self.position_limits) != set(ARM_JOINTS):
            raise ValueError("IK limits must cover exactly joint1..joint5")
        for name, (lower, upper) in self.position_limits.items():
            if not (_finite(name, lower) < _finite(name, upper)):
                raise ValueError(f"position limit for {name} must be increasing")
        low = _triple("workspace_min_m", self.workspace_min_m)
        high = _triple("workspace_max_m", self.workspace_max_m)
        if any(a >= b for a, b in zip(low, high)):
            raise ValueError("workspace bounds must be increasing")
        if _finite("singularity_radius_m", self.singularity_radius_m) <= 0:
            raise ValueError("singularity_radius_m must be positive")


@dataclass(frozen=True)
class IkResult:
    reason: str
    joints: tuple[float, float, float, float, float] | None = None
    yaw: float | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.reason == IK_OK
