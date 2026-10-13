"""core_api_web.api.v1.motion — D-603 CORE rotate-to-heading.

`POST /api/v1/motion/rotate_to` turns the robot in place to an odom heading (closed loop on odom
yaw, slow, bounded; `core_features.localization.rotate_to`). Only the D-541 trip-lease owner, or an
operator who names themselves (`operator_name`) while no lease is alive, may start it. `GET` reads
the last turn, `DELETE` stops a running one and, like every stop, is open to any operator.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core_api_web.api.deps import AuthContext, CoreServicesLike, MissionRefused, NavigationError, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import operator, owns_trip_lease, require_calibration_owner, viewer
from core_common.domain.tasks import TaskKind

motion_router = APIRouter(prefix="/api/v1/motion", tags=["motion"])
KIND = "rotate_to"


class RotateToRequest(BaseModel):
    delta_deg: Optional[float] = None
    yaw_odom: Optional[float] = None
    tol_deg: float = 5.0
    max_rate_dps: float = 20.0
    timeout_s: float = 10.0
    operator_name: str = Field(default="", max_length=64)


def _mission(svc: CoreServicesLike):
    mission = getattr(svc, "loc_mission", None)
    if mission is None:
        raise ApiError("CAPABILITY_NOT_SUPPORTED", 501, "this runtime has no in-place rotation")
    return mission


@motion_router.post("/rotate_to", status_code=202)
def rotate_to(body: RotateToRequest, auth: AuthContext = Depends(operator),
              svc: CoreServicesLike = Depends(get_services)):
    mission = _mission(svc)
    require_calibration_owner(svc, auth, "rotate_to")  # D-541 3: a live lease admits only its owner
    owner = owns_trip_lease(svc, auth)
    if not owner and not body.operator_name.strip():
        raise ApiError("OPERATOR_NAME_REQUIRED", 403,
                       "rotate_to needs the trip-lease owner or a named operator (operator_name)")
    if svc.nav.mapping_active:
        raise ApiError("MAPPING_ACTIVE", 409, "mapping session owns navigation")
    TaskKind.MOVE.require(svc.capability)
    try:
        svc.nav.require_ready()
    except NavigationError as exc:
        raise ApiError(exc.code, 503, str(exc)) from exc
    try:
        started = mission.start_rotate_to(delta_deg=body.delta_deg, yaw_odom=body.yaw_odom, tol_deg=body.tol_deg,
                                          max_rate_dps=body.max_rate_dps, timeout_s=body.timeout_s)
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", 400, str(exc)) from exc
    except MissionRefused as exc:
        raise ApiError(exc.code, 409, str(exc), detail=exc.detail) from exc
    svc.events.publish("motion.rotate_to", source=f"api:{auth.role}", data={
        "delta_deg": body.delta_deg, "yaw_odom": body.yaw_odom, "tol_deg": body.tol_deg,
        "max_rate_dps": body.max_rate_dps, "timeout_s": body.timeout_s, "lease_owner": owner,
        "operator_name": body.operator_name.strip() or None, "by": auth.label or auth.role})
    return JSONResponse(status_code=202, content=started)


@motion_router.get("/rotate_to")
def rotate_to_status(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    """The running or last turn; `{state: idle}` when the last mission was not a turn."""
    status = _mission(svc).status()
    return status if status.get("kind") == KIND else {"kind": KIND, "state": "idle", "reason": None}


@motion_router.delete("/rotate_to")
def rotate_to_stop(_: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    mission = _mission(svc)
    if mission.status().get("kind") == KIND:
        mission.end("cancelled")  # a no-op once it has ended
    return rotate_to_status(_, svc)
