"""core_api_web.api.v1.common — 라우터 모듈이 공유하는 역할 의존성과 모드 전이.

라우터를 파일로 나누면서 생기는 유일한 공유 지점이다. 여기에 엔드포인트를
두지 않는다 — 여기 있는 것은 여러 도메인이 같은 규칙을 쓰기 때문에 있는 것뿐이다.
"""

from __future__ import annotations

from core_api_web.api.deps import AuthContext, require_role, CoreServicesLike
from core_api_web.api.errors import ApiError
from core_api_web.api.deps import Mode, NavigationError
from core_common.protocol.schemas import RobotMode

viewer = require_role("viewer")
operator = require_role("operator")
admin = require_role("administrator")


def enter_navigation_mode(svc: CoreServicesLike, auth: AuthContext) -> None:
    """D-2: Nav2 velocity only reaches the wheels in NAVIGATION."""
    if svc.line_follow.active:
        status = svc.line_follow.stop()
        svc.command.clear_navigation()
        svc.state.set_line_follow(status)
    try:
        svc.nav.require_ready()
    except NavigationError as exc:
        raise ApiError(exc.code, 503, str(exc)) from exc
    if svc.modes.mode is Mode.NAVIGATION:
        return
    svc.command.clear_navigation()
    ok, reason = svc.modes.transition(Mode.NAVIGATION)
    if not ok:
        raise ApiError("MODE_CONFLICT", 409, reason)
    svc.state.set_mode(RobotMode.NAVIGATION)
    svc.events.publish(
        "mode.changed",
        source="api",
        data={"from": "api", "to": Mode.NAVIGATION.value, "by": auth.role},
    )
