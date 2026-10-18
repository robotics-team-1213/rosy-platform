"""Workcell coordinator wire values on the OMX owner UDS (D-780 §2, §3).

``StopRequestSource.COORDINATOR`` lives in ``schemas.py``; the stop reason codes, barrier states
and the two barrier request bodies live here (``schemas.py`` has no size room).
"""

from __future__ import annotations

import enum
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")


class CoordinatorStopReason(str, enum.Enum):
    """The only reasons a coordinator stop may carry; the owner records it with the stop."""

    PARTNER_FAILED = "PARTNER_FAILED"
    PARTNER_UNKNOWN = "PARTNER_UNKNOWN"
    PARTNER_LINK_LOST = "PARTNER_LINK_LOST"
    BARRIER_TIMEOUT = "BARRIER_TIMEOUT"


class BarrierState(str, enum.Enum):
    NOT_REACHED = "not_reached"
    WAITING = "waiting"
    RELEASED = "released"
    EXPIRED = "expired"


def _identity(value: str) -> str:
    if not _IDENTITY.fullmatch(value):
        raise ValueError("barrier identities must be trimmed identifiers")
    return value


class BarrierQuery(BaseModel):
    """``GetBarrier``: one Action's barriers, or every unresolved paired Action without ``action_id``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str | None = Field(default=None, min_length=1, max_length=192)

    @field_validator("action_id")
    @classmethod
    def _query_identity(cls, value: str | None) -> str | None:
        return None if value is None else _identity(value)


class BarrierPartnerArrival(BaseModel):
    """The partner arm's arrival as the coordinator read it; recorded for tracing only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instance_id: str = Field(min_length=1, max_length=96)
    action_id: str = Field(min_length=1, max_length=192)
    arrived_at: str = Field(min_length=1, max_length=64)

    @field_validator("instance_id", "action_id")
    @classmethod
    def _partner_identity(cls, value: str) -> str:
        return _identity(value)


class BarrierReleaseRequest(BaseModel):
    """``ReleaseBarrier`` body; the owner checks every field against its own journal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(min_length=1, max_length=192)
    pair_id: str = Field(min_length=1, max_length=192)
    barrier_id: str = Field(min_length=1, max_length=96)
    authority_epoch: int = Field(strict=True, ge=0)
    dispatch_generation: int = Field(strict=True, ge=0)
    partner_arrival: BarrierPartnerArrival

    @field_validator("action_id", "pair_id", "barrier_id")
    @classmethod
    def _release_identity(cls, value: str) -> str:
        return _identity(value)


__all__ = ["BarrierPartnerArrival", "BarrierQuery", "BarrierReleaseRequest", "BarrierState",
           "CoordinatorStopReason"]
