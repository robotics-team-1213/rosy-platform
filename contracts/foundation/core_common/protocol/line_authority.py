"""D-517 4 (M2), D-760 1-3: the Fleet movement authority for a CORE lane trip.

``POST /api/v1/line-follow/authority`` takes ``LineAuthorityRequest``; ``GET /api/v1/line-follow``
shows ``LineAuthorityStatus`` as ``authority`` while CORE enforces one. Field semantics are in
D-517 4 and its M2 implementation note; Fleet's sender and CORE's gate both read these bounds.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field
from .lane_route_guide import AuthorityRouteGuide

#: ``ttl_s`` is in (0, MAX_TTL_S], measured on CORE's line-follow clock (as ``hold_s``): ``time.monotonic``
#: on the Device, sim time under ``use_sim_time``; never the wall clock. 5 s since D-760 1 (was 2).
MAX_TTL_S = 5.0
#: The cap before D-760: what Fleet sends a CORE without ``line_follow_authority_shrink`` (D-760 3).
LEGACY_TTL_S = 2.0
#: ``until_m`` is in [0, MAX_UNTIL_M]: a few blocks ahead, never a whole lap.
MAX_UNTIL_M = 10.0
#: CORE takes a ``pose_stamp`` at most this far ahead of its newest odom sample (state stamps
#: ``odom_pose`` just after the line-follow manager logs the same sample).
STAMP_TOL_S = 0.05
#: A smaller end on the same leg within this refreshes the held end (Fleet map-pose noise); a
#: smaller one beyond it is ignored and does not refresh ``ttl_s``.
SHRINK_TOL_M = 0.02


class AuthorityRefused(Exception):
    """``(code, message)``: CORE refused an authority and dropped the held one; the API answers 409."""

    code = property(lambda self: self.args[0])


class LineAuthorityRequest(BaseModel):
    authority_id: str = Field(min_length=1, max_length=128)
    leg_id: str = Field(min_length=1, max_length=128)
    #: CORE wall-clock epoch seconds of the odom sample behind Fleet's pose (snapshot odom_pose.stamp).
    pose_stamp: float = Field(gt=0, allow_inf_nan=False)
    #: Metres along the trip leg from that pose to the end of the authority.
    until_m: float = Field(ge=0, le=MAX_UNTIL_M, allow_inf_nan=False)
    ttl_s: float = Field(gt=0, le=MAX_TTL_S, allow_inf_nan=False)
    #: D-760 3: true makes the end min(held end, this end) and refreshes ttl_s (``until_m`` 0: stand here);
    #: with no live authority on the leg it grants nothing (``reason`` shrink_none_held, none held).
    #: false or absent keeps D-517 4 (a smaller end is ignored and does not refresh ttl_s).
    shrink: bool = False
    #: D-760 3: rises per (robot, leg_id). CORE ignores a request at or below the newest seq it saw on that
    #: leg (``accepted`` false, ``reason`` stale_seq), and one without seq on a leg that has one
    #: (seq_required); absent on a leg that never had one: no order check (a Fleet before D-760).
    seq: Optional[int] = Field(default=None, ge=0)
    route_guide: Optional[AuthorityRouteGuide] = None


class LineAuthorityStatus(BaseModel):
    #: FREE may drive; HOLDING stands at the end (or cannot measure travel); EXPIRED: no fresh
    #: authority within ttl_s; NONE: required but none held.
    state: Literal["FREE", "HOLDING", "EXPIRED", "NONE"]
    authority_id: Optional[str] = None
    leg_id: Optional[str] = None
    remaining_m: Optional[float] = None   # odom-measured metres left to the end
    expires_in_s: Optional[float] = None
    reason: Optional[str] = None          # authority_end | authority_odom_stale | ... when not FREE
