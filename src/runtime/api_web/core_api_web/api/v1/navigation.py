"""core_api_web.api.v1.navigation — NAV-001~005 주행·SLAM·로컬라이제이션(초기 위치추정)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core_api_web.api.v1.common import (
    enter_navigation_mode,
    operator,
    require_calibration_owner,
    require_kept,
    viewer,
)
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.errors import ApiError
from core_common.domain.tasks import TaskKind


navigation_router = APIRouter(prefix="/api/v1", tags=["navigation"])


class GoalRequest(BaseModel):
    x: float | None = None
    y: float | None = None
    yaw: float | None = 0.0
    waypoint: str | None = None
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)


@navigation_router.post("/navigation/goal")
def navigation_goal(body: GoalRequest, auth: AuthContext = Depends(operator),
                    svc: CoreServicesLike = Depends(get_services)):
    if svc.line_follow.active:
        raise ApiError("LINE_FOLLOW_ACTIVE", 409,
                       "stop the selected line-follow mode before accepting a navigation goal")
    TaskKind.NAVIGATE.require(svc.capability)
    require_kept(svc, "navigation.goal_navigation")
    spec = svc.nav.resolve_goal(x=body.x, y=body.y, yaw=body.yaw, waypoint=body.waypoint)
    enter_navigation_mode(svc, auth)
    svc.nav.goal(spec, source=f"api:{auth.role}", correlation_id=body.correlation_id)
    return {
        "accepted": True,
        "mode": svc.modes.mode.value,
        "goal": {"x": spec.x, "y": spec.y, "yaw": spec.yaw},
    }


@navigation_router.post("/navigation/cancel")
def navigation_cancel(auth: AuthContext = Depends(operator),
                      svc: CoreServicesLike = Depends(get_services)):
    svc.nav.cancel(source=f"api:{auth.role}")
    return {"navigation": svc.nav.nav_state.value}


@navigation_router.post("/navigation/home")
def navigation_home(auth: AuthContext = Depends(operator),
                    svc: CoreServicesLike = Depends(get_services)):
    if svc.line_follow.active:
        raise ApiError("LINE_FOLLOW_ACTIVE", 409,
                       "stop the selected line-follow mode before accepting a return-home request")
    TaskKind.RETURN_HOME.require(svc.capability)
    require_kept(svc, "navigation.return_home")
    enter_navigation_mode(svc, auth)
    svc.nav.home(source=f"api:{auth.role}")
    return {"accepted": True, "mode": svc.modes.mode.value}


@navigation_router.get("/navigation/state")
def navigation_state(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    readiness = svc.readiness.snapshot()
    return {
        "navigation": svc.nav.nav_state.value,
        "map_id": svc.state.map_id,
        "readiness": {
            "required": readiness.required,
            "ready": readiness.ready,
            "missing": list(readiness.missing),
            "reason": readiness.reason,
        },
    }


@navigation_router.get("/navigation/path")
def navigation_path(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return {"poses": svc.maps.get_path()}


class InitialPoseRequest(BaseModel):
    x: float
    y: float
    yaw: float = 0.0


@navigation_router.post("/localization/initialpose")
def initialpose(body: InitialPoseRequest, auth: AuthContext = Depends(operator),
                svc: CoreServicesLike = Depends(get_services)):
    TaskKind.NAVIGATE.require(svc.capability)
    # D-321 addendum: a pose reset mid-calibration corrupts the owner's odometry legs.
    require_calibration_owner(svc, auth, "initial pose")
    if svc.nav.executor is None:
        raise ApiError("CAPABILITY_NOT_SUPPORTED", 501, "localization executor unavailable")
    svc.nav.executor.send_initial_pose(body.x, body.y, body.yaw)
    svc.events.publish(
        "localization.initialpose",
        source=f"api:{auth.role}",
        data={"x": body.x, "y": body.y, "yaw": body.yaw, "source": "human"},
    )
    return {"accepted": True}


slam_router = APIRouter(prefix="/api/v1/slam", tags=["slam"])


class SlamSaveRequest(BaseModel):
    name: str = Field(
        default="rosy_map",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )


@slam_router.post("/start")
def slam_start(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    svc.capability.require("slam")
    require_calibration_owner(svc, auth, "slam start")
    svc.nav.start_mapping(source=f"api:{auth.role}")
    return {"mapping": True}


@slam_router.post("/stop")
def slam_stop(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    svc.capability.require("slam")
    require_calibration_owner(svc, auth, "slam stop")
    svc.nav.stop_mapping(source=f"api:{auth.role}")
    return {"mapping": False}


@slam_router.post("/save")
def slam_save(body: SlamSaveRequest, auth: AuthContext = Depends(operator),
              svc: CoreServicesLike = Depends(get_services)):
    svc.capability.require("slam")
    try:
        map_id = svc.nav.save_map(body.name, source=f"api:{auth.role}")
    except RuntimeError as exc:
        raise ApiError("CAPABILITY_NOT_SUPPORTED", 501, str(exc))
    return {"map_id": map_id}


@slam_router.post("/reset")
def slam_reset(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    svc.capability.require("slam")
    require_calibration_owner(svc, auth, "slam reset")
    svc.nav.reset_mapping(source=f"api:{auth.role}")
    return {"reset": True}
