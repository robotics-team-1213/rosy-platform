"""Lane perception selection and observation readback, re-exported by schemas."""
from typing import Literal

from pydantic import BaseModel, ConfigDict


class LanePerceptionRequest(BaseModel):
    """Narrow administrator selection; models and filesystem paths are host-owned."""

    model_config = ConfigDict(extra="forbid")
    paint_source: Literal["threshold", "denoise", "learned"]


class LanePerceptionStatus(BaseModel):
    """Stored configuration and integrity, separate from recent frame evidence."""

    paint_source: Literal["threshold", "denoise", "learned"] = "threshold"
    camera_lane_mode: str = "line"
    model_ready: bool = False
    model_revision: str | None = None
    applied: bool = False
    applied_paint_source: Literal["threshold", "denoise", "learned", "denoise_fallback"] | None = None
    applied_model_revision: str | None = None
    applied_source_age_s: float | None = None
    reason: str = ""
