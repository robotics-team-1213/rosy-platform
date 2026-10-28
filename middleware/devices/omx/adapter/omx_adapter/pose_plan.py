"""Legacy Cell provenance adapter over the physical transfer planner (D-856).

Recipe/cell/item authority stays here. The shared backend consumes only physical
poses, reviewed simulation limits and owner-resolved object geometry.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from .kinematics import OmxKinematics, TopDownPose
from .manipulation_plan import ExecutionStateSnapshot
from .transfer_motion import (  # noqa: F401 (canonical and legacy public exports)
    ArmPlanningProfile, TransferMotionPlan, TransferMotionRequest, GraspGeometry, TransferPlanRejected,
    validate_transfer_motion_plan, PLANNER_REVISION, PROFILE_SCHEMA, STATE_INVALID, HOME_DEVIATION,
    GRIPPER_NOT_OPEN, CARRY_Z_INSUFFICIENT, WAYPOINT_DISCONTINUITY, PHASE_DURATION_EXCEEDED,
    GRIPPER_WIDTH_INVALID, GRASP_DEPTH_BELOW_FINGERTIPS, _finite, _text,
)
from .transfer_planner import AnalyticTransferPlanner

CellPlanningProfile = ArmPlanningProfile
CellTransferPlan = TransferMotionPlan
CellTransferPlanRejected = TransferPlanRejected
validate_cell_transfer_plan = validate_transfer_motion_plan
CELL_HASH_MISMATCH = "CELL_HASH_MISMATCH"
ITEM_GEOMETRY_MISMATCH = "ITEM_GEOMETRY_MISMATCH"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

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
    # Item width across the fingers (C3b B2): the grasp closes to the width-matched target.
    grasp_width_m: float

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
        object.__setattr__(self, "grasp_width_m", _finite("grasp_width_m", self.grasp_width_m, positive=True))

class CellTransferPlanProvider(Protocol):
    """Local pose-input planning port; implementations never execute a plan."""

    def plan_transfer(self, request: CellTransferRequest, profile: CellPlanningProfile,
                      state: ExecutionStateSnapshot) -> CellTransferPlan: ...

class AnalyticCellTransferPlanner(AnalyticTransferPlanner):
    """Preserve the accepted Cell/recipe boundary before physical calculation."""

    def __init__(self, kinematics: OmxKinematics, *,
                 accepted_cell_sha256: Callable[[], str | None],
                 accepted_item_geometry: Callable[[str, str], Mapping[str, float] | None],
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        if not isinstance(kinematics, OmxKinematics) or not callable(accepted_cell_sha256):
            raise ValueError("planner requires kinematics and an accepted-cell provider")
        if not callable(accepted_item_geometry):
            raise ValueError("planner requires an accepted recipe item-geometry provider")
        super().__init__(kinematics, monotonic=monotonic)
        self.accepted_cell_sha256 = accepted_cell_sha256
        self.accepted_item_geometry = accepted_item_geometry

    def plan_transfer(self, request: CellTransferRequest, profile: CellPlanningProfile,
                      state: ExecutionStateSnapshot) -> CellTransferPlan:
        if not isinstance(request, CellTransferRequest) or not isinstance(profile, CellPlanningProfile):
            raise TypeError("plan_transfer requires CellTransferRequest and CellPlanningProfile")
        if not isinstance(state, ExecutionStateSnapshot):
            raise TypeError("plan_transfer requires an ExecutionStateSnapshot")
        accepted = self.accepted_cell_sha256()
        if not isinstance(accepted, str) or accepted != request.cell_sha256:
            raise CellTransferPlanRejected(CELL_HASH_MISMATCH, "grant cell_sha256 is not the accepted cell")
        geometry = self.accepted_item_geometry(request.recipe_sha256, request.item)
        if (not isinstance(geometry, Mapping)
                or geometry.get("grasp_width_m") != request.grasp_width_m
                or geometry.get("grasp_depth_m") != request.grasp_depth_m):
            raise CellTransferPlanRejected(ITEM_GEOMETRY_MISMATCH,
                                           "grasp width/depth are not the accepted recipe's item")
        height = geometry.get("height_m")
        if (isinstance(height, bool) or not isinstance(height, (int, float))
                or request.grasp_depth_m > float(height) - profile.fingertip_overhang_m + 1e-12):
            raise CellTransferPlanRejected(GRASP_DEPTH_BELOW_FINGERTIPS,
                                           "grasp_depth_m exceeds item height - fingertip_overhang_m")
        try:
            physical = GraspGeometry(request.grasp_width_m, request.grasp_depth_m, height, True)
        except ValueError as exc:
            raise CellTransferPlanRejected(GRASP_DEPTH_BELOW_FINGERTIPS, str(exc)) from exc
        motion = TransferMotionRequest(request.home, request.pick, request.place,
                                       request.pick_approach_z, request.place_approach_z, request.carry_z)
        return super().plan_transfer(motion, profile, state, geometry=physical)
