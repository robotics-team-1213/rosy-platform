"""Policy-eligible evidence submitted by credentialed site sources (D-268).

Task-initiation evidence contract. The server derives the source identity
from the credential, never from this payload. This is not D-328 goal-success
evidence, carries no image bytes, and is not a robot command.
"""

from __future__ import annotations

import math
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_OBSERVATION_KIND = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ASSET_KINDS = frozenset({"robot", "workcell", "object"})
_TASK_KINDS = frozenset({"navigate"})
_FORBIDDEN_CLIENT_FIELDS = frozenset({"source", "source_id", "token", "policy", "satisfied"})


class PolicyObservation(BaseModel):
    """Closed v1 observation envelope; no kind is registered server-side yet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1, max_length=64)

    @field_validator("kind")
    @classmethod
    def _kind_format(cls, value: str) -> str:
        if not _OBSERVATION_KIND.fullmatch(value):
            raise ValueError("observation kind must be a lowercase snake_case identifier")
        return value


class PolicyEvidencePayload(BaseModel):
    """One credentialed observation offered as policy-eligible task-initiation evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1, max_length=160)
    asset_kind: str
    asset_id: str = Field(min_length=1, max_length=128)
    task_kind: str = Field(min_length=1, max_length=64)
    captured_at: float
    map_id: str = Field(min_length=1, max_length=160)
    calibration_revision: str = Field(min_length=1, max_length=128)
    model_revision: str = Field(min_length=1, max_length=128)
    observation: PolicyObservation

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id_format(cls, value: str) -> str:
        if not _EVIDENCE_ID.fullmatch(value):
            raise ValueError("evidence_id must be a site evidence identifier")
        return value

    @field_validator("asset_id")
    @classmethod
    def _asset_id_format(cls, value: str) -> str:
        if not _ASSET_ID.fullmatch(value):
            raise ValueError("asset_id must be a site asset identifier")
        return value

    @field_validator("asset_kind")
    @classmethod
    def _asset_kind_closed_set(cls, value: str) -> str:
        if value not in _ASSET_KINDS:
            raise ValueError(f"asset_kind must be one of {', '.join(sorted(_ASSET_KINDS))}")
        return value

    @field_validator("task_kind")
    @classmethod
    def _task_kind_closed_set(cls, value: str) -> str:
        if value not in _TASK_KINDS:
            raise ValueError(f"task_kind must be one of {', '.join(sorted(_TASK_KINDS))}")
        return value

    @field_validator("map_id", "calibration_revision", "model_revision")
    @classmethod
    def _revision_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("map and revision identifiers must not be blank")
        return value

    @field_validator("captured_at", mode="before")
    @classmethod
    def _reject_boolean_timestamp(cls, value):
        if isinstance(value, bool):
            raise ValueError("boolean is not a valid evidence timestamp")
        return value

    @field_validator("captured_at")
    @classmethod
    def _finite_timestamp(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("evidence timestamp must be finite")
        return value

    @model_validator(mode="before")
    @classmethod
    def _reject_client_identity_and_goal_vocabulary(cls, value):
        if isinstance(value, dict):
            present = _FORBIDDEN_CLIENT_FIELDS.intersection(value)
            if present:
                raise ValueError(f"client may not set {', '.join(sorted(present))}")
        return value
