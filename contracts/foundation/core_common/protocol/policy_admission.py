"""D-865 policy admission scope state and audit shapes; no new motion authority."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RobotId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
ScopeRevision = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]

POLICY_ADMISSION_PRINCIPAL = "fleet-policy-admission"


class PolicyAdmissionScope(BaseModel):
    """Human-defined approval scope. Fleet owns admission; apps never self-approve."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = False
    robots: list[RobotId] = Field(default_factory=list, max_length=32)
    step_approval_kinds: list[Literal["one_person"]] = Field(default_factory=list)
    max_admits: int = Field(default=1, ge=1)
    valid_until: str | None = None
    scope_revision: ScopeRevision

    @model_validator(mode="after")
    def _enabled_shape(self):
        if self.enabled:
            if not self.robots:
                raise ValueError("An enabled scope must name at least one robot")
            if not self.step_approval_kinds:
                raise ValueError("An enabled scope must name at least one approval kind")
            if len(set(self.robots)) != len(self.robots):
                raise ValueError("Scope robots must be unique")
        return self


class PolicyAdmissionStatus(BaseModel):
    """Readback only. Exhausted, expired or disabled scopes stay closed, never reset."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: PolicyAdmissionScope
    admits_issued: int = Field(default=0, ge=0)
    admits_remaining: int = Field(default=0, ge=0)
    reason: str | None = None


class PolicyAdmissionAuditEntry(BaseModel):
    """One auto-admit decision; the same admission checks as a human admit, recorded."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    mission_id: str = Field(min_length=1, max_length=64)
    decided_at: str
    principal: Literal["fleet-policy-admission"]
    scope_revision: ScopeRevision
    outcome: Literal["ADMITTED", "HELD"]
    generation: int = Field(ge=0)
    reason: str | None = None


class PolicyAdmissionToggleRequest(BaseModel):
    """Named-operator switch. Scope contents come from site config, never this body."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool


class PolicyAdmissionReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: PolicyAdmissionStatus


class PolicyAdmissionAuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entries: list[PolicyAdmissionAuditEntry] = Field(default_factory=list, max_length=100)
    cursor: str | None = None
