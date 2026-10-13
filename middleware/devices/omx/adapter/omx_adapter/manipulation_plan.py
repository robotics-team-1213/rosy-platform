"""Typed, ROS-free evidence and plan contracts for fixed-workcell PICK_PLACE.

This module does not infer 3D geometry from pixels or implement a production
planner. A provider must supply locally measured RGB-D pose evidence and a
collision-checked plan that passes the accepted workcell profile.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, Protocol

if TYPE_CHECKING:
    from core_common.protocol.schemas import FleetActionGrant, ResolvedTargetEvidence


MOTION_PHASES = ("approach", "grasp", "transfer", "release")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty trimmed text")
    return value


def _finite(name: str, value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else "")) from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    return result


def _vector(name: str, value: object, length: int) -> tuple[float, ...]:
    if not isinstance(value, (tuple, list)) or len(value) != length:
        raise ValueError(f"{name} must contain {length} values")
    return tuple(_finite(name, item) for item in value)


def _digest(name: str, value: object) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class RgbdObservation:
    """One locally retained, paired RGB-D observation metadata record."""

    observation_id: str
    camera_identity: str
    optical_frame_id: str
    rgb_frame_sha256: str
    depth_frame_sha256: str
    calibration_revision: str
    transform_revision: str
    capture_time_ns: int
    rgb_capture_time_ns: int
    depth_capture_time_ns: int
    received_at_monotonic_s: float

    def __post_init__(self) -> None:
        for name in ("observation_id", "camera_identity", "optical_frame_id",
                     "calibration_revision", "transform_revision"):
            _text(name, getattr(self, name))
        _digest("rgb_frame_sha256", self.rgb_frame_sha256)
        _digest("depth_frame_sha256", self.depth_frame_sha256)
        for name in ("capture_time_ns", "rgb_capture_time_ns", "depth_capture_time_ns"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer nanosecond timestamp")
        if self.rgb_capture_time_ns != self.capture_time_ns:
            raise ValueError("capture_time_ns must identify the RGB observation stamp")
        object.__setattr__(self, "received_at_monotonic_s", _finite(
            "received_at_monotonic_s", self.received_at_monotonic_s
        ))


@dataclass(frozen=True)
class ResolvedObjectPose:
    """A locally resolved 3D pose with immutable source RGB-D provenance."""

    object_id: str
    observation_id: str
    camera_identity: str
    optical_frame_id: str
    rgb_frame_sha256: str
    depth_frame_sha256: str
    capture_time_ns: int
    calibration_revision: str
    transform_revision: str
    workspace_frame_id: str
    translation_m: tuple[float, float, float]
    orientation_xyzw: tuple[float, float, float, float]
    covariance_6x6: tuple[float, ...]
    position_stddev_m: float

    def __post_init__(self) -> None:
        for name in ("object_id", "observation_id", "camera_identity", "optical_frame_id",
                     "calibration_revision", "transform_revision", "workspace_frame_id"):
            _text(name, getattr(self, name))
        _digest("rgb_frame_sha256", self.rgb_frame_sha256)
        _digest("depth_frame_sha256", self.depth_frame_sha256)
        if type(self.capture_time_ns) is not int or self.capture_time_ns <= 0:
            raise ValueError("capture_time_ns must be a positive integer nanosecond timestamp")
        object.__setattr__(self, "translation_m", _vector("translation_m", self.translation_m, 3))
        quaternion = _vector("orientation_xyzw", self.orientation_xyzw, 4)
        norm = math.sqrt(sum(value * value for value in quaternion))
        if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-3):
            raise ValueError("orientation_xyzw must be a unit quaternion")
        object.__setattr__(self, "orientation_xyzw", quaternion)
        covariance = _vector("covariance_6x6", self.covariance_6x6, 36)
        if any(not math.isclose(covariance[row * 6 + col], covariance[col * 6 + row],
                                rel_tol=0.0, abs_tol=1e-12)
               for row in range(6) for col in range(row + 1, 6)):
            raise ValueError("covariance_6x6 must be symmetric")
        if any(covariance[index] < 0 for index in (0, 7, 14, 21, 28, 35)):
            raise ValueError("covariance_6x6 diagonal must be non-negative")
        object.__setattr__(self, "covariance_6x6", covariance)
        position_stddev = _finite(
            "position_stddev_m", self.position_stddev_m, positive=True
        )
        max_axis_stddev = math.sqrt(max(covariance[0], covariance[7], covariance[14]))
        if position_stddev + 1e-12 < max_axis_stddev:
            raise ValueError("position_stddev_m must bound positional covariance")
        object.__setattr__(self, "position_stddev_m", position_stddev)


@dataclass(frozen=True)
class JointTrajectoryPoint:
    """One timed joint-space waypoint; profile-specific limits are checked later."""

    time_from_start_s: float
    positions: tuple[float, ...]
    velocities: tuple[float, ...] | None = None
    accelerations: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_from_start_s", _finite(
            "time_from_start_s", self.time_from_start_s, positive=True
        ))
        if not isinstance(self.positions, (tuple, list)) or not self.positions:
            raise ValueError("positions must contain one value per joint")
        count = len(self.positions)
        object.__setattr__(self, "positions", _vector("positions", self.positions, count))
        for name in ("velocities", "accelerations"):
            values = getattr(self, name)
            if values is not None:
                object.__setattr__(self, name, _vector(name, values, count))


@dataclass(frozen=True)
class ExecutionStateSnapshot:
    """Fresh local state used to validate a planned phase's bounded start."""

    sequence: int
    joint_positions: Mapping[str, float]
    calibration_revision: str
    transform_revision: str
    planning_scene_revision: str
    observed_at_monotonic_s: float

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if not isinstance(self.joint_positions, Mapping) or not self.joint_positions:
            raise ValueError("joint_positions must be a non-empty mapping")
        positions = {}
        for name, value in self.joint_positions.items():
            _text("joint name", name)
            positions[name] = _finite(f"joint position {name}", value)
        object.__setattr__(self, "joint_positions", MappingProxyType(positions))
        for name in ("calibration_revision", "transform_revision", "planning_scene_revision"):
            _text(name, getattr(self, name))
        object.__setattr__(self, "observed_at_monotonic_s", _finite(
            "observed_at_monotonic_s", self.observed_at_monotonic_s,
        ))


