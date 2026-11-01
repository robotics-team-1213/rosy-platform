"""D-763 7: ``POST /api/fleet/trip-jobs`` — a named operator starts a job of trip steps (SIM profile only)."""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import Depends, HTTPException, Path
from core_common.protocol.schemas import (TripJobRequest, TripJobStep,  # noqa: F401 (legacy route exports)
                                         TripJobReadResponse, TripRequestKey)

from fleet.server.job_trip_rows import ACTIVE, TripJobRows
from fleet.server.job_trip_steps import KIND, JobTripSteps
from fleet.server.mission_store import MissionConflict
from fleet.server.step_action_kinds import dispatch_open, required_approval
from fleet.server.trip_ports import TripError
from fleet.server.trip_routes import TripRequest

_LOG = logging.getLogger(__name__)


async def create_trip_job(jobs, robot_id: str, steps: list, principal_id: str, *,
                          request_key: str | None = None, request_digest: str | None = None,
                          approved_by: str | None = None, proposal_id: str | None = None,
                          expected_proposal_digest: str | None = None,
                          expected_generation: int | None = None) -> dict:
    """The 새 작업 approval: one named operator approves and starts it (registry ``one_person``); the gate is
    ``hold_job``'s, then the ledger row (``JobTripSteps`` runs it from there)."""
    if required_approval([KIND] * len(steps)) != "one_person":
        raise ValueError("a trip job needs a one-person kind")
    mission_id, epoch = uuid.uuid4().hex, jobs.runner._start_token(robot_id)[0]  # read before any await
    await jobs.runner.hold_job(robot_id, mission_id, principal_id, await jobs.caps(robot_id))
    jobs.runner.lease.jobs[robot_id].view.update(stop_epoch=epoch, creating=True)  # no row yet: the tick waits
    if jobs.runner._stop_epoch != epoch:  # an E-stop landed while the lease opened: no job
        jobs.runner.release_job(robot_id, mission_id)
        raise TripError(409, "JOB_ESTOP")
    try:
        identity = {"request_key": request_key, "request_digest": request_digest,
                    "approved_by": approved_by} if request_key is not None else {}
        if any(value is not None for value in
               (approved_by, proposal_id, expected_proposal_digest, expected_generation)):
            identity.update(approved_by=approved_by, proposal_id=proposal_id,
                            expected_proposal_digest=expected_proposal_digest, expected_generation=expected_generation)
        job = await asyncio.to_thread(jobs.rows.create, mission_id, robot_id, principal_id, steps, **identity)
    except BaseException:
        jobs.runner.release_job(robot_id, mission_id)
        raise
    jobs.runner.lease.jobs[robot_id].view.pop("creating", None)
    return job


