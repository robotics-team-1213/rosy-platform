"""D-463 lane route endpoint — ordered lane edges become one next short point.

This module is deliberately outside the D-430 safety cluster: the stop files
(``task_dispatch_routes``, ``cancel_all``, ...) stay free of decision-concern
imports, while this goal-submitting route composes the lane geometry
(``fleet.lane_route``) with the console's public goal path. A point goal stays
``GoalRequest``; a pose that is not LOCALIZED in the map frame never calls CORE.
"""

from __future__ import annotations

import math
from typing import Optional

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fleet.hub.hub import HubError
from fleet.lane_route import LaneRouteError, next_step, route_lines, step_facts
from fleet.routing.brief import route_context
from fleet.routing.road_path import plan_road_path
from fleet.routing.snap import PlanError
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


class RoadNav2Request(BaseModel):
    """Road-constrained Nav2 goal request (place_id or site coordinates)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(default=0.0, allow_inf_nan=False)
    y: float = Field(default=0.0, allow_inf_nan=False)
    yaw: Optional[float] = Field(default=None, allow_inf_nan=False)
    place_id: Optional[str] = Field(default=None, max_length=64)
    label: str = Field(default="", max_length=128)
    dry_run: bool = False


def install_lane_route_routes(app, *, console, task_service, site_maps,
                              require_named_operator) -> None:
    """D-494 5: map activation waits for a running trip, not for this route (no guard here)."""
    # One process remembers how far each robot has followed each edge list.
    # A closed lap starts and ends on one point; without this the end is the start.
    followed: dict[tuple, float] = {}

    @app.post("/api/fleet/robots/{robot_id}/route", tags=["fleet"])
    async def fleet_lane_route(
        robot_id: str, body: RouteRequest,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
        principal: SitePrincipal = Depends(require_named_operator),  # D-540 9
    ) -> dict:
        """D-463. Expand stored lane edges and send only the next short point."""
        if busy := console.trip_refusal([robot_id]):  # D-494 5: the trip loop owns this robot's motion
            raise HTTPException(409, {"code": busy.code, "message": f"{robot_id} is on a running trip"})
        active = site_maps.active()
        if active is None:
            raise HTTPException(status_code=409, detail={
                "code": "SITE_MAP_NOT_ACTIVE", "message": "activate a site map first (D-488)"})
        try:
            lines = route_lines(body.edges, active[3])
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
        route_key = (robot_id, active[0], tuple(body.edges))
        try:
            step = next_step(lines, pose[0], pose[1], along_m=followed.get(route_key, 0.0))
        except LaneRouteError as exc:
            raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
        if step is not None:
            followed[route_key] = step.at_m
        context = route_context(planner="lane_step", supplied={"edges": list(body.edges)},
                                holds=step_facts(lines, step))
        if step is None:
            followed.pop(route_key, None)
            return {"accepted": False, "queued": False, "reason": "ROUTE_COMPLETE",
                    "goal": None, "edges": list(body.edges), "context": context}
        goal = {"x": step.x, "y": step.y, "yaw": step.yaw}
        try:
            if task_service is not None:
                task = await task_service.submit_navigation(
                    robot_id=robot_id, x=step.x, y=step.y, yaw=step.yaw,
                    source="operator", actor_id=principal.principal_id,
                    request_key=idempotency_key,
                )
                return {"accepted": task["status"] == "ACCEPTED",
                        "queued": task["status"] == "QUEUED", "task": task, "goal": goal,
                        "context": context}
            result = await console.goal(robot_id, step.x, step.y, step.yaw)
            return {**result, "goal": goal, "context": context}
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

    async def _resolve_road_pose(robot_id: str):
        pose = await console.trusted_map_pose(robot_id)
        map_pose = getattr(app.state, "map_pose", None)
        arb = map_pose.arbitrated_pose(robot_id) if map_pose is not None else None
        if arb is not None and getattr(arb, "state", None) == "LOCALIZED":
            if pose is None or math.hypot(pose[0], pose[1]) < 1e-3 < math.hypot(arb.x, arb.y):
                return (float(arb.x), float(arb.y), getattr(arb, "yaw", None))
        return pose

    @app.get("/api/fleet/robots/{robot_id}/road-nav2/plan", tags=["fleet"])
    async def fleet_road_nav2_plan(
        robot_id: str,
        place_id: Optional[str] = None,
        x: float = 0.0,
        y: float = 0.0,
        yaw: Optional[float] = None,
    ) -> dict:
        """Read-only road-following path preview on the active Graph from the robot's live map pose."""
        active = site_maps.active()
        if active is None:
            raise HTTPException(status_code=409, detail={
                "code": "SITE_MAP_NOT_ACTIVE", "message": "activate a site map first (D-488)"})
        try:
            pose = await _resolve_road_pose(robot_id)
        except (HubError, RobotApiError, OSError) as exc:
            raise http_error(exc) from exc
        if pose is None:
            raise HTTPException(status_code=409, detail={
                "code": "ROUTE_POSE_UNTRUSTED",
                "message": "road-nav2 needs a LOCALIZED map pose",
            })
        graph = active[2]
        target = place_id if (place_id and place_id in graph.places) else (x, y, yaw)
        try:
            road_plan = plan_road_path(graph, pose, target)
        except PlanError as exc:
            raise http_error(exc) if not hasattr(exc, "code") else HTTPException(
                status_code=409, detail={"code": exc.code, **exc.detail}
            ) from exc
        waypoints = [dict(w) for w in road_plan.waypoints_site]
        chosen = waypoints[-1]
        for wp in waypoints:
            if math.dist((pose[0], pose[1]), (wp["x"], wp["y"])) >= 0.28:
                chosen = wp
                break
        return {
            "robot_id": robot_id,
            "map_version": road_plan.map_version,
            "start_pose": {"x": round(pose[0], 4), "y": round(pose[1], 4), "yaw": round(pose[2], 4) if pose[2] is not None else None},
            "waypoints_site": waypoints,
            "places": list(road_plan.places),
            "edges": list(road_plan.edges),
            "length_m": road_plan.length_m,
            "eta_s": road_plan.eta_s,
            "goal": {"x": chosen["x"], "y": chosen["y"], "yaw": chosen["yaw"]},
            "dispatch": False,
        }

    @app.post("/api/fleet/robots/{robot_id}/road-nav2", tags=["fleet"])
    async def fleet_road_nav2(
        robot_id: str, body: RoadNav2Request,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
        principal: SitePrincipal = Depends(require_named_operator),
    ) -> dict:
        """Plan a road-following polyline on the active Graph and dispatch along the road."""
        if busy := console.trip_refusal([robot_id]):
            raise HTTPException(409, {"code": busy.code, "message": f"{robot_id} is on a running trip"})
        active = site_maps.active()
        if active is None:
            raise HTTPException(status_code=409, detail={
                "code": "SITE_MAP_NOT_ACTIVE", "message": "activate a site map first (D-488)"})
        if not body.dry_run and task_service is not None and not idempotency_key:
            raise HTTPException(status_code=400, detail={
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "Idempotency-Key is required for navigation requests",
            })
        try:
            pose = await _resolve_road_pose(robot_id)
        except (HubError, RobotApiError, OSError) as exc:
            raise http_error(exc) from exc
        if pose is None:
            raise HTTPException(status_code=409, detail={
                "code": "ROUTE_POSE_UNTRUSTED",
                "message": "road-nav2 needs a LOCALIZED map pose",
            })
        graph = active[2]
        target = body.place_id if (body.place_id and body.place_id in graph.places) else (body.x, body.y, body.yaw)
        try:
            road_plan = plan_road_path(graph, pose, target)
        except PlanError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, **exc.detail}) from exc

        waypoints = [dict(w) for w in road_plan.waypoints_site]
        chosen = waypoints[-1]
        for wp in waypoints:
            if math.dist((pose[0], pose[1]), (wp["x"], wp["y"])) >= 0.28:
                chosen = wp
                break
        goal = {"x": chosen["x"], "y": chosen["y"], "yaw": chosen["yaw"]}
        context = route_context(
            planner="lane_step",
            supplied={"x": body.x, "y": body.y, "place_id": body.place_id},
            holds={"edges": list(road_plan.edges), "places": list(road_plan.places), "length_m": road_plan.length_m},
        )
        plan_meta = {
            "map_version": road_plan.map_version,
            "waypoints_site": waypoints,
            "places": list(road_plan.places),
            "edges": list(road_plan.edges),
            "length_m": road_plan.length_m,
            "eta_s": road_plan.eta_s,
            "goal": goal,
            "context": context,
        }
        if body.dry_run:
            return {"accepted": True, "dispatched": False, "dry_run": True, **plan_meta}
        try:
            if task_service is not None:
                task = await task_service.submit_navigation(
                    robot_id=robot_id, x=goal["x"], y=goal["y"], yaw=goal["yaw"],
                    source="operator", actor_id=principal.principal_id,
                    request_key=idempotency_key,
                )
                ok = task["status"] in ("ACCEPTED", "QUEUED")
                return {"accepted": task["status"] == "ACCEPTED", "dispatched": ok,
                        "queued": task["status"] == "QUEUED", "task": task, **plan_meta}
            result = await console.goal(robot_id, goal["x"], goal["y"], goal["yaw"])
            return {**result, "dispatched": bool(result.get("accepted")), **plan_meta}
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
