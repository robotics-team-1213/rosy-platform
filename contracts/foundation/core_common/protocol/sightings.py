"""Small derived observations for the site Fleet console (D-257).

This is a display/reconciliation contract. It carries no image bytes and is
not eligible input for automatic work (D-268).
"""

from __future__ import annotations

import math
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ROBOT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: How the worker measured this frame's image-to-map calibration (D-484).
CALIBRATION_SOURCES = ("corner_markers", "field_boundary")


class SiteSightingPayload(BaseModel):
    """One robot pose projected into the configured site map by a vision worker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    robot_id: str = Field(min_length=1, max_length=64)
    x: float
    y: float
    yaw: float
    captured_at: float
    seq: int = Field(ge=0, le=0xFFFFFFFF, strict=True)
    map_id: str = Field(min_length=1, max_length=160)
    calibration_revision: str = Field(min_length=1, max_length=128)
    processor_revision: str = Field(min_length=1, max_length=128)
    quality: float | None = Field(default=None, ge=0.0, le=1.0)
    # D-484: optional for a field_boundary source; a payload without corner
    # markers must name its calibration source instead.
    corner_marker_ids: tuple[int, int, int, int] | None = None
    calibration_source: str | None = Field(default=None, max_length=32)

    @field_validator("robot_id")
    @classmethod
    def _robot_id_format(cls, value: str) -> str:
        if not _ROBOT_ID.fullmatch(value):
            raise ValueError("robot_id must be a site robot identifier")
        return value

    @field_validator("map_id", "calibration_revision", "processor_revision")
    @classmethod
    def _revision_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("map and revision identifiers must not be blank")
        return value

    @field_validator("x", "y", "yaw", "captured_at", "quality", mode="before")
    @classmethod
    def _reject_boolean_numbers(cls, value):
        if isinstance(value, bool):
            raise ValueError("boolean is not a numeric sighting value")
        return value

    @field_validator("x", "y", "yaw", "captured_at", "quality")
    @classmethod
    def _finite_numbers(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("sighting numbers must be finite")
        return value

    @field_validator("corner_marker_ids")
    @classmethod
    def _four_unique_corner_ids(cls, value: tuple[int, int, int, int] | None):
        if value is None:
            return None
        if any(isinstance(marker_id, bool) or marker_id < 0 for marker_id in value):
            raise ValueError("corner marker ids must be non-negative integers")
        if len(set(value)) != 4:
            raise ValueError("four distinct corner marker ids are required")
        return value

    @field_validator("calibration_source")
    @classmethod
    def _known_calibration_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in CALIBRATION_SOURCES:
            raise ValueError(f"calibration source must be one of {', '.join(CALIBRATION_SOURCES)}")
        return value

    @model_validator(mode="after")
    def _markers_and_source_agree(self) -> "SiteSightingPayload":
        if self.calibration_source == "field_boundary" and self.corner_marker_ids is not None:
            raise ValueError("a field_boundary sighting carries no corner marker ids")
        if self.corner_marker_ids is None and self.calibration_source is None:
            raise ValueError("a sighting needs corner marker ids or a calibration source")
        return self

    @model_validator(mode="before")
    @classmethod
    def _reject_client_identity_and_media(cls, value):
        if isinstance(value, dict):
            forbidden = {"source_id", "source", "jpeg", "image", "image_url", "policy"}
            present = forbidden.intersection(value)
            if present:
                raise ValueError(f"client may not set {', '.join(sorted(present))}")
            marker_ids = value.get("corner_marker_ids")
            if isinstance(marker_ids, (list, tuple)) and any(type(v) is not int for v in marker_ids):
                raise ValueError("corner marker ids must be integers")
            source = value.get("calibration_source")
            if source is not None and not isinstance(source, str):
                raise ValueError("calibration source must be a string")
        return value
