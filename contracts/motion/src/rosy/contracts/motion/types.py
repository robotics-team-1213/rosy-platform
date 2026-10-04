"""D-442(a) semantic shapes; constructing a type never authorizes execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import math
from types import MappingProxyType
from typing import Protocol

from rosy.contracts.skill import AttemptIdentity


def _identifier(value, name):
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{name} must be a nonempty trimmed identifier")
    return value


def _number(value, name, *, minimum=None):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or (minimum is not None and value < minimum)):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _vector(values, count, name):
    if not isinstance(values, (tuple, list)) or len(values) != count:
        raise ValueError(f"{name} must have {count} values")
    return tuple(_number(value, name) for value in values)


def _map(values, name, *, minimum=None):
    if not isinstance(values, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return MappingProxyType({_identifier(key, name): _number(value, name, minimum=minimum)
                             for key, value in values.items()})


class MotionKind(str, Enum):
    BASE_TWIST = "base.twist"
    BASE_POSE_GOAL = "base.pose_goal"
    BASE_PATH_FOLLOW = "base.path_follow"
    ARM_JOINT_TRAJECTORY = "arm.joint_trajectory"
    ARM_TCP_POSE = "arm.tcp_pose"
    ARM_GRIPPER = "arm.gripper"


class PriorityClass(str, Enum):
    EMERGENCY = "EMERGENCY"
    SAFETY = "SAFETY"
    MANUAL = "MANUAL"
    DOCKING = "DOCKING"
    NAVIGATION = "NAVIGATION"
    SKILL = "SKILL"
    POLICY = "POLICY"
    FLEET = "FLEET"
    IDLE = "IDLE"


@dataclass(frozen=True)
class MotionHeader:
    intent_id: str
    device_id: str
    source: str
    priority_class: PriorityClass
    issued_at: float
    valid_for_s: float
    attempt: AttemptIdentity | None = None
    correlation_id: str | None = None
    envelope_ref: str | None = None
    state_sequence: int | None = None
    calibration_revision: str | None = None
    limits: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("intent_id", "device_id", "source"):
            _identifier(getattr(self, name), name)
        for name in ("correlation_id", "envelope_ref", "calibration_revision"):
            if getattr(self, name) is not None:
                _identifier(getattr(self, name), name)
        object.__setattr__(self, "priority_class", PriorityClass(self.priority_class))
        issued = _number(self.issued_at, "issued_at", minimum=0)
        validity = _number(self.valid_for_s, "valid_for_s", minimum=0)
        if validity == 0 or not math.isfinite(issued + validity):
            raise ValueError("valid_for_s must be positive with a finite deadline")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "valid_for_s", validity)
        if self.state_sequence is not None and (type(self.state_sequence) is not int or self.state_sequence < 0):
            raise ValueError("state_sequence must be a nonnegative integer")
        if self.attempt is not None:
            if type(self.attempt) is not AttemptIdentity or self.attempt.instance_id != self.device_id:
                raise ValueError("attempt identity must name the same device")
        allowed = {"linear_mps", "angular_radps", "joint_velocity_radps", "joint_acceleration_radps2"}
        limits = _map(self.limits, "limits", minimum=0)
        if not set(limits) <= allowed:
            raise ValueError("limits must name semantic SI maxima")
        object.__setattr__(self, "limits", limits)

    @property
    def attempt_id(self):
        return None if self.attempt is None else self.attempt.attempt_id

    def is_valid_at(self, now):
        now = _number(now, "now", minimum=0)
        return self.issued_at <= now < self.issued_at + self.valid_for_s


@dataclass(frozen=True)
class BaseTwist:
    linear_mps: float
    angular_radps: float
    frame: str = field(default="base_link", init=False)

    def __post_init__(self):
        for name in ("linear_mps", "angular_radps"):
            object.__setattr__(self, name, _number(getattr(self, name), name))


@dataclass(frozen=True)
class BasePoseGoal:
    x_m: float
    y_m: float
    yaw_rad: float
    position_tolerance_m: float
    yaw_tolerance_rad: float
    frame: str = "map"

    def __post_init__(self):
        _identifier(self.frame, "frame")
        for name in ("x_m", "y_m", "yaw_rad", "position_tolerance_m", "yaw_tolerance_rad"):
            minimum = 0 if "tolerance" in name else None
            object.__setattr__(self, name, _number(getattr(self, name), name, minimum=minimum))


@dataclass(frozen=True)
class BasePathFollow:
    path_ref: str
    direction: str
    frame: str = "map"

    def __post_init__(self):
        _identifier(self.path_ref, "path_ref")
        _identifier(self.frame, "frame")
        if self.direction not in {"forward", "reverse"}:
            raise ValueError("direction must be forward or reverse")


@dataclass(frozen=True)
class TrajectoryPoint:
    time_from_start_s: float
    positions: tuple[float, ...]
    velocities: tuple[float, ...] | None = None
    accelerations: tuple[float, ...] | None = None

    def __post_init__(self):
        time = _number(self.time_from_start_s, "time_from_start_s", minimum=0)
        if time == 0 or not isinstance(self.positions, (tuple, list)) or not self.positions:
            raise ValueError("trajectory point needs positive time and positions")
        object.__setattr__(self, "time_from_start_s", time)
        count = len(self.positions)
        for name in ("positions", "velocities", "accelerations"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _vector(getattr(self, name), count, name))


@dataclass(frozen=True)
class ArmJointTrajectory:
    workcell_id: str
    session_id: str
    positions: Mapping[str, float]
    duration_s: float
    joint_names: tuple[str, ...] | None = None
    trajectory_points: tuple[TrajectoryPoint, ...] | None = None
    phase_id: str | None = None
    expected_start_state_positions: Mapping[str, float] | None = None
    start_state_tolerances: Mapping[str, float] | None = None

    def __post_init__(self):
        for name in ("workcell_id", "session_id"):
            _identifier(getattr(self, name), name)
        if self.phase_id is not None:
            _identifier(self.phase_id, "phase_id")
        positions = _map(self.positions, "positions")
        duration = _number(self.duration_s, "duration_s", minimum=0)
        if not positions or duration == 0:
            raise ValueError("trajectory needs positions and positive duration")
        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "duration_s", duration)
        names = tuple(positions) if self.joint_names is None else tuple(self.joint_names)
        if len(names) != len(set(names)) or set(names) != set(positions):
            raise ValueError("joint_names must match positions")
        if self.joint_names is not None:
            object.__setattr__(self, "joint_names", names)
        if (self.expected_start_state_positions is None) != (self.start_state_tolerances is None):
            raise ValueError("expected start positions and tolerances must be supplied together")
        for name in ("expected_start_state_positions", "start_state_tolerances"):
            value = getattr(self, name)
            if value is not None:
                value = _map(value, name, minimum=0 if name == "start_state_tolerances" else None)
                if set(value) != set(names):
                    raise ValueError("start-state maps must match joint_names")
                object.__setattr__(self, name, value)
        if self.trajectory_points is not None:
            points = tuple(self.trajectory_points)
            if (not points or any(type(point) is not TrajectoryPoint or len(point.positions) != len(names)
                                  for point in points)):
                raise ValueError("trajectory point dimensions must match joints")
            if any(left.time_from_start_s >= right.time_from_start_s for left, right in zip(points, points[1:])):
                raise ValueError("trajectory point times must increase")
            if (not math.isclose(points[-1].time_from_start_s, duration, rel_tol=0.0, abs_tol=1e-9)
                    or points[-1].positions != tuple(positions[name] for name in names)):
                raise ValueError("final trajectory point must match duration and positions")
            object.__setattr__(self, "trajectory_points", points)


@dataclass(frozen=True)
class ArmTcpPose:
    position_m: tuple[float, float, float]
    orientation_xyzw: tuple[float, float, float, float]
    approach_direction: tuple[float, float, float]
    frame: str

    def __post_init__(self):
        _identifier(self.frame, "frame")
        for name, count in (("position_m", 3), ("orientation_xyzw", 4), ("approach_direction", 3)):
            object.__setattr__(self, name, _vector(getattr(self, name), count, name))
        if not any(self.orientation_xyzw) or not any(self.approach_direction):
            raise ValueError("orientation and approach direction must be nonzero")


@dataclass(frozen=True)
class ArmGripper:
    joint_name: str
    position_rad: float
    semantic: str | None = None

    def __post_init__(self):
        _identifier(self.joint_name, "joint_name")
        object.__setattr__(self, "position_rad", _number(self.position_rad, "position_rad"))
        if self.semantic not in {None, "open", "close"}:
            raise ValueError("gripper semantic must be open or close")


_PAYLOADS = {MotionKind.BASE_TWIST: BaseTwist, MotionKind.BASE_POSE_GOAL: BasePoseGoal,
             MotionKind.BASE_PATH_FOLLOW: BasePathFollow, MotionKind.ARM_JOINT_TRAJECTORY: ArmJointTrajectory,
             MotionKind.ARM_TCP_POSE: ArmTcpPose, MotionKind.ARM_GRIPPER: ArmGripper}
_SERVO = {MotionKind.BASE_TWIST, MotionKind.ARM_JOINT_TRAJECTORY, MotionKind.ARM_GRIPPER}


@dataclass(frozen=True)
class MotionIntent:
    kind: MotionKind
    header: MotionHeader
    payload: BaseTwist | BasePoseGoal | BasePathFollow | ArmJointTrajectory | ArmTcpPose | ArmGripper

    def __post_init__(self):
        object.__setattr__(self, "kind", MotionKind(self.kind))
        if type(self.header) is not MotionHeader or type(self.payload) is not _PAYLOADS[self.kind]:
            raise ValueError("kind, header and payload types must agree")
        if self.header.priority_class is PriorityClass.POLICY and self.header.envelope_ref is None:
            raise ValueError("POLICY shape requires an envelope reference, not execution authority")
        if self.kind.value.startswith("arm."):
            if self.header.state_sequence is None or self.header.calibration_revision is None:
                raise ValueError("arm intent requires state sequence and calibration")
            if (self.header.attempt is not None and isinstance(self.payload, ArmJointTrajectory)
                    and self.header.attempt.workcell_id != self.payload.workcell_id):
                raise ValueError("attempt and trajectory must name the same workcell")

    @property
    def phase(self):
        return "servo" if self.kind in _SERVO else "goal"


@dataclass(frozen=True)
class GuardedMotion:
    """Original-object admission remains the binding's job, beyond this shape."""
    payload: BaseTwist | ArmJointTrajectory | ArmGripper
    guard_revision: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self):
        if type(self.payload) not in (BaseTwist, ArmJointTrajectory, ArmGripper):
            raise ValueError("guarded payload must be servo-shaped")
        _identifier(self.guard_revision, "guard_revision")


