"""D-732 native owner receipt; a correlation is never an execution grant."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NativeOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    boot_id: UUID
    kind: Literal["navigate", "home", "dock", "undock", "follow", "teleop"]
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    phase: Literal["SUBMITTED", "RUNNING", "TERMINAL"]
    result: Literal["SUCCEEDED", "FAILED", "CANCELED", "PREEMPTED", "EXPIRED"] | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")

    @model_validator(mode="after")
    def phase_matches_result(self):
        if (self.phase == "TERMINAL") != (self.result is not None):
            raise ValueError("only a terminal operation has a result")
        return self
