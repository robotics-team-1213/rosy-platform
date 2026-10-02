"""Pose-input CELL_TRANSFER planning for the simulation profile (D-402).

The planner only returns joint trajectories. It never calls an ActionPort;
the local ArmCommandOwner remains the only submitter (D-402 §9). There is
no collision scene: placed boxes, neighbours, the carried box, and low
links are NOT protected, so this backend is for ``simulation`` only.

Pick/place/home ``yaw`` is satisfied modulo pi (the two-finger gripper is
symmetric under 180 deg). That is valid only for items that are themselves
symmetric under 180 deg about the vertical (box, slip_sheet); the relative
rotation between pick and place may differ from the request by pi.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Protocol, Sequence

import yaml

from .command_owner import ArmCommandConfig
from .kinematics import ARM_JOINTS, IkLimits, OmxKinematics, TopDownPose
from .manipulation_plan import (
    MOTION_PHASES,
    ExecutionStateSnapshot,
    JointTrajectoryPoint,
    PlannedMotionPhase,
)


PLANNER_REVISION = "omx-analytic-top-down-v1"
PROFILE_SCHEMA = "rosy.omx-sim-cell-profile.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

# Typed HOLD reasons (D-402 §7). A rejected request yields no partial plan.
CELL_HASH_MISMATCH = "CELL_HASH_MISMATCH"
STATE_INVALID = "STATE_INVALID"
HOME_DEVIATION = "HOME_DEVIATION"
GRIPPER_NOT_OPEN = "GRIPPER_NOT_OPEN"
CARRY_Z_INSUFFICIENT = "CARRY_Z_INSUFFICIENT"
WAYPOINT_DISCONTINUITY = "WAYPOINT_DISCONTINUITY"
PHASE_DURATION_EXCEEDED = "PHASE_DURATION_EXCEEDED"


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
class CellPlanningProfile:
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
    def load(cls, path: Path | str) -> "CellPlanningProfile":
        # LF-normalised so a CRLF checkout yields the same revision.
        raw = Path(path).read_bytes().replace(b"\r\n", b"\n")
        document = yaml.safe_load(raw.decode("utf-8"))
        return cls.from_mapping(document, revision=hashlib.sha256(raw).hexdigest())

    @classmethod
    def from_mapping(cls, document: object, *, revision: str) -> "CellPlanningProfile":
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
            gripper_open=gripper_open, gripper_closed=gripper_closed,
            phase_max_duration_s=MappingProxyType(phase_max),
            workspace_min_m=tuple(b[0] for b in bounds),  # type: ignore[arg-type]
            workspace_max_m=tuple(b[1] for b in bounds),  # type: ignore[arg-type]
            max_joint_state_age_s=_finite("owner.max_joint_state_age_s",
                                          owner.get("max_joint_state_age_s"), positive=True),
            action_timeout_s=action_timeout, wall_clock_bound_factor=wall_factor,
            phase_start_state_tolerance_rad=MappingProxyType(phase_tolerances), **positive,
        )

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
        )


@dataclass(frozen=True)
class CellTransferRequest:
    """Device-local view of one CELL_TRANSFER body (D-403 §2), base frame ``robot_base``."""

    job_id: str
    recipe_sha256: str
    cell_sha256: str
    step_index: int
    item: str
    home: TopDownPose
    pick: TopDownPose
    place: TopDownPose
    pick_approach_z: float
    place_approach_z: float
    carry_z: float
    # pick/place z are TCP heights this far below the item's top face (C3b B1; the recipe's
    # box grasp_depth, 0 for a slip sheet). Required so that no caller relies on a default.
    grasp_depth_m: float

    def __post_init__(self) -> None:
        _text("job_id", self.job_id)
        _text("item", self.item)
        for name in ("recipe_sha256", "cell_sha256"):
            if not isinstance(getattr(self, name), str) or not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a lowercase sha256")
        if type(self.step_index) is not int or self.step_index < 0:
            raise ValueError("step_index must be a non-negative integer")
        for name in ("home", "pick", "place"):
            if not isinstance(getattr(self, name), TopDownPose):
                raise ValueError(f"{name} must be a TopDownPose")
        for name in ("pick_approach_z", "place_approach_z", "carry_z"):
            object.__setattr__(self, name, _finite(name, getattr(self, name)))
        depth = _finite("grasp_depth_m", self.grasp_depth_m)
        if depth < 0:
            raise ValueError("grasp_depth_m must be finite and non-negative")
        object.__setattr__(self, "grasp_depth_m", depth)


@dataclass(frozen=True)
class CellTransferPlan:
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


class CellTransferPlanRejected(ValueError):
    """Planning HOLD with a typed reason; no partial plan exists."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class CellTransferPlanProvider(Protocol):
    """Local pose-input planning port; implementations never execute a plan."""

    def plan_transfer(self, request: CellTransferRequest, profile: CellPlanningProfile,
                      state: ExecutionStateSnapshot) -> CellTransferPlan: ...