def _port_state(value):
    if value not in {"disabled", "ready", "active", "hold"}:
        raise ValueError("port state must be disabled, ready, active or hold")


@dataclass(frozen=True)
class PortDecision:
    accepted: bool
    state: str
    reason: str
    intent_id: str | None = None

    def __post_init__(self):
        if type(self.accepted) is not bool:
            raise ValueError("accepted must be boolean")
        _port_state(self.state)
        _identifier(self.reason, "reason")
        if self.intent_id is not None:
            _identifier(self.intent_id, "intent_id")


@dataclass(frozen=True)
class PortState:
    state: str
    active_intent_id: str | None = None
    readback_sequence: int | None = None

    def __post_init__(self):
        _port_state(self.state)
        if self.active_intent_id is not None:
            _identifier(self.active_intent_id, "active_intent_id")
        if self.readback_sequence is not None:
            if type(self.readback_sequence) is not int or self.readback_sequence < 0:
                raise ValueError("readback_sequence must be a nonnegative integer")


@dataclass(frozen=True)
class EstopStatus:
    software_latched: bool | None
    physical_latched: bool | None = None

    def __post_init__(self):
        for value in (self.software_latched, self.physical_latched):
            if value is not None and type(value) is not bool:
                raise ValueError("estop readback must be boolean or unknown (None)")


