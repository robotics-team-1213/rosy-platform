"""D-541 7: Fleet holds a CORE trip lease for each trip robot (site config ``fleet.trip_lease_required``).

Off (the default until both robots run a CORE with the lease): no lease, trips run as before.
On: a trip starts only on a robot whose capabilities report ``trip_lease`` (else
``TRIP_LEASE_UNSUPPORTED``) and only after ``PUT /trip-lease`` opened a lease under a new
``lease_id`` (a uuid, never reused). The PUT goes with the robot's REST token, which must be
Fleet's own (D-541 1; app.py refuses the console token). Each period the lease is renewed from
its own in-flight slot, as ``trip_authority`` sends. The lease is lost, and the trip ends
``stopped`` / ``lease_lost`` and is never opened again, on: a renew CORE refuses (404 ended:
takeover, expiry, mode left, E-stop; 409 another lease), ``renewed: false`` (CORE restarted, so
the renew opened a fresh lease, which is released at once), or no confirmed renew for ``ttl_s``
since the last confirmed one was sent (CORE's own expiry is no earlier). A closed trip releases
its lease (DELETE) after its halt; a lease CORE already ended answers 404, which is fine.

D-763 6: a multi-step job holds one lease (``job_id``, CORE keeps it through IDLE) from approval to its
end (``TripAdmission.hold_job``); each step's trip adopts it and closing the trip keeps it. Between steps ``period`` is its one renewer:
this object sends only ``/trip-lease``, so no authority or goal lease outlives the trip loop driving it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from types import SimpleNamespace

from core_common.protocol.trip_lease import MAX_TTL_S, MIN_TTL_S
from fleet.server.trip_ports import TripError
from fleet.swarm.transport import RobotApiError

_LOG = logging.getLogger(__name__)
HELD, LOST, RELEASED = "held", "lost", "released"
#: D-760 1: Fleet's lease ``ttl_s`` (T_keep): the 5 s authority always expires first; ``link_wait`` lasts this long.
FLEET_TTL_S = 8.0
#: D-541 2 open refusals as trip start codes; any other refusal is TRIP_LEASE_REFUSED.
START_CODES = {"TRIP_LEASED": "TRIP_ROBOT_LEASED", "MANUAL_MODE": "TRIP_ROBOT_MANUAL",
               "CALIBRATION_ACTIVE": "CALIBRATION_ACTIVE"}


class TripLease:
    #: D-763 rev 2 Q3: ``(job_view, detail)`` opens the incident (person/AI PC) and binds the job's HOLD to it.
    on_job_lost = None
    claimed = staticmethod(lambda robot_id: None)  # the durable D-330 robot claim of a job (trip_guard)

    def __init__(self, port, clock, timeout_s: float, on_lost=None, *, required: bool = False,
                 holder: str = "fleet", ttl_s: float = FLEET_TTL_S) -> None:
        if not MIN_TTL_S <= ttl_s <= MAX_TTL_S:
            raise ValueError(f"fleet.trip_lease_ttl_s must be within {MIN_TTL_S:g}..{MAX_TTL_S:g}")
        self._port, self._clock, self._timeout_s, self._on_lost = port, clock, timeout_s, on_lost
        self.required, self.holder, self.ttl_s = required, holder, float(ttl_s)
        self._inflight: dict[str, asyncio.Future] = {}
        self._releasing: dict[str, asyncio.Future] = {}
        self.jobs: dict[str, SimpleNamespace] = {}  # robot id -> its job's hold (open=True, job=True, view)

    def job_of(self, robot_id: str):
        job = self.jobs.get(robot_id)
        return job.view["job_id"] if job is not None else self.claimed(robot_id)

    def _job_lease(self, robot_id: str):
        return (self.jobs.get(robot_id) or SimpleNamespace(view={})).view.get("lease")

    def now(self) -> float:
        """This lease's clock (``renewed_at`` is on it)."""
        return self._clock()

    def _body(self, lease_id: str, view: dict) -> dict:
        return {"lease_id": lease_id, "trip_id": view["trip_id"][:128], "holder": self.holder[:64],
                "operator_name": (view["started_by"] or "operator")[:64], "ttl_s": self.ttl_s,
                **({"job_id": view["job_id"][:128]} if view.get("job_id") else {})}

    async def _put(self, robot_id: str, body: dict) -> dict:
        return await asyncio.wait_for(self._port.trip_lease(robot_id, body), self._timeout_s) or {}

    async def open(self, robot_id: str, view: dict, caps) -> dict | None:
        """The trip's lease (``view``: its trip_id and started_by), None when off, or ``TripError``."""
        job = self.jobs.get(robot_id)
        if job is not None:  # D-763 6: only that job's own step adopts its lease; any other start is refused
            if view.get("job_id") != job.view["job_id"] or job.view["lease"]["state"] != HELD:
                raise TripError(409, "TRIP_ROBOT_BUSY", {"job_id": job.view["job_id"]})
            return job.view["lease"]
        if not self.required:
            return None
        if getattr(caps, "trip_lease", False) is not True:
            raise TripError(422, "TRIP_LEASE_UNSUPPORTED")
        pending = self._releasing.pop(robot_id, None)
        if pending is not None and not pending.done():  # the last trip's DELETE first: one lease per robot
            await asyncio.wait([pending], timeout=self._timeout_s)
        lease = {"lease_id": uuid.uuid4().hex, "state": HELD, "renewed_at": self._clock()}
        try:
            await self._put(robot_id, self._body(lease["lease_id"], view))
        except RobotApiError as exc:
            raise TripError(409, START_CODES.get(exc.code, "TRIP_LEASE_REFUSED"),
                            {"code": exc.code, **({"lease": exc.detail} if exc.detail else {})}) from exc
        except Exception as exc:  # it may have opened: release it, CORE's expiry otherwise
            self._release_later(robot_id, lease["lease_id"])
            raise TripError(422, "TRIP_ROBOT_UNREACHABLE", {"error": type(exc).__name__}) from exc
        return lease

    def period(self, lives) -> None:
        lives = list(lives)  # a held job without an open trip renews here (the gap between its steps)
        driven = {live.view["robot_id"] for live in lives if live.open}
        for live in lives + [job for robot_id, job in self.jobs.items() if robot_id not in driven]:
            lease, robot_id = live.view.get("lease"), live.view["robot_id"]
            if not live.open or not lease or lease["state"] != HELD:
                continue
            task = self._inflight.get(robot_id)
            if self._clock() - lease["renewed_at"] >= self.ttl_s:
                self._inflight[robot_id] = asyncio.ensure_future(self._lose(live, "renew_timeout"))
            elif task is None or task.done():
                self._inflight[robot_id] = asyncio.ensure_future(self._renew(live))

    async def _renew(self, live) -> None:
        lease, robot_id, sent = live.view["lease"], live.view["robot_id"], self._clock()
        try:
            answer = await self._put(robot_id, self._body(lease["lease_id"], live.view))
        except RobotApiError as exc:
            if exc.status >= 500:
                return  # CORE did not judge it; the ttl rule decides
            ended = (exc.detail or {}).get("ended") or {}
            await self._lose(live, ended.get("reason") or ("leased" if exc.code == "TRIP_LEASED" else exc.code),
                             ended.get("by"))
            return
        except Exception as exc:  # noqa: BLE001 — unreachable: the ttl rule decides
            _LOG.debug("trip lease renew to %s failed: %r", robot_id, exc)
            return
        if answer.get("renewed") is False:  # CORE restarted: this PUT opened a lease nobody holds
            self._release_later(robot_id, lease["lease_id"])
            await self._lose(live, "core_restarted")
        elif lease["state"] == HELD:
            lease["renewed_at"] = sent

    async def _lose(self, live, reason: str, by: str | None = None) -> None:
        lease = live.view["lease"]
        if lease["state"] != HELD:
            return
        lease.update(state=LOST, reason=reason)
        detail = {"lease_reason": reason, **({"lease_by": by} if by else {})}
        if self._on_lost is not None and not getattr(live, "job", False):
            await self._on_lost(live, detail)
        job = self.jobs.get(live.view["robot_id"])
        if job is not None and job.view["lease"] is lease and self.on_job_lost is not None:
            # Fleet says lost at ttl after the last confirmed renew, a little before CORE: the caller reads
            # the robot's state when it answers again and never assumes IDLE now (D-763 10).
            await self.on_job_lost(job.view, detail)

    def close(self, live) -> None:
        """The trip closed (its halt already sent): release a lease it still holds, except its job's."""
        lease = live.view.get("lease")
        if lease and lease["state"] == HELD and lease is not self._job_lease(live.view["robot_id"]):
            lease["state"] = RELEASED
            self._release_later(live.view["robot_id"], lease["lease_id"])

    def _release_later(self, robot_id: str, lease_id: str) -> None:
        self._releasing[robot_id] = asyncio.ensure_future(self._delete(robot_id, lease_id))

    async def release(self, robot_id: str, lease_id: str) -> None:
        if (self._job_lease(robot_id) or {}).get("lease_id") != lease_id:  # a step that did not start: job keeps it
            await self._delete(robot_id, lease_id)

    async def _delete(self, robot_id: str, lease_id: str) -> None:
        try:
            await asyncio.wait_for(self._port.trip_lease_release(robot_id, lease_id), self._timeout_s)
        except Exception as exc:  # noqa: BLE001 — already ended (404) or unreachable: CORE's expiry ends it
            _LOG.debug("trip lease release to %s: %r", robot_id, exc)