@dataclass(frozen=True)
class PlannedMotionPhase:
    """One motion phase that corresponds to exactly one ROS goal."""

    phase_id: str
    ordinal: int
    joint_names: tuple[str, ...]
    points: tuple[JointTrajectoryPoint, ...]
    start_state_positions: tuple[float, ...]
    source_state_sequence: int
    calibration_revision: str
    transform_revision: str
    planning_scene_revision: str

    def __post_init__(self) -> None:
        if self.phase_id not in MOTION_PHASES:
            raise ValueError("phase_id is not a supported motion phase")
        if type(self.ordinal) is not int or not 0 <= self.ordinal < len(MOTION_PHASES):
            raise ValueError("phase ordinal is outside the supported phase sequence")
        if self.phase_id != MOTION_PHASES[self.ordinal]:
            raise ValueError("phase_id and ordinal must match the ordered motion phases")
        joints = tuple(self.joint_names)
        if not joints or any(not isinstance(name, str) or not name or name != name.strip()
                             for name in joints) or len(set(joints)) != len(joints):
            raise ValueError("joint_names must be non-empty, trimmed, and unique")
        object.__setattr__(self, "joint_names", joints)
        points = tuple(self.points)
        if not points or any(not isinstance(point, JointTrajectoryPoint) for point in points):
            raise ValueError("points must contain timed joint trajectory points")
        if any(len(point.positions) != len(joints)
               or (point.velocities is not None and len(point.velocities) != len(joints))
               or (point.accelerations is not None and len(point.accelerations) != len(joints))
               for point in points):
            raise ValueError("trajectory point joint dimensions must match joint_names")
        object.__setattr__(self, "points", points)
        start_state = _vector("start_state_positions", self.start_state_positions, len(joints))
        object.__setattr__(self, "start_state_positions", start_state)
        if type(self.source_state_sequence) is not int or self.source_state_sequence < 0:
            raise ValueError("source_state_sequence must be a non-negative integer")
        for name in ("calibration_revision", "transform_revision", "planning_scene_revision"):
            _text(name, getattr(self, name))


