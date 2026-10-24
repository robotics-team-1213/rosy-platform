"""Simulation-only physical transfer calculation; no job, recipe, or ledger semantics.

No collision scene is provided. Only owner-resolved, 180-degree symmetric object
geometry is supported. The owner still validates freshness, fences and final output.
"""
from __future__ import annotations

import math
import time
from typing import Callable, Sequence

from .kinematics import ARM_JOINTS, IkLimits, OmxKinematics, TopDownPose
from .manipulation_plan import MOTION_PHASES, ExecutionStateSnapshot, JointTrajectoryPoint, PlannedMotionPhase
from .transfer_motion import (
    ArmPlanningProfile, TransferMotionPlan, TransferMotionRequest, GraspGeometry, TransferPlanRejected,
    PLANNER_REVISION, STATE_INVALID, HOME_DEVIATION, GRIPPER_NOT_OPEN, CARRY_Z_INSUFFICIENT,
    WAYPOINT_DISCONTINUITY, PHASE_DURATION_EXCEEDED, GRIPPER_WIDTH_INVALID, GRASP_DEPTH_BELOW_FINGERTIPS,
)

def _trapezoid_points(samples: Sequence[Sequence[float]], names: Sequence[str],
                      profile: ArmPlanningProfile, start_time: float) -> list[JointTrajectoryPoint]:
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

