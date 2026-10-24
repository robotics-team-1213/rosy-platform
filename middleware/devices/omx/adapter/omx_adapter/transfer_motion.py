"""Physical transfer inputs, reviewed simulation limits, and planned trajectories (D-856).

This module has no application/process identity or execution authority. The historical
simulation profile format is preserved; it does not provide collision-scene protection.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml

from .command_owner import ArmCommandConfig
from .kinematics import ARM_JOINTS, IkLimits, TopDownPose
from .manipulation_plan import MOTION_PHASES, PlannedMotionPhase

PLANNER_REVISION = "omx-analytic-top-down-v1"
PROFILE_SCHEMA = "rosy.omx-sim-cell-profile.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

# Typed HOLD reasons (D-402 §7). A rejected request yields no partial plan.
STATE_INVALID = "STATE_INVALID"
HOME_DEVIATION = "HOME_DEVIATION"
GRIPPER_NOT_OPEN = "GRIPPER_NOT_OPEN"
CARRY_Z_INSUFFICIENT = "CARRY_Z_INSUFFICIENT"
WAYPOINT_DISCONTINUITY = "WAYPOINT_DISCONTINUITY"
PHASE_DURATION_EXCEEDED = "PHASE_DURATION_EXCEEDED"
GRIPPER_WIDTH_INVALID = "GRIPPER_WIDTH_INVALID"
GRASP_DEPTH_BELOW_FINGERTIPS = "GRASP_DEPTH_BELOW_FINGERTIPS"

def _finite(name: str, value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    return number


def _bounds(name: str, value: object) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must be [lower, upper]")
    lower, upper = _finite(name, value[0]), _finite(name, value[1])
    if lower >= upper:
        raise ValueError(f"{name} must be increasing")
    return lower, upper


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty trimmed text")
    return value

@dataclass(frozen=True)
class ArmPlanningProfile:
    """Validated ``deploy/robot/omx/sim/cell_profile.yaml``; sha256 of its bytes is the revision."""

    revision: str
    kinematics_revision: str
    joint_names: tuple[str, ...]
    gripper_joint: str
    position_limits: Mapping[str, tuple[float, float]]
    velocity_limits: Mapping[str, float]
    acceleration_limits: Mapping[str, float]
    gripper_open: float
    gripper_closed: float
    gripper_preload_rad: float
    # Width-matched close (C3b B2): jaw gap(q) = 2 (o + x sin q + y cos q), o = half the
    # finger-pivot separation, (x, y) = inner fingertip contact point in the finger frame.
    jaw_pivot_half_separation_m: float
    jaw_contact_point_m: tuple[float, float]
    gripper_squeeze_m: float
    min_grasp_width_m: float
    max_grasp_width_m: float
    gripper_release_clearance_m: float
    fingertip_overhang_m: float
    phase_max_duration_s: Mapping[str, float]
    workspace_min_m: tuple[float, float, float]
    workspace_max_m: tuple[float, float, float]
    cartesian_step_m: float
    angular_step_rad: float
    max_waypoint_joint_step_rad: float
    singularity_radius_m: float
    tool_down_tolerance_rad: float
    home_joint_tolerance_rad: float
    start_state_tolerance_rad: float
    planning_limit_fraction: float
    max_joint_state_age_s: float
    action_timeout_s: float
    wall_clock_bound_factor: float
    # phase -> arm joint -> start tolerance, after grasp only (C3b A5: the held item deflects
    # the wrist). Joints not named keep start_state_tolerance_rad.
    phase_start_state_tolerance_rad: Mapping[str, Mapping[str, float]] = MappingProxyType({})

    @classmethod
    def load(cls, path: Path | str) -> "ArmPlanningProfile":
        # LF-normalised so a CRLF checkout yields the same revision.
        raw = Path(path).read_bytes().replace(b"\r\n", b"\n")
        document = yaml.safe_load(raw.decode("utf-8"))
        return cls.from_mapping(document, revision=hashlib.sha256(raw).hexdigest())

    @classmethod
    def from_mapping(cls, document: object, *, revision: str) -> "ArmPlanningProfile":
        if not isinstance(document, Mapping) or document.get("schema") != PROFILE_SCHEMA:
            raise ValueError(f"cell profile schema must be {PROFILE_SCHEMA}")
        if document.get("profile") != "simulation":
            raise ValueError("analytic top-down planning is admitted for the simulation profile only")
        if not isinstance(revision, str) or not _SHA256.fullmatch(revision):
            raise ValueError("profile revision must be a lowercase sha256")
        kin_revision = document.get("kinematics_revision")
        if not isinstance(kin_revision, str) or not _SHA256.fullmatch(kin_revision):
            raise ValueError("kinematics_revision must be a lowercase sha256")
        joints = document.get("joints")
        if not isinstance(joints, Mapping) or tuple(joints) != ARM_JOINTS:
            raise ValueError("profile joints must be exactly joint1..joint5 in order")
        gripper = document.get("gripper")
        if not isinstance(gripper, Mapping):
            raise ValueError("profile gripper section is required")
        gripper_joint = _text("gripper.joint", gripper.get("joint"))
        if gripper_joint in ARM_JOINTS:
            raise ValueError("gripper joint must not be an arm joint")
        position, velocity, acceleration = {}, {}, {}
        for name, entry in list(joints.items()) + [(gripper_joint, gripper)]:
            if not isinstance(entry, Mapping):
                raise ValueError(f"{name} limits must be a mapping")
            position[name] = _bounds(f"{name}.position", entry.get("position"))
            velocity[name] = _finite(f"{name}.velocity", entry.get("velocity"), positive=True)
            acceleration[name] = _finite(f"{name}.acceleration", entry.get("acceleration"), positive=True)
        gripper_open = _finite("gripper.open", gripper.get("open"))
        gripper_closed = _finite("gripper.closed", gripper.get("closed"))
        lower, upper = position[gripper_joint]
        if not (lower <= gripper_open <= upper and lower <= gripper_closed <= upper):
            raise ValueError("gripper open/closed targets must lie within gripper limits")
        if gripper_open == gripper_closed:
            raise ValueError("gripper open and closed targets must differ")
        gripper_preload = _finite("gripper.preload", gripper.get("preload"), positive=True)
        if gripper_preload >= abs(gripper_open - gripper_closed):
            raise ValueError("gripper preload must be shorter than the open-closed stroke")
        jaw = gripper.get("jaw")
        if not isinstance(jaw, Mapping):
            raise ValueError("gripper.jaw geometry is required (width-matched close)")
        pivots = jaw.get("pivot_y_m")
        contact = jaw.get("contact_point_m")
        if not isinstance(pivots, list) or len(pivots) != 2:
            raise ValueError("gripper.jaw.pivot_y_m must list the two finger pivot y values")
        if not isinstance(contact, list) or len(contact) != 2:
            raise ValueError("gripper.jaw.contact_point_m must be [x, y]")
        pivot_a, pivot_b = (_finite("gripper.jaw.pivot_y_m", value) for value in pivots)
        contact_x, contact_y = (_finite("gripper.jaw.contact_point_m", value) for value in contact)
        if pivot_a <= pivot_b or contact_x <= 0:
            raise ValueError("gripper.jaw pivots must be ordered and the contact point ahead of the pivot")
        squeeze = _finite("gripper.jaw.squeeze_m", jaw.get("squeeze_m"), positive=True)
        overhang = _finite("gripper.fingertip_overhang_m", gripper.get("fingertip_overhang_m"))
        if overhang < 0:
            raise ValueError("gripper.fingertip_overhang_m must be non-negative")
        min_width = _finite("gripper.jaw.min_grasp_width_m", jaw.get("min_grasp_width_m"), positive=True)
        max_width = _finite("gripper.jaw.max_grasp_width_m", jaw.get("max_grasp_width_m"), positive=True)
        release_clearance = _finite("gripper.jaw.release_clearance_m", jaw.get("release_clearance_m"),
                                    positive=True)
        if min_width - squeeze <= 0 or min_width >= max_width:
            raise ValueError("gripper.jaw needs squeeze_m < min_grasp_width_m < max_grasp_width_m")
        durations = document.get("phase_max_duration_s")
        if not isinstance(durations, Mapping) or tuple(durations) != MOTION_PHASES:
            raise ValueError("phase_max_duration_s must list approach, grasp, transfer, release")
        phase_max = {name: _finite(f"phase_max_duration_s.{name}", durations[name], positive=True)
                     for name in MOTION_PHASES}
        workspace = document.get("workspace")
        if not isinstance(workspace, Mapping):
            raise ValueError("workspace section is required")
        low = workspace.get("min_m")
        high = workspace.get("max_m")
        if not (isinstance(low, list) and isinstance(high, list) and len(low) == len(high) == 3):
            raise ValueError("workspace min_m/max_m must contain 3 values")
        bounds = [_bounds("workspace", (a, b)) for a, b in zip(low, high)]
        owner = document.get("owner")
        if not isinstance(owner, Mapping):
            raise ValueError("owner section is required")
        positive = {name: _finite(name, document.get(name), positive=True) for name in (
            "cartesian_step_m", "angular_step_rad", "max_waypoint_joint_step_rad",
            "singularity_radius_m", "tool_down_tolerance_rad", "home_joint_tolerance_rad",
            "start_state_tolerance_rad",
        )}
        action_timeout = _finite("owner.action_timeout_s", owner.get("action_timeout_s"), positive=True)
        if action_timeout < max(phase_max.values()):
            raise ValueError("owner.action_timeout_s must cover the longest phase")
        wall_factor = _finite("owner.wall_clock_bound_factor", owner.get("wall_clock_bound_factor"))
        if wall_factor < 1.0:
            raise ValueError("owner.wall_clock_bound_factor must be >= 1")
        overrides = document.get("phase_start_state_tolerance_rad", {})
        if not isinstance(overrides, Mapping):
            raise ValueError("phase_start_state_tolerance_rad must be a mapping")
        phase_tolerances: dict[str, Mapping[str, float]] = {}
        for phase_id, joints_tol in overrides.items():
            if phase_id not in ("transfer", "release") or not isinstance(joints_tol, Mapping):
                raise ValueError("phase_start_state_tolerance_rad names only transfer, release")
            checked = {}
            for name, value in joints_tol.items():
                if name not in ARM_JOINTS:
                    raise ValueError("phase_start_state_tolerance_rad names an arm joint only")
                tolerance = _finite(f"phase_start_state_tolerance_rad.{phase_id}.{name}", value)
                if tolerance > 0.1:
                    # Beyond 0.1 rad the wrist is not sagging under a held item; it is a
                    # grasp fault (C3 run10/11: -0.327 rad over-squeeze).
                    raise ValueError("phase start tolerance must be at most 0.1 rad")
                if tolerance < positive["start_state_tolerance_rad"]:
                    raise ValueError("phase start tolerance must not be below the base tolerance")
                checked[name] = tolerance
            phase_tolerances[phase_id] = MappingProxyType(checked)
        fraction = document.get("planning_limit_fraction")
        if (isinstance(fraction, bool) or not isinstance(fraction, (int, float))
                or not 0.0 < float(fraction) <= 1.0):
            raise ValueError("planning_limit_fraction must be in (0, 1]")
        return cls(
            planning_limit_fraction=float(fraction),
            revision=revision, kinematics_revision=kin_revision,
            joint_names=ARM_JOINTS + (gripper_joint,), gripper_joint=gripper_joint,
            position_limits=MappingProxyType(position),
            velocity_limits=MappingProxyType(velocity),
            acceleration_limits=MappingProxyType(acceleration),
            gripper_open=gripper_open, gripper_closed=gripper_closed, gripper_preload_rad=gripper_preload,
            jaw_pivot_half_separation_m=(pivot_a - pivot_b) / 2,
            jaw_contact_point_m=(contact_x, contact_y), gripper_squeeze_m=squeeze,
            min_grasp_width_m=min_width, max_grasp_width_m=max_width,
            gripper_release_clearance_m=release_clearance, fingertip_overhang_m=overhang,
            phase_max_duration_s=MappingProxyType(phase_max),
            workspace_min_m=tuple(b[0] for b in bounds),  # type: ignore[arg-type]
            workspace_max_m=tuple(b[1] for b in bounds),  # type: ignore[arg-type]
            max_joint_state_age_s=_finite("owner.max_joint_state_age_s",
                                          owner.get("max_joint_state_age_s"), positive=True),
            action_timeout_s=action_timeout, wall_clock_bound_factor=wall_factor,
            phase_start_state_tolerance_rad=MappingProxyType(phase_tolerances), **positive,
        )

    def jaw_gap_m(self, q: float) -> float:
        """Inner fingertip gap at gripper_joint_1 = q (gripper_joint_2 mimics -q)."""
        x, y = self.jaw_contact_point_m
        return 2.0 * (self.jaw_pivot_half_separation_m + x * math.sin(q) + y * math.cos(q))

    def gripper_contact_for_width(self, width_m: float) -> float:
        """Finger angle at which the fingertips touch an item of this width."""
        x, y = self.jaw_contact_point_m
        radius = math.hypot(x, y)
        ratio = (width_m / 2.0 - self.jaw_pivot_half_separation_m) / radius
        if not -1.0 <= ratio <= 1.0:
            raise ValueError("width is outside the jaw geometry")
        return math.asin(ratio) - math.atan2(y, x)

    def gripper_close_for_width(self, width_m: float) -> float:
        """Width-matched close target: contact minus the profile squeeze margin (C3b B2)."""
        width = _finite("grasp width", width_m, positive=True)
        if not self.min_grasp_width_m <= width <= self.max_grasp_width_m:
            raise ValueError("grasp width is outside the gripper's validated range")
        target = self.gripper_contact_for_width(width - self.gripper_squeeze_m)
        lower, upper = self.position_limits[self.gripper_joint]
        if not (lower <= target <= upper and min(self.gripper_closed, self.gripper_open)
                < target < max(self.gripper_closed, self.gripper_open)):
            raise ValueError("width-matched close target is outside the gripper stroke")
        return target

    def ik_limits(self) -> IkLimits:
        return IkLimits(
            position_limits={name: self.position_limits[name] for name in ARM_JOINTS},
            workspace_min_m=self.workspace_min_m, workspace_max_m=self.workspace_max_m,
            singularity_radius_m=self.singularity_radius_m,
        )

    def start_state_tolerances(self, phase_id: str | None = None) -> dict[str, float]:
        """Every planned joint. PickPlaceRunner skips the gripper only after grasp (D-402 §3d).

        With ``phase_id`` the profile's after-grasp per-joint tolerances apply (C3b A5).
        """
        tolerances = {name: self.start_state_tolerance_rad for name in self.joint_names}
        tolerances.update(self.phase_start_state_tolerance_rad.get(phase_id, {}))
        return tolerances

    def arm_command_config(self, *, workcell_id: str, instance_id: str,
                           calibration_revision: str,
                           allowed_owners: tuple[str, ...] = ("pilot_sim", "rule_based")) -> ArmCommandConfig:
        """Simulation owner policy built from the same file (D-402 §4, D-403 §8)."""
        return ArmCommandConfig(
            enabled=True, workcell_id=workcell_id, instance_id=instance_id,
            joint_names=self.joint_names, position_limits=dict(self.position_limits),
            velocity_limits=dict(self.velocity_limits),
            acceleration_limits=dict(self.acceleration_limits),
            allowed_owners=allowed_owners, calibration_revision=calibration_revision,
            max_joint_state_age_s=self.max_joint_state_age_s,
            max_goal_duration_s=max(self.phase_max_duration_s.values()),
            action_timeout_s=self.action_timeout_s,
            wall_clock_bound_factor=self.wall_clock_bound_factor,
            # Owner cap per joint (merge of main 7735c307 and C3b A1, the stricter of the two):
            # the largest start tolerance this profile can ever ask for that joint, i.e. the
            # base tolerance or its after-grasp override (each <= 0.1 rad).
            max_start_state_tolerances={
                name: max([self.start_state_tolerance_rad] + [
                    phase.get(name, 0.0) for phase in self.phase_start_state_tolerance_rad.values()])
                for name in self.joint_names},
        )

@dataclass(frozen=True)
class TransferMotionRequest:
    """Poses in robot_base (metres/radians) and bounded approach/carry heights."""
    home: TopDownPose
    pick: TopDownPose
    place: TopDownPose
    pick_approach_z: float
    place_approach_z: float
    carry_z: float

    def __post_init__(self) -> None:
        for name in ("home", "pick", "place"):
            if not isinstance(getattr(self, name), TopDownPose):
                raise ValueError(f"{name} must be a TopDownPose")
        for name in ("pick_approach_z", "place_approach_z", "carry_z"):
            object.__setattr__(self, name, _finite(name, getattr(self, name)))


@dataclass(frozen=True)
class GraspGeometry:
    """Owner-resolved physical geometry; constructing it grants no authority."""
    grasp_width_m: float
    grasp_depth_m: float
    height_m: float
    yaw_symmetric_pi: bool

    def __post_init__(self) -> None:
        for name in ("grasp_width_m", "height_m"):
            object.__setattr__(self, name, _finite(name, getattr(self, name), positive=True))
        depth = _finite("grasp_depth_m", self.grasp_depth_m)
        if depth < 0:
            raise ValueError("grasp_depth_m must be non-negative")
        object.__setattr__(self, "grasp_depth_m", depth)
        if self.yaw_symmetric_pi is not True:
            raise ValueError("this simulation backend requires a 180-degree symmetric object")


@dataclass(frozen=True)
class TransferMotionPlan:
    """Four timed phases for one CELL_TRANSFER; no RGB-D provenance is claimed (D-402 §2)."""

    phases: tuple[PlannedMotionPhase, ...]
    planner_revision: str
    kinematics_revision: str
    profile_revision: str
    source_state_sequence: int
    planned_at_monotonic_s: float
    gripper_joint_names: tuple[str, ...]

    def __post_init__(self) -> None:
        phases = tuple(self.phases)
        if (tuple(phase.phase_id for phase in phases) != MOTION_PHASES
                or tuple(phase.ordinal for phase in phases) != tuple(range(len(MOTION_PHASES)))):
            raise ValueError("plan phases must be exactly approach, grasp, transfer, release")
        object.__setattr__(self, "phases", phases)
        for name in ("planner_revision", "kinematics_revision", "profile_revision"):
            _text(name, getattr(self, name))
        if type(self.source_state_sequence) is not int or self.source_state_sequence < 0:
            raise ValueError("source_state_sequence must be a non-negative integer")
        object.__setattr__(self, "planned_at_monotonic_s", _finite(
            "planned_at_monotonic_s", self.planned_at_monotonic_s))
        scene = "kin:" + self.kinematics_revision
        if any(phase.source_state_sequence != self.source_state_sequence
               or phase.planning_scene_revision != scene
               or phase.joint_names != phases[0].joint_names for phase in phases):
            raise ValueError("phases must share joints, source sequence, and the kin: scene revision")
        grippers = tuple(self.gripper_joint_names)
        if not grippers or not set(grippers) < set(phases[0].joint_names) or set(grippers) & set(ARM_JOINTS):
            raise ValueError("gripper joints must be planned non-arm joints")
        object.__setattr__(self, "gripper_joint_names", grippers)


class TransferPlanRejected(ValueError):
    """Planning HOLD with a typed reason; no partial plan exists."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail

