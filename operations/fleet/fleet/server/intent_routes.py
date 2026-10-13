"""`/api/fleet/do` — 같은 통역기. 로봇 일은 그 로봇 API로, 현장 말은 이 서버가 실행한다.

`core_common.intent` 해석 결과를 사이트 호출(`_site_call`)과 로봇 호출(`_robot_call`)로
나누는 적응층이다. 판단은 여기 없다.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException

from core_common.intent import IntentError, interpret, request_schema
from fleet.hub.hub import HubError
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.server.task_store import IdempotencyConflict
from fleet.server.intent_execution import IntentExecution, STOP_VERBS, _site_call, _robot_call
from fleet.swarm.transport import RobotApiError

# D-540 9: these only stop; any other verb moves something and needs a named operator.


def install_intent_routes(app, *, console, task_service, require_operator, require_named_operator,
                          operator_guard, local_stop_fanout, cancel_pending) -> None:
    execution = IntentExecution(console, task_service, local_stop_fanout, cancel_pending)
    app.state.intent_execution = execution

    @app.post(
        "/api/fleet/do",
        dependencies=operator_guard,
        tags=["fleet"],
        openapi_extra={
            "requestBody": {
                "content": {"application/json": {"schema": request_schema()}},
            },
        },
    )
    async def fleet_do(
        body: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
        principal: SitePrincipal = Depends(require_operator),
    ) -> dict:
        try:
            calls = interpret(body)
        except IntentError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc
        if any(call.verb not in STOP_VERBS for call in calls):
            require_named_operator(principal)
        steps = []
        for call in calls:
            try:
                result = await execution.step(call, principal, idempotency_key, len(steps))
            except IdempotencyConflict as exc:
                raise HTTPException(status_code=409, detail={
                    "code": "IDEMPOTENCY_CONFLICT", "message": str(exc),
                }) from exc
            except ValueError as exc:
                code = str(exc)
                status = 404 if code == "UNKNOWN_ROBOT" else 400
                raise HTTPException(status_code=status, detail={"code": code}) from exc
            except (HubError, RobotApiError, OSError) as exc:
                raise http_error(exc) from exc
            steps.append({"do": call.verb, "robot": call.robot, "path": call.path, "result": result})
        return {
            "accepted": all(step["result"].get("accepted", True) for step in steps),
            "queued": any(step["result"].get("queued", False) for step in steps),
            "steps": steps,
        }
