"""D-2/D-369: the Fleet console's forward/backward step is CORE's reviewed nudge mission.

Fleet never drives (`fleet.server.nudge_routes`): it only checks the robot is free and asks
CORE's `POST /api/v1/localization/mission` (`nudge_forward` / `nudge_backward`), whose D-424
body clearance, blind-beam and stop-gap rules judge the step's direction. A relative step is
in the robot's own frame — it needs no site pose and no `LOCALIZED` robot, which is why the
site-frame `road-nav2` route stays out of this.
"""

from __future__ import annotations

import logging
from typing import Callable

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.server.http_errors import http_error
from fleet.server.trip_guard import engaged
from fleet.swarm.transport import RobotApiError

logger = logging.getLogger(__name__)

#: CORE `MissionConfig.nudge_linear` / `nudge_max_m`; `max_time_s` = distance / speed + spare.
NUDGE_LINEAR_MPS = 0.03
NUDGE_MAX_M = 0.10
SPARE_S = 5.0


class StepRequest(BaseModel):
    """One relative step of the robot in its own frame."""
    model_config = ConfigDict(extra="forbid")
    direction: str = Field(pattern="^(forward|backward)$")
    distance_m: float = Field(default=NUDGE_MAX_M, gt=0.0, le=NUDGE_MAX_M, allow_inf_nan=False)


def install_nudge_step_route(app, *, console, trip_busy: Callable[[str], bool],
                             require_named_operator, record_event) -> None:
    """`POST /api/fleet/robots/{robot_id}/step`: a named operator steps a free robot."""

    @app.post("/api/fleet/robots/{robot_id}/step", tags=["fleet"])
    async def robot_step(robot_id: str, body: StepRequest,
                         principal=Depends(require_named_operator)) -> dict:
        client = console.clients().get(robot_id)
        if client is None:
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_ROBOT"})
        held = engaged(console, robot_id) or ("trip" if trip_busy(robot_id) else None)
        if held:
            raise HTTPException(status_code=409, detail={
                "code": "STEP_ROBOT_BUSY",
                "message": f"{robot_id} already moves for the console ({held}); stop that first"})
        kind = "nudge_forward" if body.direction == "forward" else "nudge_backward"
        try:
            answer = await client.localization_mission(
                kind, max_distance_m=body.distance_m,
                max_time_s=body.distance_m / NUDGE_LINEAR_MPS + SPARE_S)
        except (RobotApiError, OSError, httpx.HTTPError) as exc:
            if isinstance(exc, (OSError, httpx.HTTPError)):
                raise HTTPException(status_code=409, detail={
                    "code": "ROBOT_OFFLINE",
                    "message": f"{robot_id} did not answer the step request"}) from exc
            raise http_error(exc) from exc    # CORE refused (clearance, lease, readiness): its words
        record_event("step", principal.principal_id, {
            "robot_id": robot_id, "direction": body.direction, "distance_m": body.distance_m,
            "kind": kind, "mission": answer})
        logger.info("step: %s %s %.3f m by %s -> %s", robot_id, body.direction,
                    body.distance_m, principal.principal_id, answer.get("state"))
        return answer
