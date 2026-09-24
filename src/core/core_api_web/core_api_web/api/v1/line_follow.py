"""D-143 line-follow mode selection and status API."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import enter_navigation_mode, operator, viewer
from core_common.domain.tasks import TaskKind
from core_common.protocol.schemas import DockState, RobotMode
from core_api_web.api.deps import Mode
from core_api_web.api.deps import LineFollowMode


line_follow_router = APIRouter(prefix="/api/v1/line-follow", tags=["line-follow"])


class LineFollowModeRequest(BaseModel):
    mode: str


def _status(svc: CoreServicesLike) -> dict:
    return svc.line_follow.status().model_dump()


@line_follow_router.get("")
def get_line_follow(_: AuthContext = Depends(viewer),
                    svc: CoreServicesLike = Depends(get_services)):
    return _status(svc)


@line_follow_router.put("/mode")
def set_line_follow_mode(body: LineFollowModeRequest,
                         auth: AuthContext = Depends(operator),
                         svc: CoreServicesLike = Depends(get_services)):
    try:
        selected = LineFollowMode(body.mode)
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", 400, "unknown line-follow mode") from exc

    if selected is LineFollowMode.OFF:
        was_active = svc.line_follow.active
        status = svc.line_follow.stop()
        svc.command.clear_navigation()
        svc.state.set_line_follow(status)
        if was_active and svc.modes.mode is Mode.NAVIGATION:
            ok, reason = svc.modes.transition(Mode.IDLE)
            if not ok:
                raise ApiError("MODE_CONFLICT", 409, reason)
            svc.state.set_mode(RobotMode.IDLE)
        return _status(svc)

    if svc.safety.estop or svc.modes.is_emergency:
        raise ApiError("EMERGENCY_ACTIVE", 409, "release emergency stop first")
    if svc.modes.mode is Mode.DOCKING or svc.docking.state in (
            DockState.DOCKING, DockState.UNDOCKING):
        # 도킹이 바퀴를 쥐고 있다. 조용히 빼앗지 않는다 — 먼저 취소하게 한다.
        raise ApiError("DOCKING_ACTIVE", 409, "cancel docking first")
    if svc.nav.mapping_active:
        raise ApiError("MAPPING_ACTIVE", 409, "mapping session owns navigation")

    TaskKind.NAVIGATE.require(svc.capability)
    svc.nav.cancel(source=f"line_follow:{auth.role}")
    svc.command.clear_navigation()
    enter_navigation_mode(svc, auth)
    status = svc.line_follow.set_mode(selected)
    svc.state.set_line_follow(status)
    return _status(svc)
