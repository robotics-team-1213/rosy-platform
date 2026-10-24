"""Internal measured physical facts; no admission, completion or clearance verdict.

Poses and bounds use the observation's common frame. Object origin is explicit;
an absent object pose remains absent. Capture times are source UTC nanoseconds,
not refreshed when a consumer reads a record. Producer authentication and Fleet
policy/attempt/freshness checks belong to the consumers, not these records.
"""
from collections.abc import Mapping
from dataclasses import dataclass
import math
import re
from types import MappingProxyType


def _reference(value, *, maximum=192):
    if (not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)):
        raise ValueError("physical facts require explicit trimmed references")


def _digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("physical facts require a lowercase SHA-256 digest")


def _counter(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError("physical facts require nonnegative integer counters/timestamps")


def _vector(value, length):
    if not isinstance(value, (tuple, list)) or len(value) != length:
        raise ValueError("physical vector has the wrong shape")
    try:
        valid = all(type(item) in (int, float) and math.isfinite(item) for item in value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("physical vector must contain finite measured numbers")
    return tuple(float(item) for item in value)


@dataclass(frozen=True)
class PhysicalPose:
    position_m: tuple[float, float, float]
    orientation_xyzw: tuple[float, float, float, float]

    def __post_init__(self):
        position, orientation = _vector(self.position_m, 3), _vector(self.orientation_xyzw, 4)
        if not math.isclose(sum(value * value for value in orientation), 1.0, rel_tol=0, abs_tol=1e-6):
            raise ValueError("physical orientation must be a measured unit quaternion")
        object.__setattr__(self, "position_m", position)
        object.__setattr__(self, "orientation_xyzw", orientation)


@dataclass(frozen=True)
class Bounds3:
    min_m: tuple[float, float, float]
    max_m: tuple[float, float, float]

    def __post_init__(self):
        lower, upper = _vector(self.min_m, 3), _vector(self.max_m, 3)
        if any(low > high for low, high in zip(lower, upper)):
            raise ValueError("physical bounds are reversed")
        object.__setattr__(self, "min_m", lower)
        object.__setattr__(self, "max_m", upper)


@dataclass(frozen=True)
class LinkPhysicalState:
    bounds: Bounds3
    linear_velocity_m_s: tuple[float, float, float]
    angular_velocity_rad_s: tuple[float, float, float]

    def __post_init__(self):
        if not isinstance(self.bounds, Bounds3):
            raise ValueError("measured link bounds are required")
        object.__setattr__(self, "linear_velocity_m_s", _vector(self.linear_velocity_m_s, 3))
        object.__setattr__(self, "angular_velocity_rad_s", _vector(self.angular_velocity_rad_s, 3))


@dataclass(frozen=True)
class ArmPhysicalState:
    workcell_id: str
    instance_id: str
    journal_id: str
    owner_session_id: str
    model_digest: str
    calibration_revision: str
    transform_revision: str
    links_observed_at_ns: int
    links: Mapping[str, LinkPhysicalState]
    gripper_observed_at_ns: int
    gripper_state: str
    held_state: str
    held_object_ref: str | None

    def __post_init__(self):
        for value in (self.workcell_id, self.instance_id, self.owner_session_id,
                      self.calibration_revision, self.transform_revision):
            _reference(value)
        _reference(self.journal_id, maximum=64)
        _digest(self.model_digest)
        _counter(self.links_observed_at_ns)
        _counter(self.gripper_observed_at_ns)
        if (not isinstance(self.links, Mapping) or len(self.links) > 128
                or any(not isinstance(value, LinkPhysicalState) for value in self.links.values())):
            raise ValueError("physical links require a bounded measured map")
        links = dict(self.links)
        for name in links:
            _reference(name)
        object.__setattr__(self, "links", MappingProxyType(links))
        if not isinstance(self.gripper_state, str) or self.gripper_state not in {"OPEN", "CLOSED", "MOVING", "UNKNOWN"}:
            raise ValueError("gripper observation has an unsupported state")
        if not isinstance(self.held_state, str) or self.held_state not in {"NONE", "HELD", "UNKNOWN"}:
            raise ValueError("held-object observation has an unsupported state")
        if self.held_object_ref is not None:
            _reference(self.held_object_ref)
        if self.held_state == "NONE" and self.held_object_ref is not None:
            raise ValueError("an empty gripper cannot report a held object reference")


@dataclass(frozen=True)
class TransferObservation:
    evidence_id: str
    producer_id: str
    evaluator_revision: str
    sequence: int
    action_id: str
    attempt_id: str
    frame_id: str
    policy_digest: str
    catalog_digest: str
    bindings_digest: str
    object_ref: str
    object_origin_id: str
    object_observed_at_ns: int
    object_pose: PhysicalPose | None
    owners: tuple[ArmPhysicalState, ...]

    def __post_init__(self):
        for value in (self.evidence_id, self.producer_id, self.evaluator_revision, self.action_id,
                      self.attempt_id, self.frame_id, self.object_ref, self.object_origin_id):
            _reference(value)
        for value in (self.policy_digest, self.catalog_digest, self.bindings_digest):
            _digest(value)
        _counter(self.sequence)
        _counter(self.object_observed_at_ns)
        if self.object_pose is not None and not isinstance(self.object_pose, PhysicalPose):
            raise ValueError("object pose must be measured or explicitly absent")
        if not isinstance(self.owners, (tuple, list)) or len(self.owners) > 32:
            raise ValueError("physical participants require a bounded list")
        owners = tuple(self.owners)
        if any(not isinstance(owner, ArmPhysicalState) for owner in owners):
            raise ValueError("physical participants must carry their measured state")
        if len({(owner.workcell_id, owner.instance_id) for owner in owners}) != len(owners):
            raise ValueError("duplicate physical participant")
        object.__setattr__(self, "owners", owners)

    @property
    def sample_times_ns(self):
        return (self.object_observed_at_ns,) + tuple(
            timestamp for owner in self.owners
            for timestamp in (owner.links_observed_at_ns, owner.gripper_observed_at_ns))
