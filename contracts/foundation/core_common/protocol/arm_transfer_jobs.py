"""D-856 physical transfer proposals and admission; no application workflow facts."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .arm_transfer import ArmActionId, ArmScopeId
from .arm_transfer_preflight import ArmDigest, ArmPhysicalRef

ArmTransferRequestKey = Annotated[ArmPhysicalRef, Field(max_length=160)]
_Counter = Annotated[int, Field(strict=True, ge=0, lt=2**63)]
_Principal = Annotated[ArmPhysicalRef, Field(max_length=96)]


class ArmTransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")
    workcell_id: ArmScopeId
    instance_id: ArmScopeId
    object_ref: ArmPhysicalRef
    source: ArmPhysicalRef
    target: ArmPhysicalRef

    @model_validator(mode="after")
    def _distinct(self):
        if self.source == self.target:
            raise ValueError("source and target must differ")
        return self


class ArmTransferJobCreate(ArmTransferRequest):
    request_key: ArmTransferRequestKey


class ArmTransferJobAdmit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    expected_proposal_digest: ArmDigest
    expected_generation: _Counter


class ArmTransferJobSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    mission_id: ArmActionId
    action_kind: Literal["ARM_TRANSFER"]
    proposal_principal_id: _Principal
    request_key: ArmTransferRequestKey
    request_digest: ArmDigest
    proposal_digest: ArmDigest
    transfer: ArmTransferRequest
    resource_policy_digest: ArmDigest
    status: Literal["PROPOSED", "READY", "RUNNING", "ACTION_SUCCEEDED", "GOAL_CONFIRMED", "HOLD"]
    authority_epoch: _Counter | None
    dispatch_generation: _Counter | None
    approved_by: _Principal | None
    reason: ArmPhysicalRef | None

    @model_validator(mode="after")
    def _approval(self):
        approval = (self.approved_by, self.authority_epoch, self.dispatch_generation)
        complete = all(value is not None for value in approval)
        if any(value is not None for value in approval) and not complete:
            raise ValueError("approval identity and fence must be present together")
        if self.status == "PROPOSED" and complete:
            raise ValueError("a proposed job has no approval")
        if self.status not in {"PROPOSED", "HOLD"} and not complete:
            raise ValueError("an active job requires approval and a fence")
        if self.approved_by == self.proposal_principal_id:
            raise ValueError("the proposer cannot approve its own transfer")
        return self


class ArmTransferJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    job: ArmTransferJobSnapshot
