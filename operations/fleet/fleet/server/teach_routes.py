"""D-494 6 teach API: record a driven lane and add it (or an address) to the site map draft.

Every write needs a named operator and is a site map event beside the HTTP audit. Errors are
``{"detail": {"code", "detail"}}`` like the site map routes. Nothing here moves a robot.
"""

from __future__ import annotations

import inspect
from typing import Annotated, Literal, Optional, Union

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.server.site_auth import SitePrincipal
from fleet.site_map import PlaceKind
from fleet.server.site_map_store import SiteMapError
from fleet.server.teach_service import TeachError, TeachService

PlaceId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,32}$")]
Revision = Optional[Annotated[str, Field(min_length=1, max_length=64)]]


class NewPlace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)
    # an edge end has no robot yaw, so it cannot be a D-513 start place
    kind: Literal["park", "charge", "stop", "junction", "turnaround"] = "junction"


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: str = Field(min_length=1, max_length=96)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    teach_id: str = Field(min_length=1, max_length=64)
    from_: Union[PlaceId, NewPlace] = Field(alias="from")
    to: Union[PlaceId, NewPlace]
    direction: Literal["one_way", "two_way"] = "one_way"
    drive_mode: Literal["lane", "free"] = "lane"
    speed_cap_mps: float = Field(gt=0.0, le=5.0, allow_inf_nan=False)
    width_m: Optional[float] = Field(default=None, gt=0.0, le=10.0, allow_inf_nan=False)
    expected_revision: Revision = None


class PlaceRequest(NewPlace):
    robot_id: str = Field(min_length=1, max_length=96)
    kind: PlaceKind = "junction"
    expected_revision: Revision = None


def _ref(value):
    return value.model_dump() if isinstance(value, NewPlace) else value


def install_teach_routes(app, *, service: TeachService, read_guard, require_named_operator) -> None:
    app.state.teach = service

    async def guarded(work):
        try:
            result = work()
            return await result if inspect.isawaitable(result) else result
        except TeachError as exc:
            raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": exc.detail}) from exc
        except SiteMapError as exc:
            raise HTTPException(status_code=exc.status_code,
                                detail={"code": exc.code, "detail": {"message": str(exc)}}) from exc

    @app.get("/api/fleet/teach", dependencies=read_guard, tags=["site-map"])
    def teach_view() -> dict:
        return service.view()

    @app.post("/api/fleet/teach/start", tags=["site-map"])
    async def teach_start(body: StartRequest, principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        return await guarded(lambda: service.start(body.robot_id, principal.principal_id))

    @app.post("/api/fleet/teach/stop", tags=["site-map"])
    async def teach_stop(principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        return await guarded(lambda: service.stop(principal.principal_id))

    @app.post("/api/fleet/teach/confirm", tags=["site-map"])
    async def teach_confirm(body: ConfirmRequest, principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        return await guarded(lambda: service.confirm(
            body.teach_id, start=_ref(body.from_), end=_ref(body.to), direction=body.direction,
            drive_mode=body.drive_mode, speed_cap_mps=body.speed_cap_mps, width_m=body.width_m,
            expected_revision=body.expected_revision, principal_id=principal.principal_id))

    @app.post("/api/fleet/teach/place", tags=["site-map"])
    async def teach_place(body: PlaceRequest, principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        return await guarded(lambda: service.place(body.robot_id, name=body.name, kind=body.kind,
                                                   expected_revision=body.expected_revision,
                                                   principal_id=principal.principal_id))
