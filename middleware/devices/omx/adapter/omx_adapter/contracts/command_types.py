"""ROS-free validated command types shared by the single OMX command owner."""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol

from ..final_state import normalize_final_state_errors
from .manipulation_plan import JointTrajectoryPoint


KNOWN_OWNERS = frozenset({"leader_teleop", "moveit", "rule_based", "learned_policy", "pilot_sim"})


def _positive_finite(name: str, value: object) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return number


def _nonempty(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ArmCommandConfig:
    """Explicit command policy; disabled and unconfigured by default."""

    enabled: bool = False
    workcell_id: str = ""
    instance_id: str = ""
    joint_names: tuple[str, ...] = ()
    position_limits: Mapping[str, tuple[float, float]] | None = None
    velocity_limits: Mapping[str, float] | None = None
    acceleration_limits: Mapping[str, float] | None = None
    max_start_state_tolerances: Mapping[str, float] | None = None
    max_final_state_errors: Mapping[str, float | None] | None = None  # D-785, final_state.py
    allowed_owners: tuple[str, ...] = ()
    calibration_revision: str = ""
    max_joint_state_age_s: float = 0.5
    max_goal_duration_s: float = 1.0
    action_timeout_s: float = 2.0
    # Set only when the owner clock is simulation time (C3b A3): the wall clock then bounds
    # joint-state age and action time at this factor x the sim limits, so a frozen or
    # crawling simulation still HOLDs. None = the owner clock is already a wall clock.
    wall_clock_bound_factor: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be boolean")
        if not self.enabled:
            return
        _nonempty("workcell_id", self.workcell_id)
        _nonempty("instance_id", self.instance_id)
        _nonempty("calibration_revision", self.calibration_revision)
        names = tuple(self.joint_names)
        if not names or any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError("enabled command policy requires joint_names")
        if len(set(names)) != len(names):
            raise ValueError("joint_names must be unique")
        limits = dict(self.position_limits or {})
        if set(limits) != set(names):
            raise ValueError("position_limits must exactly match joint_names")
        normalized: dict[str, tuple[float, float]] = {}
        for name in names:
            try:
                lower, upper = limits[name]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"position limit for {name} must contain lower and upper bounds") from exc
            if isinstance(lower, bool) or isinstance(upper, bool):
                raise ValueError(f"position limit for {name} must be finite and increasing")
            values = (float(lower), float(upper))
            if not all(math.isfinite(value) for value in values) or values[0] >= values[1]:
                raise ValueError(f"position limit for {name} must be finite and increasing")
            normalized[name] = values
        object.__setattr__(self, "joint_names", names)
        object.__setattr__(self, "position_limits", MappingProxyType(normalized))
        for field_name in ("velocity_limits", "acceleration_limits"):
            configured = getattr(self, field_name)
            if configured is None:
                continue
            limits = dict(configured)
            if set(limits) != set(names):
                raise ValueError(f"{field_name} must exactly match joint_names")
            checked = {
                name: _positive_finite(f"{field_name}[{name}]", limits[name])
                for name in names
            }
            object.__setattr__(self, field_name, MappingProxyType(checked))
        if self.max_start_state_tolerances is not None:
            configured_tolerances = dict(self.max_start_state_tolerances)
            if set(configured_tolerances) != set(names):
                raise ValueError("max_start_state_tolerances must exactly match joint_names")
            checked_tolerances: dict[str, float] = {}
            for name in names:
                value = configured_tolerances[name]
                if isinstance(value, bool):
                    raise ValueError(f"max_start_state_tolerances[{name}] must be finite and non-negative")
                try:
                    value = float(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"max_start_state_tolerances[{name}] must be finite and non-negative"
                    ) from exc
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"max_start_state_tolerances[{name}] must be finite and non-negative")
                checked_tolerances[name] = value
            object.__setattr__(self, "max_start_state_tolerances", MappingProxyType(checked_tolerances))
        owners = tuple(self.allowed_owners)
        if not owners or len(set(owners)) != len(owners) or not set(owners) <= KNOWN_OWNERS:
            raise ValueError("allowed_owners must be a non-empty unique subset of known owners")
        object.__setattr__(self, "allowed_owners", owners)
        final_errors = normalize_final_state_errors(names, self.max_final_state_errors)
        object.__setattr__(self, "max_final_state_errors", final_errors)
        for limit in ("max_joint_state_age_s", "max_goal_duration_s", "action_timeout_s"):
            object.__setattr__(self, limit, _positive_finite(limit, getattr(self, limit)))
        if self.action_timeout_s < self.max_goal_duration_s:
            raise ValueError("action_timeout_s must be at least max_goal_duration_s")
        if self.wall_clock_bound_factor is not None:
            factor = self.wall_clock_bound_factor
            if (isinstance(factor, bool) or not isinstance(factor, (int, float))
                    or not math.isfinite(factor) or factor < 1.0):
                raise ValueError("wall_clock_bound_factor must be a finite number >= 1")
            object.__setattr__(self, "wall_clock_bound_factor", float(factor))