def _trapezoid_points(samples: Sequence[Sequence[float]], names: Sequence[str],
                      profile: CellPlanningProfile, start_time: float) -> list[JointTrajectoryPoint]:
    """Time one rest-to-rest segment. Samples include the start; points exclude it.

    Path parameter s in [0, 1] follows one trapezoid. Its peak rate and
    acceleration come from the slowest joint so that, with discrete path
    derivatives q' and q'', |q' s_dot| <= v_max and |q' s_ddot| + |q''| s_dot^2
    <= a_max hold at every reported point.
    """
    n = len(samples) - 1
    ds = 1.0 / n
    dims = range(len(names))
    first = []
    second = []
    for i in range(n + 1):
        lo, hi = max(i - 1, 0), min(i + 1, n)
        first.append([(samples[hi][j] - samples[lo][j]) / ((hi - lo) * ds) for j in dims])
        if 0 < i < n:
            second.append([(samples[i + 1][j] - 2 * samples[i][j] + samples[i - 1][j]) / (ds * ds)
                           for j in dims])
        else:
            second.append([0.0 for _ in dims])
    g1 = [max(abs(row[j]) for row in first) for j in dims]
    g2 = [max(abs(row[j]) for row in second) for j in dims]
    # Plan below the owner's limits; see planning_limit_fraction in the profile.
    fraction = profile.planning_limit_fraction
    v_max = {name: profile.velocity_limits[name] * fraction for name in names}
    a_max = {name: profile.acceleration_limits[name] * fraction for name in names}
    s_dot = math.inf
    for j, name in enumerate(names):
        if g1[j] > 0:
            s_dot = min(s_dot, v_max[name] / g1[j])
        if g2[j] > 0:
            # Curvature may use at most half of the acceleration budget.
            s_dot = min(s_dot, math.sqrt(a_max[name] / (2.0 * g2[j])))
    s_ddot = min((a_max[name] - g2[j] * s_dot * s_dot) / g1[j]
                 for j, name in enumerate(names) if g1[j] > 0)
    if s_dot * s_dot / s_ddot >= 1.0:
        accel_time = math.sqrt(1.0 / s_ddot)
        s_dot = s_ddot * accel_time
        blend = 0.5
        total = 2.0 * accel_time
    else:
        accel_time = s_dot / s_ddot
        blend = s_dot * s_dot / (2.0 * s_ddot)
        total = 2.0 * accel_time + (1.0 - 2.0 * blend) / s_dot
    points = []
    for i in range(1, n + 1):
        s = i * ds
        if i == n:
            t, rate, accel = total, 0.0, 0.0
        elif s <= blend:
            t = math.sqrt(2.0 * s / s_ddot)
            rate, accel = s_ddot * t, s_ddot
        elif s >= 1.0 - blend:
            remaining = math.sqrt(2.0 * (1.0 - s) / s_ddot)
            t, rate, accel = total - remaining, s_ddot * remaining, -s_ddot
        else:
            t, rate, accel = accel_time + (s - blend) / s_dot, s_dot, 0.0
        points.append(JointTrajectoryPoint(
            time_from_start_s=start_time + t,
            positions=tuple(samples[i]),
            velocities=tuple(first[i][j] * rate for j in dims) if i < n else tuple(0.0 for _ in dims),
            accelerations=(tuple(first[i][j] * accel + second[i][j] * rate * rate for j in dims)
                           if i < n else tuple(0.0 for _ in dims)),
        ))
    return points


