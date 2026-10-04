"""Read-only preview freshness and raw-pixel exposure quality."""
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict


class VisionPreviewQuality(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    valid: bool
    reason: Literal['low_light', 'overexposed', 'usable']


class VisionPreviewStatus(BaseModel):
    available: bool = False
    stale: bool = False
    source: Optional[str] = None
    frame_id: Optional[str] = None
    captured_at: Optional[float] = None
    age_ms: Optional[int] = None
    width: int = 0
    height: int = 0
    overlay: str = 'none'
    sequence: int = 0
    quality: Optional[VisionPreviewQuality] = None
    quality_age_ms: Optional[int] = None
    raw_available: bool = False
    raw_sequence: Optional[int] = None
