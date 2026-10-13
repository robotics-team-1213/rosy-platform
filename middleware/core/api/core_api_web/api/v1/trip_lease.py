"""D-541: the Fleet trip lease.

`PUT /trip-lease` opens the lease for the calling token (Fleet's own enrolment
token) or renews it (same token, same `lease_id`) inside `ttl_s`. `DELETE` is
the owner's normal end and does not stop the robot. `POST /takeover` is a
non-owner's explicit take: the lease ends and CORE leaves the robot IDLE in the
same request; MANUAL is a separate request after it.
While the lease lives, motion and mode writes from any other token get 409
`TRIP_LEASED` (see `common.require_calibration_owner`). Nothing here commands
motion beyond that stop (D-2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from core_api_web.api.deps import (
    TRIP_LEASE_DEFAULT_TTL_S,
    AuthContext,
    CoreServicesLike,
    Mode,
    TripLeaseError,
    get_services,
)
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import lease_actor, operator

trip_lease_router = APIRouter(prefix="/api/v1/trip-lease", tags=["trip-lease"])

_STATUS = {"VALIDATION_ERROR": 400, "FORBIDDEN": 403, "NOT_FOUND": 404}


class TripLeaseRequest(BaseModel):
    lease_id: str
    trip_id: str
    holder: str
    operator_name: str
    ttl_s: float = TRIP_LEASE_DEFAULT_TTL_S


class TakeoverRequest(BaseModel):
    lease_id: str
    reason: str = Field(default="", max_length=200)


def _raise(exc: TripLeaseError) -> None:
    raise ApiError(exc.code, _STATUS.get(exc.code, 409), str(exc), detail=exc.detail) from exc


def _refusal(svc: CoreServicesLike):
    """D-541 2: why a lease may not open now, or None."""
    session = svc.calibration.current()
    if session is not None:
        # D-541 8: the two leases exclude each other, whichever token holds the calibration.
        return TripLeaseError("CALIBRATION_ACTIVE",
                              f"calibration '{session['label']}' is in progress", {"session": session})
    if svc.safety.estop or svc.modes.is_emergency:
        return TripLeaseError("EMERGENCY_ACTIVE", "release emergency stop first")
    if svc.modes.mode is Mode.DOCKING:
        # The docking run owns the wheels; a lease over it would fence the operator's MANUAL rescue.
        return TripLeaseError("MODE_CONFLICT", "robot is DOCKING; a trip starts from IDLE or NAVIGATION")
    if svc.modes.mode is Mode.MANUAL:
        # Even with the driver's hands off: someone set MANUAL; IDLE first, then a new trip.
        return TripLeaseError("MANUAL_MODE", "robot is in MANUAL; set IDLE before a trip")
    return None


@trip_lease_router.put("")
def open_trip_lease(body: TripLeaseRequest, request: Request, auth: AuthContext = Depends(operator),
                    svc: CoreServicesLike = Depends(get_services)):
    # One admission with calibration: neither lease opens over the other in a race.
    with svc.modes.idle_admission:
        try:
            lease, renewed = svc.trip_lease.open(
                lease_id=body.lease_id, trip_id=body.trip_id, holder=body.holder,
                operator_name=body.operator_name, ttl_s=body.ttl_s, owner_id=auth.token_id,
                origin=request.client.host if request.client else "",
                refuse=lambda: _refusal(svc))
        except TripLeaseError as exc:
            _raise(exc)
    return {"trip_lease": lease, "renewed": renewed}


@trip_lease_router.delete("/{lease_id}")
def release_trip_lease(lease_id: str, auth: AuthContext = Depends(operator),
                       svc: CoreServicesLike = Depends(get_services)):
    try:
        return {"trip_lease_ended": svc.trip_lease.release(lease_id, auth.token_id)}
    except TripLeaseError as exc:
        _raise(exc)


@trip_lease_router.post("/takeover")
def take_over_trip_lease(body: TakeoverRequest, auth: AuthContext = Depends(operator),
                         svc: CoreServicesLike = Depends(get_services)):
    try:
        ended = svc.trip_lease.takeover(body.lease_id, by_id=auth.token_id, by=lease_actor(auth),
                                        reason=body.reason)
    except TripLeaseError as exc:
        _raise(exc)
    return {"trip_lease_ended": ended, "mode": svc.modes.mode.value}
