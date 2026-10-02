"""core_api_web.api.v1.control — 모드 전이와 SAF-002 teleop."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core_api_web.api.v1.common import apply_mode, operator, require_calibration_owner, require_kept
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.errors import ApiError
from core_api_web.api.deps import Mode
from core_common.domain.tasks import TaskKind


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
    apply_mode(svc, auth, new_mode)
    return {"mode": new_mode.value}


@control_router.post("/teleop")
def teleop(body: TeleopRequest, auth: AuthContext = Depends(operator),
           svc: CoreServicesLike = Depends(get_services)):
    TaskKind.MOVE.require(svc.capability)
    require_calibration_owner(svc, auth, "teleop")
    require_kept(svc, "teleop")
    accepted, code = svc.command.teleop(body.linear, body.angular, source="manual")
    if not accepted:
        raise ApiError(code, 409 if code in ("MODE_CONFLICT", "EMERGENCY_ACTIVE") else 400,
                       f"teleop rejected: {code}")
    return {"accepted": True}
