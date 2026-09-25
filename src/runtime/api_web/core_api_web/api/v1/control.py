"""core_api_web.api.v1.control — 모드 전이와 SAF-002 teleop."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core_api_web.api.v1.common import operator
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.errors import ApiError
from core_api_web.api.deps import Mode
from core_common.domain.tasks import TaskKind
from core_common.protocol.schemas import RobotMode


control_router = APIRouter(prefix="/api/v1", tags=["control"])


class ModeRequest(BaseModel):
    mode: str = Field(pattern="^(IDLE|MANUAL|NAVIGATION)$")


class TeleopRequest(BaseModel):
    linear: float = 0.0
    angular: float = 0.0


@control_router.post("/mode")
def set_mode(body: ModeRequest, auth: AuthContext = Depends(operator),
             svc: CoreServicesLike = Depends(get_services)):
    new_mode = Mode(body.mode)
    if svc.line_follow.active:
        status = svc.line_follow.stop()
        svc.command.clear_navigation()
        svc.state.set_line_follow(status)
    if new_mode is Mode.NAVIGATION:
        TaskKind.NAVIGATE.require(svc.capability)
        if svc.modes.mode is not Mode.NAVIGATION:
            svc.command.clear_navigation()
    if new_mode is Mode.MANUAL:
        # 조건 없이 부른다. `cancel()` 은 거둘 것이 없으면 스스로 돌아서고,
        # nav_state 만 보면 아직 목표를 내지 않은 군집 세션을 놓친다 —
        # 그러면 수동으로 넘어간 뒤에도 대형이 무장된 채로 남는다.
        svc.nav.cancel(source=f"mode:{auth.role}")
    ok, reason = svc.modes.transition(new_mode)
    if not ok:
        raise ApiError("MODE_CONFLICT", 409, reason)
    svc.state.set_mode(RobotMode(new_mode.value))
    svc.events.publish("mode.changed", source="api",
                       data={"from": "api", "to": new_mode.value, "by": auth.role})
    return {"mode": new_mode.value}


@control_router.post("/teleop")
def teleop(body: TeleopRequest, auth: AuthContext = Depends(operator),
           svc: CoreServicesLike = Depends(get_services)):
    TaskKind.MOVE.require(svc.capability)
    accepted, code = svc.command.teleop(body.linear, body.angular, source="manual")
    if not accepted:
        raise ApiError(code, 409 if code in ("MODE_CONFLICT", "EMERGENCY_ACTIVE") else 400,
                       f"teleop rejected: {code}")
    return {"accepted": True}
