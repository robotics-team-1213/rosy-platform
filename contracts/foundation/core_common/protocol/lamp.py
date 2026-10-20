"""Display-only identify request, canonically re-exported from schemas."""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class LampIdentifyRequest(BaseModel):
    """A short, display-only LED challenge (color None: the robot's own); the face owner may refuse it."""
    model_config = ConfigDict(extra="forbid")
    color: Optional[Literal["blue", "amber"]] = None
