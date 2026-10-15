"""D-763 7: ``POST /api/fleet/trip-jobs`` — a named operator starts a job of trip steps (SIM profile only)."""

from __future__ import annotations

import asyncio
import logging

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.server.job_trip_rows import ACTIVE, TripJobRows
from fleet.server.job_trip_steps import KIND, JobTripSteps
from fleet.server.mission_store import MissionConflict
from fleet.server.step_action_kinds import dispatch_open
from fleet.server.trip_ports import TripError
from fleet.server.trip_routes import PlaceRef, TripRequest

_LOG = logging.getLogger(__name__)


class TripJobStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    to: PlaceRef
    via: list[PlaceRef] = Field(default_factory=list, max_length=8)


class TripJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    steps: list[TripJobStep] = Field(min_length=1, max_length=8)


def install_trip_job_routes(app, *, store, runner, console, deployment_profile: str, episodes,
                            require_named_operator, operator_guard):
    """The route and the loop (``app.state.job_trips``); nothing at all outside a profile the registry opens."""
    if store is None:
        return None
    if not dispatch_open(deployment_profile, KIND):  # a TRIP ledger opened here: its open jobs keep no robot moving
        rows = TripJobRows(store)
        for mission_id in rows.ids(ACTIVE):
            rows.hold(mission_id, "FLEET_PROFILE_CLOSED", {})
            _LOG.warning("trip job %s held: the %s profile does not run trip steps", mission_id, deployment_profile)
        return None

    async def plan(robot_id, step, principal_id):
        try:
            return (await app.state.trip_plan(robot_id, TripRequest(**step), principal_id))["plan_id"]
        except HTTPException as exc:
            raise TripError(exc.status_code, exc.detail["code"], exc.detail.get("detail")) from exc

    async def incident(robot_id, job_id, reason, detail):
        """The case of a held job (rev 2 Q3): a human-tier problem episode the AI PC reads; the work list shows 개입."""
        _LOG.warning("trip job %s on %s holds: %s %s", job_id, robot_id, reason, detail)
        await asyncio.to_thread(episodes.opened, robot_id=robot_id, kind="job_hold", tier="human",
                                problem_id=f"job_hold:{job_id}:{detail['held_event']}",  # one per HOLD, retried
                                type_key=f"job_hold:{robot_id}:trip", context={"job_id": job_id, "reason": reason, **detail}, decision=None)

    jobs = app.state.job_trips = JobTripSteps(store, runner, plan=plan, caps=console._shown_capabilities,
                                              incident=incident)
    jobs.recover()

    @app.post("/api/fleet/trip-jobs", dependencies=operator_guard, tags=["fleet-work"])
    async def fleet_trip_job(body: TripJobRequest, principal=Depends(require_named_operator)) -> dict:
        if body.robot_id not in console.robot_ids:
            raise HTTPException(404, detail={"code": "UNKNOWN_ROBOT", "detail": {}})
        active = runner._store.active()
        unknown = sorted({p for s in body.steps for p in (s.to, *s.via)} - set(active[2].places if active else ()))
        if unknown:
            raise HTTPException(422, detail={"code": "TRIP_UNKNOWN_PLACE", "detail": {"places": unknown}})
        try:
            steps = [step.model_dump(mode="json") for step in body.steps]
            return {"job": await jobs.create(body.robot_id, steps, principal.principal_id)}
        except TripError as exc:
            raise HTTPException(exc.status, detail={"code": exc.code, "detail": exc.detail}) from exc
        except MissionConflict as exc:
            raise HTTPException(409, detail={"code": "JOB_ROBOT_REFUSED", "detail": {"message": str(exc)}}) from exc
    return jobs


__all__ = ["install_trip_job_routes"]
