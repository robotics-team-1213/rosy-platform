"""Internal two-sample checks for the isolated managed-arm transfer profile.

World supplies measured facts. Fleet supplies an installed policy, authenticated
producer identity and durable attempt/boundary context. Success here writes
nothing: the coordinator must still check current claims, identities and fences
in the same transaction that stores its receipt and releases claims.
"""
from hashlib import sha256
import json
import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from core_common.protocol.arm_transfer import ArmJournalId
from core_common.protocol.arm_transfer_preflight import ArmDigest, ArmPhysicalRef
from rosy.world.state.projections.omx_geometry import ArmGeometry
from rosy.world.state.projections.physical_transfer import Bounds3, PhysicalPose, TransferObservation

from .dispatch_admission import normalize_resources

Counter = Annotated[int, Field(strict=True, ge=0, lt=2**63)]
Nonnegative = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
Scope = tuple[ArmPhysicalRef, ArmPhysicalRef]
ResourceId = Annotated[ArmPhysicalRef, Field(max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class TransferParticipant(_Closed):
    workcell_id: ArmPhysicalRef
    instance_id: ArmPhysicalRef
    arm_resource_id: ResourceId
    geometry: ArmGeometry
    calibration_revision: ArmPhysicalRef
    transform_revision: ArmPhysicalRef

    @field_serializer("geometry")
    def _serialize_geometry(self, value):
        return {"model_digest": value.model_digest, "required_links": sorted(value.required_links)}


class TransferOwnerTarget(_Closed):
    workcell_id: ArmPhysicalRef
    instance_id: ArmPhysicalRef
    journal_id: ArmJournalId
    owner_session_id: ArmPhysicalRef


class PhysicalTransferPolicy(_Closed):
    participants: Annotated[tuple[TransferParticipant, ...], Field(min_length=1, max_length=32)]
    primary: Scope
    zones: Annotated[tuple[Bounds3, ...], Field(min_length=1, max_length=32)]
    zone_resource_ids: Annotated[tuple[ResourceId, ...], Field(min_length=1, max_length=32)]
    object_resource_id: ResourceId
    zone_margin_m: Nonnegative
    producer_id: ArmPhysicalRef
    evaluator_revision: ArmPhysicalRef
    frame_id: ArmPhysicalRef
    catalog_digest: ArmDigest
    bindings_digest: ArmDigest
    object_ref: ArmPhysicalRef
    object_origin_id: ArmPhysicalRef
    source_pose: PhysicalPose
    target_pose: PhysicalPose
    position_tolerance_m: Nonnegative
    orientation_tolerance_rad: Annotated[Nonnegative, Field(le=math.pi)]
    max_linear_speed_m_s: Nonnegative
    max_angular_speed_rad_s: Nonnegative
    max_age_ns: Annotated[Counter, Field(gt=0, le=60_000_000_000)]
    min_separation_ns: Annotated[Counter, Field(gt=0)]

    @model_validator(mode="after")
    def _scope_and_timing(self):
        scopes = {(p.workcell_id, p.instance_id) for p in self.participants}
        if len(scopes) != len(self.participants) or self.primary not in scopes:
            raise ValueError("policy requires unique participants and an installed primary")
        if self.min_separation_ns > self.max_age_ns:
            raise ValueError("observation interval exceeds the freshness window")
        if (len(set(self.zone_resource_ids)) != len(self.zones)
                or len(self.zone_resource_ids) != len(self.zones)
                or len({p.arm_resource_id for p in self.participants}) != len(self.participants)):
            raise ValueError("policy requires distinct arm and zone resource bindings")
        self.resources  # Validate the existing shared claim-key format, including owner workcells.
        return self

    @property
    def resources(self):
        keys = [("workcell", p.workcell_id) for p in self.participants]
        keys += [("arm", p.arm_resource_id) for p in self.participants]
        keys += [("zone", value) for value in self.zone_resource_ids]
        keys.append(("object", self.object_resource_id))
        return tuple((kind, identifier) for kind, identifier, _ in normalize_resources(keys))

    @property
    def digest(self):
        document = self.model_dump(mode="json")
        return sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class TransferEvidenceContext(_Closed):
    action_id: ArmPhysicalRef
    attempt_id: ArmPhysicalRef
    phase: Literal["PRE_DISPATCH", "POST_ACTION"]
    not_before_ns: Counter
    owners: Annotated[tuple[TransferOwnerTarget, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def _unique(self):
        if (self.action_id == self.attempt_id or len({(p.workcell_id, p.instance_id) for p in self.owners})
                != len(self.owners)):
            raise ValueError("attempt context requires distinct identities and owner scopes")
        return self


class PhysicalEvidenceRejected(ValueError):
    """Stable rejection reason; rejection never changes the ledger or claims."""


def _pose_matches(actual, goal, policy):
    if actual is None or math.dist(actual.position_m, goal.position_m) > policy.position_tolerance_m:
        return False
    # Preserve measured input; remove allowed norm error only for angle comparison.
    a, b = actual.orientation_xyzw, goal.orientation_xyzw
    dot = abs(sum(x * y for x, y in zip(a, b))) / (math.hypot(*a) * math.hypot(*b))
    return 2 * math.acos(min(1., dot)) <= policy.orientation_tolerance_rad


def _outside(bounds, zone, margin):
    return any(high < low_zone - margin or low > high_zone + margin
               for low, high, low_zone, high_zone in zip(bounds.min_m, bounds.max_m, zone.min_m, zone.max_m))


def validate_transfer_observations(policy, context, samples, *, now_ns, authenticated_producer_id):
    """Check facts only; context time is READY acquisition or durable success.

    All participant grippers must be empty/open in this first isolated profile;
    carried objects and attachments have no reviewed bounds model here. The
    authenticated identity comes from ingress credentials, never a body field.
    """
    try:
        policy = PhysicalTransferPolicy.model_validate(policy)
        context = TransferEvidenceContext.model_validate(context)
    except ValueError as exc:
        raise PhysicalEvidenceRejected("PHYSICAL_CONTEXT_INVALID") from exc
    if (type(now_ns) is not int or not 0 <= now_ns < 2**63
            or not isinstance(samples, (tuple, list)) or len(samples) != 2
            or any(not isinstance(sample, TransferObservation) for sample in samples)):
        raise PhysicalEvidenceRejected("PHYSICAL_SAMPLE_INVALID")
    if authenticated_producer_id != policy.producer_id:
        raise PhysicalEvidenceRejected("PHYSICAL_PRODUCER_MISMATCH")
    participants = {(p.workcell_id, p.instance_id): p for p in policy.participants}
    targets = {(p.workcell_id, p.instance_id): p for p in context.owners}
    if set(targets) != set(participants):
        raise PhysicalEvidenceRejected("PHYSICAL_SCOPE_MISMATCH")
    first, second = samples
    if (first.evidence_id == second.evidence_id or first.sequence >= second.sequence
            or min(second.sample_times_ns) - max(first.sample_times_ns) < policy.min_separation_ns):
        raise PhysicalEvidenceRejected("PHYSICAL_ORDER_INVALID")
    goal = policy.source_pose if context.phase == "PRE_DISPATCH" else policy.target_pose
    for sample in samples:
        if (any(t <= context.not_before_ns or t > now_ns or now_ns - t > policy.max_age_ns
                for t in sample.sample_times_ns)):
            raise PhysicalEvidenceRejected("PHYSICAL_TIME_INVALID")
        expected = (policy.producer_id, policy.evaluator_revision, context.action_id, context.attempt_id,
                    policy.frame_id, policy.digest, policy.catalog_digest, policy.bindings_digest,
                    policy.object_ref, policy.object_origin_id)
        actual = (sample.producer_id, sample.evaluator_revision, sample.action_id, sample.attempt_id,
                  sample.frame_id, sample.policy_digest, sample.catalog_digest, sample.bindings_digest,
                  sample.object_ref, sample.object_origin_id)
        if actual != expected:
            raise PhysicalEvidenceRejected("PHYSICAL_CONTEXT_MISMATCH")
        if not _pose_matches(sample.object_pose, goal, policy):
            raise PhysicalEvidenceRejected("PHYSICAL_POSE_MISMATCH")
        if {(owner.workcell_id, owner.instance_id) for owner in sample.owners} != set(participants):
            raise PhysicalEvidenceRejected("PHYSICAL_SCOPE_MISMATCH")
        for owner in sample.owners:
            scope = (owner.workcell_id, owner.instance_id)
            installed, target = participants[scope], targets[scope]
            if ((owner.journal_id, owner.owner_session_id, owner.model_digest, owner.calibration_revision,
                 owner.transform_revision) != (target.journal_id, target.owner_session_id,
                 installed.geometry.model_digest, installed.calibration_revision, installed.transform_revision)):
                raise PhysicalEvidenceRejected("PHYSICAL_OWNER_MISMATCH")
            if set(owner.links) != installed.geometry.required_links:
                raise PhysicalEvidenceRejected("PHYSICAL_COVERAGE_INCOMPLETE")
            if owner.gripper_state != "OPEN" or owner.held_state != "NONE" or owner.held_object_ref is not None:
                raise PhysicalEvidenceRejected("PHYSICAL_GRIPPER_UNCONFIRMED")
            for link in owner.links.values():
                if (link.linear_velocity_m_s is None or link.angular_velocity_rad_s is None
                        or math.hypot(*link.linear_velocity_m_s) > policy.max_linear_speed_m_s
                        or math.hypot(*link.angular_velocity_rad_s) > policy.max_angular_speed_rad_s):
                    raise PhysicalEvidenceRejected("PHYSICAL_NOT_AT_REST")
                if any(not _outside(link.bounds, zone, policy.zone_margin_m) for zone in policy.zones):
                    raise PhysicalEvidenceRejected("PHYSICAL_ZONE_OCCUPIED")
