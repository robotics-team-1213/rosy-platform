"""Existing intent execution owners shared by HTTP and admitted channel steps."""
import asyncio
import logging
from hashlib import sha256
from fastapi import HTTPException
from fleet.hub.hub import HubError

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


class IntentExecution:
    def __init__(self, console, task_service, local_stop_fanout, cancel_pending):
        self.console, self.task_service = console, task_service
        self.local_stop_fanout, self.cancel_pending = local_stop_fanout, cancel_pending

    async def step(self, call, principal, idempotency_key, index, *, admission=None):
        console, task_service = self.console, self.task_service
        local_stop_fanout, cancel_pending = self.local_stop_fanout, self.cancel_pending
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
                child_key = sha256(f"{idempotency_key}:{index}".encode()).hexdigest()
                task = await task_service.submit_navigation(
                    robot_id=call.robot, x=float(call.body["x"]),
                    y=float(call.body["y"]), yaw=float(call.body.get("yaw") or 0.0),
                    source="operator", actor_id=principal.principal_id, request_key=child_key, admission=admission,
                )
                result = {"accepted": task["status"] == "ACCEPTED",
                          "queued": task["status"] == "QUEUED", "task": task}
            else:
                result = await _robot_call(console, call)
        return result