@dataclass(frozen=True)
class JointStateSnapshot:
    positions: Mapping[str, float]
    sequence: int
    received_at: float
    calibration_revision: str
    # Raw intake clock values; not UTC or an authenticated clock identity.
    source_stamp_ns: int | None = None
    source_now_ns: int | None = None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("joint-state sequence must be a non-negative integer")
        try:
            received_at = float(self.received_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("joint-state receive time must be finite monotonic time") from exc
        if isinstance(self.received_at, bool) or not math.isfinite(received_at):
            raise ValueError("joint-state receive time must be finite monotonic time")
        object.__setattr__(self, "received_at", received_at)
        normalized = dict(self.positions)
        for name, value in normalized.items():
            if not isinstance(name, str) or not name.strip() or isinstance(value, bool):
                raise ValueError("joint-state positions must be named finite numbers")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("joint-state positions must be named finite numbers") from exc
            if not math.isfinite(number):
                raise ValueError("joint-state positions must be named finite numbers")
            normalized[name] = number
        object.__setattr__(self, "positions", MappingProxyType(normalized))
        _nonempty("calibration_revision", self.calibration_revision)
        if self.source_stamp_ns is not None or self.source_now_ns is not None:
            if (type(self.source_stamp_ns) is not int or type(self.source_now_ns) is not int
                    or not 0 < self.source_stamp_ns <= self.source_now_ns):
                raise ValueError("joint-state source metadata requires a positive ordered integer pair")


@dataclass(frozen=True)
class TrajectoryCommand:
    workcell_id: str
    instance_id: str
    command_id: str
    session_id: str
    owner: str
    positions: Mapping[str, float]
    duration_s: float
    source_state_sequence: int
    calibration_revision: str
    joint_names: tuple[str, ...] | None = None
    trajectory_points: tuple[JointTrajectoryPoint, ...] | None = None
    phase_id: str | None = None
    # Expected start positions and tolerances for every commanded joint (main b0979ad6 +
    # C3b A1). When set, the owner checks them against its own newest fresh joint state under
    # its lock, caps each tolerance at config.max_start_state_tolerances, and binds the
    # dispatch to that state's sequence; source_state_sequence is then the caller's observed
    # state, which may be older but never newer.
    expected_start_state_positions: Mapping[str, float] | None = None
    start_state_tolerances: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "workcell_id", "instance_id", "command_id", "session_id", "owner", "calibration_revision"
        ):
            _nonempty(field_name, getattr(self, field_name))
        if self.phase_id is not None:
            _nonempty("phase_id", self.phase_id)
        if type(self.source_state_sequence) is not int or self.source_state_sequence < 0:
            raise ValueError("source_state_sequence must be a non-negative integer")
        normalized = dict(self.positions)
        for name, value in normalized.items():
            if not isinstance(name, str) or not name.strip() or isinstance(value, bool):
                raise ValueError("command positions must be named finite numbers")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("command positions must be named finite numbers") from exc
            if not math.isfinite(number):
                raise ValueError("command positions must be named finite numbers")
            normalized[name] = number
        object.__setattr__(self, "positions", MappingProxyType(normalized))
        duration = _positive_finite("duration_s", self.duration_s)
        object.__setattr__(self, "duration_s", duration)
        names = tuple(normalized) if self.joint_names is None else tuple(self.joint_names)
        if (not names or any(not isinstance(name, str) or not name or name != name.strip()
                             for name in names) or len(set(names)) != len(names)):
            raise ValueError("joint_names must be non-empty, trimmed, and unique")
        if set(names) != set(normalized):
            raise ValueError("joint_names must exactly match command positions")
        object.__setattr__(self, "joint_names", names)
        expected_start = self.expected_start_state_positions
        tolerances = self.start_state_tolerances
        if (expected_start is None) != (tolerances is None):
            raise ValueError("expected start positions and tolerances must be provided together")
        if expected_start is not None and tolerances is not None:
            expected_start = dict(expected_start)
            tolerances = dict(tolerances)
            if set(expected_start) != set(names) or set(tolerances) != set(names):
                raise ValueError("start-state positions and tolerances must match joint_names")
            for name in names:
                expected_value = expected_start[name]
                tolerance = tolerances[name]
                if isinstance(expected_value, bool) or isinstance(tolerance, bool):
                    raise ValueError("start-state positions and tolerances must be finite numbers")
                try:
                    expected_value = float(expected_value)
                    tolerance = float(tolerance)
                except (TypeError, ValueError) as exc:
                    raise ValueError("start-state positions and tolerances must be finite numbers") from exc
                if not math.isfinite(expected_value) or not math.isfinite(tolerance) or tolerance < 0:
                    raise ValueError("start-state positions and tolerances must be finite numbers")
                expected_start[name] = expected_value
                tolerances[name] = tolerance
            object.__setattr__(self, "expected_start_state_positions", MappingProxyType(expected_start))
            object.__setattr__(self, "start_state_tolerances", MappingProxyType(tolerances))
        points = self.trajectory_points
        if points is None:
            points = (JointTrajectoryPoint(
                time_from_start_s=duration,
                positions=tuple(normalized[name] for name in names),
            ),)
        else:
            points = tuple(points)
        if not points or any(not isinstance(point, JointTrajectoryPoint) for point in points):
            raise ValueError("trajectory_points must contain timed joint trajectory points")
        if any(len(point.positions) != len(names)
               or (point.velocities is not None and len(point.velocities) != len(names))
               or (point.accelerations is not None and len(point.accelerations) != len(names))
               for point in points):
            raise ValueError("trajectory point dimensions must match joint_names")
        if any(left.time_from_start_s >= right.time_from_start_s
               for left, right in zip(points, points[1:])):
            raise ValueError("trajectory point times must be strictly increasing")
        if not math.isclose(points[-1].time_from_start_s, duration, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("duration_s must equal the final trajectory point time")
        final_positions = dict(zip(names, points[-1].positions))
        if final_positions != dict(normalized):
            raise ValueError("command positions must match the final trajectory point")
        object.__setattr__(self, "trajectory_points", points)


class ActionHandle(Protocol):
    def cancel(self) -> object: ...
    def done(self) -> bool: ...
    def succeeded(self) -> bool: ...


class ActionPort(Protocol):
    def send_goal(self, command: TrajectoryCommand) -> ActionHandle: ...


@dataclass(frozen=True)
class CommandDecision:
    accepted: bool
    state: str
    reason: str
    command_id: str | None = None
    cancel_outcome: str | None = None
