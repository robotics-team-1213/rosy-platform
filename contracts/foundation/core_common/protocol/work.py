"""D-664 common read projection; execution state remains owned by each ledger."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FleetWorkSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["task", "mission"]
    source_id: str = Field(min_length=1)
    action_kind: str = Field(min_length=1)
    status: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    workcell_id: str | None = None
    reason: str | None = None
    updated_at: str


class FleetWorkDecisionRequest(BaseModel):
    """D-763 7/5b: admit or reject a waiting job at the dispatch stop generation the operator saw."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_generation: int = Field(ge=0)


class FleetWorkOverview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observed_at: str
    rows: list[FleetWorkSummary] = Field(max_length=200)
    tasks_available: bool
    missions_available: bool
    truncated_sources: list[Literal["task", "mission"]] = Field(max_length=2)
