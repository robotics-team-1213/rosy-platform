"""D-321 addendum: attended calibration session lease.

`POST /calibration/session` opens the lease for the calling token, the owner
renews it with `/heartbeat` inside `ttl_s`, and `DELETE` ends it. While it is
alive every screen shows `activity: CALIBRATING` and drive/mode writes from any
other token get 409 `CALIBRATION_ACTIVE` (see `common.require_calibration_owner`).
Nothing here commands motion (D-2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core_api_web.api.deps import (
    AuthContext,
    CalibrationSessionError,
    CoreServicesLike,
    Mode,
    ROLE_RANK,
    get_services,
)
from core_common.protocol.schemas import DockState, NavigationState
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import operator, viewer


calibration_router = APIRouter(prefix="/api/v1/calibration", tags=["calibration"])

_STATUS = {"VALIDATION_ERROR": 400, "FORBIDDEN": 403, "NOT_FOUND": 404,
           "CALIBRATION_ACTIVE": 409}


class SessionRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    label: str = Field(default="", max_length=80)
    ttl_s: float = 30.0


#: Navigation states that mean "a goal still owns the wheels".
_NAV_BUSY = frozenset({NavigationState.PLANNING, NavigationState.NAVIGATING, NavigationState.BLOCKED})


def _busy_reason(svc: CoreServicesLike) -> str | None:
    """Why a lease may not start now, or None.

    A lease fences *other* tokens; it must not be opened over motion someone
    else already started, or that motion keeps running under the owner's lease.
    """
    if svc.modes.mode not in (Mode.IDLE, Mode.MANUAL):
        return f"robot mode is {svc.modes.mode.value}; calibration starts from IDLE or MANUAL"
    if svc.nav.nav_state in _NAV_BUSY or svc.nav.mapping_active:
        return "navigation or mapping is in progress"
    if svc.docking.state in (DockState.DOCKING, DockState.UNDOCKING):
        return "docking is in progress"
    if svc.line_follow.active:
        return "line-follow is active"
    if svc.swarm.active:
        return "a swarm follow session is active"
    return None


def _raise(exc: CalibrationSessionError) -> None:
    detail = {"session": exc.session} if exc.session is not None else None
    raise ApiError(exc.code, _STATUS.get(exc.code, 400), str(exc), detail=detail) from exc


@calibration_router.get("/session")
def get_session(_: AuthContext = Depends(viewer),
                svc: CoreServicesLike = Depends(get_services)):
    return {"session": svc.calibration.current()}


@calibration_router.post("/session", status_code=201)
def start_session(body: SessionRequest, auth: AuthContext = Depends(operator),
                  svc: CoreServicesLike = Depends(get_services)):
    busy = _busy_reason(svc)
    if busy is not None:
        raise ApiError("MODE_CONFLICT", 409, f"calibration refused: {busy}")
    try:
        session = svc.calibration.start(
            kind=body.kind, label=body.label, ttl_s=body.ttl_s,
            owner_id=auth.token_id, owner_role=auth.role, owner_label=auth.label)
    except CalibrationSessionError as exc:
        _raise(exc)
    return {"session": session}


@calibration_router.post("/session/{session_id}/heartbeat")
def heartbeat_session(session_id: str, auth: AuthContext = Depends(operator),
                      svc: CoreServicesLike = Depends(get_services)):
    try:
        return {"session": svc.calibration.heartbeat(session_id, auth.token_id)}
    except CalibrationSessionError as exc:
        _raise(exc)


@calibration_router.delete("/session/{session_id}")
def end_session(session_id: str, auth: AuthContext = Depends(operator),
                svc: CoreServicesLike = Depends(get_services)):
    force = auth.rank >= ROLE_RANK["administrator"]
    try:
        return {"session": svc.calibration.end(session_id, by_id=auth.token_id, force=force)}
    except CalibrationSessionError as exc:
        _raise(exc)
