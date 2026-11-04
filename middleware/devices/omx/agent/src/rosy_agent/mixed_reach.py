"""D-402 IK reach for the mixed planner (D-781 §3 rule 4, D-778 G1): the ``mixed_cell.Reach`` shape.

``rosy.processes.palletizing.mixed_cell`` takes reach as an injected predicate
``reach(role, pose) -> bool`` with ``pose`` in the ``cell`` frame (x, y, z in m, yaw in rad) and
ships only an annulus stand-in. This composition answers the same question with the OMX analytic
top-down IK and a planning profile's protective limits: the pose is moved into the arm's base frame
(planar ``base_in_cell``: translate by the base x, y, rotate by -yaw; the base sits at cell z 0, as
in ``mixed_cell_doc``) and must have an in-limit top-down solution (yaw honoured modulo pi, D-402 §5).

It checks single poses only. It does not check the straight segments between them, phase durations
or collisions (the owner's planner rejects those at execution, D-402 §6-7), and its limits are the
simulation profile's nominal limits, not measured OMX hardware limits (cell_profile.yaml header).
The palletizing process is not imported: a pose is anything with ``x``, ``y``, ``z`` and ``yaw``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from omx_adapter.kinematics import IkLimits, IkResult, OmxKinematics, TopDownPose

Base = tuple[float, float, float]  # x, y, yaw of the arm base in the cell frame


def pose_in_base(base: Base, pose: Any) -> TopDownPose:
    """A cell-frame TCP pose in one arm's base frame (the mixed_submission.pose_in_base transform)."""
    bx, by, byaw = base
    dx, dy = float(pose.x) - bx, float(pose.y) - by
    c, s = math.cos(byaw), math.sin(byaw)
    return TopDownPose(c * dx + s * dy, -s * dx + c * dy, float(pose.z),
                       math.remainder(float(pose.yaw) - byaw, math.tau))


class IkReach:
    """``reach(role, pose)`` backed by ``OmxKinematics.solve_top_down`` for each arm base."""

    def __init__(self, bases: Mapping[str, Base], kinematics: OmxKinematics, limits: IkLimits) -> None:
        if not bases:
            raise ValueError("IK reach needs at least one arm base")
        self.bases = {role: tuple(float(v) for v in base) for role, base in bases.items()}
        if any(len(base) != 3 or not all(math.isfinite(v) for v in base) for base in self.bases.values()):
            raise ValueError("each arm base is a finite (x, y, yaw)")
        self.kinematics, self.limits = kinematics, limits

    def solve(self, role: str, pose: Any) -> IkResult:
        return self.kinematics.solve_top_down(pose_in_base(self.bases[role], pose), self.limits)

    def __call__(self, role: str, pose: Any) -> bool:
        return self.solve(role, pose).ok


def ik_reach_from_profile(bases: Mapping[str, Base], profile_path: Path | str, *,
                          kinematics: OmxKinematics | None = None) -> Callable[[str, Any], bool]:
    """IK reach with a planning profile's limits; refuses a profile reviewed against other geometry."""
    from omx_adapter.pose_plan import CellPlanningProfile

    kinematics = kinematics or OmxKinematics.load()
    profile = CellPlanningProfile.load(profile_path)
    if profile.kinematics_revision != kinematics.revision:
        raise ValueError("planning profile was reviewed against other kinematics")
    return IkReach(bases, kinematics, profile.ik_limits())


def workcell_bases(workcell: Any) -> dict[str, Base]:
    """``{role: (x, y, yaw)}`` from a planner Workcell (anything with ``arms[].role/x/y/yaw``)."""
    return {arm.role: (arm.x, arm.y, arm.yaw) for arm in workcell.arms}


__all__ = ["IkReach", "ik_reach_from_profile", "pose_in_base", "workcell_bases"]
