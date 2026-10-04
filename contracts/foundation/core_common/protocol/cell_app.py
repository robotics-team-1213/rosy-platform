"""Fleet Cell workspace requests and barrier readback; no robot control authority."""

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CellAppDocumentSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    document: dict[str, Any]
    expected_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CellAppCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    recipe_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    recipe_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    cell_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    cell_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class CellAppProposalRequest(CellAppCompileRequest):
    request_key: str = Field(min_length=1, max_length=160)
    workcell_id: str = Field(min_length=1, max_length=96)
    instance_id: str = Field(min_length=1, max_length=96)

    @field_validator("request_key", "workcell_id", "instance_id")
    @classmethod
    def _trimmed_identifier(cls, value):
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("identifier must be trimmed and contain no control characters")
        return value


class CellOperatorCheckpoint(BaseModel):
    """Read-only manual sheet barrier. Confirmed access is not implemented by this model."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)
    checkpoint_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["operator_sheet"]
    before_transfer_ordinal: int = Field(gt=0)
    pallet_id: str = Field(min_length=1, max_length=192)
    layer_index: int = Field(ge=0)
    sheet_pose_base: dict[str, float]
    thickness_m: float = Field(gt=0)
    status: Literal["WAITING", "WAITING_ACCESS"]
    updated_at: str

    @field_validator("pallet_id")
    @classmethod
    def _pallet_identifier(cls, value):
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("pallet identity must be trimmed without control characters")
        return value

    @field_validator("sheet_pose_base", mode="before")
    @classmethod
    def _finite_pose(cls, value):
        if (not isinstance(value, dict) or set(value) != {"x_m", "y_m", "z_m", "yaw_rad"}
                or any(type(item) not in (int, float) or not math.isfinite(item) for item in value.values())):
            raise ValueError("sheet pose must contain four finite numeric coordinates")
        return value

    @field_validator("updated_at")
    @classmethod
    def _aware_timestamp(cls, value):
        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("checkpoint timestamp requires a timezone")
        return value
