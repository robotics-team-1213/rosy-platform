"""D-856 physical transfer planning facts, without admission or execution authority."""
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


def _reference(value: str) -> str:
    if value != value.strip() or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise ValueError("physical reference must be trimmed and control-free")
    return value


ArmPhysicalRef = Annotated[str, Field(strict=True, min_length=1, max_length=192), AfterValidator(_reference)]
ArmDigest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]


class ArmTransferCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workcell_id: ArmPhysicalRef
    instance_id: Annotated[ArmPhysicalRef, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")]
    catalog_digest: ArmDigest
    source: ArmPhysicalRef
    target: ArmPhysicalRef
    geometry: ArmPhysicalRef


class ArmTransferCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: ArmTransferCheckRequest
    journal_id: ArmPhysicalRef
    profile_revision: ArmDigest
    kinematics_revision: ArmDigest
    calibration_revision: ArmPhysicalRef
    transform_revision: ArmPhysicalRef
    planning_scene_revision: ArmPhysicalRef
    source_state_sequence: Annotated[int, Field(strict=True, ge=0)]
    state_age_s: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    simulation: Literal[True]
    collision_checked: Literal[False]

    @field_validator("simulation", "collision_checked", mode="before")
    @classmethod
    def _explicit_boolean(cls, value):
        if type(value) is not bool:
            raise ValueError("planning scope must be an explicit boolean")
        return value


class ArmTransferCheckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    check: ArmTransferCheckResult
    received_at: AwareDatetime


class ArmTransferCheckRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: Literal["ARM_CATALOG_CHANGED", "ARM_REFERENCE_UNAVAILABLE", "ARM_STATE_UNAVAILABLE",
                  "ARM_TRANSFER_UNPLANNABLE"]
    reason: ArmPhysicalRef

    @model_validator(mode="after")
    def _reason_matches_code(self):
        expected = {"ARM_CATALOG_CHANGED": "CATALOG_MISMATCH",
                    "ARM_REFERENCE_UNAVAILABLE": "REFERENCE_UNAVAILABLE", "ARM_STATE_UNAVAILABLE": "STATE_INVALID"}
        if self.code in expected and self.reason != expected[self.code]:
            raise ValueError("preflight refusal reason does not match its code")
        return self


ARM_PREFLIGHT_REJECTION_STATUS = {
    "ARM_CATALOG_CHANGED": 409, "ARM_REFERENCE_UNAVAILABLE": 404,
    "ARM_STATE_UNAVAILABLE": 409, "ARM_TRANSFER_UNPLANNABLE": 422,
}
