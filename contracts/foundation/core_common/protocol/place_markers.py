"""Floor place markers seen by a ceiling camera (D-564).

Display and teach input only: the poses become draft site map places an operator
saves; nothing here moves a robot. Source identity comes from the source token,
never from the payload (D-257).
"""

from __future__ import annotations

import math
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: DICT_4X4_50 has ids 0..49.
MAX_MARKER_ID = 49
MAX_MARKERS = 16


def check_place_marker_ids(ids, *, corner_ids: Iterable[int] | None = None,
                           robot_marker_ids: Iterable[int] = ()) -> tuple[int, ...]:
    """The one config rule both site-camera parsers apply; raises ValueError."""
    if not isinstance(ids, (list, tuple)) or any(
            type(marker_id) is not int or not 0 <= marker_id <= MAX_MARKER_ID for marker_id in ids):
        raise ValueError(f"place_markers must be a list of integer ids 0-{MAX_MARKER_ID}")
    if len(set(ids)) != len(ids):
        raise ValueError("place_markers ids must be distinct")
    if set(ids) & set(corner_ids or ()):
        raise ValueError("place_markers must not reuse corner_marker_ids")
    if set(ids) & set(robot_marker_ids):
        raise ValueError("place_markers must not reuse robot_markers ids")
    return tuple(ids)


class PlaceMarkerPose(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    marker_id: int = Field(ge=0, le=MAX_MARKER_ID, strict=True)
    x: float
    y: float
    yaw: float

    @field_validator("x", "y", "yaw", mode="before")
    @classmethod
    def _numbers(cls, value):
        if isinstance(value, bool):
            raise ValueError("boolean is not a numeric marker value")
        return value

    @field_validator("x", "y", "yaw")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("marker numbers must be finite")
        return value


class PlaceMarkerPayload(BaseModel):
    """Every configured place marker one source saw in one frame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    map_id: str = Field(min_length=1, max_length=160)
    calibration_revision: str = Field(min_length=1, max_length=128)
    captured_at: float = Field(allow_inf_nan=False)
    seq: int = Field(ge=0, le=0xFFFFFFFF, strict=True)
    markers: tuple[PlaceMarkerPose, ...] = Field(min_length=1, max_length=MAX_MARKERS)

    @field_validator("map_id", "calibration_revision")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("map and revision identifiers must not be blank")
        return value

    @field_validator("captured_at", mode="before")
    @classmethod
    def _no_bool_time(cls, value):
        if isinstance(value, bool):
            raise ValueError("boolean is not a capture time")
        return value

    @model_validator(mode="after")
    def _distinct_markers(self) -> "PlaceMarkerPayload":
        ids = [marker.marker_id for marker in self.markers]
        if len(set(ids)) != len(ids):
            raise ValueError("place marker ids must be distinct in one frame")
        return self

    @model_validator(mode="before")
    @classmethod
    def _reject_client_identity(cls, value):
        if isinstance(value, dict) and {"source_id", "source"} & value.keys():
            raise ValueError("client may not set the source")
        return value
