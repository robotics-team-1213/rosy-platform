"""D-488 2 / D-490 5: ``POST /api/fleet/robots/{id}/trip`` plans and returns; it never drives.

The robot's LOCALIZED map pose and the active site map go into the pure planner
(``fleet.routing``). Every plan, refused or not, is a row in the site map store (D-490 8).
D-491 5: ``POST /api/fleet/trips/{plan_id}/start`` runs a stored plan through the trip loop
(``trip_runner``); ``/cancel`` and ``/confirm-replan`` act on it and ``GET`` reads it. The
plan request's ``execute: true`` stays 501: starting is always its own named-operator call.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from typing import Annotated, Optional, Union

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.hub.hub import HubError
from fleet.routing.snap import PlanError
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.routing.execute import plan_body
from fleet.server.trip_runner import PLAN_TTL_S, TripError
from fleet.swarm.transport import RobotApiError

PlaceRef = Annotated[str, Field(min_length=1, max_length=64)]
_LOG = logging.getLogger(__name__)


class TripPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    yaw: Optional[float] = Field(default=None, ge=-math.pi, le=math.pi, allow_inf_nan=False)


class TripRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    to: Union[PlaceRef, TripPoint]
    via: list[PlaceRef] = Field(default_factory=list, max_length=8)
    arrive_yaw: Optional[float] = Field(default=None, ge=-math.pi, le=math.pi, allow_inf_nan=False)
    speed_cap: Optional[float] = Field(default=None, gt=0.0, le=5.0, allow_inf_nan=False)
    execute: bool = False


def _refuse(code: str, detail: Optional[dict] = None, status: int = 422) -> HTTPException:
    """D-490 부록: every trip error is ``{"detail": {"code", "detail"}}``."""
    return HTTPException(status_code=status, detail={"code": code, "detail": detail or {}})


def install_trip_routes(app, *, console, site_maps, routing_config, require_named_operator, runner,
                        read_guard) -> None:
    app.state.trip_runner = runner
    not_open = _refuse("TRIP_EXECUTION_NOT_AVAILABLE",
                       {"message": "start the plan with POST /api/fleet/trips/{plan_id}/start"}, 501)
    failed_versions: set = set()  # an unexpected planner failure is logged once per map version

    @app.post("/api/fleet/robots/{robot_id}/trip", tags=["fleet"])
    async def fleet_trip(robot_id: str, body: TripRequest,
                         principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        if body.execute:
            raise not_open
        plan_id = uuid.uuid4().hex
        active = site_maps.active()
        summary = body.model_dump(mode="json", exclude={"execute"})

        def record(result: dict) -> None:
            site_maps.record_plan(plan_id=plan_id, robot_id=robot_id[:96], principal_id=principal.principal_id,
                                  map_version=active[0] if active else None, request=summary, result=result)

        if robot_id not in console.robot_ids:
            record({"error": "UNKNOWN_ROBOT"})
            raise _refuse("UNKNOWN_ROBOT", status=404)

        if active is None:
            record({"error": "TRIP_NO_ACTIVE_MAP"})
            raise _refuse("TRIP_NO_ACTIVE_MAP")
        try:
            pose = await console.trusted_map_pose(robot_id)
        except (HubError, RobotApiError, OSError) as exc:
            record({"error": "ROBOT_POSE_UNAVAILABLE", "detail": {"kind": type(exc).__name__}})
            raise http_error(exc) from exc
        if pose is None or pose[2] is None:
            record({"error": "TRIP_POSE_UNTRUSTED"})
            raise _refuse("TRIP_POSE_UNTRUSTED")
        goal = body.to if isinstance(body.to, str) else (body.to.x, body.to.y, body.to.yaw)
        # ponytail: robot kind / drive modes / max speed are not in the robot contract yet;
        # unknown kind keeps kind-restricted edges out, every drive mode is allowed for a preview.
        request = PlanRequest(map_version=active[0], start_pose=(pose[0], pose[1], pose[2]), goal=goal,
                              via=tuple(body.via), arrive_yaw=body.arrive_yaw, speed_cap=body.speed_cap)
        try:
            plan = plan_trip(active[2], request, routing_config)
        except PlanError as exc:
            record({"error": exc.code, "detail": exc.detail})
            raise _refuse(exc.code, exc.detail) from exc
        except Exception as exc:  # a planner bug is a coded 500, logged once, never a bare traceback
            if active[0] not in failed_versions:
                failed_versions.add(active[0])
                _LOG.exception("trip planner failed on site map v%s", active[0])
            record({"error": "TRIP_PLAN_FAILED", "detail": {"kind": type(exc).__name__}})
            raise _refuse("TRIP_PLAN_FAILED", {"map_version": active[0]}, 500) from exc
        body = plan_body(plan)
        # D-491 5: the whole body is kept so /trips/{plan_id}/start runs exactly this plan.
        record({"segments": len(plan.segments), "length_m": plan.length_m, "eta_s": plan.eta_s, "plan": body})
        return {"plan_id": plan_id, **body, "expires_at": time.time() + PLAN_TTL_S}

    def trip_error(exc: TripError) -> HTTPException:
        return _refuse(exc.code, exc.detail, exc.status)

    @app.post("/api/fleet/trips/{plan_id}/start", tags=["fleet"])
    async def fleet_trip_start(plan_id: str, principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            return await runner.start(plan_id, principal.principal_id)
        except TripError as exc:
            raise trip_error(exc) from exc

    @app.post("/api/fleet/trips/{trip_id}/cancel", tags=["fleet"])
    async def fleet_trip_cancel(trip_id: str, principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            return await runner.cancel(trip_id, principal.principal_id)
        except TripError as exc:
            raise trip_error(exc) from exc

    @app.post("/api/fleet/trips/{trip_id}/confirm-replan", tags=["fleet"])
    async def fleet_trip_confirm_replan(trip_id: str,
                                        principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            return await runner.confirm_replan(trip_id, principal.principal_id)
        except TripError as exc:
            raise trip_error(exc) from exc

    @app.get("/api/fleet/trips", dependencies=read_guard, tags=["fleet"])
    def fleet_trips() -> dict:
        return {"running": runner.running(), "trips": runner.recent()}

    @app.get("/api/fleet/trips/{trip_id}", dependencies=read_guard, tags=["fleet"])
    def fleet_trip_view(trip_id: str) -> dict:
        view = runner.view(trip_id)
        if view is None:
            raise _refuse("TRIP_UNKNOWN", status=404)
        return view