@dataclass(frozen=True)
class ResolvedPickPlacePlan:
    source_pose: ResolvedObjectPose
    destination_pose: ResolvedObjectPose
    phases: tuple[PlannedMotionPhase, ...]
    planner_revision: str
    planning_scene_revision: str
    calibration_revision: str
    transform_revision: str
    source_state_sequence: int
    planned_at_monotonic_s: float

    def __post_init__(self) -> None:
        if not isinstance(self.source_pose, ResolvedObjectPose) or not isinstance(
            self.destination_pose, ResolvedObjectPose
        ):
            raise ValueError("source_pose and destination_pose must be resolved object poses")
        phases = tuple(self.phases)
        if tuple(phase.phase_id for phase in phases) != MOTION_PHASES:
            raise ValueError("plan phases must be exactly approach, grasp, transfer, release")
        if tuple(phase.ordinal for phase in phases) != tuple(range(len(MOTION_PHASES))):
            raise ValueError("plan phase ordinals must be contiguous and ordered")
        object.__setattr__(self, "phases", phases)
        for name in ("planner_revision", "planning_scene_revision",
                     "calibration_revision", "transform_revision"):
            _text(name, getattr(self, name))
        if type(self.source_state_sequence) is not int or self.source_state_sequence < 0:
            raise ValueError("source_state_sequence must be a non-negative integer")
        object.__setattr__(self, "planned_at_monotonic_s", _finite(
            "planned_at_monotonic_s", self.planned_at_monotonic_s
        ))
        if any(phase.source_state_sequence != self.source_state_sequence for phase in phases):
            raise ValueError("all phases must cite the plan's source joint-state sequence")
        if any(phase.calibration_revision != self.calibration_revision
               or phase.transform_revision != self.transform_revision
               or phase.planning_scene_revision != self.planning_scene_revision
               for phase in phases):
            raise ValueError("all phases must cite the plan's calibration, transform, and scene revisions")


@dataclass(frozen=True)
class ManipulationPlanningProfile:
    """Explicit accepted workcell bounds; there are no hardware defaults."""

    workcell_id: str
    instance_id: str
    workspace_frame_id: str
    workspace_min_m: tuple[float, float, float]
    workspace_max_m: tuple[float, float, float]
    joint_names: tuple[str, ...]
    calibration_revision: str
    transform_revision: str
    planning_scene_revision: str
    max_observation_age_s: float
    max_position_stddev_m: float
    max_rgb_depth_skew_ns: int

    def __post_init__(self) -> None:
        for name in ("workcell_id", "instance_id", "workspace_frame_id",
                     "calibration_revision", "transform_revision", "planning_scene_revision"):
            _text(name, getattr(self, name))
        lower = _vector("workspace_min_m", self.workspace_min_m, 3)
        upper = _vector("workspace_max_m", self.workspace_max_m, 3)
        if any(low >= high for low, high in zip(lower, upper)):
            raise ValueError("workspace bounds must be increasing")
        object.__setattr__(self, "workspace_min_m", lower)
        object.__setattr__(self, "workspace_max_m", upper)
        joints = tuple(self.joint_names)
        if not joints or any(not isinstance(name, str) or not name or name != name.strip()
                             for name in joints) or len(set(joints)) != len(joints):
            raise ValueError("joint_names must be non-empty, trimmed, and unique")
        object.__setattr__(self, "joint_names", joints)
        object.__setattr__(self, "max_observation_age_s", _finite(
            "max_observation_age_s", self.max_observation_age_s, positive=True
        ))
        object.__setattr__(self, "max_position_stddev_m", _finite(
            "max_position_stddev_m", self.max_position_stddev_m, positive=True
        ))
        if type(self.max_rgb_depth_skew_ns) is not int or self.max_rgb_depth_skew_ns < 0:
            raise ValueError("max_rgb_depth_skew_ns must be a non-negative integer")


class PickPlacePlanProvider(Protocol):
    """Local geometry/planning port; implementations must never execute a plan."""

    def resolve_and_plan(
        self,
        grant: FleetActionGrant,
        local_observation: RgbdObservation,
        workcell_profile: ManipulationPlanningProfile,
    ) -> ResolvedPickPlacePlan: ...


def _pose_matches_evidence(pose: ResolvedObjectPose, evidence: ResolvedTargetEvidence,
                           observation: RgbdObservation) -> None:
    checks = (
        (pose.object_id == evidence.object_id, "object identity"),
        (pose.observation_id == evidence.observation_id == observation.observation_id, "observation identity"),
        (pose.camera_identity == evidence.camera_identity == observation.camera_identity, "camera identity"),
        (pose.optical_frame_id == evidence.optical_frame_id == observation.optical_frame_id, "optical frame"),
        (pose.rgb_frame_sha256 == evidence.frame_sha256 == observation.rgb_frame_sha256, "RGB frame digest"),
        (pose.depth_frame_sha256 == observation.depth_frame_sha256, "depth frame digest"),
        (pose.capture_time_ns == evidence.capture_time_ns == observation.capture_time_ns, "capture time"),
        (pose.calibration_revision == evidence.calibration_revision == observation.calibration_revision,
         "calibration revision"),
        (pose.transform_revision == evidence.transform_revision == observation.transform_revision,
         "transform revision"),
    )
    for matches, field in checks:
        if not matches:
            raise ValueError(f"resolved object pose {field} does not match grant and RGB-D evidence")


