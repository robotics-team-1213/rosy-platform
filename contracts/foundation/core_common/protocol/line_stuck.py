"""D-718 conditional stuck answer; CORE retains final action admission."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LineStuckPrecondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phase: Literal["ASKING"]
    attempts: int = Field(strict=True, ge=0)
