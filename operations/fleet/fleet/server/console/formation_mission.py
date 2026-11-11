"""D-1002: a formation mission on site lanes — the leader's TRIP job plus a FOR-004 follower session, one record.

Fleet composes two things it already owns and adds only the lane check: the followers are armed first
(``FormationControl.formation_start``, D-20 relay + robot-side TRAIL/COLUMN follow), then the leader gets
an ordinary trip job (``create_trip_job``, D-763 7), so the step ledger row is the mission record and its
``mission_id`` names the formation. FOR-004 already cancels the leader's navigation on HOLD/ABORT, which the
leader's trip job records as HOLD; when the leader's job ends (lease released) the formation is stopped here.
Fleet never sends ``/cmd_vel``: every stop is the robot's own (SWM-004, D-18).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core_common.protocol.trip_jobs import TripJobStep
from fleet.hub.hub import HubError
from fleet.swarm.api.types import DEFAULT_SPACING, Formation, MIN_SPACING

log = logging.getLogger(__name__)

#: Site lane width (world_261026 track, 2.44 x 1.22 m) and the robot body the lane must hold twice side by side for
#: any formation with a lateral slot; it never does, so only single-file formations drive on lanes.
LANE_WIDTH_M = 1.22
ROBOT_BODY_M = 0.20
#: Relay cut -> follower hold measured in SIM (D-559: 1.14-1.20 s); the spacing must cover the distance a
#: follower travels while the stop is still arriving, plus one body and a margin.
HOLD_LATENCY_S = 1.5
SPACING_MARGIN_M = 0.10
DEFAULT_MAX_SPEED = 0.18
LANE_FORMATIONS = (Formation.COLUMN, Formation.TRAIL)
#: consecutive ledger read failures (0.5 s apart) before the mission ends and disarms rather than watch a row it cannot see
LEDGER_READ_FAILURES_MAX = 10
MAX_FOLLOWERS = 3  # 2-4 robots in a 2.44 m straight: more cannot stand single file at MIN_SPACING


def min_lane_spacing(max_speed: float) -> float:
    return ROBOT_BODY_M + max_speed * HOLD_LATENCY_S + SPACING_MARGIN_M


def lane_fit(formation: str, spacing: Optional[float], max_speed: Optional[float], followers: int, *,
             lane_width_m: float = LANE_WIDTH_M) -> dict:
    """Reject before any robot is armed. Returns the checked numbers for the mission view."""
    try:
        shape = Formation(formation)
    except ValueError as exc:
        raise HubError("INVALID_FORMATION", f"unknown formation {formation!r}") from exc
    spacing = DEFAULT_SPACING if spacing is None else float(spacing)
    speed = DEFAULT_MAX_SPEED if max_speed is None else float(max_speed)
    if shape not in LANE_FORMATIONS:
        raise HubError("FORMATION_LANE_UNFIT",
                       f"{shape.value} needs a lateral slot; a {lane_width_m} m lane holds one {ROBOT_BODY_M} m "
                       "body per row, use COLUMN or TRAIL")
    floor = max(MIN_SPACING, min_lane_spacing(speed))
    if spacing < floor:
        raise HubError("FORMATION_LANE_UNFIT",
                       f"spacing {spacing} m is under the stopping gap {floor:.2f} m at {speed} m/s "
                       f"(body {ROBOT_BODY_M} + {HOLD_LATENCY_S} s hold latency + {SPACING_MARGIN_M} margin)")
    if not 1 <= followers <= MAX_FOLLOWERS:
        raise HubError("FORMATION_LANE_UNFIT", f"{followers} followers; lanes take 1-{MAX_FOLLOWERS}")
    return {"formation": shape.value, "spacing": spacing, "max_speed": speed, "spacing_floor": round(floor, 3),
            "lane_width_m": lane_width_m, "followers": followers}


class FormationMissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    leader: str
    members: list[str] = Field(min_length=2, max_length=1 + MAX_FOLLOWERS)
    formation: str = "TRAIL"
    spacing: Optional[float] = None
    max_speed: Optional[float] = None
    steps: list[TripJobStep] = Field(min_length=1, max_length=8)


class FormationMission:
    """One formation mission at a time; ``start`` arms, then opens the leader's trip job."""

    def __init__(self, console, create_job: Callable[..., Awaitable[dict]],
                 leader_job_open: Callable[[str], Awaitable[bool]], *, period_s: float = 0.5) -> None:
        """``leader_job_open(mission_id)`` reads the ledger row: a HOLD keeps the lease entry (``lease.jobs``) until
        a person resumes or cancels, so the lease is not the signal; the row status is."""
        self._console, self._create_job, self._leader_job_open = console, create_job, leader_job_open
        self._period_s = period_s
        self.view: Optional[dict] = None
        self._watch: Optional[asyncio.Task] = None

    async def start(self, body: FormationMissionRequest, principal_id: str) -> dict:
        if self.view is not None and self.view["state"] == "RUNNING":
            raise HubError("FORMATION_ACTIVE", "a formation mission is running; stop it first")
        fit = lane_fit(body.formation, body.spacing, body.max_speed, len(body.members) - 1)
        status = await self._console.formation_start(body.leader, fit["formation"], fit["spacing"], fit["max_speed"],
                                                     members=body.members)
        steps = [step.model_dump(mode="json") for step in body.steps]
        try:
            job = await self._create_job(body.leader, steps, principal_id)
        except BaseException:
            await self._console.formation_stop()  # armed followers must not wait for a leader that never drives
            raise
        self.view = {"mission_id": job["mission_id"], "leader": body.leader, "members": list(body.members),
                     "state": "RUNNING", "end_reason": None, **fit, "formation_status": status}
        self._watch = asyncio.get_running_loop().create_task(self._run())
        return self.status()

    def status(self) -> dict:
        if self.view is None:
            return {"active": False}
        return {"active": self.view["state"] == "RUNNING", **self.view,
                "formation_status": self._console.formation_status()}

    async def _run(self) -> None:
        """The leader's job leaves READY/RUNNING (arrived, HOLD after FOR-004 cancelled it, cancelled): the
        formation ends with it."""
        mission_id, failures = self.view["mission_id"], 0
        while True:
            try:
                if not await self._leader_job_open(mission_id):
                    break
                failures = 0
            except Exception as exc:  # noqa: BLE001 - a ledger read failure must not leave followers armed for ever
                failures += 1
                log.warning("formation mission %s: ledger read failed (%d): %s", mission_id, failures, exc)
                if failures >= LEDGER_READ_FAILURES_MAX:
                    self.view["end_reason"] = "ledger_unreadable"
                    break
            await asyncio.sleep(self._period_s)
        formation = self._console.formation_status()
        self.view["end_reason"] = self.view["end_reason"] or formation.get("reason") or "leader_job_ended"
        self.view["state"] = "ENDED"
        try:
            await self._console.formation_stop()
        except Exception as exc:  # noqa: BLE001 - the stop reason is still recorded
            log.warning("formation mission %s: stop failed: %s", self.view["mission_id"], exc)

    async def stop(self) -> dict:
        if self._watch is not None:
            self._watch.cancel()
        if self.view is not None and self.view["state"] == "RUNNING":
            self.view.update(state="ENDED", end_reason="stopped")
        # FOR-004 stop cancels the leader's navigation; the step trip ends and the job HOLDs through the incident
        # path like every stop sent through Fleet (D-763 rev 2 Q3): a person resumes or cancels that job.
        await self._console.formation_stop()
        return self.status()


