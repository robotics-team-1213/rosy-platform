"""Authenticated map reference editing; no robot command delegation."""
import math

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from fleet.server.site_auth import SitePrincipal
from fleet.server.start_points import StartPointError


class StartPointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    map_id: str = Field(min_length=1, max_length=160)
    calibration_revision: str = Field(min_length=1, max_length=160)
    expected_revision: str | None = Field(default=None, min_length=1, max_length=64)
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    yaw: float = Field(ge=-math.pi, le=math.pi, allow_inf_nan=False)


def install_start_point_routes(app, *, service, read_guard, require_operator):
    app.state.start_points = service
    def fail(exc):
        return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})

    @app.get("/api/fleet/start-points", dependencies=read_guard, tags=["start-points"])
    async def listing():
        return service.listing()

    @app.put("/api/fleet/start-points/{source_id}", tags=["start-points"])
    async def save(source_id: str, body: StartPointRequest, principal: SitePrincipal = Depends(require_operator)):
        try:
            return service.save(source_id, body.model_dump(), principal_id=principal.principal_id)
        except StartPointError as exc:
            raise fail(exc) from exc

    @app.delete("/api/fleet/start-points/{source_id}", tags=["start-points"])
    async def delete(source_id: str, expected_revision: str = Query(min_length=1, max_length=64),
                     principal: SitePrincipal = Depends(require_operator)):
        try:
            return service.delete(source_id, expected_revision=expected_revision, principal_id=principal.principal_id)
        except StartPointError as exc:
            raise fail(exc) from exc
