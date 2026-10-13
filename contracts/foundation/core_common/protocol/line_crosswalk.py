"""D-573 6: ``line_follow.crosswalk``, the gate's armed zone or (개정 2026-10-10) CORE's camera-zone view."""
from typing import Optional

from pydantic import BaseModel


class LineCrosswalkStatus(BaseModel):
    """Camera source until the Fleet hint (D-573 1) lands; null = positively outside every zone."""

    # gate: armed | approaching | looking | waiting | crossing; any config: inside | ahead | unknown
    state: str
    zone_id: Optional[str] = None
    source: str = "camera"                # map | camera | both
    # gate: person_present | look_unknown | sensor_stale | zone_lost;
    # unknown: pose_stale | perception_stale | not_watched | zone_unplaced
    reason: Optional[str] = None
    waiting_s: Optional[float] = None
    look_progress: Optional[float] = None
