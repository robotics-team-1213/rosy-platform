"""Closed measured facts and physical receipts; no application completion verdicts."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from .arm_transfer import ArmActionId, ArmScopeId
from .arm_transfer_jobs import ArmTransferJobSnapshot
from .arm_transfer_preflight import ArmDigest, ArmPhysicalRef

_Counter = Annotated[int, Field(strict=True, ge=0, lt=2**63)]
_Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]


def _sequence(value):
    return tuple(value) if isinstance(value, list) else value


def _datetime(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value


_Vector = Annotated[tuple[_Number, _Number, _Number], BeforeValidator(_sequence)]
_Quaternion = Annotated[tuple[_Number, _Number, _Number, _Number], BeforeValidator(_sequence)]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class ArmObservationPose(_Closed):
    position_m: _Vector
    orientation_xyzw: _Quaternion

    @model_validator(mode="after")
    def _unit_orientation(self):
        if abs(sum(value * value for value in self.orientation_xyzw) - 1) > 1e-6:
            raise ValueError("measured orientation must be a unit quaternion")
        return self


class ArmObservationBounds(_Closed):
    min_m: _Vector
    max_m: _Vector

    @model_validator(mode="after")
    def _ordered(self):
        if any(low > high for low, high in zip(self.min_m, self.max_m)):
            raise ValueError("measured bounds must be ordered")
        return self


class ArmLinkObservation(_Closed):
    bounds: ArmObservationBounds
    linear_velocity_m_s: _Vector | None
    angular_velocity_rad_s: _Vector | None


class ArmTransferOwnerContext(_Closed):
    workcell_id: ArmScopeId
    instance_id: ArmScopeId
    journal_id: ArmPhysicalRef
    owner_session_id: ArmPhysicalRef
    model_digest: ArmDigest
    calibration_revision: ArmPhysicalRef
    transform_revision: ArmPhysicalRef


class ArmOwnerObservation(ArmTransferOwnerContext):
    links_observed_at_ns: _Counter
    links: Annotated[dict[ArmPhysicalRef, ArmLinkObservation], Field(min_length=1, max_length=128)]
    gripper_observed_at_ns: _Counter
    gripper_state: Literal["OPEN", "CLOSED", "MOVING", "UNKNOWN"]
    held_state: Literal["NONE", "HELD", "UNKNOWN"]
    held_object_ref: ArmPhysicalRef | None

    @model_validator(mode="after")
    def _held_reference(self):
        if self.held_state == "NONE" and self.held_object_ref is not None:
            raise ValueError("an empty gripper cannot name a held object")
        return self


def _unique_owners(owners):
    scopes = [(owner.workcell_id, owner.instance_id) for owner in owners]
    if len(set(scopes)) != len(scopes):
        raise ValueError("physical owner scopes must be unique")


class ArmTransferObservation(_Closed):
    evidence_id: ArmPhysicalRef
    producer_id: Annotated[ArmPhysicalRef, Field(max_length=96)]
    evaluator_revision: ArmPhysicalRef
    sequence: _Counter
    action_id: ArmActionId
    attempt_id: ArmActionId
    frame_id: ArmPhysicalRef
    policy_digest: ArmDigest
    catalog_digest: ArmDigest
    bindings_digest: ArmDigest
    object_ref: ArmPhysicalRef
    object_origin_id: ArmPhysicalRef
    object_observed_at_ns: _Counter
    object_pose: ArmObservationPose | None
    owners: Annotated[tuple[ArmOwnerObservation, ...], BeforeValidator(_sequence), Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def _owners(self):
        _unique_owners(self.owners)
        return self


class ArmTransferObservationRequest(_Closed):
    phase: Literal["PRE_DISPATCH", "POST_ACTION"]
    expected_request_digest: ArmDigest
    observations: Annotated[tuple[ArmTransferObservation, ArmTransferObservation], BeforeValidator(_sequence)]


class ArmTransferObservationContext(_Closed):
    mission_id: ArmActionId
    request_digest: ArmDigest
    action_id: ArmActionId
    attempt_id: ArmActionId
    status: Literal["PREPARED", "SUBMITTING", "ACTION_SUCCEEDED", "HOLD", "UNKNOWN"]
    phase: Literal["PRE_DISPATCH", "POST_ACTION"]
    not_before_ns: _Counter
    capture_deadline: Annotated[AwareDatetime, BeforeValidator(_datetime)] | None
    producer_id: Annotated[ArmPhysicalRef, Field(max_length=96)]
    evaluator_revision: ArmPhysicalRef
    frame_id: ArmPhysicalRef
    policy_digest: ArmDigest
    catalog_digest: ArmDigest
    bindings_digest: ArmDigest
    object_ref: ArmPhysicalRef
    object_origin_id: ArmPhysicalRef
    min_separation_ns: _Counter
    max_age_ns: _Counter
    owners: Annotated[tuple[ArmTransferOwnerContext, ...], BeforeValidator(_sequence), Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def _owners(self):
        _unique_owners(self.owners)
        return self


class ArmTransferObservationContextResponse(_Closed):
    context: ArmTransferObservationContext | None


class ArmTransferPhysicalReceipt(_Closed):
    receipt_id: ArmPhysicalRef
    mission_id: ArmActionId
    action_id: ArmActionId
    attempt_id: ArmActionId
    request_digest: ArmDigest
    workcell_id: ArmScopeId
    instance_id: ArmScopeId
    policy_digest: ArmDigest
    evidence_digest: ArmDigest
    object_ref: ArmPhysicalRef
    source: ArmPhysicalRef
    target: ArmPhysicalRef
    authority_epoch: _Counter
    dispatch_generation: _Counter
    validated_at_ns: _Counter
    physical_status: Literal["AT_TARGET_AND_CLEAR"]


class ArmTransferPhysicalReceiptResponse(_Closed):
    receipt: ArmTransferPhysicalReceipt


class ArmTransferObservationReply(_Closed):
    job: ArmTransferJobSnapshot
    receipt: ArmTransferPhysicalReceipt | None

    @model_validator(mode="after")
    def _receipt(self):
        job, receipt = self.job, self.receipt
        if (job.status == "GOAL_CONFIRMED") != (receipt is not None):
            raise ValueError("only a physically confirmed job carries a physical receipt")
        if receipt is not None:
            actual = (receipt.mission_id, receipt.workcell_id, receipt.instance_id, receipt.object_ref,
                      receipt.source, receipt.target, receipt.policy_digest, receipt.authority_epoch,
                      receipt.dispatch_generation)
            expected = (job.mission_id, job.transfer.workcell_id, job.transfer.instance_id, job.transfer.object_ref,
                        job.transfer.source, job.transfer.target, job.resource_policy_digest,
                        job.authority_epoch, job.dispatch_generation)
            if actual != expected:
                raise ValueError("physical receipt must match the confirmed job and original fence")
        return self


class ArmTransferCancelRequest(_Closed):
    reason: ArmPhysicalRef
