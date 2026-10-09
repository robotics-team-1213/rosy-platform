"""D-512 display half: an operator-set tether circle per robot, drawn on the Fleet map.
D-526: ``tether_watch.TetherWatch`` stops a robot outside it; each row carries its ``watch``.
Setting or clearing a tether restarts its watch. Kept in memory: a Fleet restart clears every tether.
"""
import logging
from typing import Annotated

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.server.site_auth import SitePrincipal
from fleet.server.tether_watch import TetherWatch, map_pose

_LOG = logging.getLogger("fleet.tether_routes")
Metres = Annotated[float, Field(ge=-1000, le=1000, allow_inf_nan=False)]


class TetherRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    anchor_xy: list[Metres] = Field(min_length=2, max_length=2)  # strict: a JSON array, not a tuple
    radius_m: float = Field(gt=0, le=50, allow_inf_nan=False)


def install_tether_routes(app, *, console, trip_runner, read_guard, require_named_operator) -> None:
    tethers: dict[str, dict] = {}
    app.state.tethers = tethers

    stamps: dict[str, object] = {}

    async def pose(robot_id: str):
        """The map's pose, counted only when CORE judges its pose channel fresh (evidence.pose, STALE_POSE_S)
        and the state is new since the last read (the stamp catches a cached hub state; a repeated stamp skips
        that tick only, the 2 s pose age in the watch decides). Missing evidence (older CORE) is no pose."""
        state = (await console._gather_state(robot_id))[0] or {}
        evidence = (state.get("evidence") or {}).get("pose")
        if not isinstance(evidence, dict) or evidence.get("evidence") != "fresh":
            return None
        stamp = state.get("timestamp")  # robot clock: used only to tell one state from the next
        if stamp is None or stamps.get(robot_id) == stamp:
            return None
        stamps[robot_id] = stamp
        return map_pose(state)

    async def stop(robot_id: str) -> None:  # the existing per-robot CORE E-Stop, then its trip ends
        try:
            await console.hub.scatter_estop(robot_id)
        finally:  # the E-Stop's outcome stands even if ending the trip fails
            try:
                await trip_runner.cancel_robot(robot_id, "tether_trip")
            except Exception:
                _LOG.exception("tether trip cancel failed robot=%s", robot_id)
    watch = app.state.tether_watch = TetherWatch(tethers, pose=pose, stop=stop)
    console.alarm_sources.append(watch.alarms)

    def known(robot_id: str) -> None:
        if robot_id not in console.robot_ids:
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_ROBOT"})

    @app.get("/api/fleet/tethers", dependencies=read_guard, tags=["tether"])
    def tether_list() -> dict:
        for key in [key for key in tethers if key not in console.robot_ids]:  # robot left the roster
            del tethers[key]
        return {"watch_age_s": watch.tick_age_s(), "tethers": [{"robot_id": key, **row, "watch": watch.view(key)} for key, row in sorted(tethers.items())]}

    @app.post("/api/fleet/robots/{robot_id}/tether", tags=["tether"])
    def tether_set(robot_id: str, body: TetherRequest,
                   principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        known(robot_id)
        old = tethers.get(robot_id)
        _LOG.warning("tether set robot=%s by=%s radius_m=%s->%s", robot_id, principal.principal_id,
                     None if old is None else old["radius_m"], body.radius_m)
        tethers[robot_id] = {"anchor_xy": body.anchor_xy, "radius_m": body.radius_m,
                             "set_by": principal.principal_id}
        watch.reset(robot_id)
        return {"robot_id": robot_id, **tethers[robot_id]}

    @app.delete("/api/fleet/robots/{robot_id}/tether", tags=["tether"])
    def tether_clear(robot_id: str, principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        known(robot_id)
        old = tethers.get(robot_id)
        _LOG.warning("tether cleared robot=%s by=%s radius_m=%s", robot_id, principal.principal_id,
                     None if old is None else old["radius_m"])
        watch.reset(robot_id)
        return {"robot_id": robot_id, "cleared": tethers.pop(robot_id, None) is not None}
