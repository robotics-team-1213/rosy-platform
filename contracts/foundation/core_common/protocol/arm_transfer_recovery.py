"""D-899 bounded recovery wire facts; HTTP installation and physical acceptance are separate."""
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from .arm_transfer import ArmActionId, ArmJournalId, ArmScopeId
from .arm_transfer_jobs import ArmTransferJobAdmit, ArmTransferRequestKey
from .arm_transfer_observations import ArmTransferObservation, _sequence, _unique_owners
from .arm_transfer_preflight import ArmDigest, ArmPhysicalRef
from .device_actions import DeviceActionPhaseReceipt, DeviceActionState

_Counter = Annotated[int, Field(strict=True, ge=0, lt=2**63)]
_Principal = Annotated[ArmPhysicalRef, Field(max_length=96)]
_Phase = Literal["approach", "grasp", "transfer", "release"]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class ArmTransferRecoveryCreate(_Closed):
    request_key: ArmTransferRequestKey
    expected_context_digest: ArmDigest


class ArmTransferRecoveryApprove(ArmTransferJobAdmit):
    model_config = ConfigDict(revalidate_instances="always")
    expected_evidence_digest: ArmDigest


class ArmTransferRecoveryRequestSnapshot(_Closed):
    request_id: ArmActionId
    request_key: ArmTransferRequestKey
    proposal_digest: ArmDigest
    context_digest: ArmDigest
    proposed_by: _Principal
    requested_at_ns: _Counter


class ArmTransferRecoveryRequestResponse(_Closed):
    request: ArmTransferRecoveryRequestSnapshot


class ArmTransferExecutionReview(_Closed):
    scope: Literal["owner_reported_execution_only"]
    action_outcome: DeviceActionState
    owner_reason: Annotated[str, Field(max_length=256)] | None
    phase_summaries: Annotated[tuple[DeviceActionPhaseReceipt, ...], BeforeValidator(_sequence), Field(max_length=4)]
    failure_phase: _Phase | None
    last_reported_phase: _Phase | None
    task_outcome: Literal["succeeded", "failed", "unknown"]
    physical_failure_cause: None


class ArmTransferRecoveryPreview(_Closed):
    parent_mission_id: ArmActionId
    recovery_limit: Annotated[int, Field(strict=True, ge=1, le=1)]
    child_mission_id: ArmActionId | None
    status: Literal["UNAVAILABLE", "AVAILABLE", "WAITING_OBSERVATIONS", "READY_FOR_APPROVAL", "EXPIRED", "CHILD_CREATED"]
    context_digest: ArmDigest | None
    request_id: ArmActionId | None
    proposal_digest: ArmDigest | None
    evidence_digest: ArmDigest | None
    proposed_by: _Principal | None
    expected_generation: _Counter | None
    can_request: bool
    can_approve: bool
    reason: ArmPhysicalRef | None
    execution_authorized: Literal[False]
    execution_review: ArmTransferExecutionReview | None = None

    @model_validator(mode="after")
    def _binding(self):
        if self.status == "CHILD_CREATED":
            if (self.child_mission_id is None or self.child_mission_id == self.parent_mission_id
                    or self.can_request or self.can_approve):
                raise ValueError("a recovery child is separate and exhausts the retry budget")
        elif self.child_mission_id is not None:
            raise ValueError("only CHILD_CREATED carries a child identity")
        if self.can_request and (self.status in {"UNAVAILABLE", "CHILD_CREATED"}
                                or self.context_digest is None or self.expected_generation is None):
            raise ValueError("request capability requires an available source and generation")
        if self.status == "READY_FOR_APPROVAL":
            if any(value is None for value in (self.context_digest, self.request_id, self.proposal_digest,
                                               self.evidence_digest, self.proposed_by, self.expected_generation)):
                raise ValueError("approval readiness requires an exact request, proof and generation")
        elif self.can_approve:
            raise ValueError("only a ready recovery can be approved")
        return self


class ArmTransferRecoveryPreviewResponse(_Closed):
    recovery: ArmTransferRecoveryPreview


class ArmTransferRecoveryOwnerContext(_Closed):
    workcell_id: ArmScopeId
    instance_id: ArmScopeId
    journal_id: ArmJournalId
    owner_session_id: ArmPhysicalRef


class ArmTransferRecoveryEvidenceContext(_Closed):
    action_id: ArmActionId
    attempt_id: ArmActionId
    phase: Literal["PRE_DISPATCH"]
    not_before_ns: _Counter
    owners: Annotated[tuple[ArmTransferRecoveryOwnerContext, ...], BeforeValidator(_sequence),
                      Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def _owners(self):
        _unique_owners(self.owners)
        return self


class ArmTransferRecoveryContext(_Closed):
    mission_id: ArmActionId
    request_id: ArmActionId
    proposal_digest: ArmDigest
    purpose: Literal["RECOVERY_RESET"]
    execution_authorized: Literal[False]
    context: ArmTransferRecoveryEvidenceContext
    producer_id: _Principal
    evaluator_revision: ArmPhysicalRef
    frame_id: ArmPhysicalRef
    policy_digest: ArmDigest
    catalog_digest: ArmDigest
    bindings_digest: ArmDigest
    object_ref: ArmPhysicalRef
    object_origin_id: ArmPhysicalRef
    min_separation_ns: _Counter
    max_age_ns: _Counter


class ArmTransferRecoveryContextResponse(_Closed):
    context: ArmTransferRecoveryContext | None


class ArmTransferRecoveryObservationRequest(_Closed):
    purpose: Literal["RECOVERY_RESET"]
    expected_proposal_digest: ArmDigest
    observations: Annotated[tuple[ArmTransferObservation, ArmTransferObservation], BeforeValidator(_sequence)]


class ArmTransferRecoveryObservationReply(_Closed):
    evidence_digest: ArmDigest
