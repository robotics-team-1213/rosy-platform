"""core_api_web.api.v1.docking — DNC-003/005 도크 등록·teach·도킹 명령."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core_api_web.api.v1.common import admin, operator, viewer
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.errors import ApiError
from core_api_web.api.deps import DockError, DockInstance, DockType
from core_common.domain.tasks import TaskKind


docking_router = APIRouter(prefix="/api/v1/docking", tags=["docking"])

#: DockError 코드 → HTTP. 거부 사유를 그대로 계약으로 노출한다.
_DOCK_HTTP = {
    "NOT_FOUND": 404,
    "DOCK_EXISTS": 409,
    "UNKNOWN_DOCK_TYPE": 400,
    "MAP_MISMATCH": 409,
    "EMERGENCY_ACTIVE": 409,
    "DOCKING_ACTIVE": 409,
    "NOT_DOCKED": 409,
    "DOCK_REQUIRED": 400,
    "CAPABILITY_NOT_SUPPORTED": 501,
    "LINE_FOLLOW_ACTIVE": 409,
    "MODE_CONFLICT": 409,
    "NO_ODOMETRY": 409,
}


def _dock_error(exc: DockError) -> ApiError:
    return ApiError(exc.code, _DOCK_HTTP.get(exc.code, 400), str(exc))


class DockTypeRequest(BaseModel):
    name: str
    detector: str = "simulated"
    staging_offset_m: float = 0.7
    docking_threshold_m: float = 0.05
    max_retries: int = 3
    undock_distance_m: float = 0.35
    tag_id: int | None = None
    tag_size_m: float | None = None
    # 주차형 (docs/plans/2026-09-23-lane-network-parking-design.md). 기본값은 원래 도크.
    staging: bool = True
    approach: str = "bearing"
    settle: str = "agent"
    tag_offset_m: float | None = None
    acquire_creep_m: float = 0.0
    backoff_m: float | None = None
    undock_turn_rad: float = 0.0


class DockRequest(BaseModel):
    id: str
    type: str
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    map_id: str | None = None
    agent_url: str | None = None


class DockCommand(BaseModel):
    dock: str | None = None


@docking_router.get("/status")
def docking_status(_: AuthContext = Depends(viewer),
                   svc: CoreServicesLike = Depends(get_services)):
    """상태 조회는 capability 로 막지 않는다 — 막으면 대시보드가 "도킹 없음"
    조차 표시할 수 없다."""
    body = svc.docking.status().model_dump()
    body["supported"] = svc.capability.supports("docking.supported")
    return body


@docking_router.get("/docks")
def list_docks(_: AuthContext = Depends(viewer),
               svc: CoreServicesLike = Depends(get_services)):
    return {"docks": [d.model_dump() for d in svc.docking.database.list()]}


@docking_router.post("/types")
def create_dock_type(body: DockTypeRequest, _: AuthContext = Depends(admin),
                     svc: CoreServicesLike = Depends(get_services)):
    try:
        return svc.docking.database.add_type(DockType(**body.model_dump())).model_dump()
    except (DockError, ValueError) as exc:
        raise _dock_error(exc) if isinstance(exc, DockError) else \
            ApiError("VALIDATION_ERROR", 400, str(exc))


@docking_router.post("/docks")
def create_dock(body: DockRequest, _: AuthContext = Depends(admin),
                svc: CoreServicesLike = Depends(get_services)):
    try:
        return svc.docking.database.add(DockInstance(**body.model_dump())).model_dump()
    except DockError as exc:
        raise _dock_error(exc)


@docking_router.delete("/docks/{dock_id}")
def delete_dock(dock_id: str, _: AuthContext = Depends(admin),
                svc: CoreServicesLike = Depends(get_services)):
    try:
        svc.docking.remove_dock(dock_id)
    except DockError as exc:
        raise _dock_error(exc)
    return {"deleted": dock_id}


@docking_router.post("/docks/{dock_id}/teach")
def teach_dock(dock_id: str, auth: AuthContext = Depends(operator),
               svc: CoreServicesLike = Depends(get_services)):
    """teach-by-docking — 지금 로봇이 선 자리를 도크 포즈로 기록한다.

    줄자로 SLAM 맵 좌표를 재서 쓸 만한 값이 나오지 않는다. 이렇게 기록해야
    포즈가 나중에 복귀에 쓸 바로 그 맵과 자기모순 없이 일치한다.
    """
    snapshot = svc.state.snapshot()
    try:
        taught = svc.docking.database.teach(
            dock_id, x=snapshot.pose.x, y=snapshot.pose.y, yaw=snapshot.pose.yaw,
            map_id=snapshot.map_id)
    except DockError as exc:
        raise _dock_error(exc)
    return taught.model_dump()


@docking_router.post("/dock")
def docking_dock(body: DockCommand, auth: AuthContext = Depends(operator),
                 svc: CoreServicesLike = Depends(get_services)):
    TaskKind.DOCK.require(svc.capability)              # DNC-003 — 미지원이면 501
    try:
        # 매니저가 DOCKING 을 먼저 쥔다 (CoreServices.take_docking_mode). 못
        # 쥐면 아무것도 바꾸지 않고 MODE_CONFLICT 다.
        svc.docking.dock(body.dock)
    except DockError as exc:
        raise _dock_error(exc)
    return svc.docking.status().model_dump()


@docking_router.post("/undock")
def docking_undock(auth: AuthContext = Depends(operator),
                   svc: CoreServicesLike = Depends(get_services)):
    TaskKind.DOCK.require(svc.capability)
    try:
        svc.docking.undock()
    except DockError as exc:
        raise _dock_error(exc)
    return svc.docking.status().model_dump()


@docking_router.post("/cancel")
def docking_cancel(auth: AuthContext = Depends(operator),
                   svc: CoreServicesLike = Depends(get_services)):
    TaskKind.DOCK.require(svc.capability)
    svc.docking.cancel()
    return svc.docking.status().model_dump()
