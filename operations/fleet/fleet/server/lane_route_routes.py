"""D-463 lane route endpoint — ordered lane edges become one next short point.

This module is deliberately outside the D-430 safety cluster: the stop files
(``task_dispatch_routes``, ``cancel_all``, ...) stay free of decision-concern
imports, while this goal-submitting route composes the lane geometry
(``fleet.lane_route``) with the console's public goal path. A point goal stays
``GoalRequest``; a pose that is not LOCALIZED in the map frame never calls CORE.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, model_validator

from fleet.hub.hub import HubError
from fleet.lane_route import LaneRouteError, next_step, route_lines
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.server.task_store import IdempotencyConflict
from fleet.swarm.transport import RobotApiError


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


def install_lane_route_routes(app, *, console, task_service,
                              require_operator, operator_guard) -> None:
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