class AnalyticTransferPlanner:
    """Return physical trajectories; never select or approve their object geometry."""
    planner_revision = PLANNER_REVISION

    def __init__(self, kinematics: OmxKinematics, *,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        if not isinstance(kinematics, OmxKinematics):
            raise ValueError("planner requires device kinematics")
        self.kinematics = kinematics
        self.monotonic = monotonic

    def plan_transfer(self, request: TransferMotionRequest, profile: ArmPlanningProfile,
                      state: ExecutionStateSnapshot, *, geometry: GraspGeometry) -> TransferMotionPlan:
        if not isinstance(request, TransferMotionRequest) or not isinstance(profile, ArmPlanningProfile):
            raise TypeError("plan_transfer requires TransferMotionRequest and ArmPlanningProfile")
        if not isinstance(state, ExecutionStateSnapshot) or not isinstance(geometry, GraspGeometry):
            raise TypeError("plan_transfer requires execution state and owner-resolved GraspGeometry")
        if geometry.grasp_depth_m > geometry.height_m - profile.fingertip_overhang_m + 1e-12:
            raise TransferPlanRejected(GRASP_DEPTH_BELOW_FINGERTIPS,
                                       "grasp_depth_m exceeds item height - fingertip_overhang_m")
        kin = self.kinematics
        if profile.kinematics_revision != kin.revision:
            raise TransferPlanRejected(STATE_INVALID, "profile was reviewed against other geometry")
        if set(state.joint_positions) != set(profile.joint_names):
            raise TransferPlanRejected(STATE_INVALID, "state joint map does not match the profile")
        if state.planning_scene_revision != kin.planning_scene_revision:
            raise TransferPlanRejected(STATE_INVALID, "state planning scene is not this geometry")
        depth = geometry.grasp_depth_m
        if (request.carry_z < max(request.pick_approach_z, request.place_approach_z)
                or request.pick_approach_z < request.pick.z + depth
                or request.place_approach_z < request.place.z + depth):
            raise TransferPlanRejected(CARRY_Z_INSUFFICIENT,
                                           "need item top (z + grasp_depth_m) <= approach_z <= carry_z")
        limits = profile.ik_limits()
        current = tuple(state.joint_positions[name] for name in ARM_JOINTS)
        home = self._solve(request.home, limits, current[4])
        current_fk = kin.fk(current)
        if (current_fk.tool_down_error_rad > profile.tool_down_tolerance_rad
                or any(abs(a - b) > profile.home_joint_tolerance_rad for a, b in zip(current, home))):
            raise TransferPlanRejected(HOME_DEVIATION, "start state is not the taught home")
        # approach holds the gripper at the open target from its first point, so a
        # gripper that is not already open would be commanded to jump. Reject instead.
        if abs(state.joint_positions[profile.gripper_joint] - profile.gripper_open) > profile.start_state_tolerance_rad:
            raise TransferPlanRejected(GRIPPER_NOT_OPEN, "gripper is not open at the start of approach")

        try:
            closed = profile.gripper_close_for_width(geometry.grasp_width_m)
        except ValueError as exc:
            raise TransferPlanRejected(GRIPPER_WIDTH_INVALID, str(exc)) from None
        names = profile.joint_names
        open_ = profile.gripper_open
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
        # Open only to item width + release clearance at the place, so the fingertips do not
        # sweep into a neighbour (C3b run11); open fully after the vertical retreat to carry_z.
        # A release width the jaw cannot reach below full open is rejected, never replaced by
        # a full open at the place (review minor 3).
        try:
            release_q = profile.gripper_contact_for_width(
                geometry.grasp_width_m + profile.gripper_release_clearance_m)
        except ValueError:
            raise TransferPlanRejected(GRIPPER_WIDTH_INVALID, "release width is outside the jaw model") from None
        if not closed < release_q < open_:
            raise TransferPlanRejected(GRIPPER_WIDTH_INVALID, "release width needs a full open at the place")
        release_open = self._gripper(arm, closed, release_q, profile)
        # Return to the same home joint vector we started from (one q5 of the two yaw twins).
        retreat, arm, _ = self._travel(pose, arm, request.home, request.home.z,
                                       request.carry_z, limits, profile, end_reference_q5=home[4])
        segments["release"] = ([release_open, [a + (release_q,) for a in retreat[0]],
                                self._gripper(retreat[0][-1], release_q, open_, profile)]
                               + [[a + (open_,) for a in seg] for seg in retreat[1:]])

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
                raise TransferPlanRejected(STATE_INVALID, f"{phase_id} has no motion")
            if elapsed > profile.phase_max_duration_s[phase_id]:
                raise TransferPlanRejected(
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
        return TransferMotionPlan(
            phases=tuple(phases), planner_revision=self.planner_revision,
            kinematics_revision=kin.revision, profile_revision=profile.revision,
            source_state_sequence=state.sequence,
            planned_at_monotonic_s=self.monotonic(),
            gripper_joint_names=(profile.gripper_joint,),
        )

    def _solve(self, pose: TopDownPose, limits: IkLimits, reference_q5: float) -> tuple[float, ...]:
        result = self.kinematics.solve_top_down(pose, limits, reference_q5=reference_q5)
        if not result.ok:
            raise TransferPlanRejected(
                result.reason, f"({pose.x:.4f}, {pose.y:.4f}, {pose.z:.4f}, yaw {pose.yaw:.3f}) {result.detail}")
        fk = self.kinematics.fk(result.joints)
        position = (fk.x, fk.y, fk.z)
        if (any(abs(a - b) > 1e-6 for a, b in zip(position, (pose.x, pose.y, pose.z)))
                or any(v < lo or v > hi for v, lo, hi in zip(
                    position, limits.workspace_min_m, limits.workspace_max_m))):
            raise TransferPlanRejected("OUTSIDE_WORKSPACE", "FK check of waypoint failed")
        return result.joints

    def _line(self, start_pose: TopDownPose, start_arm: tuple[float, ...], target_xyz: tuple[float, float, float],
              target_yaw: float | None, limits: IkLimits, profile: ArmPlanningProfile,
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
                raise TransferPlanRejected(WAYPOINT_DISCONTINUITY, f"joint jump near sample {i}")
            samples.append(arm)
        return samples, arm, TopDownPose(x1, y1, z1, arm[0] - arm[4])

    def _travel(self, start_pose: TopDownPose, start_arm: tuple[float, ...], target: TopDownPose,
                approach_z: float, carry_z: float, limits: IkLimits, profile: ArmPlanningProfile,
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
                 profile: ArmPlanningProfile) -> list[tuple[float, ...]]:
        count = math.ceil(abs(end - start) / profile.angular_step_rad - 1e-9)
        return [arm + (start + (end - start) * i / count,) for i in range(count + 1)]
