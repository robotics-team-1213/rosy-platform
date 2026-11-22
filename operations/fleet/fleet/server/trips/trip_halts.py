"""D-494 5: trip halts through the junction/cancel ports; a trip open before a restart is never resumed."""
import asyncio
import logging

from fleet.routing.cost import STOP
from fleet.server.trip_ports import OPEN

_LOG = logging.getLogger("fleet.server.trip_runner")  # the trip loop's logger, as before the D-517 split


def error_code(exc: BaseException) -> str:
    return getattr(exc, "code", None) or type(exc).__name__


class TripHalts:
    def __init__(self, store, junction, config, call, clock, cancel_goal, release_queue, busy, roster=None):
        self._store, self._junction, self._config, self._call, self._clock = store, junction, config, call, clock
        self._cancel_goal, self._release_queue, self._busy, self.roster = cancel_goal, release_queue, busy, roster
        self.reconcile_handoff = None
        self.pending_handoffs = {}
        self.restarted = store.trips(states=OPEN, limit=1000)  # ``run_restart`` stops each (retried until it takes)
        for trip in self.restarted:
            trip.update(state="stopped", reason="restart", updated_at=clock())
            store.put_trip(trip)
        for trip in store.pending_handoff_stops():
            if trip["state"] in OPEN:
                trip.update(state="stopped", reason="restart", updated_at=clock())
                store.put_trip(trip)
            self.track_handoff_stop(trip)
        self.restarted = [trip for trip in self.restarted if trip["robot_id"] not in self.pending_handoffs]

    def track_handoff_stop(self, trip):
        if trip["state"] not in OPEN and trip["detail"].get("named_stop_handoff_pending"):
            self.pending_handoffs[trip["robot_id"]] = trip

    def watch_handoff_stops(self, inflight):
        if self.reconcile_handoff is None:
            return
        for robot_id, trip in self.pending_handoffs.items():
            task = inflight.get(robot_id)
            if task is None or task.done():
                inflight[robot_id] = asyncio.create_task(self._read_handoff_stop(robot_id, trip))

    async def _read_handoff_stop(self, robot_id, trip):
        detail = trip["detail"]
        try:
            verified = await self._call(self.reconcile_handoff(
                robot_id, detail["named_stop_handoff_pending"], detail.get("named_stop_operation")))
        except Exception:
            return
        if not verified or self.pending_handoffs.get(robot_id) is not trip:
            return
        resolved = {**detail, "named_stop_handoff_stop_verified": True}
        del resolved["named_stop_handoff_pending"]
        try:
            self._store.put_trip({**trip, "detail": resolved, "updated_at": self._clock()})
        except Exception:
            _LOG.exception("could not persist recovered handoff stop for %s", robot_id)
            return
        trip["detail"] = resolved
        self.pending_handoffs.pop(robot_id, None)

    async def halt_robot(self, robot_id: str, lane: bool, place: str | None, *, handoff_pending=False) -> dict:
        """Best effort, every call bounded: lane -> junction ``stop`` then line-follow OFF; free -> cancel."""
        errors = []

        async def attempt(call) -> bool:
            try:
                await self._call(call)
                return True
            except Exception as exc:  # the halt must try every step whatever one of them raised
                errors.append(error_code(exc))
                return False

        if lane:
            if place:
                await attempt(self._junction.send_junction(robot_id, STOP, place, 0.0, self._config.junction_expires_s))
            sent = {"stop_sent": await attempt(self._junction.hold(robot_id))}
        else:
            canceled = await attempt(self._cancel_goal(robot_id))
            if handoff_pending:
                # A lost handoff reply leaves either Nav2 or the lane controller holding the wheels.
                held = await attempt(self._junction.hold(robot_id))
                canceled = canceled and held
            sent = {"stop_sent": canceled}
            try:
                self._release_queue(robot_id)
            except Exception as exc:  # the stop above is what matters
                errors.append(error_code(exc))
        if errors:
            sent["error"] = errors[-1]
        return sent

    async def run_restart(self) -> None:
        """Outside the tick path: retry every ``restart_retry_s`` up to ``restart_attempts``."""
        for _attempt in range(int(self._config.restart_attempts)):
            await self.halt_restarted()
            if not self.restarted:
                return
            await asyncio.sleep(self._config.restart_retry_s)
        _LOG.warning("gave up stopping robots of trips open before the restart: %s",
                     sorted({trip["robot_id"] for trip in self.restarted}))
        self.restarted = []

    async def halt_restarted(self) -> None:
        """Stop each such robot until it takes it or leaves the roster; a new trip's robot is that trip's."""
        roster = set(self.roster()) if self.roster is not None else None
        pending = []
        for trip in self.restarted:
            if roster is not None and trip["robot_id"] not in roster:
                continue
            if self._busy(trip["robot_id"]):
                pending.append(trip)
                continue
            try:
                result = await self.halt_robot(trip["robot_id"], trip.get("drive_mode") == "lane",
                                               trip.get("next_place"), handoff_pending=bool(
                                                   (trip.get("detail") or {}).get("named_stop_handoff_pending")))
                trip.update(detail={**(trip.get("detail") or {}), **result}, updated_at=self._clock())
                self._store.put_trip(trip)
            except Exception:
                _LOG.exception("could not stop robot %s of a trip open before the restart", trip.get("robot_id"))
                result = {}
            if not result.get("stop_sent"):
                pending.append(trip)
        self.restarted = pending
