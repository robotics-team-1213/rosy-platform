"""D-836 bounded trip job admission requests; no new motion authority."""
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

RobotId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
PlaceRef = Annotated[str, Field(min_length=1, max_length=64)]


def _request_key(value: str) -> str:
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise ValueError("Request key must be trimmed and contain no control characters")
    return value


TripRequestKey = Annotated[str, Field(min_length=1, max_length=128), AfterValidator(_request_key)]


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


class TripJobStepSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    step_index: int = Field(ge=0)
    step: TripJobStep
    status: Literal["WAITING", "READY", "RUNNING", "ACTION_SUCCEEDED", "GOAL_CONFIRMED", "HOLD"]
    action_id: str | None
    attempt_id: str | None
    reason: str | None


class TripJobSnapshot(BaseModel):
    """Execution facts only; no Cell documents or application completion claims."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    mission_id: str
    request_key: TripRequestKey | None
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    robot_id: RobotId
    status: Literal["READY", "RUNNING", "ACTION_SUCCEEDED", "GOAL_CONFIRMED", "HOLD"]
    current_step_index: int = Field(ge=0)
    steps: list[TripJobStepSnapshot] = Field(min_length=1, max_length=8)
    reason: str | None
    updated_at: str


class TripJobReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    job: TripJobSnapshot
