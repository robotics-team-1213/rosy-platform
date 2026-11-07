"""D-721 Amendment (S1): the station recovery requests Fleet can read, and an operator's recorded approval.

Read-only plus one record. Approval commands no robot: motion is S2, so the response says
``started: false``. The list and the approval both answer from the same ``decide`` call at the time
of the request, so an approval never outlives the answer that justified it.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Awaitable, Callable, Optional

from fastapi import Depends, HTTPException

from fleet.server.console.person_request_routes import install_person_request_routes
from fleet.server.console.person_request_store import PersonRequestStore
from fleet.station_recovery import decide

logger = logging.getLogger(__name__)


def _conflict(code: str, **detail) -> HTTPException:
    return HTTPException(409, detail={"code": code, **detail})


def install_person_requests(app, gathered, read_guard, require_named_operator, require_proposer) -> None:
    tasks = getattr(app.state, "task_service", None)
    store = PersonRequestStore(tasks.store.path if tasks is not None else None)

    async def known_robots() -> set:
        return {row["robot_id"] for row in (await gathered())["robots"]}
    install_person_request_routes(app, store, read_guard, require_proposer, require_named_operator, known_robots)


def _by_battery(row: dict) -> tuple:
    """Lowest battery first, unknown last, so the neediest robot is offered a bay first."""
    percent = ((row.get("power_health") or {}).get("battery") or {}).get("percent")
    return (not isinstance(percent, (int, float)), percent if isinstance(percent, (int, float)) else 0.0,
            row["robot_id"])


def install_station_recovery_routes(app, enabled: bool, guards: tuple,
                                    gathered: Callable[[], Awaitable[dict]],
                                    bay_inputs: Callable[[], Awaitable[tuple]]) -> None:
    """``enabled`` is ``fleet.station_recovery.enabled`` (default false); off, nothing is asked or approved.

    ``guards`` is ``(read_guard, require_named_operator, require_proposer)``. The person request routes
    (always on, they only note what a person is asked to do) are installed here too.

    The charge-bay plan, map pose service and site map event log are read from ``app.state`` when asked.
    """
    read_guard, require_named_operator, require_proposer = guards
    install_person_requests(app, gathered, read_guard, require_named_operator, require_proposer)
    map_pose = getattr(app.state, "map_pose", None)
    another_returning = lambda: False   # S1 starts no return; S2 reads the open recovery trips here

    async def answers() -> tuple[Optional[int], list[dict]]:
        active, robots, bays = await bay_inputs()
        plan = app.state.charge_bays.plan(robots, bays) if active is not None and bays else None
        rows = (await gathered())["robots"]
        low_first = sorted(rows, key=_by_battery)
        returning, out = another_returning(), []
        for row in low_first:
            pose = map_pose.arbitrated_pose(row["robot_id"]) if map_pose is not None else None
            answer = decide(row, pose, plan, returning)
            if answer is None:
                continue
            if answer["bay"] is not None and plan is not None:   # two askers never get the same bay
                plan = deepcopy(plan)
                for b in plan["bays"]:
                    if b["bay"] == answer["bay"]:
                        b["state"], b["robot_id"] = "planned", row["robot_id"]
            out.append(answer)
        return (active[0] if active is not None else None), sorted(out, key=lambda a: a["robot_id"])

    @app.get("/api/fleet/station-recovery", dependencies=read_guard, tags=["fleet"])
    async def station_recovery_requests() -> dict:
        if not enabled:
            return {"enabled": False, "reason": "disabled", "map_version": None, "requests": [], "dispatch": False}
        map_version, requests = await answers()
        return {"enabled": True, "reason": None, "map_version": map_version, "requests": requests,
                "dispatch": False}

    @app.post("/api/fleet/station-recovery/{robot_id}/approve", tags=["fleet"])
    async def station_recovery_approve(robot_id: str, principal=Depends(require_named_operator)) -> dict:
        if not enabled:
            raise _conflict("STATION_RECOVERY_DISABLED")
        map_version, requests = await answers()
        answer = next((a for a in requests if a["robot_id"] == robot_id), None)
        if answer is None or not answer["request"]:
            raise _conflict("STATION_RECOVERY_NOT_ACTIONABLE", reason=(answer or {}).get("reason") or "no_request")
        if answer["reason"] is not None:
            raise _conflict("STATION_RECOVERY_NOT_ACTIONABLE", reason=answer["reason"])
        maps = getattr(app.state, "site_maps", None)
        if maps is not None:
            maps.record_event("station_recovery_approved", principal.principal_id,
                         {"robot_id": robot_id, "bay": answer["bay"], "level": answer["level"],
                          "percent": answer["percent"], "map_version": map_version, "started": False})
        logger.info("station recovery: %s approved by %s for bay %s (S1 records only, nothing was sent)",
                    robot_id, principal.principal_id, answer["bay"])
        return {"robot_id": robot_id, "approved": True, "bay": answer["bay"], "started": False,
                "reason": "not_implemented",
                "message": "Approval recorded. Motion is not built yet, so no robot was commanded."}
