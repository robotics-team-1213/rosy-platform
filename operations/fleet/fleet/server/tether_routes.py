"""D-512 display half: an operator-set tether circle per robot, drawn on the Fleet map.
D-526: ``tether_watch.TetherWatch`` stops a robot outside it; each row carries its ``watch``.
Setting or clearing a tether restarts its watch. Kept in memory: a Fleet restart clears every tether.
"""
from typing import Annotated

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.server.site_auth import SitePrincipal
from fleet.server.tether_watch import TetherWatch, map_pose

Metres = Annotated[float, Field(ge=-1000, le=1000, allow_inf_nan=False)]


class TetherRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    anchor_xy: list[Metres] = Field(min_length=2, max_length=2)  # strict: a JSON array, not a tuple
    radius_m: float = Field(gt=0, le=50, allow_inf_nan=False)


def install_tether_routes(app, *, console, trip_runner, read_guard, require_named_operator) -> None:
    tethers: dict[str, dict] = {}
    app.state.tethers = tethers

    async def pose(robot_id: str):  # the map's pose: a fresh hub heartbeat, else CORE REST
        return map_pose((await console._gather_state(robot_id))[0])

    async def stop(robot_id: str) -> None:  # the existing per-robot CORE E-Stop, then its trip ends
        try:
            await console.hub.scatter_estop(robot_id)
        finally:
            await trip_runner.cancel_robot(robot_id, "tether_trip")
    watch = app.state.tether_watch = TetherWatch(tethers, pose=pose, stop=stop)

    def known(robot_id: str) -> None:
        if robot_id not in console.robot_ids:
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_ROBOT"})

    @app.get("/api/fleet/tethers", dependencies=read_guard, tags=["tether"])
    def tether_list() -> dict:
        for key in [key for key in tethers if key not in console.robot_ids]:  # robot left the roster
            del tethers[key]
        return {"tethers": [{"robot_id": key, **row, "watch": watch.view(key)} for key, row in sorted(tethers.items())]}

    @app.post("/api/fleet/robots/{robot_id}/tether", tags=["tether"])
    def tether_set(robot_id: str, body: TetherRequest,
                   principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        known(robot_id)
        tethers[robot_id] = {"anchor_xy": body.anchor_xy, "radius_m": body.radius_m,
                             "set_by": principal.principal_id}
        watch.reset(robot_id)
        return {"robot_id": robot_id, **tethers[robot_id]}

    @app.delete("/api/fleet/robots/{robot_id}/tether", tags=["tether"])
    def tether_clear(robot_id: str, _principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        known(robot_id)
        watch.reset(robot_id)
        return {"robot_id": robot_id, "cleared": tethers.pop(robot_id, None) is not None}
