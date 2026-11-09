"""D-721 Amendment (S1): the station recovery requests Fleet can read, and their recorded approval.

Read-only plus one record. Fleet approves an actionable request by itself (``fleet:auto``, user decision
2026-11-08: a low robot must not wait for a person); a named operator may still approve by hand. Approval
commands no robot: motion is S2, so the response says ``started: false``. The list and the approval both
answer from the same ``decide`` call at the time, so an approval never outlives the answer that justified it.
"""

from __future__ import annotations

import logging
import time
from copy import deepcopy
from typing import Awaitable, Callable, Optional

from fastapi import Depends, HTTPException

from fleet.server.person_request_routes import install_person_request_routes
from fleet.server.person_request_store import PersonRequestStore
from fleet.station_recovery import decide

logger = logging.getLogger(__name__)


AUTO_APPROVER = "fleet:auto"
AUTO_EVERY_S = 5.0


def _conflict(code: str, **detail) -> HTTPException:
    return HTTPException(409, detail={"code": code, **detail})


class RobotRequests:
    """Delivers an open person request to its robot through the roster's own authenticated client, and takes it
    away again. These two calls are everything a person request may do to a robot."""

    def __init__(self, clients, wall=time.time) -> None:
        self._clients, self._wall = clients, wall

    async def put(self, robot_id: str, record: dict) -> None:
        await self._clients[robot_id].person_request_put({
            "request_id": record["id"], "kind": record["kind"], "text": record["text"], "why": record["why"],
            "ttl_s": max(1.0, min(3600.0, record["expires_at"] - self._wall()))})

    async def read(self, robot_id: str):
        """What the robot holds right now (its view, with ``id``), or None. Raises when it cannot be read."""
        return (await self._clients[robot_id].person_request_get()).get("person_request")

    async def clear(self, robot_id: str, request_id: str) -> None:
        await self._clients[robot_id].person_request_clear(request_id)


def install_person_requests(app, gathered, read_guard, require_named_operator, require_proposer) -> None:
    tasks = getattr(app.state, "task_service", None)
    store = PersonRequestStore(tasks.store.path if tasks is not None else None)

    async def known_robots() -> set:
        return {row["robot_id"] for row in (await gathered())["robots"]}
    console = getattr(app.state, "console", None)
    robots = RobotRequests(console.clients) if console is not None else None
    install_person_request_routes(app, store, read_guard, require_proposer, require_named_operator, known_robots,
                                  robots)


def _by_battery(row: dict) -> tuple:
    """Lowest battery first, unknown last, so the neediest robot is offered a bay first."""
    percent = ((row.get("power_health") or {}).get("battery") or {}).get("percent")
    return (not isinstance(percent, (int, float)), percent if isinstance(percent, (int, float)) else 0.0,
            row["robot_id"])


def install_station_recovery_routes(app, enabled: bool, guards: tuple,
                                    gathered: Callable[[], Awaitable[dict]],
                                    bay_inputs: Callable[[], Awaitable[tuple]], monotonic=time.monotonic) -> None:
    """``enabled`` is ``fleet.station_recovery.enabled`` (default false); off, nothing is asked or approved.

    ``guards`` is ``(read_guard, require_named_operator, require_proposer)``. The person request routes
    (always on, they only note what a person is asked to do) are installed here too.

    The charge-bay plan, map pose service and site map event log are read from ``app.state`` when asked.
    ``app.state.station_recovery_auto`` is the periodic step that approves actionable requests; it rides
    Fleet's charge-bay tick.
    """
    read_guard, require_named_operator, require_proposer = guards
    install_person_requests(app, gathered, read_guard, require_named_operator, require_proposer)
    map_pose = getattr(app.state, "map_pose", None)
    another_returning = lambda: False   # S1 starts no return; S2 reads the open recovery trips here
    approved: dict = {}   # robot_id -> who approved while its request stays actionable; S2 starts from it
    last = {"at": None}

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
            out.append({**answer, "approved_by": approved.get(row["robot_id"])})
        return (active[0] if active is not None else None), sorted(out, key=lambda a: a["robot_id"])

    def record_approval(answer: dict, by: str, map_version) -> None:
        approved[answer["robot_id"]] = by
        maps = getattr(app.state, "site_maps", None)
        if maps is not None:
            maps.record_event("station_recovery_approved", by,
                              {"robot_id": answer["robot_id"], "bay": answer["bay"], "level": answer["level"],
                               "percent": answer["percent"], "map_version": map_version, "started": False})
        logger.info("station recovery: %s approved by %s for bay %s (S1 records only, nothing was sent)",
                    answer["robot_id"], by, answer["bay"])

    async def auto_approve() -> None:
        """Approve each actionable request once; a robot that stops being actionable is asked afresh next time."""
        if not enabled:
            return
        now = monotonic()
        if last["at"] is not None and now - last["at"] < AUTO_EVERY_S:
            return
        last["at"] = now
        map_version, requests = await answers()
        ready = {a["robot_id"]: a for a in requests if a["request"] and a["reason"] is None}
        for robot_id in [r for r in approved if r not in ready]:
            del approved[robot_id]
        for robot_id, answer in sorted(ready.items()):
            if robot_id not in approved:
                record_approval(answer, AUTO_APPROVER, map_version)
    app.state.station_recovery_auto = auto_approve
    tick = getattr(app.state, "charge_bays_tick", None)   # Fleet's existing one-second loop carries it
    if tick is not None and enabled:
        async def tick_and_approve() -> None:
            await tick()
            await auto_approve()
        app.state.charge_bays_tick = tick_and_approve

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
        record_approval(answer, principal.principal_id, map_version)
        return {"robot_id": robot_id, "approved": True, "bay": answer["bay"], "started": False,
                "reason": "not_implemented",
                "message": "Approval recorded. Motion is not built yet, so no robot was commanded."}