def validate_transfer_motion_plan(plan: TransferMotionPlan, profile: ArmPlanningProfile, *,
                                kinematics_revision: str, now_monotonic_s: float) -> None:
    """Fail closed unless the plan cites this profile/geometry and stays within its limits."""
    if not isinstance(plan, TransferMotionPlan):
        raise ValueError("plan must be a TransferMotionPlan")
    now = _finite("now_monotonic_s", now_monotonic_s)
    if plan.profile_revision != profile.revision:
        raise ValueError("plan profile revision does not match the accepted profile")
    if plan.kinematics_revision != kinematics_revision or profile.kinematics_revision != kinematics_revision:
        raise ValueError("plan kinematics revision does not match the device geometry")
    if plan.planned_at_monotonic_s > now:
        raise ValueError("plan timestamp is from the future")
    if plan.gripper_joint_names != (profile.gripper_joint,):
        raise ValueError("plan gripper joints do not match the profile")
    for phase in plan.phases:
        if phase.joint_names != profile.joint_names:
            raise ValueError("planned joint map does not match the profile")
        if phase.points[-1].time_from_start_s > profile.phase_max_duration_s[phase.phase_id]:
            raise ValueError(f"{phase.phase_id} exceeds its maximum duration")
        for point in phase.points:
            if point.velocities is None or point.accelerations is None:
                raise ValueError("planned points must carry velocities and accelerations")
            for name, q, v, a in zip(phase.joint_names, point.positions,
                                     point.velocities, point.accelerations):
                lower, upper = profile.position_limits[name]
                if (not lower <= q <= upper or abs(v) > profile.velocity_limits[name] + 1e-9
                        or abs(a) > profile.acceleration_limits[name] + 1e-9):
                    raise ValueError(f"{phase.phase_id} point exceeds {name} limits")
