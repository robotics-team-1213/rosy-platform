"""D-484 site map API: read the active map, edit one draft, activate it.

``GET /api/fleet/site-map`` (D-257 camera rectangle) stays as it is; these live below it.
Activation needs a named operator, is in the HTTP audit, and is refused while a lane route
is running. Nothing here talks to a robot.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.server.site_auth import SitePrincipal
from fleet.server.site_map_store import SiteMapError
from fleet.site_map import SiteMap


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    map: SiteMap
    expected_revision: Optional[str] = Field(default=None, min_length=1, max_length=64)


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(min_length=1, max_length=64)


def install_site_map_routes(app, *, site_maps, route_active, read_guard,
                            require_operator, require_named_operator) -> None:
    app.state.site_maps = site_maps

    def fail(exc: SiteMapError) -> HTTPException:
        return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})

    @app.get("/api/fleet/site-map/active", dependencies=read_guard, tags=["site-map"])
    def site_map_active() -> dict:
        view = site_maps.active_view()
        if view is None:
            raise HTTPException(status_code=404, detail={"code": "SITE_MAP_NOT_ACTIVE"})
        return view

    @app.get("/api/fleet/site-map/draft", dependencies=read_guard, tags=["site-map"])
    def site_map_draft() -> dict:
        return site_maps.draft_view()

    @app.put("/api/fleet/site-map/draft", tags=["site-map"])
    def site_map_save_draft(body: DraftRequest, principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            return site_maps.save_draft(body.map, expected_revision=body.expected_revision,
                                        principal_id=principal.principal_id)
        except SiteMapError as exc:
            raise fail(exc) from exc

    @app.post("/api/fleet/site-map/activate", tags=["site-map"])
    def site_map_activate(body: ActivateRequest,
                          principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            return site_maps.activate(expected_revision=body.expected_revision,
                                      principal_id=principal.principal_id, route_active=route_active())
        except SiteMapError as exc:
            raise fail(exc) from exc
