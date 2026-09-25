"""Vision detection evidence (D-137 T2) — typed, immutable, advisory-only.

A detector reports boxes; it never decides motion. CORE re-evaluates per
candidate and drops stale evidence. An empty `detections` with an advancing
`seq` is absence ("nothing there"); a `seq` jump is loss ("missed frames") —
the two must not be confused (D-136).
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field, field_validator, model_validator


#: D-136: older than this, the evidence is INVALID — a stale "clear" is the
#: most dangerous false negative.
DETECTION_MAX_AGE_S = 0.3


class Detection(BaseModel):
    """One box. Coordinates are normalized to the input frame (0..1)."""

    label: str
    x: float
    y: float
    w: float
    h: float
    confidence: float
    track_id: int | None = None

    @field_validator("label")
    @classmethod
    def _label_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("detection label required")
        return value

    @field_validator("confidence")
    @classmethod
    def _confidence_bounded(cls, value: float) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool) \
                or not 0.0 <= value <= 1.0:
            raise ValueError("detection confidence must be in [0, 1]")
        return value

    @field_validator("track_id")
    @classmethod
    def _track_non_negative(cls, value: int | None) -> int | None:
        if value is not None and (not isinstance(value, int)
                                  or isinstance(value, bool) or value < 0):
            raise ValueError("detection track_id must be non-negative")
        return value

    @model_validator(mode="after")
    def _box_inside_frame(self) -> "Detection":
        for name in ("x", "y", "w", "h"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) \
                    or not math.isfinite(value):
                raise ValueError(f"detection {name} must be finite")
        if not 0.0 <= self.x <= 1.0 or not 0.0 <= self.y <= 1.0:
            raise ValueError("detection origin must be normalized to [0, 1]")
        if not 0.0 < self.w <= 1.0 or not 0.0 < self.h <= 1.0:
            raise ValueError("detection size must be in (0, 1]")
        if self.x + self.w > 1.0 or self.y + self.h > 1.0:
            raise ValueError("detection box must fit inside the frame")
        return self


class DetectionEvidence(BaseModel):
    """One detector frame. `model_revision` binds weights + input geometry
    (D-47 pattern): an unknown revision fails closed downstream."""

    model_revision: str
    observed_at: float
    seq: int = Field(ge=0)
    input_width: int = Field(gt=0)
    input_height: int = Field(gt=0)
    input_fps: float = Field(gt=0)
    #: v1.11 additive: producer-side inference latency when reported.  The
    #: packet stays valid without it (plan 2026-09-20-yolo-advisory-sequence T2).
    inference_ms: float | None = Field(default=None, ge=0.0)
    detections: list[Detection] = Field(default_factory=list)

    @field_validator("model_revision")
    @classmethod
    def _revision_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("model revision required")
        return value

    @field_validator("observed_at")
    @classmethod
    def _stamp_finite(cls, value: float) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool) \
                or not math.isfinite(value):
            raise ValueError("observed_at must be finite")
        return value

    @field_validator("inference_ms")
    @classmethod
    def _latency_non_negative(cls, value: float | None) -> float | None:
        if value is not None and (not isinstance(value, (int, float))
                                  or isinstance(value, bool) or value < 0
                                  or not math.isfinite(value)):
            raise ValueError("inference_ms must be a non-negative number")
        return value

    def fresh(self, now: float, max_age_s: float = DETECTION_MAX_AGE_S) -> bool:
        return bool(self.observed_at <= now <= self.observed_at + max_age_s)

    def gap_after(self, last_seq: int) -> int:
        """Missed frames between `last_seq` and this evidence. Zero means the
        stream is continuous — an empty `detections` then reads as absence."""
        return max(0, self.seq - last_seq - 1)

    def of_label(self, label: str, min_confidence: float = 0.0) -> list[Detection]:
        return [d for d in self.detections
                if d.label == label and d.confidence >= min_confidence]
