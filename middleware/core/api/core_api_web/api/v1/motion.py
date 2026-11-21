"""core_api_web.api.v1.motion — D-603 CORE rotate-to-heading.

`POST /api/v1/motion/rotate_to` turns the robot in place to an odom heading (closed loop on odom
yaw, slow, bounded; `core_features.localization.rotate_to`). Only the D-541 trip-lease owner, or an
operator who names themselves (`operator_name`) while no lease is alive, may start it. `GET` reads
the last turn, `DELETE` stops a running one and, like every stop, is open to any operator.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Optional
from uuid import UUID

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


def _admit(svc: CoreServicesLike, auth: AuthContext, name: str, operator_name: str) -> bool:
    """Who may move the robot (D-541/D-603); returns whether the caller owns the trip lease."""
    require_calibration_owner(svc, auth, name)  # D-541 3: a live lease admits only its owner
    owner = owns_trip_lease(svc, auth)
    if not owner and not operator_name.strip():
        raise ApiError("OPERATOR_NAME_REQUIRED", 403,
                       f"{name} needs the trip-lease owner or a named operator (operator_name)")
    if svc.nav.mapping_active:
        raise ApiError("MAPPING_ACTIVE", 409, "mapping session owns navigation")
    TaskKind.MOVE.require(svc.capability)
    try:
        svc.nav.require_ready()
    except NavigationError as exc:
        raise ApiError(exc.code, 503, str(exc)) from exc
    return owner


@motion_router.post("/rotate_to", status_code=202)
def rotate_to(body: RotateToRequest, auth: AuthContext = Depends(operator),
              svc: CoreServicesLike = Depends(get_services)):
    mission = _mission(svc)
    owner = _admit(svc, auth, "rotate_to", body.operator_name)
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


class ReparkRequest(BaseModel):
    forward_m: float = 0.0   # robot body frame: forward +
    left_m: float = 0.0      # left +
    operator_name: str = Field(default="", max_length=64)


@motion_router.post("/repark", status_code=202)
def repark(body: ReparkRequest, auth: AuthContext = Depends(operator),
           svc: CoreServicesLike = Depends(get_services)):
    """Cell arm reach fix: a bounded sideways shift (<= 0.06 m) / fore-aft (<= 0.10 m) built of
    rotate_to and nudge missions (`core_features.localization.repark`); same admission as rotate_to."""
    runner = _mission(svc).repark
    owner = _admit(svc, auth, "repark", body.operator_name)
    try:
        started = runner.start(body.forward_m, body.left_m)
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", 400, str(exc)) from exc
    except MissionRefused as exc:
        raise ApiError(exc.code, 409, str(exc), detail=exc.detail) from exc
    svc.events.publish("motion.repark", source=f"api:{auth.role}", data={
        "forward_m": body.forward_m, "left_m": body.left_m, "lease_owner": owner,
        "operator_name": body.operator_name.strip() or None, "by": auth.label or auth.role})
    return JSONResponse(status_code=202, content=started)


class ScopedReparkRequest(ReparkRequest):
    correlation_id: str = Field(min_length=1, max_length=128, strict=True)
    expected_boot_id: UUID
    expected_owner_generation: int = Field(ge=0, strict=True)
    expected_idle_epoch: int = Field(ge=0, strict=True)
    expected_map_grid_id: str = Field(min_length=1, max_length=128, strict=True)
    expected_nav_run_id: UUID
    expected_nav_generation: int = Field(ge=0, strict=True)
    expected_nav_correlation_id: str = Field(min_length=1, max_length=128, strict=True)


@motion_router.post("/repark/run", status_code=202)
def scoped_repark(body: ScopedReparkRequest, auth: AuthContext = Depends(operator),
                  svc: CoreServicesLike = Depends(get_services)):
    runner = _mission(svc).repark
    identity = (str(body.expected_boot_id), str(body.expected_nav_run_id), body.expected_nav_generation,
                body.expected_nav_correlation_id, body.expected_map_grid_id)
    first = True

    @contextmanager
    def admission():
        nonlocal first
        with svc.state.map_grid_gate:
            if svc.state.map_grid_id != body.expected_map_grid_id:
                raise MissionRefused("REPARK_MAP_GRID_CHANGED", "loaded grid changed before correction")
            try:
                _admit(svc, auth, "repark", body.operator_name)
            except ApiError as exc:
                raise MissionRefused(exc.code, str(exc)) from exc
            if first and not svc.nav.matches_precision_handover(identity, body.expected_idle_epoch):
                raise MissionRefused("REPARK_HANDOVER_CHANGED", "exact grid-bound handover is unavailable")
            first = False
            yield

    previous = {"boot_id": body.expected_boot_id, "run_id": body.expected_nav_run_id,
                "owner_generation": body.expected_nav_generation, "correlation_id": body.expected_nav_correlation_id}
    try:
        started = runner.start_scoped(body.forward_m, body.left_m, correlation_id=body.correlation_id,
                                      expected_boot_id=body.expected_boot_id,
                                      expected_owner_generation=body.expected_owner_generation,
                                      expected_idle_epoch=body.expected_idle_epoch,
                                      expected_navigation=previous, admission=admission)
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", 400, str(exc)) from exc
    except MissionRefused as exc:
        raise ApiError(exc.code, 409, str(exc), detail=exc.detail) from exc
    svc.events.publish("motion.repark", source=f"api:{auth.role}", data=started["operation"])
    return JSONResponse(status_code=202, content=started)


@motion_router.get("/repark/run")
def scoped_repark_status(run_id: UUID | None = None,
                         correlation_id: str | None = None, _: AuthContext = Depends(viewer),
                         svc: CoreServicesLike = Depends(get_services)):
    if run_id is not None and correlation_id is not None:
        raise ApiError("VALIDATION_ERROR", 400, "supply only one repark lookup key")
    return _mission(svc).repark.scoped_status(run_id, correlation_id=correlation_id)


@motion_router.get("/repark")
def repark_status(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return _mission(svc).repark.status()


@motion_router.delete("/repark")
def repark_stop(_: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    runner = _mission(svc).repark
    runner.cancel()
    return runner.status()
