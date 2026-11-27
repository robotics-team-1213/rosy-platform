"""D-1086 draft: a Nav2 road trip that ended for a non-hazard reason is planned and started again with its request.

User 2026-11-28: a robot that stops is tried again on the same way at least three times. D-1082 resends inside one
trip; this is the step after it, once the trip has closed. No new motion writer: the reissue is the ordinary plan path
(``app.state.trip_plan``) and ``TripRunner.start``, with every start check they already make (battery, caps,
pose, traffic, binding). What decides here:

* which ends qualify (``eligible``, default deny; the table is in the ADR),
* what must hold right now before the next start (``_ready``: two good state reads on two polls, no E-stop, proven
  stopped, robot LOCALIZED, no goal held, the same map version and binding as the trip started under, no open trip
  or job on the robot),
* when (REISSUE_DELAYS_S after each end, all within TOTAL_S of the first end) and how often (MAX_REISSUES per chain).

A trip started on the robot by anyone else drops the pending reissue. The reissue runs under the principal who
started the original trip (same request, same scope) and both trips point at each other:
``detail['reissue']`` on the ended trip, ``detail['reissued_from']`` on the new one. Pending reissues live in
memory only: a Fleet restart forgets them (nothing moves).
"""
from __future__ import annotations

import asyncio
import logging

from fleet.server.handoff_traffic import _fresh_stopped
from fleet.server.trip_halts import halt_unconfirmed
from fleet.server.trip_ports import TripError

REISSUE_DELAYS_S = (10.0, 20.0, 40.0)
MAX_REISSUES = len(REISSUE_DELAYS_S)
TOTAL_S = 600.0             # from the chain's first end; past it the original reason stands
POLL_S = 1.0
READY_READS = 2             # consecutive good reads, one per poll
_RUNNING = ("NAVIGATING", "PLANNING")
_SETTLED_NAV = ("IDLE", "ARRIVED", "CANCELED", "FAILED")
#: D-1082 ends that may be reissued: the 4th stop (None) or the episode window; never an E-stop, a scope change or
#: a robot that did not prove it stopped (wait_s).
_RECOVERY_ENDS = (None, "window")

_LOG = logging.getLogger("fleet.server.trip_runner")


def eligible(view: dict, request: dict) -> str | None:
    """The reissue class of an ended trip, or None (never reissued)."""
    detail = view.get("detail") or {}
    state, reason = view.get("state"), view.get("reason")
    if (state not in ("stopped", "failed") or request.get("drive_mode") != "nav2" or not isinstance(request.get("to"), str)
            or view.get("repeat") or view.get("convoy") or request.get("repeat") or request.get("convoy")
            or (view.get("lease") or {}).get("job_id") or view.get("purpose") or detail.get("parking_handoff")
            or view.get("hold") is not None or detail.get("canceled_by") is not None
            or halt_unconfirmed(detail) or detail.get("traffic_hold") or detail.get("peer_wait")
            or detail.get("camera_lane_fallback") or "off_lane_m" in detail):
        return None
    if (state, reason) == ("stopped", "pose"):
        return "pose_wait_expired"
    if (state, reason) == ("stopped", "map_frame") and detail.get("binding") == "ROBOT_NOT_LOCALIZED":
        return "relocalization_wait_expired"
    if (state, reason) == ("failed", "TRIP_ROBOT_UNREACHABLE"):
        return "robot_unreachable"
    if (state, reason) == ("failed", "GOAL_LEASE_NOT_ACTIVE"):
        return "goal_lease_ended"
    rec = detail.get("recovery") or {}
    if (state == "stopped" and reason in ("stall", "navigation") and rec.get("state") == "exhausted"
            and detail.get("recovery_end") in _RECOVERY_ENDS and not rec.get("same_spot")):
        return "recovery_exhausted"
    return None


def _code(exc) -> str:
    if isinstance(exc, TripError):
        return exc.code
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict) and detail.get("code"):
        return detail["code"]
    return getattr(exc, "code", None) or type(exc).__name__