class AnalyticCellTransferPlanner:
    """D-402 analytic top-down backend of CellTransferPlanProvider (simulation only)."""

    planner_revision = PLANNER_REVISION

    def __init__(self, kinematics: OmxKinematics, *,
                 accepted_cell_sha256: Callable[[], str | None],
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        if not isinstance(kinematics, OmxKinematics) or not callable(accepted_cell_sha256):
            raise ValueError("planner requires kinematics and an accepted-cell provider")
        self.kinematics = kinematics
        self.accepted_cell_sha256 = accepted_cell_sha256
        self.monotonic = monotonic

    def plan_transfer(self, request: CellTransferRequest, profile: CellPlanningProfile,
                      state: ExecutionStateSnapshot) -> CellTransferPlan:
        if not isinstance(request, CellTransferRequest) or not isinstance(profile, CellPlanningProfile):
            raise TypeError("plan_transfer requires CellTransferRequest and CellPlanningProfile")
        if not isinstance(state, ExecutionStateSnapshot):
            raise TypeError("plan_transfer requires an ExecutionStateSnapshot")
        # Second cell-hash check, immediately before planning (D-403 §9).
        accepted = self.accepted_cell_sha256()
        if not isinstance(accepted, str) or accepted != request.cell_sha256:
            raise CellTransferPlanRejected(CELL_HASH_MISMATCH, "grant cell_sha256 is not the accepted cell")
        kin = self.kinematics
        if profile.kinematics_revision != kin.revision:
            raise CellTransferPlanRejected(STATE_INVALID, "profile was reviewed against other geometry")
        if set(state.joint_positions) != set(profile.joint_names):
            raise CellTransferPlanRejected(STATE_INVALID, "state joint map does not match the profile")
        if state.planning_scene_revision != kin.planning_scene_revision:
            raise CellTransferPlanRejected(STATE_INVALID, "state planning scene is not this geometry")
        depth = request.grasp_depth_m
        if (request.carry_z < max(request.pick_approach_z, request.place_approach_z)
                or request.pick_approach_z < request.pick.z + depth
                or request.place_approach_z < request.place.z + depth):
            raise CellTransferPlanRejected(CARRY_Z_INSUFFICIENT,
                                           "need item top (z + grasp_depth_m) <= approach_z <= carry_z")
        limits = profile.ik_limits()
        current = tuple(state.joint_positions[name] for name in ARM_JOINTS)
        home = self._solve(request.home, limits, current[4])
        current_fk = kin.fk(current)
        if (current_fk.tool_down_error_rad > profile.tool_down_tolerance_rad
                or any(abs(a - b) > profile.home_joint_tolerance_rad for a, b in zip(current, home))):
            raise CellTransferPlanRejected(HOME_DEVIATION, "start state is not the taught home")
        # approach holds the gripper at the open target from its first point, so a
        # gripper that is not already open would be commanded to jump. Reject instead.
        if abs(state.joint_positions[profile.gripper_joint] - profile.gripper_open) > profile.start_state_tolerance_rad:
            raise CellTransferPlanRejected(GRIPPER_NOT_OPEN, "gripper is not open at the start of approach")

        names = profile.joint_names
        open_, closed = profile.gripper_open, profile.gripper_closed
        pose_home = TopDownPose(request.home.x, request.home.y, request.home.z,
                                home[0] - home[4])
        segments: dict[str, list[list[tuple[float, ...]]]] = {}
        arm = home
        approach, arm, pose = self._travel(pose_home, arm, request.pick, request.pick_approach_z,
                                           request.carry_z, limits, profile)
        segments["approach"] = [[a + (open_,) for a in seg] for seg in approach]
        segments["grasp"] = [self._gripper(arm, open_, closed, profile)]
        transfer, arm, pose = self._travel(pose, arm, request.place, request.place_approach_z,
                                           request.carry_z, limits, profile)
        segments["transfer"] = [[a + (closed,) for a in seg] for seg in transfer]
        release_open = self._gripper(arm, closed, open_, profile)
        # Return to the same home joint vector we started from (one q5 of the two yaw twins).
        retreat, arm, _ = self._travel(pose, arm, request.home, request.home.z,
                                       request.carry_z, limits, profile, end_reference_q5=home[4])
        segments["release"] = [release_open] + [[a + (open_,) for a in seg] for seg in retreat]

        phases = []
        start = home + (open_,)
        for ordinal, phase_id in enumerate(MOTION_PHASES):
            points: list[JointTrajectoryPoint] = []
            elapsed = 0.0
            for samples in segments[phase_id]:
                if len(samples) < 2:
                    continue
                points.extend(_trapezoid_points(samples, names, profile, elapsed))
                elapsed = points[-1].time_from_start_s
            if not points:
                raise CellTransferPlanRejected(STATE_INVALID, f"{phase_id} has no motion")
            if elapsed > profile.phase_max_duration_s[phase_id]:
                raise CellTransferPlanRejected(
                    PHASE_DURATION_EXCEEDED,
                    f"{phase_id} needs {elapsed:.2f} s > {profile.phase_max_duration_s[phase_id]} s",
                )
            phases.append(PlannedMotionPhase(
                phase_id=phase_id, ordinal=ordinal, joint_names=names, points=tuple(points),
                start_state_positions=start, source_state_sequence=state.sequence,
                calibration_revision=state.calibration_revision,
                transform_revision=state.transform_revision,
                planning_scene_revision=kin.planning_scene_revision,
            ))
            start = points[-1].positions
        return CellTransferPlan(
            phases=tuple(phases), planner_revision=self.planner_revision,
            kinematics_revision=kin.revision, profile_revision=profile.revision,
            source_state_sequence=state.sequence,
            planned_at_monotonic_s=self.monotonic(),
            gripper_joint_names=(profile.gripper_joint,),
        )

    def _solve(self, pose: TopDownPose, limits: IkLimits, reference_q5: float) -> tuple[float, ...]:
        result = self.kinematics.solve_top_down(pose, limits, reference_q5=reference_q5)
        if not result.ok:
            raise CellTransferPlanRejected(
                result.reason, f"({pose.x:.4f}, {pose.y:.4f}, {pose.z:.4f}, yaw {pose.yaw:.3f}) {result.detail}")
        fk = self.kinematics.fk(result.joints)
        position = (fk.x, fk.y, fk.z)
        if (any(abs(a - b) > 1e-6 for a, b in zip(position, (pose.x, pose.y, pose.z)))
                or any(v < lo or v > hi for v, lo, hi in zip(
                    position, limits.workspace_min_m, limits.workspace_max_m))):
            raise CellTransferPlanRejected("OUTSIDE_WORKSPACE", "FK check of waypoint failed")
        return result.joints

    def _line(self, start_pose: TopDownPose, start_arm: tuple[float, ...], target_xyz: tuple[float, float, float],
              target_yaw: float | None, limits: IkLimits, profile: CellPlanningProfile,
              end_reference_q5: float | None = None,
              ) -> tuple[list[tuple[float, ...]], tuple[float, ...], TopDownPose]:
        """Straight Cartesian segment; yaw follows q5 continuity toward ``target_yaw``.

        ``target_yaw`` is honoured modulo pi: the end q5 is the in-limit one of the
        two 180-deg twins nearest ``end_reference_q5`` (default: the start q5).
        """
        x0, y0, z0 = start_pose.x, start_pose.y, start_pose.z
        x1, y1, z1 = target_xyz
        yaw0 = start_arm[0] - start_arm[4]
        if target_yaw is None:
            yaw_delta = 0.0
        else:
            reference = start_arm[4] if end_reference_q5 is None else end_reference_q5
            end = self._solve(TopDownPose(x1, y1, z1, target_yaw), limits, reference)
            yaw_delta = (end[0] - end[4]) - yaw0
        distance = math.dist((x0, y0, z0), (x1, y1, z1))
        count = max(math.ceil(distance / profile.cartesian_step_m - 1e-9),
                    math.ceil(abs(yaw_delta) / profile.angular_step_rad - 1e-9))
        samples = [start_arm]
        arm = start_arm
        for i in range(1, count + 1):
            s = i / count
            pose = TopDownPose(x0 + (x1 - x0) * s, y0 + (y1 - y0) * s, z0 + (z1 - z0) * s,
                               yaw0 + yaw_delta * s)
            arm = self._solve(pose, limits, arm[4])
            if max(abs(a - b) for a, b in zip(arm, samples[-1])) > profile.max_waypoint_joint_step_rad:
                raise CellTransferPlanRejected(WAYPOINT_DISCONTINUITY, f"joint jump near sample {i}")
            samples.append(arm)
        return samples, arm, TopDownPose(x1, y1, z1, arm[0] - arm[4])

    def _travel(self, start_pose: TopDownPose, start_arm: tuple[float, ...], target: TopDownPose,
                approach_z: float, carry_z: float, limits: IkLimits, profile: CellPlanningProfile,
                end_reference_q5: float | None = None):
        """Vertical to carry_z, horizontal at carry_z, vertical to approach_z, vertical to target.

        The first segment is vertical in either direction: when carry_z is below the
        start height (e.g. a high taught home), the arm descends straight down to
        carry_z before any horizontal motion. That still obeys D-402 §6 (no diagonal).
        """
        segments = []
        pose, arm = start_pose, start_arm
        for xyz, yaw in (((pose.x, pose.y, carry_z), None),
                         ((target.x, target.y, carry_z), target.yaw),
                         ((target.x, target.y, approach_z), None),
                         ((target.x, target.y, target.z), None)):
            samples, arm, pose = self._line(pose, arm, xyz, yaw, limits, profile,
                                            end_reference_q5 if yaw is not None else None)
            segments.append(samples)
        return segments, arm, pose

    @staticmethod
    def _gripper(arm: tuple[float, ...], start: float, end: float,
                 profile: CellPlanningProfile) -> list[tuple[float, ...]]:
        count = math.ceil(abs(end - start) / profile.angular_step_rad - 1e-9)
        return [arm + (start + (end - start) * i / count,) for i in range(count + 1)]


def validate_cell_transfer_plan(plan: CellTransferPlan, profile: CellPlanningProfile, *,
                                kinematics_revision: str, now_monotonic_s: float) -> None:
    """Fail closed unless the plan cites this profile/geometry and stays within its limits."""
    if not isinstance(plan, CellTransferPlan):
        raise ValueError("plan must be a CellTransferPlan")
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