def install_trip_job_routes(app, *, store, runner, console, deployment_profile: str, episodes,
                            require_named_operator, operator_guard, require_viewer, read_guard,
                            require_proposer=None):
    """Scoped facts remain readable when a profile closes; only open profiles install the writer and loop."""
    from fleet.server.trip_proposal_routes import install_trip_proposal_routes  # D-908
    proposals = dict(require_proposer=require_proposer, require_viewer=require_viewer,
                     require_named_operator=require_named_operator)
    if store is None:
        install_trip_proposal_routes(app, cell_job_store=None, jobs=None, check=None, **proposals)
        return None
    rows = TripJobRows(store)

    async def read(principal, **identity):
        job = await asyncio.to_thread(rows.read, principal.principal_id, **identity)
        if job is None:
            raise HTTPException(404, detail={"code": "TRIP_JOB_NOT_FOUND"})
        return {"job": job}

    @app.get("/api/fleet/trip-jobs", dependencies=read_guard, response_model=TripJobReadResponse,
             tags=["fleet-work"])
    async def trip_job_request(request_key: TripRequestKey, principal=Depends(require_viewer)):
        return await read(principal, request_key=request_key)

    @app.get("/api/fleet/trip-jobs/{mission_id}", dependencies=read_guard, response_model=TripJobReadResponse,
             tags=["fleet-work"])
    async def trip_job_read(mission_id: str = Path(min_length=1, max_length=192),
                            principal=Depends(require_viewer)):
        return await read(principal, mission_id=mission_id)

    if not dispatch_open(deployment_profile, KIND):  # a TRIP ledger opened here: its open jobs keep no robot moving
        for mission_id in rows.ids(ACTIVE):
            rows.hold(mission_id, "FLEET_PROFILE_CLOSED", {})
            _LOG.warning("trip job %s held: the %s profile does not run trip steps", mission_id, deployment_profile)
        install_trip_proposal_routes(app, cell_job_store=store, jobs=None, check=None, **proposals)
        return None

    async def plan(robot_id, step, principal_id):
        try:
            return (await app.state.trip_plan(robot_id, TripRequest(**step), principal_id))["plan_id"]
        except HTTPException as exc:
            raise TripError(exc.status_code, exc.detail["code"], exc.detail.get("detail")) from exc

    async def incident(robot_id, job_id, reason, detail):
        """The case of a held job (rev 2 Q3): a human-tier problem episode the AI PC reads; the work list shows 개입."""
        _LOG.warning("trip job %s on %s holds: %s %s", job_id, robot_id, reason, detail)
        problem_id = f"job_hold:{job_id}:{detail['held_event']}"  # one per HOLD; a retried case writes no second row
        # ponytail: dedupe over this robot's newest 50 episodes, not atomic; a unique key in ProblemLog if it matters
        if any(row["problem_id"] == problem_id for row in await asyncio.to_thread(episodes.episodes, 50, robot_id)):
            return
        await asyncio.to_thread(episodes.opened, robot_id=robot_id, kind="job_hold", tier="human",
                                problem_id=problem_id,
                                type_key=f"job_hold:{robot_id}:trip", decision=None,
                                context={"job_id": job_id, "reason": reason, **detail})

    jobs = app.state.job_trips = JobTripSteps(store, runner, plan=plan, caps=console._shown_capabilities,
                                              incident=incident)
    jobs.recover()

    def check(candidates, steps):  # steps as plain dicts
        if any(robot not in console.robot_ids for robot in candidates):
            raise HTTPException(404, detail={"code": "UNKNOWN_ROBOT", "detail": {}})
        active = runner._store.active()
        unknown = sorted({p for s in steps for p in (s["to"], *s["via"])} - set(active[2].places if active else ()))
        if unknown:
            raise HTTPException(422, detail={"code": "TRIP_UNKNOWN_PLACE", "detail": {"places": unknown}})

    install_trip_proposal_routes(app, cell_job_store=store, jobs=jobs, check=check, **proposals)

    @app.post("/api/fleet/trip-jobs", dependencies=operator_guard, tags=["fleet-work"])
    async def fleet_trip_job(body: TripJobRequest, principal=Depends(require_named_operator)) -> dict:
        def validate():
            check(body.candidate_robot_ids or [body.robot_id], [step.model_dump(mode="json") for step in body.steps])
        try:
            steps = [step.model_dump(mode="json") for step in body.steps]
            if body.candidate_robot_ids is not None:
                from fleet.server.trip_candidates import create_candidate_trip_job
                return {"job": await create_candidate_trip_job(
                    jobs, body.candidate_robot_ids, steps, principal.principal_id, body.request_key, validate=validate)}
            validate()
            return {"job": await create_trip_job(jobs, body.robot_id, steps, principal.principal_id)}
        except TripError as exc:
            raise HTTPException(exc.status, detail={"code": exc.code, "detail": exc.detail}) from exc
        except MissionConflict as exc:
            raise HTTPException(409, detail={"code": "JOB_ROBOT_REFUSED", "detail": {"message": str(exc)}}) from exc
    return jobs


__all__ = ["create_trip_job", "install_trip_job_routes"]
