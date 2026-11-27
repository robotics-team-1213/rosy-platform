"""D-1086: a Nav2 road trip that ended for a non-hazard reason is planned and started again with its request.

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

from fleet.server import trip_back_off as back
from fleet.server.handoff_traffic import _fresh_stopped
from fleet.server.trip_halts import error_code, halt_unconfirmed

REISSUE_DELAYS_S = (10.0, 20.0, 40.0)
MAX_REISSUES = len(REISSUE_DELAYS_S)
TOTAL_S = 600.0             # from the chain's first end; past it the original reason stands
POLL_S = 1.0
READY_READS = 2             # consecutive good reads, one per poll
_RUNNING = ("NAVIGATING", "PLANNING")
_SETTLED_NAV = ("IDLE", "ARRIVED", "CANCELED", "FAILED")
#: D-1082 ends that may be reissued: the 4th stop (None) or the episode window; never an E-stop, a scope change or
#: a robot that did not prove it stopped (wait_s, or a wait that ran out while still ``waiting_for`` it).
_RECOVERY_ENDS = (None, "window")
#: TRIP_ROBOT_UNREACHABLE also ends a step that raised these: a fault in Fleet, not a lost link.
_NOT_LINK = ("RuntimeError", "ValueError")

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
    if (state, reason) == ("failed", "TRIP_ROBOT_UNREACHABLE") and detail.get("kind") not in _NOT_LINK:
        return "robot_unreachable"
    if (state, reason) == ("failed", "GOAL_LEASE_NOT_ACTIVE"):
        return "goal_lease_ended"
    rec = detail.get("recovery") or {}
    # "attempts" is the D-1082 ladder's record: without it a same-spot repeat could not be told, so no reissue.
    if (state == "stopped" and reason in ("stall", "navigation") and rec.get("state") == "exhausted"
            and detail.get("recovery_end") in _RECOVERY_ENDS and rec.get("waiting_for") is None
            and "attempts" in rec):
        return "same_spot" if rec.get("same_spot") else "recovery_exhausted"   # same_spot: only after a back-off
    return None


def _code(exc) -> str:
    detail = getattr(exc, "detail", None)   # a refused plan is an HTTPException whose detail carries the code
    return detail["code"] if isinstance(detail, dict) and detail.get("code") else error_code(exc)


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
            try:
                await self._robot(live)
            except Exception:  # noqa: BLE001 - one robot's fault must not starve the others
                _LOG.exception("trip reissue: %s", live.view.get("robot_id"))

    async def _robot(self, live) -> None:
        robot_id, trip_id = live.view["robot_id"], live.view["trip_id"]
        item = self.pending.get(robot_id)
        if item is not None and trip_id != item["trip_id"]:
            self._drop(item, "new_trip", by_trip=trip_id)        # someone else started a trip on it
        elif item is not None and self._stops(robot_id) != item["stops"]:
            self._drop(item, "stopped_since")   # an E-stop or line-follow OFF since the end, even if released
        elif item is not None:
            await self._advance(item, live)
        elif not live.open and trip_id not in self.seen:
            self.seen.add(trip_id)
            self._judge(live)

    def _stops(self, robot_id: str) -> tuple:
        return self.runner._stop_epoch, self.runner._start_cancels.get(robot_id, 0)

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
                "stops": self._stops(view["robot_id"]), "chain": chain,
                "root": chain.get("root", view["trip_id"])}
        if not item["principal"]:
            self._write(live, {**record, "state": "no_principal"})
            return
        if kind == "same_spot":   # D-1087: the same request from the same spot fails the same way; back off first
            count, total = chain.get("back_offs", 0), chain.get("back_off_m", 0.0)
            if count >= back.MAX_BACK_OFFS or total + back.BACK_OFF_M > back.MAX_TOTAL_M + 1e-9:
                rec = view["detail"].get("recovery") or {}
                self._write(live, {**record, "state": "gave_up",
                                   "gave_up": back.side_text(rec, rec.get("attempts") or [])})
                return
            item["back_off"] = record["back_off"] = {"phase": "pending", "attempt": count + 1,
                                                     "distance_m": back.BACK_OFF_M, "total_m": total}
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
        bo = item.get("back_off")
        if bo is not None and bo["phase"] == "backing":
            await self._backing(item, bo, now)
            return
        why = await self._ready(item)
        if why is None and bo is not None:   # D-1087: Fleet's own back-off conditions, then the look again
            check = back.refusal if bo["phase"] == "pending" else back.looked_again
            why = await check(self.runner, live, item["robot_id"], item["state"])
        if why is not None:   # wait one more interval; TOTAL_S still bounds the chain
            item["reads"] = 0
            record.update(waiting_for=why, checked_at=now, next_at=now + REISSUE_DELAYS_S[record["attempt"] - 1])
            self._write(item["live"], record)
            return
        record.pop("waiting_for", None)
        item["reads"] += 1
        if item["reads"] < READY_READS:
            return
        if bo is not None and bo["phase"] == "pending":
            await self._step_back(item, bo, now)
            return
        await self._start(item)

    async def _step_back(self, item: dict, bo: dict, now: float) -> None:
        """One CORE nudge_backward through the console's step; a refusal ends the chain (same spot stands)."""
        robot_id = item["robot_id"]
        me = await back._pose(self.runner, robot_id)
        bo["before"] = None if me is None else [round(me.x, 4), round(me.y, 4)]
        bo["lat_m"] = (item["live"].view["detail"].get("lane_departure") or {}).get("lat_m")
        try:
            answer = await self.runner.robot_step(robot_id, "backward", bo["distance_m"])
        except Exception as exc:  # noqa: BLE001 - recorded; nothing moved
            bo["result"] = _code(exc)
            self._drop(item, "back_off_refused")
            return
        bo.update(phase="backing", started_at=now, mission=answer.get("state"), traffic_held=answer.get("traffic_held"))
        item["reads"] = 0
        self._write(item["live"], item["record"])

    async def _backing(self, item: dict, bo: dict, now: float) -> None:
        """Wait for CORE to end the step; an end Fleet cannot read before the step's own bound is no reissue."""
        limit = bo["distance_m"] / back.STEP_SPEED_MPS + back.STEP_SPARE_S
        try:
            status = await self.runner._call(self.runner.robot_step_status(item["robot_id"]))
        except Exception:  # noqa: BLE001 - unread: CORE still ends the step on its own distance and time
            status = None
        state = (status or {}).get("state") if isinstance(status, dict) else None
        if state in ("done", "aborted") and (status.get("kind") in (None, "nudge_backward")):
            me = await back._pose(self.runner, item["robot_id"])
            bo.update(result=state if state == "done" else f"aborted:{status.get('reason')}", ended_at=now,
                      after=None if me is None else [round(me.x, 4), round(me.y, 4)])
            if state != "done":
                self._drop(item, "back_off_aborted")
                return
            bo["phase"] = "looking"
            item["reads"] = 0
            self._write(item["live"], item["record"])
        elif now - bo["started_at"] >= limit:
            bo.update(result="unconfirmed", ended_at=now)
            self._drop(item, "back_off_unconfirmed")

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
        item["state"] = state
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
        new = self.runner._find(new_id)
        bo = item.get("back_off") or {}
        backed = bo.get("result") == "done"
        if new is not None:
            new.view["detail"]["reissued_from"] = {
                "trip_id": item["trip_id"], "root": item["root"], "attempt": record["attempt"],
                "previous_reason": record["previous_reason"], "first_end_at": record["first_end_at"],
                "by": "auto_reissue", "principal": item["principal"],
                "back_offs": item["chain"].get("back_offs", 0) + int(backed),
                "back_off_m": round(item["chain"].get("back_off_m", 0.0) + (bo["distance_m"] if backed else 0.0), 3)}
            if backed:   # D-1087: the first leg slow and recentred (nav2_recovery_ladder.first_leg)
                new.view["detail"]["first_leg"] = {"until_m": back.FIRST_LEG_M, "why": "back_off"}
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
