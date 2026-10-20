"""D-763 7: a job's 운행 step is a Fleet trip — no separate motion record.

A job of ``TRIP`` steps (its rows: ``job_trip_rows``) holds one CORE trip lease from its start to its end
(``TripAdmission.hold_job``, slice 6). Each step plans from the robot's pose now on the robot card's plan path
(``trip_routes`` ``plan``) and starts that trip under the job (``TripRunner.start(job_id=)``: the same start checks;
its goals are ``trip`` goals, never ``operator`` ones; Rule M sees it as the robot's open trip). Only ``arrived``
confirms a step (D-763 2). Any other end, a refused start or a lost job lease HOLDs the job with the reason, opens
one case (rev 2 Q3, the ``incident`` port) and gives the lease up. Nothing retries or reopens: the way on is the
ledger's named-operator ``resume``, after which the next tick takes a new lease and plans a new trip that passes
its start checks. After a Fleet restart every open trip job HOLDs (``recover``). SIM only (registry
``open_profiles``) until device proof (D-763 4).
"""

from __future__ import annotations

import asyncio
import json
import logging

from fleet.server.cell_job_store import CANCELLED_REASON
from fleet.server.job_trip_rows import ACTIVE, ADMISSIONS, KIND, TripJobRows
from fleet.server.trip_ports import OPEN, TripError

_LOG = logging.getLogger(__name__)


class JobTripSteps:
    def __init__(self, store, runner, *, plan, caps, incident, period_s: float = 0.5) -> None:
        self.store, self.rows, self.runner, self.period_s = store, TripJobRows(store), runner, period_s
        self.plan, self.caps, self.incident = plan, caps, incident  # (robot, step, who) -> plan_id; (robot); case
        self.candidate_lock = asyncio.Lock()
        runner.lease.on_job_lost = self._lost
        self._lost_jobs: set = set()  # lost leases whose HOLD this loop has not seen yet (``_step``)

    def recover(self) -> int:
        """D-494 5 at startup: no job step drives again by itself; every open trip job HOLDs (its case: ``tick``)."""
        return sum(self.rows.hold(mission_id, "FLEET_RESTARTED", {}) for mission_id in self.rows.ids(ACTIVE))

    async def tick(self) -> None:
        for mission_id in await asyncio.to_thread(self.rows.ids, ("READY", "RUNNING")):
            try:
                await self._step(await asyncio.to_thread(self.store.get, mission_id))
            except Exception:  # noqa: BLE001 - one job's failure is that job's, never the loop's
                _LOG.exception("trip step of job %s failed", mission_id)
        for robot_id, hold in list(self.runner.lease.jobs.items()):  # each HOLD gives the lease up; an end frees it
            if hold.view.get("creating"):
                continue  # ``create`` writes its row now; it releases the lease itself if that fails
            try:
                job = await asyncio.to_thread(self.store.get, hold.view["job_id"])
                if job is None or job["status"] in ("HOLD", "GOAL_CONFIRMED"):
                    self._lost_jobs.discard(hold.view["job_id"])  # held (or done): a READY after this is a resume
                if job is None or job["status"] == "GOAL_CONFIRMED" or job["reason"] == CANCELLED_REASON:
                    self.runner.release_job(robot_id, hold.view["job_id"])
                elif job["status"] == "HOLD" and hold.view["lease"]["state"] == "held":
                    await self.runner.stop_job(robot_id, job["reason"])
            except Exception:  # noqa: BLE001
                _LOG.exception("trip job lease of %s could not be settled", robot_id)
        for row in await asyncio.to_thread(self.rows.uncased):  # every HOLD, whoever wrote it, reaches a person once
            try:
                detail = {**json.loads(row["detail_json"]), "held_event": row["event_id"]}
                await self.incident(row["instance_id"], row["mission_id"], row["reason"], detail)
                await asyncio.to_thread(self.rows.cased, row["mission_id"], row["event_id"])
            except Exception:  # noqa: BLE001 - not marked: the next pass tries again
                _LOG.exception("case of held trip job %s could not be opened", row["mission_id"])

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                _LOG.exception("trip job tick failed")
            await asyncio.sleep(self.period_s)

    async def _step(self, job: dict) -> None:
        mission_id, robot_id, index = job["mission_id"], job["instance_id"], job["current_step_index"]
        step = job["steps"][index]
        if job["status"] == "RUNNING":
            live = self.runner._find(step["action_id"])  # a closed trip is read from storage off the loop
            view = (live.view if live is not None
                    else await asyncio.to_thread(self.runner._store.trip, step["action_id"]))
            view = view or {"state": "missing", "reason": "TRIP_UNKNOWN"}
            if view["state"] == "arrived":
                await asyncio.to_thread(self.rows.arrived, mission_id, index, step["action_id"])
            elif view["state"] not in OPEN:
                await self._fail(job, view.get("reason") or view["state"], {"trip_id": step["action_id"],
                                                                             "trip_state": view["state"]})
            return
        actor = next(event["actor_id"] for event in reversed(job["events"]) if event["event_type"] in ADMISSIONS)
        token = self.runner._start_token(robot_id)  # a stop after this read refuses the start
        try:
            hold = self.runner.lease.jobs.get(robot_id)
            mine = hold is not None and hold.view["job_id"] == mission_id
            if not mine or hold.view["lease"]["state"] != "held":  # a new lease only after the loss's HOLD + resume
                if mission_id in self._lost_jobs:
                    raise TripError(409, "JOB_LEASE_LOST", {"robot_state": "unconfirmed"})
                await self.runner.hold_job(robot_id, mission_id, actor, await self.caps(robot_id))
                self.runner.lease.jobs[robot_id].view["stop_epoch"] = token[0]
            elif hold.view.get("stop_epoch") != token[0]:  # an E-stop since the lease (its end_trip may not have run)
                raise TripError(409, "JOB_ESTOP")
            elif self.runner.lease.now() - hold.view["lease"]["renewed_at"] > 2 * self.period_s:
                return  # no renew confirmed lately: the lease rule decides before a new step starts
            plan_id = await self.plan(robot_id, step["step"], actor)
            if await asyncio.to_thread(self.rows.started, mission_id, index, plan_id, actor):
                await self.runner.start(plan_id, actor, job_id=mission_id, start_token=token)
        except TripError as exc:
            await self._fail(job, exc.code, {"detail": exc.detail})

    async def _fail(self, job: dict, reason: str, detail: dict) -> None:
        try:
            await asyncio.to_thread(self.rows.hold, job["mission_id"], reason, detail)
        finally:  # the lease goes even when the ledger write fails; the case opens in ``tick``
            await self.runner.stop_job(job["instance_id"], reason)

    async def _lost(self, view: dict, detail: dict) -> None:
        """``TripLease.on_job_lost``: declared at ttl after the last confirmed renew, before CORE's own expiry, so
        the robot is never assumed IDLE here (D-763 10); the start checks of a resumed step read it again."""
        self._lost_jobs.add(view["job_id"])  # before any await: a tick in the gap must not take a new lease
        detail = {**detail, "robot_state": "unconfirmed"}
        if not await asyncio.to_thread(self.rows.hold, view["job_id"], "JOB_LEASE_LOST", detail):
            job = await asyncio.to_thread(self.store.get, view["job_id"])  # None: its row is not written yet
            if job is not None and job["status"] == "HOLD":  # HOLD already: a resume after this is the operator's
                self._lost_jobs.discard(view["job_id"])


__all__ = ["KIND", "JobTripSteps"]
