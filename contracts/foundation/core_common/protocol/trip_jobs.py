"""D-836 bounded trip job admission requests; no new motion authority."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

RobotId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
PlaceRef = Annotated[str, Field(min_length=1, max_length=64)]


class TripJobStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    to: PlaceRef
    via: list[PlaceRef] = Field(default_factory=list, max_length=8)


class TripJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: RobotId | None = None
    candidate_robot_ids: list[RobotId] | None = Field(default=None, min_length=1, max_length=8)
    request_key: str | None = Field(default=None, min_length=1, max_length=128)
    steps: list[TripJobStep] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _selection(self):
        if (self.robot_id is None) == (self.candidate_robot_ids is None):
            raise ValueError("Supply exactly one robot or candidate pool")
        if self.candidate_robot_ids is None:
            if self.request_key is not None:
                raise ValueError("Request key is supported only for candidate admission")
        else:
            if len(set(self.candidate_robot_ids)) != len(self.candidate_robot_ids):
                raise ValueError("Candidate robot IDs must be unique")
            if (not self.request_key or self.request_key != self.request_key.strip()
                    or any(ord(c) < 32 for c in self.request_key)):
                raise ValueError("Candidate admission requires a trimmed request key")
        return self
