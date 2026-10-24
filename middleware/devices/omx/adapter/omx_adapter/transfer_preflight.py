"""Read-only simulation reach checks against owner-installed physical references.

The caller supplies an owner-admitted measured state and its monotonic clock.
Successful calculation conveys no reservation, execution permit or collision guarantee.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping

from .kinematics import OmxKinematics, TopDownPose
from .manipulation_plan import ExecutionStateSnapshot
from .transfer_motion import (
    ArmPlanningProfile, GraspGeometry, TransferMotionRequest, TransferPlanRejected,
    STATE_INVALID, _SHA256, _finite, _text, validate_transfer_motion_plan,
)
from .transfer_planner import AnalyticTransferPlanner


@dataclass(frozen=True)
class TransferPose:
    pose: TopDownPose
    approach_z: float

    def __post_init__(self) -> None:
        if not isinstance(self.pose, TopDownPose):
            raise ValueError("a base-frame TopDownPose is required")
        object.__setattr__(self, "approach_z", _finite("approach_z", self.approach_z))


@dataclass(frozen=True)
class ArmTransferCatalog:
    """Physical installation data; constructing it is not device acceptance."""

    workcell_id: str
    instance_id: str
    profile_revision: str
    kinematics_revision: str
    calibration_revision: str
    transform_revision: str
    planning_scene_revision: str
    home: TopDownPose
    carry_z: float
    poses: Mapping[str, TransferPose]
    geometries: Mapping[str, GraspGeometry]
    frame: str = field(default="robot_base", init=False)
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("workcell_id", "instance_id", "profile_revision", "kinematics_revision",
                     "calibration_revision", "transform_revision", "planning_scene_revision"):
            _text(name, getattr(self, name))
        if not _SHA256.fullmatch(self.profile_revision):
            raise ValueError("profile_revision must be its content SHA-256")
        if not isinstance(self.home, TopDownPose):
            raise ValueError("home must be a base-frame TopDownPose")
        object.__setattr__(self, "carry_z", _finite("carry_z", self.carry_z))
        for name, kind in (("poses", TransferPose), ("geometries", GraspGeometry)):
            values = getattr(self, name)
            if not isinstance(values, Mapping) or not values:
                raise ValueError(f"{name} must be a non-empty physical reference map")
            for key, value in values.items():
                _text(f"{name} key", key)
                if not isinstance(value, kind):
                    raise ValueError(f"{name} contains an invalid physical value")
            object.__setattr__(self, name, MappingProxyType(dict(values)))
        document = {name: getattr(self, name) for name in (
            "workcell_id", "instance_id", "profile_revision", "kinematics_revision",
            "calibration_revision", "transform_revision", "planning_scene_revision", "frame", "carry_z")}
        document.update(schema="rosy.omx-transfer-catalog.v1", home=asdict(self.home),
                        poses={key: asdict(value) for key, value in self.poses.items()},
                        geometries={key: asdict(value) for key, value in self.geometries.items()})
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        object.__setattr__(self, "digest", hashlib.sha256(encoded).hexdigest())


@dataclass(frozen=True)
class TransferCheck:
    """Facts about one calculation, deliberately without a trajectory or permit."""

    workcell_id: str
    instance_id: str
    catalog_digest: str
    source: str
    target: str
    geometry: str
    profile_revision: str
    kinematics_revision: str
    calibration_revision: str
    transform_revision: str
    planning_scene_revision: str
    source_state_sequence: int
    observed_at_monotonic_s: float
    checked_at_monotonic_s: float


class TransferPreflight:
    """No driver, journal, claim or submit port exists on this service."""

    def __init__(self, catalog: ArmTransferCatalog, profile: ArmPlanningProfile,
                 kinematics: OmxKinematics, *, execution_state: Callable[[], ExecutionStateSnapshot],
                 monotonic: Callable[[], float]) -> None:
        if (not isinstance(catalog, ArmTransferCatalog) or not isinstance(profile, ArmPlanningProfile)
                or not isinstance(kinematics, OmxKinematics)):
            raise ValueError("installed catalog, planning profile and device kinematics are required")
        if (catalog.profile_revision != profile.revision
                or catalog.kinematics_revision != kinematics.revision
                or profile.kinematics_revision != kinematics.revision
                or catalog.planning_scene_revision != kinematics.planning_scene_revision):
            raise ValueError("installed catalog does not match this profile and kinematics")
        if not callable(execution_state) or not callable(monotonic):
            raise ValueError("owner-admitted state and its monotonic clock are required")
        self.catalog, self.profile, self.kinematics = catalog, profile, kinematics
        self.execution_state, self.monotonic = execution_state, monotonic
        self.planner = AnalyticTransferPlanner(kinematics, monotonic=self._clock)

    def _clock(self) -> float:
        try:
            return _finite("owner monotonic clock", self.monotonic())
        except (TypeError, ValueError) as exc:
            raise TransferPlanRejected(STATE_INVALID, "owner monotonic clock is invalid") from exc

    def _check_state(self, state: ExecutionStateSnapshot, now: float) -> None:
        catalog = self.catalog
        if not isinstance(state, ExecutionStateSnapshot):
            raise TransferPlanRejected(STATE_INVALID, "owner-admitted measured state is unavailable")
        if (state.observed_at_monotonic_s > now
                or now - state.observed_at_monotonic_s > self.profile.max_joint_state_age_s):
            raise TransferPlanRejected(STATE_INVALID, "measured state is stale or from the future")
        if (set(state.joint_positions) != set(self.profile.joint_names)
                or state.calibration_revision != catalog.calibration_revision
                or state.transform_revision != catalog.transform_revision
                or state.planning_scene_revision != catalog.planning_scene_revision):
            raise TransferPlanRejected(STATE_INVALID, "measured joints or installation revisions changed")

    def check_transfer(self, *, catalog_digest: str, source: str, target: str,
                       geometry: str) -> TransferCheck:
        catalog = self.catalog
        if catalog_digest != catalog.digest:
            raise TransferPlanRejected("CATALOG_MISMATCH", "installed physical catalog changed")
        for key, values in ((source, catalog.poses), (target, catalog.poses), (geometry, catalog.geometries)):
            if not isinstance(key, str) or key not in values:
                raise TransferPlanRejected("REFERENCE_UNAVAILABLE", "physical reference is unavailable")
        state = self.execution_state()
        started = self._clock()
        self._check_state(state, started)
        pick, place = catalog.poses[source], catalog.poses[target]
        request = TransferMotionRequest(catalog.home, pick.pose, place.pose,
                                        pick.approach_z, place.approach_z, catalog.carry_z)
        plan = self.planner.plan_transfer(request, self.profile, state, geometry=catalog.geometries[geometry])
        checked = self._clock()
        if checked < started or checked < plan.planned_at_monotonic_s:
            raise TransferPlanRejected(STATE_INVALID, "owner monotonic clock moved backwards")
        self._check_state(state, checked)
        validate_transfer_motion_plan(plan, self.profile, kinematics_revision=self.kinematics.revision,
                                      now_monotonic_s=checked)
        return TransferCheck(
            workcell_id=catalog.workcell_id, instance_id=catalog.instance_id, catalog_digest=catalog.digest,
            source=source, target=target, geometry=geometry, profile_revision=self.profile.revision,
            kinematics_revision=self.kinematics.revision, calibration_revision=state.calibration_revision,
            transform_revision=state.transform_revision, planning_scene_revision=state.planning_scene_revision,
            source_state_sequence=state.sequence, observed_at_monotonic_s=state.observed_at_monotonic_s,
            checked_at_monotonic_s=checked)
