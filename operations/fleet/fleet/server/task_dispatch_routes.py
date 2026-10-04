"""작업·디스패치 HTTP 표면 — task_store 소유 경로와 국소 정지 팬아웃.

디스패치 통제 readback/rearm, 로봇 목표·취소·라인 모드, 작업 readback/취소,
전체 주행 취소(cancel-all, D-421, 래치 없음)와 전체 비상 정지(estop)가 여기 산다. OMX 국소 정지 팬아웃(`fanout_local_omx_stops`)은
rearm 롤백·fleet_do·estop 이 같은 영수증 규칙으로 쓴다.

task_service 가 없는 배치에서도 목표·취소·정지 경로는 남는다 — 대기열 없이
console 이 곧장 흩뿌리는 원본 동작을 그대로 둔다.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Mapping, Optional

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from fleet.hub.hub import HubError
from fleet.lane_route import LaneRouteError, next_step, route_lines
from fleet.server.cancel_all import DriveCancelFence, cancel_all_driving
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.server.owner_recovery_routes import install_owner_recovery_routes
from fleet.server.task_store import IdempotencyConflict, InvalidTaskTransition
from fleet.swarm.transport import RobotApiError

_LOG = logging.getLogger(__name__)


class GoalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float
    y: float
    yaw: float = 0.0

    @field_validator("x", "y", "yaw", mode="before")
    @classmethod
    def _finite_numeric_goal(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("goal coordinates must be finite numbers")
        return value


class DispatchRearmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_generation: int

    @field_validator("expected_generation", mode="before")
    @classmethod
    def _non_negative_generation(cls, value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("expected_generation must be a non-negative integer")
        return value


class LineFollowModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: str


class RouteRequest(BaseModel):
    """D-463. Ordered lane-graph edge ids. A point goal stays GoalRequest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    edges: list[str]

    @model_validator(mode="after")
    def _edge_ids(self) -> "RouteRequest":
        if not 1 <= len(self.edges) <= 8:
            raise ValueError("route needs 1 to 8 lane-graph edge ids")
        if any(not item or len(item) > 32 for item in self.edges):
            raise ValueError("edge id must be 1 to 32 characters")
        return self


def fanout_local_omx_stops(configured_omx: Mapping[str, str], stop_transport,
                           control: Mapping | None, *, reason: str) -> dict:
    if not configured_omx:
        return {"state": "NOT_CONFIGURED", "instances": []}
    if stop_transport is None or control is None:
        return {"state": "UNKNOWN", "instances": [
            {"workcell_id": workcell_id, "instance_id": instance_id,
             "state": "UNKNOWN", "reason": "FLEET_DISPATCH_CONTROL_UNAVAILABLE"}
            for workcell_id, instance_id in configured_omx.items()
        ]}
    results = []
    for workcell_id, instance_id in configured_omx.items():
        try:
            outcome = stop_transport.stop(
                workcell_id=workcell_id, instance_id=instance_id,
                authority_epoch=control["authority_epoch"],
                dispatch_generation=control["generation"], reason=reason,
            )
            if not isinstance(outcome, Mapping):
                outcome = {"state": "UNKNOWN", "reason": "INVALID_STOP_RECEIPT"}
        except Exception as exc:
            _LOG.exception("OMX StopLocal fanout failed instance=%s", instance_id)
            outcome = {"state": "UNKNOWN", "reason": type(exc).__name__}
        results.append({"workcell_id": workcell_id, "instance_id": instance_id,
                        **dict(outcome)})
    states = {row["state"] for row in results}
    overall = "LOCAL_LATCHED" if states == {"LOCAL_LATCHED"} else (
        "REQUESTED" if states and states <= {"LOCAL_LATCHED", "REQUESTED"}
        else "UNKNOWN"
    )
    return {"state": overall, "instances": results}


def cancel_pending_task_queue(task_service, console, robot_id: Optional[str] = None, *,
                              actor_id: str = "site-console") -> None:
    if task_service is None:
        return
    canceled = (task_service.cancel_all_queued(actor_id=actor_id) if robot_id is None else
                task_service.cancel_queued_for_robot(robot_id, actor_id=actor_id))
    console.discard_task_queue_entries(set(canceled))


