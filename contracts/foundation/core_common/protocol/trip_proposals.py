"""D-908 neutral trip proposals and separate operator admission; no cargo or process fields."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from .trip_jobs import RobotId, TripJobStep, TripRequestKey

_Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_Principal = Annotated[str, Field(min_length=1, max_length=96)]
ProposalId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]


class TripProposalCreate(BaseModel):
    """Same limits as the v1.292 candidate form of TripJobRequest, with the key required."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_robot_ids: list[RobotId] = Field(min_length=1, max_length=8)
    request_key: TripRequestKey
    steps: list[TripJobStep] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _unique(self):
        if len(set(self.candidate_robot_ids)) != len(self.candidate_robot_ids):
            raise ValueError("Candidate robot IDs must be unique")
        return self


class TripProposalAdmit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_proposal_digest: _Digest
    expected_generation: StrictInt = Field(ge=0, lt=2**63)


class TripProposalSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    proposal_id: ProposalId
    proposal_principal_id: _Principal
    request_key: TripRequestKey
    request_digest: _Digest
    proposal_digest: _Digest
    candidate_robot_ids: list[RobotId]
    steps: list[TripJobStep]
    status: Literal["PROPOSED", "ADMITTED"]
    dispatch_generation: int | None
    approved_by: _Principal | None
    mission_id: str | None

    @model_validator(mode="after")
    def _admission(self):
        admitted = (self.dispatch_generation, self.approved_by, self.mission_id)
        if (self.status == "ADMITTED") != all(value is not None for value in admitted) or (
                self.status == "PROPOSED" and any(value is not None for value in admitted)):
            raise ValueError("admission identity, fence and job are present together and only when admitted")
        if self.approved_by == self.proposal_principal_id:
            raise ValueError("the proposer cannot admit its own trip")
        return self


class TripProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    proposal: TripProposalSnapshot
