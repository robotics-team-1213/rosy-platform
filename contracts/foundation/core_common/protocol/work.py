"""D-664 common read projection; execution state remains owned by each ledger."""

import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


_Source = Literal["task", "mission", "trip", "cell_job"]


class FleetTaskStatus(str, enum.Enum):
    """Site Fleet task lifecycle; separate from a robot command ACK."""

    REQUESTED = "REQUESTED"
    QUEUED = "QUEUED"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    HOLD = "HOLD"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


class FleetWorkWait(BaseModel):
    """D-763 8 (v1.237): the trip read's ``wait`` answer (v1.232); null keys = no answer this tick."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: str | None = None
    waiting: bool | None = None
    bound_s: float | None = None
    over_bound: bool | None = None


class FleetWorkSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: _Source
    source_id: str = Field(min_length=1)
    action_kind: str = Field(min_length=1)
    status: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    workcell_id: str | None = None
    reason: str | None = None
    updated_at: str
    #: D-763 8 (v1.237): read projection only; ledger states are unchanged. null = a status this read does not know.
    visible_state: Literal["approval_pending", "in_progress", "waiting", "intervention", "ended"] | None = None
    wait: FleetWorkWait | None = None
    #: D-763 7: the step-kind registry's approval for a PROPOSED row; null otherwise.
    approval: Literal["two_person", "proposer_only", "one_person"] | None = None


class FleetWorkDecisionRequest(BaseModel):
    """D-763 7/5b (API v1.230): admit or reject a waiting job at the stop generation the operator saw."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_generation: int = Field(ge=0)


class FleetWorkOverview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observed_at: str
    rows: list[FleetWorkSummary] = Field(max_length=400)
    tasks_available: bool
    missions_available: bool
    cell_jobs_available: bool
    truncated_sources: list[_Source] = Field(max_length=4)
    #: D-763 9 (v1.237): 새 작업 kinds that can run on this site now (an action_kind of their rows).
    kinds: list[Literal["trip", "CELL_TRANSFER"]] = Field(max_length=2)