def install_task_dispatch_routes(
    app, *, console, task_service, configured_omx,
    stop_transport, require_viewer, require_operator,
    read_guard, operator_guard, drive_cancel: DriveCancelFence | None = None, require_named_operator=None,
) -> None:
    drive_cancel = drive_cancel or DriveCancelFence()
    if require_named_operator is not None:
        install_owner_recovery_routes(app, configured_omx=configured_omx, stop_transport=stop_transport,
                                      task_service=task_service, require_viewer=require_viewer,
                                      require_named_operator=require_named_operator)

    if task_service is not None:
        @app.get("/api/fleet/dispatch-control", dependencies=read_guard,
                 tags=["fleet-control"])
        def dispatch_control_readback() -> dict:
            return task_service.store.dispatch_control()

        @app.post("/api/fleet/dispatch/rearm", dependencies=operator_guard,
                  tags=["fleet-control"])
        async def dispatch_rearm(
            body: DispatchRearmRequest,
            principal: SitePrincipal = Depends(require_operator),
        ) -> dict:
            try:
                control = task_service.store.rearm_dispatch(
                    expected_generation=body.expected_generation,
                    actor_id=principal.principal_id,
                )
            except InvalidTaskTransition as exc:
                raise HTTPException(status_code=409, detail={
                    "code": "DISPATCH_REARM_REFUSED", "message": str(exc),
                }) from exc
            if configured_omx:
                local_rearm = []
                for workcell_id, instance_id in configured_omx.items():
                    try:
                        # The owner reads Fleet's live fence while rearming. Keep the
                        # event loop available to serve that authenticated readback.
                        result = await asyncio.to_thread(
                            stop_transport.rearm,
                            workcell_id=workcell_id, instance_id=instance_id,
                            authority_epoch=control["authority_epoch"],
                            dispatch_generation=control["generation"],
                        )
                        if not isinstance(result, Mapping):
                            result = {"state": "UNKNOWN", "reason": "INVALID_REARM_RECEIPT"}
                    except Exception as exc:
                        _LOG.exception("OMX local rearm failed instance=%s", instance_id)
                        result = {"state": "UNKNOWN", "reason": type(exc).__name__}
                    local_rearm.append({"workcell_id": workcell_id,
                                        "instance_id": instance_id, **dict(result)})
                if any(item["state"] != "OPEN" for item in local_rearm):
                    try:
                        stopped = task_service.store.trip_stop_latch(
                            actor_id=principal.principal_id,
                            reason="OMX_LOCAL_REARM_FAILED",
                        )
                    except Exception:
                        _LOG.exception("failed to close Fleet dispatch after OMX rearm refusal")
                        try:
                            stopped = task_service.store.dispatch_control()
                        except Exception:
                            stopped = None
                    await asyncio.to_thread(
                        fanout_local_omx_stops, configured_omx, stop_transport, stopped,
                        reason="OMX_REARM_ROLLBACK",
                    )
                    raise HTTPException(status_code=409, detail={
                        "code": "LOCAL_WORKCELL_REARM_FAILED",
                        "fleet_dispatch": stopped,
                        "omx_local_rearm": local_rearm,
                    })
                control["omx_local_rearm"] = local_rearm
            return control

    @app.post("/api/fleet/robots/{robot_id}/goal", dependencies=operator_guard, tags=["fleet"])
    async def fleet_goal(
        robot_id: str, body: GoalRequest,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
        principal: SitePrincipal = Depends(require_operator),
    ) -> dict:
        try:
            if task_service is not None:
                if not idempotency_key:
                    raise HTTPException(status_code=400, detail={
                        "code": "IDEMPOTENCY_KEY_REQUIRED",
                        "message": "Idempotency-Key is required for navigation requests",
                    })
                task = await task_service.submit_navigation(
                    robot_id=robot_id, x=body.x, y=body.y, yaw=body.yaw,
                    source="operator", actor_id=principal.principal_id,
                    request_key=idempotency_key,
                )
                return {"accepted": task["status"] == "ACCEPTED",
                        "queued": task["status"] == "QUEUED", "task": task}
            return await console.goal(robot_id, body.x, body.y, body.yaw)
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

    @app.post("/api/fleet/robots/{robot_id}/route", dependencies=operator_guard,
              tags=["fleet"])
    async def fleet_lane_route(
        robot_id: str, body: RouteRequest,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
        principal: SitePrincipal = Depends(require_operator),
    ) -> dict:
        """D-463. Expand stored lane edges and send only the next short point."""
        try:
            lines = route_lines(body.edges)
        except LaneRouteError as exc:
            raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
        if task_service is not None and not idempotency_key:
            raise HTTPException(status_code=400, detail={
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "Idempotency-Key is required for navigation requests",
            })
        try:
            pose = await console.trusted_map_pose(robot_id)
        except (HubError, RobotApiError, OSError) as exc:
            raise http_error(exc) from exc
        if pose is None:
            raise HTTPException(status_code=409, detail={
                "code": "ROUTE_POSE_UNTRUSTED",
                "message": "lane route needs a LOCALIZED map pose",
            })
        try:
            step = next_step(lines, pose[0], pose[1])
        except LaneRouteError as exc:
            raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
        if step is None:
            return {"accepted": False, "queued": False, "reason": "ROUTE_COMPLETE",
                    "goal": None, "edges": list(body.edges)}
        goal = {"x": step.x, "y": step.y, "yaw": step.yaw}
        try:
            if task_service is not None:
                task = await task_service.submit_navigation(
                    robot_id=robot_id, x=step.x, y=step.y, yaw=step.yaw,
                    source="operator", actor_id=principal.principal_id,
                    request_key=idempotency_key,
                )
                return {"accepted": task["status"] == "ACCEPTED",
                        "queued": task["status"] == "QUEUED", "task": task, "goal": goal}
            result = await console.goal(robot_id, step.x, step.y, step.yaw)
            return {**result, "goal": goal}
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

    @app.post("/api/fleet/robots/{robot_id}/line-follow", dependencies=operator_guard,
              tags=["fleet"])
    async def fleet_line_follow_mode(
        robot_id: str, body: LineFollowModeRequest,
        principal: SitePrincipal = Depends(require_operator),
    ) -> dict:
        try:
            result = await console.line_follow_mode(robot_id, body.mode)
            return {"robot_id": robot_id, "actor_id": principal.principal_id, "result": result}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_MODE"}) from exc
        except (HubError, RobotApiError, OSError) as exc:
            raise http_error(exc) from exc

    if task_service is not None:
        @app.get("/api/fleet/tasks/{task_id}", dependencies=read_guard, tags=["fleet-tasks"])
        def fleet_task_readback(task_id: str) -> dict:
            task = task_service.store.get_task(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
            return {"task": task, "history": task_service.store.history(task_id)}

        @app.post("/api/fleet/tasks/{task_id}/cancel", dependencies=operator_guard,
                  tags=["fleet-tasks"])
        def fleet_task_cancel(task_id: str,
                              principal: SitePrincipal = Depends(require_operator)) -> dict:
            try:
                task = task_service.cancel_queued_task(task_id, actor_id=principal.principal_id)
            except KeyError:
                raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"}) from None
            except InvalidTaskTransition:
                raise HTTPException(status_code=409, detail={
                    "code": "TASK_ALREADY_DISPATCHED",
                    "message": "only a task not yet dispatched can be canceled here",
                }) from None
            console.discard_task_queue_entries({task_id})
            return {"task": task}

    @app.post("/api/fleet/robots/{robot_id}/cancel", dependencies=operator_guard, tags=["fleet"])
    async def fleet_cancel(robot_id: str,
                           principal: SitePrincipal = Depends(require_operator)) -> dict:
        cancel_pending_task_queue(task_service, console, robot_id,
                                  actor_id=principal.principal_id)
        try:
            result = await console.cancel(robot_id)
        except (HubError, RobotApiError, OSError) as exc:
            raise http_error(exc) from exc
        return result

    @app.post("/api/fleet/cancel-all", dependencies=operator_guard, tags=["fleet"])
    async def fleet_cancel_all(principal: SitePrincipal = Depends(require_operator)) -> dict:
        # D-421: 래치 없는 전체 주행 취소. 한 대가 실패해도 200 — 본문이 로봇별로 말한다.
        return await cancel_all_driving(console, task_service, drive_cancel,
                                        actor_id=principal.principal_id)

    @app.post("/api/fleet/estop", dependencies=operator_guard, tags=["fleet"])
    async def fleet_estop(principal: SitePrincipal = Depends(require_operator)) -> dict:
        # 이쪽은 한 대가 거절해도 200 이다 — 어느 대가 섰고 어느 대가 못 섰는지는 본문에
        # 다 들어 있고, 화면은 그 목록을 보여 줘야 한다.
        stop_control = None
        if task_service is not None:
            try:
                stop_control = task_service.store.trip_stop_latch(
                    actor_id=principal.principal_id,
                )
            except Exception:
                _LOG.exception(
                    "emergency stop dispatch latch unavailable; continuing stop fanout "
                    "principal=%s",
                    principal.principal_id,
                )
                try:
                    stop_control = task_service.store.dispatch_control()
                except Exception:
                    _LOG.exception("emergency stop dispatch readback unavailable")
        local_stop_task = asyncio.to_thread(
            fanout_local_omx_stops, configured_omx, stop_transport, stop_control,
            reason="FLEET_ESTOP",
        )
        result, local_stop = await asyncio.gather(console.estop_all(), local_stop_task)
        try:
            cancel_pending_task_queue(task_service, console,
                                      actor_id=principal.principal_id)
        except Exception:
            _LOG.exception(
                "emergency stop queue cleanup unavailable principal=%s",
                principal.principal_id,
            )
        result = dict(result)
        result["omx_local_stop"] = local_stop
        if stop_control is not None:
            result["fleet_dispatch_control"] = stop_control
        return result
