"""D-541 1: trip lease contract pieces — TTL bounds, the refusal error, and the state snapshot fields.

Split from schemas.py, which has no size room. The lease state itself is CORE's (core/trip_lease.py).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, model_serializer


MIN_TTL_S = 1.0
MAX_TTL_S = 10.0
DEFAULT_TTL_S = 5.0


class TripLeaseError(Exception):
    """A request the lease refuses. ``code`` is the ERR-102 code."""

    def __init__(self, code: str, message: str, detail: Optional[dict] = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


class TripLeaseStatus(BaseModel):
    """The live Fleet trip lease (v1.157 additive). The holder's token is not shown."""

    lease_id: str
    trip_id: str
    holder: str
    operator_name: str
    since: str
    expires_in_s: float


class TripLeaseEnded(BaseModel):
    """Why the last trip lease ended, shown for a few seconds after the end."""

    lease_id: str
    reason: str   # mode_left | estop | taken_over | expired | released
    by: str = ""


class TripLeaseFields(BaseModel):
    """Base of StateSnapshot: two optional fields whose key is absent (not null) when unset."""

    trip_lease: Optional[TripLeaseStatus] = None
    trip_lease_ended: Optional[TripLeaseEnded] = None

    @model_serializer(mode="wrap")
    def _omit_absent_trip_lease(self, handler):
        data = handler(self)
        for key in ("trip_lease", "trip_lease_ended"):
            if data.get(key) is None:
                data.pop(key, None)
        return data
