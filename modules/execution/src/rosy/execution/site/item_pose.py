"""Per-step ``item_at_pose`` goal predicate judged by the site (D-403 §5, D-328 §4).

A producer reports where the item is (``sim_model_pose``: a Gazebo model pose) and the gripper
release readback. It never says whether the goal is met: the site compares the pose with the
step's target under configured tolerances. Pure: no ROS, SQLite, HTTP or process import.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass

_EVIDENCE_FIELDS = frozenset({
    "predicate_id", "item_id", "evidence_source", "evidence_id", "producer_id", "model_name",
    "pose", "observed_at", "action_id", "attempt_id", "gripper_state", "gripper_evidence_id",
})
_POSE = ("x", "y", "z", "roll", "pitch", "yaw")
_TOLERANCE_FIELDS = frozenset({"schema", "basis", "xy_m", "z_m", "yaw_rad", "tilt_rad",
                               "yaw_period_rad", "item_centre_above_tcp_m"})


def _finite(value: object, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{field} must be positive")
    return float(value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 192:
        raise ValueError(f"{field} must be a non-empty trimmed string")
    return value


@dataclass(frozen=True)
class ItemPoseTolerance:
    """Configured limits; ``basis`` says which measurement they come from."""

    xy_m: float
    z_m: float
    yaw_rad: float
    tilt_rad: float
    yaw_period_rad: float
    item_centre_above_tcp_m: Mapping[str, float]
    basis: str

    @classmethod
    def from_mapping(cls, raw: Mapping) -> ItemPoseTolerance:
        if (not isinstance(raw, Mapping) or set(raw) != _TOLERANCE_FIELDS
                or raw["schema"] != "rosy.item-pose-tolerance.v1"):
            raise ValueError("item pose tolerance config has an invalid shape")
        offsets = raw["item_centre_above_tcp_m"]
        if not isinstance(offsets, Mapping) or not offsets:
            raise ValueError("item_centre_above_tcp_m must name at least one item")
        if not isinstance(raw["basis"], str) or len(raw["basis"].strip()) < 20:
            raise ValueError("item pose tolerances must state their basis")
        return cls(
            xy_m=_finite(raw["xy_m"], "xy_m", positive=True),
            z_m=_finite(raw["z_m"], "z_m", positive=True),
            yaw_rad=_finite(raw["yaw_rad"], "yaw_rad", positive=True),
            tilt_rad=_finite(raw["tilt_rad"], "tilt_rad", positive=True),
            yaw_period_rad=_finite(raw["yaw_period_rad"], "yaw_period_rad", positive=True),
            item_centre_above_tcp_m={_text(key, "item"): _finite(value, f"offset {key}")
                                     for key, value in offsets.items()},
            basis=raw["basis"].strip(),
        )


@dataclass(frozen=True)
class ItemPosePredicate:
    predicate_id: str
    condition: str
    item_id: str
    target: Mapping[str, float]
    tolerance: ItemPoseTolerance
    evidence_source: str

    def to_dict(self) -> dict:
        tolerance = asdict(self.tolerance)
        tolerance.pop("item_centre_above_tcp_m")
        return {"predicate_id": self.predicate_id, "condition": self.condition,
                "item_id": self.item_id, "target": dict(self.target), "tolerance": tolerance,
                "evidence_source": self.evidence_source}


def item_pose_predicate(job_id: str, step_index: int, inputs: Mapping,
                        tolerance: ItemPoseTolerance) -> ItemPosePredicate:
    """The predicate of one pallet.transfer step: the item's model centre at its place pose."""
    item = inputs["item"]
    if item not in tolerance.item_centre_above_tcp_m:
        raise ValueError(f"no configured item model offset for {item!r}")
    place = inputs["destination_pose_base"]
    item_id = f"{_text(job_id, 'job_id')}:{step_index}"
    return ItemPosePredicate(
        predicate_id=f"{item_id}:item_at_pose", condition="item_at_pose", item_id=item_id,
        target={"x": place["x_m"], "y": place["y_m"],
                "z": place["z_m"] + tolerance.item_centre_above_tcp_m[item], "yaw": place["yaw_rad"]},
        tolerance=tolerance, evidence_source="sim_model_pose",
    )


@dataclass(frozen=True)
class ItemPoseEvidence:
    """What a producer may report. There is deliberately no ``satisfied`` field."""

    predicate_id: str
    item_id: str
    evidence_source: str
    evidence_id: str
    producer_id: str
    model_name: str
    pose: Mapping[str, float]
    observed_at: float
    action_id: str
    attempt_id: str
    gripper_state: str
    gripper_evidence_id: str

    @classmethod
    def from_mapping(cls, raw: Mapping) -> ItemPoseEvidence:
        if not isinstance(raw, Mapping) or set(raw) != _EVIDENCE_FIELDS:
            raise ValueError("item pose evidence has an invalid shape (producers do not judge it)")
        if raw["evidence_source"] != "sim_model_pose":
            raise ValueError("item_at_pose evidence must come from sim_model_pose")
        pose = raw["pose"]
        if not isinstance(pose, Mapping) or set(pose) != set(_POSE):
            raise ValueError("pose must contain x, y, z, roll, pitch and yaw")
        values = {key: _text(raw[key], key) for key in _EVIDENCE_FIELDS - {"pose", "observed_at"}}
        return cls(pose={key: _finite(pose[key], f"pose.{key}") for key in _POSE},
                   observed_at=_finite(raw["observed_at"], "observed_at"), **values)

    def to_dict(self) -> dict:
        return {**asdict(self), "pose": dict(self.pose)}


@dataclass(frozen=True)
class ItemPoseVerdict:
    satisfied: bool
    reasons: tuple[str, ...]
    errors: Mapping[str, float]


def _wrapped(delta: float, period: float) -> float:
    return abs((delta + period / 2) % period - period / 2)


def verify_item_at_pose(predicate: ItemPosePredicate, evidence: ItemPoseEvidence, *,
                        now: float, max_age_s: float) -> ItemPoseVerdict:
    """Site judgement: identity, freshness, released gripper, xy, z, yaw (mod period), tilt."""
    tol, target, pose = predicate.tolerance, predicate.target, evidence.pose
    errors = {
        "xy": math.hypot(pose["x"] - target["x"], pose["y"] - target["y"]),
        "z": abs(pose["z"] - target["z"]),
        "yaw": _wrapped(pose["yaw"] - target["yaw"], tol.yaw_period_rad),
        # Angle between the item's up axis and the base z axis.
        "tilt": math.acos(max(-1.0, min(1.0, math.cos(pose["roll"]) * math.cos(pose["pitch"])))),
    }
    reasons = []
    if (evidence.predicate_id, evidence.item_id) != (predicate.predicate_id, predicate.item_id):
        reasons.append("item")
    if not 0 <= now - evidence.observed_at <= max_age_s:
        reasons.append("stale")
    if evidence.gripper_state != "OPEN":
        reasons.append("gripper")
    limits = {"xy": tol.xy_m, "z": tol.z_m, "yaw": tol.yaw_rad, "tilt": tol.tilt_rad}
    reasons += [name for name, limit in limits.items() if errors[name] > limit]
    return ItemPoseVerdict(satisfied=not reasons, reasons=tuple(reasons), errors=errors)


__all__ = [
    "ItemPoseEvidence", "ItemPosePredicate", "ItemPoseTolerance", "ItemPoseVerdict",
    "item_pose_predicate", "verify_item_at_pose",
]
