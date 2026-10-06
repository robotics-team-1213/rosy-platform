"""D-488 site map API: read the active map, edit one draft, activate it.

``GET /api/fleet/site-map`` (D-257 camera rectangle) stays as it is; these live below it.
Saving the draft and activating it need a named operator and are recorded as site map
events; activation is also in the HTTP audit and is refused while a lane route is running.
Errors use ``{"detail": {"code", "detail"}}`` like ``/trip``. Nothing here talks to a robot.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fleet.server.site_auth import SitePrincipal
from fleet.server.site_map_store import SiteMapError
from fleet.site_map import SiteMap

#: A 20k-point map is about 0.5 MB of JSON; the draft body is read at most this far.
MAX_DRAFT_BYTES = 2 * 1024 * 1024


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    map: SiteMap
    expected_revision: Optional[str] = Field(default=None, min_length=1, max_length=64)


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(min_length=1, max_length=64)


def site_map_error(status: int, code: str, message: str = "") -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": {"message": message} if message else {}})


async def _bounded_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and (len(declared) > 12 or not declared.isdigit() or int(declared) > MAX_DRAFT_BYTES):
        raise site_map_error(413, "SITE_MAP_TOO_LARGE", f"draft body is limited to {MAX_DRAFT_BYTES} bytes")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_DRAFT_BYTES:
            raise site_map_error(413, "SITE_MAP_TOO_LARGE", f"draft body is limited to {MAX_DRAFT_BYTES} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def install_site_map_routes(app, *, site_maps, route_active, read_guard, require_named_operator) -> None:
    app.state.site_maps = site_maps

    def fail(exc: SiteMapError) -> HTTPException:
        return site_map_error(exc.status_code, exc.code, str(exc))

    @app.get("/api/fleet/site-map/active", dependencies=read_guard, tags=["site-map"])
    def site_map_active() -> dict:
        view = site_maps.active_view()
        if view is None:
            raise site_map_error(404, "SITE_MAP_NOT_ACTIVE")
        return view

    @app.get("/api/fleet/site-map/draft", dependencies=read_guard, tags=["site-map"])
    def site_map_draft() -> dict:
        return site_maps.draft_view()

    @app.put("/api/fleet/site-map/draft", tags=["site-map"])
    async def site_map_save_draft(request: Request,
                                  principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            body = DraftRequest.model_validate_json(await _bounded_body(request))
        except ValidationError as exc:  # field errors without the submitted values
            errors = [{"loc": [str(part) for part in item["loc"]], "msg": item["msg"]}
                      for item in exc.errors(include_url=False, include_context=False, include_input=False)[:20]]
            raise HTTPException(status_code=422, detail={"code": "SITE_MAP_INVALID",
                                                         "detail": {"errors": errors}}) from exc
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
