"""POST /api/v1/do — 통역된 일을 기존 핸들러로 실행한다.

기본 경로는 그대로다. 이 문은 "이렇게 해" 한 덩어리를 그 경로로 바꿀 뿐이다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import operator
from core_api_web.api.v1.control import TeleopRequest, teleop
from core_api_web.api.v1.docking import DockCommand, docking_dock, docking_undock
from core_api_web.api.v1.navigation import (
    GoalRequest,
    navigation_cancel,
    navigation_goal,
    navigation_home,
)
from core_api_web.api.v1.safety import safety_stop
from core_api_web.api.v1.swarm import swarm_cancel, swarm_follow
from core_common.intent import IntentError, interpret
from core_common.protocol.schemas import SwarmFollowParams

intent_router = APIRouter(prefix="/api/v1", tags=["intent"])


@intent_router.post("/do")
def do_intent(body: dict, auth: AuthContext = Depends(operator),
              svc: CoreServicesLike = Depends(get_services)):
    try:
        calls = interpret(body)
    except IntentError as exc:
        raise ApiError(exc.code, 400, str(exc)) from exc
    results = []
    for call in calls:
        if call.scope != "robot":
            raise ApiError("SITE_ONLY", 400, f"{call.verb} is a site sentence")
        results.append({"do": call.verb, "path": call.path, "result": _run(call, auth, svc)})
    return {"accepted": True, "steps": results}


def _run(call, auth: AuthContext, svc: CoreServicesLike):
    if call.verb == "navigate":
        return navigation_goal(GoalRequest(**call.body), auth, svc)
    if call.verb == "home":
        return navigation_home(auth, svc)
    if call.verb == "cancel":
        return navigation_cancel(auth, svc)
    if call.verb == "stop":
        return safety_stop(auth, svc)
    if call.verb == "move":
        return teleop(TeleopRequest(**call.body), auth, svc)
    if call.verb == "follow":
        return swarm_follow(SwarmFollowParams(**call.body), auth, svc)
    if call.verb == "follow_cancel":
        return swarm_cancel(auth, svc)
    if call.verb == "dock":
        return docking_dock(DockCommand(**call.body), auth, svc)
    if call.verb == "undock":
        return docking_undock(auth, svc)
    raise ApiError("UNKNOWN_VERB", 400, call.verb)
