"""D-484 2 / D-486 5: ``POST /api/fleet/robots/{id}/trip`` plans and returns; it never drives.

The robot's LOCALIZED map pose and the active site map go into the pure planner
(``fleet.routing``). Every plan, refused or not, is a row in the site map store (D-486 8).
Execution (``execute: true`` and ``POST /api/fleet/trips/{plan_id}/start``) opens with D-484
M2; until then both answer 501.
"""

from __future__ import annotations

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
from fleet.swarm.transport import RobotApiError

PlaceRef = Annotated[str, Field(min_length=1, max_length=64)]
#: D-486 5: a plan may be started within this long on the same map version.
PLAN_TTL_S = 30.0


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


def _refuse(code: str, detail: Optional[dict] = None) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, "detail": detail or {}})


def install_trip_routes(app, *, console, site_maps, routing_config, require_named_operator) -> None:
    not_open = HTTPException(status_code=501, detail={
        "code": "TRIP_EXECUTION_NOT_AVAILABLE", "message": "trip execution opens with D-484 M2"})

    @app.post("/api/fleet/robots/{robot_id}/trip", tags=["fleet"])
    async def fleet_trip(robot_id: str, body: TripRequest,
                         principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        if body.execute:
            raise not_open
        if robot_id not in console.robot_ids:
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_ROBOT"})
        plan_id = uuid.uuid4().hex
        active = site_maps.active()
        summary = body.model_dump(mode="json", exclude={"execute"})

        def record(result: dict) -> None:
            site_maps.record_plan(plan_id=plan_id, robot_id=robot_id, principal_id=principal.principal_id,
                                  map_version=active[0] if active else None, request=summary, result=result)

        if active is None:
            record({"error": "TRIP_NO_ACTIVE_MAP"})
            raise _refuse("TRIP_NO_ACTIVE_MAP")
        try:
            pose = await console.trusted_map_pose(robot_id)
        except (HubError, RobotApiError, OSError) as exc:
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
        record({"segments": len(plan.segments), "length_m": plan.length_m, "eta_s": plan.eta_s})
        return {
            "plan_id": plan_id, "map_version": plan.map_version,
            "segments": [{"edge_id": e, "forward": f, "s_from": a, "s_to": b} for e, f, a, b in plan.segments],
            "places": list(plan.places),
            "actions": [{"place_id": p, "action": a, "theta_deg": t} for p, a, t in plan.actions],
            "length_m": plan.length_m, "eta_s": plan.eta_s, "expires_at": time.time() + PLAN_TTL_S,
        }

    @app.post("/api/fleet/trips/{plan_id}/start", tags=["fleet"])
    async def fleet_trip_start(plan_id: str, _principal: SitePrincipal = Depends(require_named_operator)):
        raise not_open
