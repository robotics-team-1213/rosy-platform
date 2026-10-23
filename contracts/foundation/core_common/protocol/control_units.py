"""D-855 bounded control-unit candidates and owner-sourced delegation snapshots."""

from datetime import datetime
from enum import Enum
import json
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


UnitId = Annotated[str, Field(strict=True, min_length=1, max_length=64,
                              pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
DelegationId = Annotated[str, Field(strict=True, min_length=1, max_length=128,
                                    pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Coordinate = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class ControlGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    x: Coordinate
    y: Coordinate
    yaw: Coordinate = 0.0


class ControlNavigationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target_unit: UnitId
    robot_id: UnitId
    goal: ControlGoal


class ControlWorkRequest(ControlNavigationCandidate):
    delegation_id: DelegationId


class ControlIngressRequest(ControlWorkRequest):
    origin_id: UnitId
    config_revision: UnitId


class ControlApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: int = Field(ge=1, strict=True)


class ControlDelegationState(str, Enum):
    PENDING = "PENDING"
    APPROVING = "APPROVING"
    REQUESTED = "REQUESTED"
    QUEUED = "QUEUED"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    UNKNOWN = "UNKNOWN"
    HOLD = "HOLD"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


class ControlDelegationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    origin_id: UnitId
    delegation_id: DelegationId
    request: ControlNavigationCandidate
    owner_unit: UnitId
    config_revision: UnitId
    status: ControlDelegationState
    revision: int = Field(ge=1, strict=True)
    owner_revision: int = Field(ge=0, strict=True)
    local_actor: str | None = Field(default=None, min_length=1, max_length=96,
                                   pattern=r"^[^\x00-\x1f\x7f]+$")
    local_task_id: DelegationId | None = None
    cancel_requested: bool = Field(strict=True)
    result: dict[str, Any]
    updated_at: datetime

    @field_validator("result")
    @classmethod
    def bounded_json_result(cls, value):
        try:
            size = len(json.dumps(value, allow_nan=False).encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise ValueError("owner result must be finite JSON") from exc
        if size > 65_536:
            raise ValueError("owner result exceeds 64 KiB")
        return value


class ControlUnitReply(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    unit_id: UnitId
    config_revision: UnitId
    stale: bool = Field(strict=True)
    delegation: ControlDelegationSnapshot