class TripReissue:
    def __init__(self, runner, plan, *, clock=None, sleep=asyncio.sleep):
        self.runner, self.plan = runner, plan
        self.clock = clock or runner._clock
        self.sleep = sleep
        self.pending: dict[str, dict] = {}
        # trip ids already judged; the first poll marks every closed one seen.
        # shortcut: grows by one id per ended trip for the process life (a few hundred a day), prune if that changes
        self.seen: set[str] | None = None

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - one bad poll must not end the watch
                _LOG.exception("trip reissue poll failed")
            await self.sleep(POLL_S)

    async def tick(self) -> None:
        runner = self.runner
        lives = list(runner._live.values())
        if self.seen is None:
            self.seen = {live.view["trip_id"] for live in lives if not live.open}
            return
        for live in lives:
            robot_id, trip_id = live.view["robot_id"], live.view["trip_id"]
            item = self.pending.get(robot_id)
            if item is not None and trip_id != item["trip_id"]:
                self._drop(item, "new_trip", by_trip=trip_id)        # someone else started a trip on it
                continue
            if item is not None:
                await self._advance(item, live)
            elif not live.open and trip_id not in self.seen:
                self.seen.add(trip_id)
                self._judge(live)

    # ---- one ended trip -----------------------------------------------------------------

    def _judge(self, live) -> None:
        view = live.view
        row = self.runner._store.plan(view["trip_id"]) or {}
        request = dict(row.get("request") or {})
        kind = eligible(view, request)
        if kind is None:
            return
        chain = view["detail"].get("reissued_from") or {}
        attempt = chain.get("attempt", 0) + 1
        now = self.clock()
        first = chain.get("first_end_at", now)
        record = {"state": "scheduled", "attempt": attempt, "max": MAX_REISSUES, "kind": kind,
                  "previous_reason": view.get("reason"), "first_end_at": first}
        if attempt > MAX_REISSUES or now - first >= TOTAL_S:
            self._write(live, {**record, "state": "limit"})
            return
        item = {"robot_id": view["robot_id"], "trip_id": view["trip_id"], "live": live, "request": request,
                "principal": view.get("started_by"), "map_version": view.get("map_version"),
                "binding_id": view["detail"].get("nav2_binding_id"), "reads": 0, "record": record,
                "root": chain.get("root", view["trip_id"])}
        if not item["principal"]:
            self._write(live, {**record, "state": "no_principal"})
            return
        record["next_at"] = now + REISSUE_DELAYS_S[attempt - 1]
        self.pending[view["robot_id"]] = item
        self._write(live, record)

    async def _advance(self, item: dict, live) -> None:
        record, now = item["record"], self.clock()
        if now - record["first_end_at"] >= TOTAL_S:
            self._drop(item, "total_limit")
            return
        if now < record["next_at"]:
            return
        why = await self._ready(item)
        if why is not None:   # wait one more interval; TOTAL_S still bounds the chain
            item["reads"] = 0
            record.update(waiting_for=why, checked_at=now, next_at=now + REISSUE_DELAYS_S[record["attempt"] - 1])
            self._write(item["live"], record)
            return
        record.pop("waiting_for", None)
        item["reads"] += 1
        if item["reads"] < READY_READS:
            return
        await self._start(item)

    async def _ready(self, item: dict) -> str | None:
        """None when every condition holds on this read; else what is missing."""
        runner, robot_id = self.runner, item["robot_id"]
        if runner.robot_busy(robot_id) or runner.lease.job_of(robot_id) is not None:
            return "robot_busy"
        try:
            state = await runner._call(runner._robot_state(robot_id))
        except Exception:  # noqa: BLE001 - no answer is no proof
            return "state_unread"
        if not isinstance(state, dict):
            return "state_unread"
        if (state.get("safety") or {}).get("estop") is not False:
            return "estop"
        if state.get("navigation") in _RUNNING or state.get("navigation") not in _SETTLED_NAV or not _fresh_stopped(state):
            return "robot_stopped"
        if state.get("goal") is not None or state.get("mode") not in ("IDLE", "NAVIGATION"):
            return "robot_idle"
        if (state.get("localization") or {}).get("state") != "LOCALIZED":
            return "localized"
        active = runner._store.active()
        if active is None or active[0] != item["map_version"]:
            return "map_version"
        if item["binding_id"] is not None:
            if (runner._store.map_bindings.active(robot_id) or {}).get("binding_id") != item["binding_id"]:
                return "binding"
            fit, _why = runner._store.map_bindings.matching_fit(robot_id, state, (active[1].map_id, active[0]))
            if fit is None:
                return "binding"
        return None

    async def _start(self, item: dict) -> None:
        from fleet.server.trip_routes import TripRequest   # late: the routes module pulls in the whole trip stack
        record, robot_id = item["record"], item["robot_id"]
        del self.pending[robot_id]
        try:
            planned = await self.plan(robot_id, TripRequest(**item["request"]), item["principal"])
            trip = await self.runner.start(planned["plan_id"], item["principal"])
        except Exception as exc:  # noqa: BLE001 - recorded; the attempt is spent, the robot was not moved
            code = _code(exc)
            record.update(state="start_refused", error=code, ended_at=self.clock())
            self._write(item["live"], record)
            _LOG.warning("trip %s: reissue %d refused: %s", item["trip_id"], record["attempt"], code)
            return
        new_id = trip["trip_id"]
        record.update(state="reissued", next_trip_id=new_id, reissued_at=self.clock(), by="auto_reissue")
        self._write(item["live"], record)
        new = self.runner._live.get(robot_id)
        if new is not None and new.view["trip_id"] == new_id:
            new.view["detail"]["reissued_from"] = {
                "trip_id": item["trip_id"], "root": item["root"], "attempt": record["attempt"],
                "previous_reason": record["previous_reason"], "first_end_at": record["first_end_at"],
                "by": "auto_reissue", "principal": item["principal"]}
            self.runner._store.put_trip(new.view)
        _LOG.warning("trip %s: reissued as %s (%d/%d, %s)", item["trip_id"], new_id, record["attempt"],
                     MAX_REISSUES, record["kind"])
        event = getattr(self.runner._store, "record_event", None)
        if event is not None:
            event("trip_reissue", item["principal"], {"robot_id": robot_id, "trip_id": item["trip_id"],
                                                       "next_trip_id": new_id, "attempt": record["attempt"],
                                                       "kind": record["kind"], "by": "auto_reissue"})

    def _drop(self, item: dict, why: str, **extra) -> None:
        self.pending.pop(item["robot_id"], None)
        item["record"].update(state="dropped", dropped=why, ended_at=self.clock(), **extra)
        self._write(item["live"], item["record"])

    def _write(self, live, record: dict) -> None:
        live.view["detail"]["reissue"] = dict(record)
        self.runner._store.put_trip(live.view)   # a closed trip: the store row only, no lease or halt side effects
