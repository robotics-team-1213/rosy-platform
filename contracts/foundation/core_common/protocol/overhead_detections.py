"""Anonymous overhead-camera robot detections for the site Fleet console (D-457 4).

Display and cross-check only (D-268). A payload carries floor positions in map metres:
no image, no pixel coordinates and no robot id (Fleet pairs detections with robot
self-reported poses). Not an input to D-395 localization, traffic, bays or missions.
The machine source is ``test/fixtures/protocol/overhead-detections.v1.json``.

D-589: an optional ``tuning`` object reports the camera's recognition tuning (state, score,
real EV, AE locked). It is left out of the JSON when absent, so payloads without it are
unchanged.
"""

from __future__ import annotations

import math
from typing import Literal, Optional, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_DETECTIONS = 16
DetectorStatus = Literal["OK", "LEARNING", "CALIBRATION_REQUIRED", "SCENE_CHANGED"]
STATUSES = get_args(DetectorStatus)
TuningState = Literal["off", "waiting", "tuning", "locked", "paused", "unsupported"]
TUNING_STATES = get_args(TuningState)


def _no_boolean(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not a numeric detection value")
    return value


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("detection numbers must be finite")
    return value


class OverheadDetection(BaseModel):
    """One floor blob: position and floor-equivalent diameter in map metres."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float
    y: float
    footprint_m: float = Field(gt=0.0, le=2.0)
    score: float = Field(ge=0.0, le=1.0)
    marker_id: Optional[int] = Field(default=None, ge=0, strict=True,
                                     exclude_if=lambda value: value is None)

    @field_validator("x", "y", "footprint_m", "score", mode="before")
    @classmethod
    def _numbers_not_boolean(cls, value):
        return _no_boolean(value)

    @field_validator("x", "y", "footprint_m", "score")
    @classmethod
    def _numbers_finite(cls, value: float) -> float:
        return _finite(value)


class TuningStatus(BaseModel):
    """D-589 8: the source camera's recognition tuning, display only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: TuningState
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)  # recognition score, None unmeasured
    ev: Optional[float] = Field(default=None, ge=-10.0, le=10.0)  # applied compensation in real EV
    locked: bool = Field(strict=True)                              # AE locked as applied

    @field_validator("score", "ev", mode="before")
    @classmethod
    def _numbers_not_boolean(cls, value):
        return _no_boolean(value)

    @field_validator("score", "ev")
    @classmethod
    def _numbers_finite(cls, value: Optional[float]) -> Optional[float]:
        return None if value is None else _finite(value)


class OverheadDetectionsPayload(BaseModel):
    """One processed frame of one camera source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=64)
    map_id: str = Field(min_length=1, max_length=160)
    calibration_revision: Optional[str] = Field(default=None, min_length=1, max_length=128)
    processor_revision: str = Field(min_length=1, max_length=128)
    captured_at: float
    seq: int = Field(ge=0, le=0xFFFFFFFF, strict=True)
    status: DetectorStatus
    detections: tuple[OverheadDetection, ...] = Field(default=(), max_length=MAX_DETECTIONS)
    tuning: Optional[TuningStatus] = Field(default=None, exclude_if=lambda value: value is None)

    @field_validator("source_id", "map_id", "calibration_revision", "processor_revision")
    @classmethod
    def _identifiers_non_empty(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("source, map and revision identifiers must not be blank")
        return value

    @field_validator("captured_at", mode="before")
    @classmethod
    def _captured_not_boolean(cls, value):
        return _no_boolean(value)

    @field_validator("captured_at")
    @classmethod
    def _captured_finite(cls, value: float) -> float:
        return _finite(value)

    @model_validator(mode="after")
    def _status_rules(self) -> "OverheadDetectionsPayload":
        markers = [d.marker_id for d in self.detections if d.marker_id is not None]
        if len(markers) != len(set(markers)):
            raise ValueError("a marker may occur only once in one frame")
        if self.status != "OK" and self.detections:
            raise ValueError("detections are reported only with status OK")
        if self.status == "CALIBRATION_REQUIRED" and self.calibration_revision is not None:
            raise ValueError("CALIBRATION_REQUIRED carries no calibration revision")
        if self.status != "CALIBRATION_REQUIRED" and self.calibration_revision is None:
            raise ValueError("calibration_revision is required unless CALIBRATION_REQUIRED")
        return self
