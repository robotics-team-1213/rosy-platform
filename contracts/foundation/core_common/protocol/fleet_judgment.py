"""Read-only Fleet judgment and observed closure DTOs (D-660); no execution authority."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict


class FleetJudgmentReceipt(BaseModel):
    """Read-only Fleet assessment, including untrusted/missing source metadata."""
    model_config = ConfigDict(extra="forbid")
    necessity: Literal["INTERVENE", "DO_NOT_INTERVENE", "ABSTAIN"]
    reason: str
    request: dict[str, Any]
    policy_revision: str
    evaluated_at: float
    valid_until: float
    shadow: Literal[True] = True
    action_admissible: Literal[False] = False


class FleetObservedClosure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["OPEN", "NATURAL_CLEARANCE", "CLEARANCE_OBSERVED", "OBSERVATION_ENDED"]
    action_credit: Literal["NONE", "UNVERIFIED"]
    reason: Optional[str]
    observed_at: Optional[str]
