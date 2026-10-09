"""D-525 signal advice for a CORE lane trip: display only, no motion effect.

``POST /api/v1/line-follow/advice`` takes ``LineAdviceRequest``; ``GET /api/v1/line-follow`` shows
``LineAdviceStatus`` as ``advice`` while an unexpired advice carries a signal. Advice is never a
permission: ``may_enter`` is copied from Fleet's table for the operator, and nothing in the
line-follow decision path reads ``AdviceStore`` (pinned by an import-lint test).
"""
from __future__ import annotations

import threading
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from core_common.protocol.line_authority import MAX_TTL_S


class SignalAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(min_length=1, max_length=128)
    approach: str = Field(min_length=1, max_length=128)
    #: Route metres from the robot front to the stop line at ``pose_stamp``; < 0 means inside.
    stop_m: float = Field(allow_inf_nan=False)
    lamp: Literal["green", "yellow", "red"]
    left_s: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    green_in_s: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    exact: bool
    may_enter: bool  # display only, not a permission


class LineAdviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advice_id: str = Field(min_length=1, max_length=128)
    leg_id: str = Field(min_length=1, max_length=128)
    #: Per (robot, leg) counter from Fleet's one sender; breaks ties on the same ``pose_stamp``.
    seq: int = Field(ge=0)
    fleet_epoch: str = Field(min_length=1, max_length=64)
    #: Opaque CORE wall-clock stamp (snapshot odom_pose.stamp) echoed back by Fleet.
    pose_stamp: float = Field(gt=0, allow_inf_nan=False)
    ttl_s: float = Field(gt=0, le=MAX_TTL_S, allow_inf_nan=False)
    map_version: Optional[int] = None
    route_rev: Optional[int] = None
    signal: Optional[SignalAdvice] = None  # None clears the shown advice


class LineAdviceStatus(LineAdviceRequest):
    expires_in_s: float


class AdviceStore:
    """The newest advice, TTL on an injected monotonic clock.

    Ordering is ``(pose_stamp, seq)`` and only against an unexpired entry on the same leg and
    fleet epoch: ``pose_stamp`` is wall clock and the Pi has no RTC, so after the stored entry
    expires (or on a leg / Fleet restart) the next valid advice wins whatever its stamp.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entry: Optional[LineAdviceRequest] = None
        self._expires_at = 0.0

    def accept(self, req: LineAdviceRequest, now: float) -> tuple[bool, Optional[str]]:
        with self._lock:
            old = self._entry
            if (old is not None and now < self._expires_at and old.leg_id == req.leg_id
                    and old.fleet_epoch == req.fleet_epoch
                    and (req.pose_stamp, req.seq) <= (old.pose_stamp, old.seq)):
                return False, "stale"
            self._entry, self._expires_at = req, now + req.ttl_s
            return True, None

    def current(self, now: float) -> Optional[dict]:
        with self._lock:
            entry, expires_at = self._entry, self._expires_at
        if entry is None or entry.signal is None or now >= expires_at:
            return None
        return LineAdviceStatus(**entry.model_dump(),
                                expires_in_s=round(expires_at - now, 3)).model_dump()
