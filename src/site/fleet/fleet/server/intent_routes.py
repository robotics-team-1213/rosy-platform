"""`/api/fleet/do` — 같은 통역기. 로봇 일은 그 로봇 API로, 현장 말은 이 서버가 실행한다.

`core_common.intent` 해석 결과를 사이트 호출(`_site_call`)과 로봇 호출(`_robot_call`)로
나누는 적응층이다. 판단은 여기 없다.
"""

from __future__ import annotations

import asyncio
import logging
from hashlib import sha256
from typing import Optional

from fastapi import Depends, Header, HTTPException

from core_common.intent import IntentError, interpret, request_schema
from fleet.hub.hub import HubError
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.server.task_store import IdempotencyConflict
from fleet.swarm.transport import RobotApiError

_LOG = logging.getLogger(__name__)


async def _site_call(console, call) -> dict:
    if call.verb == "formation_start":
        return await console.formation_start(
            call.body["leader"], call.body.get("formation", "COLUMN"),
            call.body.get("spacing"), call.body.get("max_speed"),
            members=call.body.get("members"))
    if call.verb == "formation_stop":
        return await console.formation_stop()
    if call.verb == "formation_resume":
        return await console.formation_resume()
    if call.verb == "estop":
        return await console.estop_all()
    raise HubError("UNKNOWN_VERB", call.verb)


async def _robot_call(console, call) -> dict:
    robot = call.robot
    if call.verb == "navigate":
        if call.body.get("x") is None or call.body.get("y") is None:
            raise HubError("WAYPOINT_STAYS_ON_ROBOT", "name a point, or tell the robot itself")
        return await console.goal(robot, float(call.body["x"]), float(call.body["y"]),
                                  float(call.body.get("yaw") or 0.0))
    if call.verb == "cancel":
        return await console.cancel(robot)
    if call.verb == "stop":
        return await console._client(robot).estop()
    if call.verb == "follow":
        from core_common.protocol.schemas import SwarmFollowParams
        return await console._client(robot).follow(SwarmFollowParams(**call.body))
    return await console._client(robot)._post(call.path, call.body or None)


def install_intent_routes(app, *, console, task_service, require_operator,
                          operator_guard, local_stop_fanout, cancel_pending) -> None:
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
        steps = []
        for call in calls:
            try:
                if call.scope == "site":
                    stop_control = None
                    if call.verb == "estop":
                        if task_service is not None:
                            try:
                                stop_control = task_service.store.trip_stop_latch(
                                    actor_id=principal.principal_id,
                                )
                            except Exception:
                                _LOG.exception("dispatch latch unavailable for site E-stop")
                                try:
                                    stop_control = task_service.store.dispatch_control()
                                except Exception:
                                    _LOG.exception("dispatch readback unavailable for site E-stop")
                        cancel_pending(actor_id=principal.principal_id)
                    result = await _site_call(console, call)
                    if call.verb == "estop":
                        result["omx_local_stop"] = await asyncio.to_thread(
                            local_stop_fanout, stop_control,
                            reason="FLEET_ESTOP",
                        )
                else:
                    if not call.robot:
                        raise HubError("ROBOT_REQUIRED", call.verb)
                    if call.verb in {"cancel", "stop"}:
                        cancel_pending(call.robot, actor_id=principal.principal_id)
                    if task_service is not None and call.verb == "navigate":
                        if not idempotency_key:
                            raise HTTPException(status_code=400, detail={
                                "code": "IDEMPOTENCY_KEY_REQUIRED",
                                "message": "Idempotency-Key is required for navigation requests",
                            })
                        if call.body.get("x") is None or call.body.get("y") is None:
                            raise HubError("WAYPOINT_STAYS_ON_ROBOT",
                                           "name a point, or tell the robot itself")
                        child_key = sha256(f"{idempotency_key}:{len(steps)}".encode()).hexdigest()
                        task = await task_service.submit_navigation(
                            robot_id=call.robot, x=float(call.body["x"]),
                            y=float(call.body["y"]), yaw=float(call.body.get("yaw") or 0.0),
                            source="operator", actor_id=principal.principal_id, request_key=child_key,
                        )
                        result = {"accepted": task["status"] == "ACCEPTED",
                                  "queued": task["status"] == "QUEUED", "task": task}
                    else:
                        result = await _robot_call(console, call)
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
