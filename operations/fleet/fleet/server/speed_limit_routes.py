"""D-1005: the console sets a robot's manual speed through CORE, which owns the limits and the ceiling.

Fleet adds no limit of its own: CORE refuses a value above the signed ceiling (400) and records who asked.
"""
from __future__ import annotations

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.hub.hub import HubError
from fleet.server.http_errors import http_error
from fleet.swarm.transport import RobotApiError


class ManualSpeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    manual_linear: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    manual_angular: float | None = Field(default=None, ge=0, allow_inf_nan=False)


def install_speed_limit_routes(app, *, console, require_operator, named_guard) -> None:
    @app.put("/api/fleet/robots/{robot_id}/speed-limits", dependencies=named_guard, tags=["fleet"])
    async def set_manual_speed(robot_id: str, body: ManualSpeedRequest, principal=Depends(require_operator)) -> dict:
        client = console.clients().get(robot_id)
        if client is None:
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_ROBOT"})
        asked = body.model_dump(exclude_none=True)
        if not asked:
            raise HTTPException(status_code=400, detail={"code": "VALIDATION_ERROR", "message": "no speed given"})
        try:
            result = await client.speed_limits({**asked, "operator_name": getattr(principal, "principal_id", None)})
        except (HubError, RobotApiError, OSError, httpx.HTTPError) as exc:
            raise http_error(exc) from exc
        return {"robot_id": robot_id, "limits": result.get("limits")}
