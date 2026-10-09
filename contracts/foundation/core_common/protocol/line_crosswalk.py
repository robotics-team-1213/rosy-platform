"""D-573 6: ``line_follow.crosswalk``, the CORE crosswalk gate's armed zone."""
from typing import Optional

from pydantic import BaseModel


class LineCrosswalkStatus(BaseModel):
    """Camera source until the Fleet hint (D-573 1) lands; null outside an armed zone."""

    state: str                            # armed | approaching | looking | waiting | crossing
    zone_id: Optional[str] = None
    source: str = "camera"                # map | camera | both
    reason: Optional[str] = None          # person_present | look_unknown | sensor_stale | zone_lost
    waiting_s: Optional[float] = None
    look_progress: Optional[float] = None
