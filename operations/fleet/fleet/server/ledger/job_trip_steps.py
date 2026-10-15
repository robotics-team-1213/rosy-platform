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
import logging
import uuid

from fleet.server.cell_job_store import CANCELLED_REASON
from fleet.server.job_trip_rows import ACTIVE, KIND, TripJobRows
from fleet.server.step_action_kinds import required_approval
from fleet.server.trip_ports import OPEN, TripError

_LOG = logging.getLogger(__name__)


class JobTripSteps:
    def __init__(self, store, runner, *, plan, caps, incident, period_s: float = 0.5) -> None:
        self.store, self.rows, self.runner, self.period_s = store, TripJobRows(store), runner, period_s
        self.plan, self.caps, self.incident = plan, caps, incident  # (robot, step, who) -> plan_id; (robot); case
        runner.lease.on_job_lost = self._lost

    def recover(self) -> int:
        """D-494 5 at startup: no job step drives again by itself; every open trip job HOLDs for re-approval."""
        return sum(self.rows.hold(mission_id, "FLEET_RESTARTED", {}) for mission_id in self.rows.ids(ACTIVE))

    async def create(self, robot_id: str, steps: list, principal_id: str) -> dict:
        """One named operator approves and starts it (registry ``one_person``); the gate is ``hold_job``'s."""
        if required_approval([KIND] * len(steps)) != "one_person":
            raise ValueError("a trip job needs a one-person kind")
        mission_id = uuid.uuid4().hex
        await self.runner.hold_job(robot_id, mission_id, principal_id, await self.caps(robot_id))
        try:
            return await asyncio.to_thread(self.rows.create, mission_id, robot_id, principal_id, steps)
        except BaseException:
            self.runner.release_job(robot_id, mission_id)
            raise

    async def tick(self) -> None:
        for mission_id in await asyncio.to_thread(self.rows.ids, ("READY", "RUNNING")):
            try:
                await self._step(await asyncio.to_thread(self.store.get, mission_id))
            except Exception:  # noqa: BLE001 - one job's failure is that job's, never the loop's
                _LOG.exception("trip step of job %s failed", mission_id)
        for robot_id, hold in list(self.runner.lease.jobs.items()):  # each HOLD gives the lease up; an end frees it
            job = await asyncio.to_thread(self.store.get, hold.view["job_id"])
            if job is None or job["status"] == "GOAL_CONFIRMED" or job["reason"] == CANCELLED_REASON:
                self.runner.release_job(robot_id, hold.view["job_id"])
            elif job["status"] == "HOLD" and hold.view["lease"]["state"] == "held":
                await self.runner.stop_job(robot_id, job["reason"])

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
            view = self.runner.view(step["action_id"]) or {"state": "missing", "reason": "TRIP_UNKNOWN"}
            if view["state"] == "arrived":
                await asyncio.to_thread(self.rows.arrived, mission_id, index, step["action_id"])
            elif view["state"] not in OPEN:
                await self._fail(job, view.get("reason") or view["state"], {"trip_id": step["action_id"],
                                                                             "trip_state": view["state"]})
            return
        actor = next((event["actor_id"] for event in reversed(job["events"]) if event["event_type"] in (
            "CELL_JOB_ADMITTED", "CELL_JOB_RESUMED")), job["proposal_principal_id"])
        try:
            hold = self.runner.lease.jobs.get(robot_id)
            if hold is None or hold.view["job_id"] != mission_id or hold.view["lease"]["state"] != "held":
                await self.runner.hold_job(robot_id, mission_id, actor, await self.caps(robot_id))  # re-approval
            plan_id = await self.plan(robot_id, step["step"], actor)
            if await asyncio.to_thread(self.rows.started, mission_id, index, plan_id, actor):
                await self.runner.start(plan_id, actor, job_id=mission_id)
        except TripError as exc:
            await self._fail(job, exc.code, {"detail": exc.detail})

    async def _fail(self, job: dict, reason: str, detail: dict) -> None:
        if await asyncio.to_thread(self.rows.hold, job["mission_id"], reason, detail):
            await self.incident(job["instance_id"], job["mission_id"], reason, detail)
        await self.runner.stop_job(job["instance_id"], reason)  # its hook finds the HOLD: no second case

    async def _lost(self, view: dict, detail: dict) -> None:
        """``TripLease.on_job_lost``: declared at ttl after the last confirmed renew, before CORE's own expiry, so
        the robot is never assumed IDLE here (D-763 10); the start checks of a resumed step read it again."""
        detail = {**detail, "robot_state": "unconfirmed"}
        if await asyncio.to_thread(self.rows.hold, view["job_id"], "JOB_LEASE_LOST", detail):
            await self.incident(view["robot_id"], view["job_id"], "JOB_LEASE_LOST", detail)


__all__ = ["KIND", "JobTripSteps"]
