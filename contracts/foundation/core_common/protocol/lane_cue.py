"""D-511 rev 1: Fleet's lane return cue for a CORE CAMERA_LINE keep (user, 2026-10-10).

``POST /api/v1/line-follow/lane-cue`` takes ``LaneCueRequest``; ``GET /api/v1/line-follow`` shows
the unexpired one as ``lane_cue``. Fleet judges it from the ceiling camera (Rosy Cam) map pose and
the site map; it is a hint, never a permission: CORE reads it only while its own CAMERA_LINE keep
drives (``fleet_lane_cue_enabled``) and the IR guard, the body stop and the D-573 crosswalk gate
still win. Angles in degrees, robot frame left +.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

#: A cue lives at most this long; Fleet renews it at 2 Hz (ttl 1.0 s).
MAX_CUE_TTL_S = 2.0


class CrosswalkAhead(BaseModel):
    """The next crosswalk along the lane: body front to its near edge (0 inside), its length."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    distance_m: float = Field(ge=0, le=5, allow_inf_nan=False)
    length_m: float = Field(ge=0, le=2, allow_inf_nan=False)


class LaneCueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cue_id: str = Field(min_length=1, max_length=160)
    fleet_epoch: str = Field(min_length=1, max_length=64)
    seq: int = Field(ge=0)
    ttl_s: float = Field(gt=0, le=MAX_CUE_TTL_S, allow_inf_nan=False)
    state: Literal["ON_LANE", "ON_LINE", "OFF_LANE", "OFF_MAP", "WRONG_WAY"]
    #: Where the lane centre is, seen from the robot (ON_LINE / OFF_LANE).
    side: Optional[Literal["left", "right"]] = None
    #: To the re-entry point on the lane, robot frame.
    bearing_deg: Optional[float] = Field(None, ge=-180, le=180, allow_inf_nan=False)
    #: Lane direction minus robot heading: turn this much to face the lane's way.
    turn_deg: Optional[float] = Field(None, ge=-180, le=180, allow_inf_nan=False)
    lane_heading_deg: Optional[float] = Field(None, ge=-180, le=180, allow_inf_nan=False)
    offset_m: Optional[float] = Field(None, ge=-10, le=10, allow_inf_nan=False)
    edge_id: Optional[str] = Field(None, max_length=128)
    crosswalk_ahead: Optional[CrosswalkAhead] = None
