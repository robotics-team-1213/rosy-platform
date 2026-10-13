"""Explicit, ROS-independent differential-drive motor command contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import math
from typing import Any


def _finite_number(name: str, value: Any) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{name} must be a finite number') from error
    if not math.isfinite(converted):
        raise ValueError(f'{name} must be a finite number')
    return converted


def _positive_finite(name: str, value: Any) -> float:
    try:
        converted = _finite_number(name, value)
    except ValueError as error:
        raise ValueError(f'{name} must be a positive finite number') from error
    if converted <= 0:
        raise ValueError(f'{name} must be a positive finite number')
    return converted


@dataclass(frozen=True)
class DriveGeometry:
    """Physical dimensions used for differential-drive kinematics."""

    wheel_radius_m: float
    wheel_separation_m: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            'wheel_radius_m',
            _positive_finite('wheel_radius_m', self.wheel_radius_m),
        )
        object.__setattr__(
            self,
            'wheel_separation_m',
            _positive_finite('wheel_separation_m', self.wheel_separation_m),
        )


@dataclass(frozen=True)
class DriveLimits:
    """Independent velocity limits enforced before a UART write is attempted."""

    max_linear_mps: float
    max_angular_rps: float
    max_wheel_rpm: float

    def __post_init__(self) -> None:
        for name in ('max_linear_mps', 'max_angular_rps', 'max_wheel_rpm'):
            object.__setattr__(self, name, _positive_finite(name, getattr(self, name)))


@dataclass(frozen=True)
class MotorCommandPlan:
    """A validated, bounded command ready for the two-motor driver."""

    requested_linear_mps: float
    requested_angular_rps: float
    applied_linear_mps: float
    applied_angular_rps: float
    left_rpm: float
    right_rpm: float
    limit_reasons: tuple[str, ...]

    @property
    def limited(self) -> bool:
        return bool(self.limit_reasons)

    @property
    def is_stop(self) -> bool:
        return self.left_rpm == 0.0 and self.right_rpm == 0.0


class CommandStatus(str, Enum):
    """Observable result of one requested motor action."""

    APPLIED = 'APPLIED'
    LIMITED = 'LIMITED'
    REJECTED = 'REJECTED'
    DRIVER_ERROR = 'DRIVER_ERROR'


@dataclass(frozen=True)
class MotorCommandOutcome:
    """Structured command result suitable for logs and diagnostics."""

    status: CommandStatus
    reason: str
    plan: MotorCommandPlan | None = None

    @property
    def accepted(self) -> bool:
        return self.status in {CommandStatus.APPLIED, CommandStatus.LIMITED}


def _clamp(value: float, maximum: float) -> float:
    return max(-maximum, min(maximum, value))


def plan_twist(
    linear_mps: Any,
    angular_rps: Any,
    geometry: DriveGeometry,
    limits: DriveLimits,
) -> MotorCommandPlan:
    """Validate and convert a body twist into bounded mounted-motor RPM."""
    requested_linear = _finite_number('linear_mps', linear_mps)
    requested_angular = _finite_number('angular_rps', angular_rps)
    applied_linear = _clamp(requested_linear, limits.max_linear_mps)
    applied_angular = _clamp(requested_angular, limits.max_angular_rps)
    reasons: list[str] = []
    if applied_linear != requested_linear:
        reasons.append('linear speed limited')
    if applied_angular != requested_angular:
        reasons.append('angular speed limited')

    left_mps = applied_linear - applied_angular * geometry.wheel_separation_m / 2.0
    right_mps = applied_linear + applied_angular * geometry.wheel_separation_m / 2.0
    rpm_scale = 60.0 / (2.0 * math.pi * geometry.wheel_radius_m)
    left_rpm = left_mps * rpm_scale
    # The right DYNAMIXEL is mounted in the opposite direction.
    right_rpm = -right_mps * rpm_scale

    peak_rpm = max(abs(left_rpm), abs(right_rpm))
    if peak_rpm > limits.max_wheel_rpm:
        scale = limits.max_wheel_rpm / peak_rpm
        left_rpm *= scale
        right_rpm *= scale
        applied_linear *= scale
        applied_angular *= scale
        reasons.append('wheel RPM limited')

    return MotorCommandPlan(
        requested_linear_mps=requested_linear,
        requested_angular_rps=requested_angular,
        applied_linear_mps=applied_linear,
        applied_angular_rps=applied_angular,
        left_rpm=left_rpm,
        right_rpm=right_rpm,
        limit_reasons=tuple(reasons),
    )


class MotorController:
    """Plan and execute bounded wheel commands through a small driver sink."""

    def __init__(
        self,
        geometry: DriveGeometry,
        limits: DriveLimits,
        write_wheel_rpm: Callable[[float, float], bool],
    ) -> None:
        if not callable(write_wheel_rpm):
            raise TypeError('write_wheel_rpm must be callable')
        self.geometry = geometry
        self.limits = limits
        self._write_wheel_rpm = write_wheel_rpm

    def command_twist(self, linear_mps: Any, angular_rps: Any) -> MotorCommandOutcome:
        try:
            plan = plan_twist(linear_mps, angular_rps, self.geometry, self.limits)
        except ValueError as error:
            return MotorCommandOutcome(CommandStatus.REJECTED, str(error))

        if plan.limited:
            status = CommandStatus.LIMITED
            reason = '; '.join(plan.limit_reasons)
        else:
            status = CommandStatus.APPLIED
            reason = 'command applied'
        return self._execute(plan, status, reason)

    def stop(self) -> MotorCommandOutcome:
        plan = plan_twist(0.0, 0.0, self.geometry, self.limits)
        return self._execute(plan, CommandStatus.APPLIED, 'stop applied')

    def _execute(
        self,
        plan: MotorCommandPlan,
        success_status: CommandStatus,
        success_reason: str,
    ) -> MotorCommandOutcome:
        try:
            accepted = bool(self._write_wheel_rpm(plan.left_rpm, plan.right_rpm))
        except Exception as error:
            return MotorCommandOutcome(
                CommandStatus.DRIVER_ERROR,
                f'motor driver error: {error}',
                plan,
            )
        if not accepted:
            return MotorCommandOutcome(
                CommandStatus.DRIVER_ERROR,
                'motor driver rejected wheel RPM',
                plan,
            )
        return MotorCommandOutcome(success_status, success_reason, plan)