def leader_job_open(store, mission_id: str) -> bool:
    """A READY/RUNNING/ACTION_SUCCEEDED row; HOLD and GOAL_CONFIRMED (and a gone row) end the formation."""
    from fleet.server.job_trip_rows import ACTIVE
    job = store.get(mission_id)
    return job is not None and job["status"] in ACTIVE


def install_formation_mission_routes(app, *, console, jobs, require_named_operator, operator_guard, read_guard):
    from fleet.server.trip_job_routes import create_trip_job
    from fleet.server.trip_ports import TripError

    if jobs is None:  # this deployment profile runs no TRIP steps (D-763 7): no leader job, no formation mission
        app.state.formation_mission = None
        return None

    async def create_job(leader: str, steps: list, principal_id: str) -> dict:
        return await create_trip_job(jobs, leader, steps, principal_id)

    mission = app.state.formation_mission = FormationMission(
        console, create_job, lambda mission_id: asyncio.to_thread(leader_job_open, jobs.store, mission_id))

    @app.get("/api/fleet/formation/mission", dependencies=read_guard, tags=["formation"])
    async def formation_mission_state() -> dict:
        return mission.status()

    @app.post("/api/fleet/formation/mission", dependencies=operator_guard, tags=["formation"])
    async def formation_mission_start(body: FormationMissionRequest, principal=Depends(require_named_operator)) -> dict:
        try:
            return await mission.start(body, principal.principal_id)
        except HubError as exc:
            raise HTTPException(409 if exc.code == "FORMATION_ACTIVE" else 422,
                                detail={"code": exc.code, "detail": {"message": str(exc)}}) from exc
        except TripError as exc:
            raise HTTPException(exc.status, detail={"code": exc.code, "detail": exc.detail}) from exc

    @app.post("/api/fleet/formation/mission/stop", dependencies=operator_guard, tags=["formation"])
    async def formation_mission_stop() -> dict:
        return await mission.stop()

    return mission


__all__ = ["FormationMission", "FormationMissionRequest", "lane_fit", "leader_job_open", "min_lane_spacing",
           "install_formation_mission_routes"]