def validate_pick_place_plan(
    plan: ResolvedPickPlacePlan,
    grant: FleetActionGrant,
    local_observation: RgbdObservation,
    workcell_profile: ManipulationPlanningProfile,
    *,
    now_monotonic_s: float,
) -> None:
    """Fail closed unless poses, plan phases, and source state match current evidence."""
    now = _finite("now_monotonic_s", now_monotonic_s)
    if grant.action_kind != "PICK_PLACE":
        raise ValueError("grant action kind must be PICK_PLACE")
    if (grant.workcell_id, grant.instance_id) != (
        workcell_profile.workcell_id, workcell_profile.instance_id,
    ):
        raise ValueError("grant workcell identity does not match planning profile")
    if (local_observation.observation_id != grant.source_evidence.observation_id
            or local_observation.observation_id != grant.destination_evidence.observation_id):
        raise ValueError("local RGB-D observation does not match grant observation")
    if (local_observation.rgb_frame_sha256 != grant.source_evidence.frame_sha256
            or local_observation.rgb_frame_sha256 != grant.destination_evidence.frame_sha256):
        raise ValueError("local RGB-D frame digest does not match grant frame digest")
    metadata_checks = (
        (local_observation.camera_identity == grant.source_evidence.camera_identity,
         "camera identity"),
        (local_observation.optical_frame_id == grant.source_evidence.optical_frame_id,
         "optical frame"),
        (local_observation.calibration_revision == grant.source_evidence.calibration_revision,
         "calibration revision"),
        (local_observation.transform_revision == grant.source_evidence.transform_revision,
         "transform revision"),
        (local_observation.capture_time_ns == grant.source_evidence.capture_time_ns,
         "capture time"),
    )
    for matches, field in metadata_checks:
        if not matches:
            raise ValueError(f"local RGB-D {field} does not match Fleet grant")
    skew_ns = abs(local_observation.rgb_capture_time_ns - local_observation.depth_capture_time_ns)
    if skew_ns > workcell_profile.max_rgb_depth_skew_ns:
        raise ValueError("RGB and depth captures are not synchronized")
    age = now - local_observation.received_at_monotonic_s
    if age < 0 or age > workcell_profile.max_observation_age_s:
        raise ValueError("local RGB-D observation is stale or from the future")
    _pose_matches_evidence(plan.source_pose, grant.source_evidence, local_observation)
    _pose_matches_evidence(plan.destination_pose, grant.destination_evidence, local_observation)
    for resolved_pose in (plan.source_pose, plan.destination_pose):
        if resolved_pose.workspace_frame_id != workcell_profile.workspace_frame_id:
            raise ValueError("resolved pose workspace frame does not match accepted workspace frame")
        if any(value < low or value > high for value, low, high in zip(
            resolved_pose.translation_m, workcell_profile.workspace_min_m,
            workcell_profile.workspace_max_m,
        )):
            raise ValueError("resolved pose exceeds accepted workspace bounds")
        if resolved_pose.position_stddev_m > workcell_profile.max_position_stddev_m:
            raise ValueError("resolved pose uncertainty exceeds accepted bound")
    if (plan.calibration_revision != workcell_profile.calibration_revision
            or plan.transform_revision != workcell_profile.transform_revision
            or plan.planning_scene_revision != workcell_profile.planning_scene_revision):
        raise ValueError("plan revisions do not match accepted workcell profile")
    if plan.source_state_sequence < 0:
        raise ValueError("plan requires a current source joint-state sequence")
    if plan.planned_at_monotonic_s > now:
        raise ValueError("plan timestamp is from the future")
    if plan.planned_at_monotonic_s < local_observation.received_at_monotonic_s:
        raise ValueError("plan predates its source RGB-D observation")
    if any(phase.joint_names != workcell_profile.joint_names for phase in plan.phases):
        raise ValueError("planned trajectory joint map does not match accepted workcell profile")
