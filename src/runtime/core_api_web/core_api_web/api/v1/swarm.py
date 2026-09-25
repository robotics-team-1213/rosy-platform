"""core_api_web.api.v1.swarm — SWM-002 follow 프리미티브 (API Ref §5.5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core_api_web.api.v1.common import enter_navigation_mode, operator, viewer
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.errors import ApiError
from core_api_web.api.deps import Mode
from core_api_web.api.deps import SwarmError
from core_common.protocol.schemas import SwarmFollowParams

swarm_router = APIRouter(prefix="/api/v1/swarm", tags=["swarm"])

#: SwarmError 코드 → HTTP. 도킹과 같은 규칙: 미지원은 501, 상태 충돌은 409.
_SWARM_HTTP = {
    "CAPABILITY_NOT_SUPPORTED": 501,
    "EMERGENCY_ACTIVE": 409,
    "DOCKING_ACTIVE": 409,
    "MAPPING_ACTIVE": 409,
    "VALIDATION_ERROR": 400,
}


def _swarm_error(exc: SwarmError) -> ApiError:
    return ApiError(exc.code, _SWARM_HTTP.get(exc.code, 400), str(exc))


@swarm_router.post("/follow")
def swarm_follow(body: SwarmFollowParams, auth: AuthContext = Depends(operator),
                 svc: CoreServicesLike = Depends(get_services)):
    """추종 시작. 목표는 NAVIGATION 모드에서만 바퀴에 닿는다 (D-2, SWM-001)."""
    # 아무것도 바꾸기 전에 두 문을 다 통과시킨다. follow() 는 상태를 바꾸고
    # 이벤트를 내므로, 그 뒤에 모드 전이가 409 로 막히면 운영자는 거절을 받는데
    # 로봇은 참조 프레임 하나에 달려나갈 준비가 된 채로 남는다.
    try:
        svc.swarm.check_follow(body)
    except SwarmError as exc:
        raise _swarm_error(exc)
    # 이미 NAVIGATION 이면 전이가 아니다 — `transition()` 도 같은 모드를 통과시킨다.
    # can_transition 만 보면 대형을 바꾸려 follow 를 다시 부를 때 409 가 난다.
    if (svc.modes.mode is not Mode.NAVIGATION
            and not svc.modes.can_transition(Mode.NAVIGATION)):
        raise ApiError("MODE_CONFLICT", 409,
                       f"cannot follow from {svc.modes.mode.value}")

    status = svc.swarm.follow(body, source=f"api:{auth.role}")
    try:
        enter_navigation_mode(svc, auth)
    except ApiError:
        # 여기까지 올 일은 없어야 하지만, 왔다면 무장된 채로 두지 않는다.
        svc.swarm.cancel(source="api", reason="mode_conflict")
        raise
    return {**svc.swarm.state_payload(), "role": status.role.value}


@swarm_router.post("/cancel")
def swarm_cancel(auth: AuthContext = Depends(operator),
                 svc: CoreServicesLike = Depends(get_services)):
    svc.swarm.cancel(source=f"api:{auth.role}")
    return svc.swarm.state_payload()


@swarm_router.get("/state")
def swarm_state(_: AuthContext = Depends(viewer),
                svc: CoreServicesLike = Depends(get_services)):
    return svc.swarm.state_payload()
