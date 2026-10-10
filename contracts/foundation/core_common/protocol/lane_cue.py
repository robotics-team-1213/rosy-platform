"""D-511 rev 1: Fleet's lane return cue for a CORE CAMERA_LINE keep (user, 2026-10-10).

``POST /api/v1/line-follow/lane-cue`` takes ``LaneCueRequest``; ``GET /api/v1/line-follow`` shows
the unexpired one as ``lane_cue``. Fleet judges it from the ceiling camera (Rosy Cam) map pose and
the site map; it is a hint, never a permission: CORE reads it only while its own CAMERA_LINE keep
drives (``fleet_lane_cue_enabled``) and the IR guard, the body stop and the D-573 crosswalk gate
still win. Crosswalk zones do not travel here: they reach CORE as the D-517 authority
``crosswalks[]`` (D-573). Angles in degrees, robot frame left +.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

#: A cue lives at most this long; Fleet renews it at 2 Hz (ttl 1.0 s).
MAX_CUE_TTL_S = 2.0


class LaneGuide(BaseModel):
    """D-511 rev 2: the lane just ahead, from Fleet's map. A prior for the keep, never a command."""
    model_config = ConfigDict(extra="forbid")

    ahead_m: float = Field(gt=0, le=2, allow_inf_nan=False)
    #: Lane direction ``ahead_m`` along the lane minus the robot heading (robot frame, left +).
    heading_ahead_deg: Optional[float] = Field(None, ge=-180, le=180, allow_inf_nan=False)
    curvature_1pm: float = Field(ge=-50, le=50, allow_inf_nan=False)
    to_end_m: float = Field(ge=0, le=50, allow_inf_nan=False)
    next_place_id: str = Field(min_length=1, max_length=128)
    ring: bool


class LaneCueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cue_id: str = Field(min_length=1, max_length=160)
    fleet_epoch: str = Field(min_length=1, max_length=64)
    seq: int = Field(ge=0)
    ttl_s: float = Field(gt=0, le=MAX_CUE_TTL_S, allow_inf_nan=False)
    #: CORE wall-clock stamp of the newest odom in Fleet's pose (snapshot odom_pose.stamp, as the
    #: D-517 authority); a pivot angle is counted from the odom yaw at this stamp.
    pose_stamp: float = Field(gt=0, allow_inf_nan=False)
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
    guide: Optional[LaneGuide] = None
    #: D-511 rev 4: Fleet checked on the map that the turn circle (0.0926 m) fits here; WRONG_WAY turns
    #: in place only then, otherwise CORE holds (latched) for Fleet.
    turn_spot: bool = False