@dataclass(frozen=True)
class PortCapabilities:
    kinds: tuple[MotionKind, ...]
    joint_names: tuple[str, ...] = ()
    frames: tuple[str, ...] = ()
    limits: Mapping[str, float] = field(default_factory=dict)

    supports_stream: bool = False
    supports_goals: bool = False

    def __post_init__(self):
        kinds = tuple(MotionKind(kind) for kind in self.kinds)
        if len(kinds) != len(set(kinds)) or not set(kinds) <= _SERVO:
            raise ValueError("port accepts unique servo kinds only")
        if type(self.supports_stream) is not bool or type(self.supports_goals) is not bool:
            raise ValueError("transport modes must be boolean")
        object.__setattr__(self, "kinds", kinds)
        object.__setattr__(self, "joint_names", tuple(_identifier(name, "joint_name") for name in self.joint_names))
        object.__setattr__(self, "frames", tuple(_identifier(frame, "frame") for frame in self.frames))
        limits = _map(self.limits, "limits", minimum=0)
        if not set(limits) <= {"linear_mps", "angular_radps", "joint_velocity_radps", "joint_acceleration_radps2"}:
            raise ValueError("limits must name semantic SI maxima")
        object.__setattr__(self, "limits", limits)


class DeviceControlPort(Protocol):
    def capabilities(self) -> PortCapabilities: ...
    def submit(self, cmd: GuardedMotion) -> PortDecision: ...
    def cancel(self, intent_id: str) -> PortDecision: ...
    def state(self) -> PortState: ...
    def estop_status(self) -> EstopStatus: ...
