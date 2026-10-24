"""D-856 physical arm grant DTO; runtime acceptance requires separate installation."""
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .arm_transfer_preflight import ArmDigest, ArmPhysicalRef

ArmActionId = Annotated[ArmPhysicalRef, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")]
ArmScopeId = Annotated[ArmActionId, Field(max_length=96)]
ArmRevision = Annotated[ArmPhysicalRef, Field(max_length=128)]
ArmJournalId = Annotated[ArmPhysicalRef, Field(max_length=64)]


class ArmTransferCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action_kind: Literal["ARM_TRANSFER"]
    control_mode: Literal["fleet_managed"]
    workcell_id: ArmScopeId
    instance_id: ArmScopeId
    journal_id: ArmJournalId
    owner_session_id: ArmPhysicalRef
    catalog_digest: ArmDigest
    bindings_digest: ArmDigest
    resource_policy_digest: ArmDigest
    capability_revision: ArmRevision
    config_revision: ArmRevision


class ArmTransferPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    object_ref: ArmPhysicalRef
    catalog_digest: ArmDigest
    bindings_digest: ArmDigest
    source: ArmPhysicalRef
    target: ArmPhysicalRef
    resource_policy_digest: ArmDigest

    @model_validator(mode="after")
    def _different_locations(self):
        if self.source == self.target:
            raise ValueError("transfer source and target must differ")
        return self


class FleetArmTransferGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mission_id: ArmActionId
    step_id: ArmActionId
    action_id: ArmActionId
    attempt_id: ArmActionId
    owner_journal_id: ArmJournalId
    owner_session_id: ArmPhysicalRef
    request_digest: ArmDigest
    workcell_id: ArmScopeId
    instance_id: ArmScopeId
    action_kind: Literal["ARM_TRANSFER"]
    arm_transfer: ArmTransferPayload
    capability_revision: ArmRevision
    config_revision: ArmRevision
    authority_epoch: Annotated[int, Field(strict=True, ge=0)]
    dispatch_generation: Annotated[int, Field(strict=True, ge=0)]
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def _identities_and_expiry(self):
        identities = (self.mission_id, self.step_id, self.action_id, self.attempt_id)
        if len(set(identities)) != len(identities):
            raise ValueError("mission, step, action and attempt identities must be distinct")
        if self.expires_at <= self.issued_at:
            raise ValueError("grant expiry must follow issuance")
        return self
