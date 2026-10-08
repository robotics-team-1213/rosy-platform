"""D-512 display half: an operator-set tether circle per robot, drawn on the Fleet map.

Fleet only shows it; the guard that stops a run outside the circle is tools/device_test.
Kept in memory: a Fleet restart clears every tether.
"""
from typing import Annotated

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.server.site_auth import SitePrincipal

Metres = Annotated[float, Field(allow_inf_nan=False)]


class TetherRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    anchor_xy: list[Metres] = Field(min_length=2, max_length=2)  # strict: a JSON array, not a tuple
    radius_m: float = Field(gt=0, le=50, allow_inf_nan=False)


def install_tether_routes(app, *, robot_ids, read_guard, require_named_operator) -> None:
    tethers: dict[str, dict] = {}
    app.state.tethers = tethers

    def known(robot_id: str) -> None:
        if robot_id not in robot_ids():
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_ROBOT"})

    @app.get("/api/fleet/tethers", dependencies=read_guard, tags=["tether"])
    def tether_list() -> dict:
        return {"tethers": [{"robot_id": key, **row} for key, row in sorted(tethers.items())]}

    @app.post("/api/fleet/robots/{robot_id}/tether", tags=["tether"])
    def tether_set(robot_id: str, body: TetherRequest,
                   principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        known(robot_id)
        tethers[robot_id] = {"anchor_xy": body.anchor_xy, "radius_m": body.radius_m,
                             "set_by": principal.principal_id}
        return {"robot_id": robot_id, **tethers[robot_id]}

    @app.delete("/api/fleet/robots/{robot_id}/tether", tags=["tether"])
    def tether_clear(robot_id: str, _principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        known(robot_id)
        return {"robot_id": robot_id, "cleared": tethers.pop(robot_id, None) is not None}
