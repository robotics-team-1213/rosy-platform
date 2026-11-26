"""D-494 5: trip halts through the junction/cancel ports; a trip open before a restart is never resumed."""
import asyncio
from contextlib import nullcontext
import logging

from core_common.protocol.evidence import STALE_POSE_S
from rosy.world.state.projections.map_pose_samples import parse_utc

from fleet.routing.cost import STOP
from fleet.server.trip_ports import OPEN

_LOG = logging.getLogger("fleet.server.trip_runner")  # the trip loop's logger, as before the D-517 split


def error_code(exc: BaseException) -> str:
    return getattr(exc, "code", None) or type(exc).__name__


def halt_unconfirmed(detail: dict | None) -> bool:
    """True when a stop attempt explicitly failed (stop_sent=False) or recorded an error."""
    return isinstance(detail, dict) and (
        detail.get("stop_sent") is False
        or ("error" in detail and detail["error"] != "TRIP_NOT_RUNNING")
    )


def _cancel_ack(receipt) -> bool:
    from fleet.server.goal_admission import cancel_confirmed as _cancel_confirmed

    return (
        isinstance(receipt, dict)
        and "error" not in receipt
        and receipt.get("ok") is not False
        and receipt.get("cancel_confirmed") is not False
        and receipt.get("stop_sent") is not False
        and (_cancel_confirmed(receipt) or receipt.get("cancel_confirmed") is True or receipt.get("stop_sent") is True)
    )


def pre_dispatch_wait(trip: dict) -> bool:
    detail = trip.get("detail") or {}
    peer = detail.get("peer_wait") or {}
    return (detail.get("drive_mode") == "nav2" and peer.get("stage") == "pre_dispatch_peer_check"
            and peer.get("command_robot_id") == trip["robot_id"] and peer.get("dispatch_attempted") is False
            and isinstance(peer.get("waiting_on"), list) and peer.get("blocked_by") in peer["waiting_on"]
            and not any(detail.get(k) for k in ("nav2_route", "last_peer_wait", "named_stop_handoff_pending",
                                                "camera_lane_fallback")))


def idle_cancel_owner(receipt, received_at):
    if (not isinstance(receipt, dict) or receipt.get("navigation") != "IDLE"
            or receipt.get("operation", False) is not None or "error" in receipt
            or any(receipt.get(k) is False for k in ("ok", "stop_sent", "cancel_confirmed"))):
        return None
    observed = parse_utc(receipt.get("idle_observed_at"))
    if observed is None or abs(received_at - observed) >= STALE_POSE_S:
        return None
    owner = receipt.get("idle_owner") or {}
    if (isinstance(owner, dict) and isinstance(owner.get("boot_id"), str) and owner["boot_id"] and owner.get("owner_run_id", False) is None
            and all(type(owner.get(k)) is int and owner[k] >= 0 for k in ("owner_generation", "transport_generation",
                                                                         "mode_epoch", "dock_owner_generation"))):
        return owner, max(received_at, observed)
    return None


def pause_proof_args(trip: dict) -> dict:
    hold = trip.get("hold") or {}
    args = {}
    if hold.get("reason") == "fleet_hold" and (hold.get("stop") is not None or trip.get("drive_mode") in {"free", "nav2"}):
        args["pause_after"] = hold.get("at", 0)
    if pre_dispatch_wait(trip):  # no goal was ever sent, so a cancel needs the same idle proof as a pause
        args["peer_idle"] = True
    return args


class TripHalts:
    def __init__(self, store, junction, config, call, clock, cancel_goal, release_queue, busy, roster=None, lock_for=None):
        self._store, self._junction, self._config, self._call, self._clock = store, junction, config, call, clock
        self._cancel_goal, self._release_queue, self._busy, self.roster = cancel_goal, release_queue, busy, roster
        self._lock_for = lock_for
        self.dock_stop = None
        self.reconcile_handoff = None
        self.pending_handoffs = {}
        self.read_stop_state = self.read_navigation = self.wire_epoch = None
        self.gave_up = []
        self.restarted = store.trips(states=OPEN, limit=1000)  # ``run_restart`` stops each (retried until it takes)
        for trip in self.restarted:
            detail = {**(trip.get("detail") or {}), "stop_sent": False}
            trip.update(state="stopped", reason="restart", detail=detail, updated_at=clock())
            store.put_trip(trip)
        for trip in store.pending_handoff_stops():
            if trip["state"] in OPEN:
                detail = {**(trip.get("detail") or {}), "stop_sent": False}
                trip.update(state="stopped", reason="restart", detail=detail, updated_at=clock())
                store.put_trip(trip)
            self.track_handoff_stop(trip)
        seen_ids = {t["trip_id"] for t in self.restarted}
        unconfirmed_stops = getattr(store, "unconfirmed_trip_stops", None)
        rows = unconfirmed_stops() if callable(unconfirmed_stops) else store.trips(states=("canceled", "stopped"), limit=1000)
        for trip in rows:
            if trip["trip_id"] not in seen_ids and halt_unconfirmed(trip.get("detail")):
                self.restarted.append(trip)
                seen_ids.add(trip["trip_id"])
        self.restarted = [trip for trip in self.restarted if trip["robot_id"] not in self.pending_handoffs]

    @staticmethod
    def dock_owned(trip):
        return ((trip.get("detail") or {}).get("parking_handoff") or {}).get("phase") in {
            "submitting", "docking", "staging_confirmed", "waiting_for_commission", "waiting_for_clearance"}

    def unconfirmed_dock(self, robot):
        return any(t["robot_id"] == robot and self.dock_owned(t)
                   for t in (*self.restarted, *self.gave_up))

    async def halt_dock(self, trip):
        try:
            return await self._call(self.dock_stop(trip))
        except Exception:
            return {"stop_sent": False, "error": "DOCK_CANCEL_UNCONFIRMED"}

    def track_handoff_stop(self, trip):
        if self.dock_owned(trip) and trip["state"] not in OPEN:
            self.clear_trip(trip["trip_id"])
            if halt_unconfirmed(trip.get("detail")):
                self.gave_up.append(trip)
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

    async def measured_stop(self, robot_id: str, after: float, *, idle_only=False) -> dict | None:
        """Read CORE directly. A cached idle before this stop cannot prove quiescence."""
        if self.read_stop_state is None:
            return None
        state = await self._call(self.read_stop_state(robot_id))
        if not isinstance(state, dict):
            return None
        sample = (state.get("evidence") or {}).get("velocity") or {}
        stamp = parse_utc(sample.get("sampled_at"))
        vel = state.get("velocity") or {}
        # CORE snapshots omit goal; only the pre-dispatch idle proof (owner checked separately) may rely on that.
        if (sample.get("evidence") != "fresh" or stamp is None or stamp <= after
                or not 0 <= self._clock() - stamp < STALE_POSE_S
                or state.get("robot_id") != robot_id or state.get("goal") is not None or not idle_only and "goal" not in state
                or (state.get("line_follow") or {}).get("mode") != "OFF"
                or state.get("navigation") not in {"IDLE", "ARRIVED", "CANCELED", "FAILED"}
                or state.get("mode") not in {"IDLE", "NAVIGATION"}
                or idle_only and (state["mode"] != "IDLE" or state["navigation"] != "IDLE")
                or any(type(vel.get(k)) not in (float, int) or vel[k] != 0.0 for k in ("linear", "angular"))):
            return None
        return {"sampled_at": sample["sampled_at"], "navigation": state["navigation"],
                "goal": None, "velocity": {"linear": 0.0, "angular": 0.0}}

    def idle_wire(self, robot):
        return self.wire_epoch(robot) if self.wire_epoch else None

    async def measured_idle_stop(self, robot, after, owner, wire):
        if wire is None or self.idle_wire(robot) != wire or self.read_navigation is None:
            return None
        proof = await self.measured_stop(robot, after, idle_only=True)
        if proof is None:
            return None
        nav = await self._call(self.read_navigation(robot))
        if (isinstance(nav, dict) and nav.get("navigation") == "IDLE" and nav.get("idle_owner") == owner
                and self.idle_wire(robot) == wire):
            return {**proof, "basis": "pre_dispatch_idle", "idle_owner": owner}
        return None

    async def halt_robot(self, robot_id: str, lane: bool, place: str | None, *, handoff_pending=False,
                         pause_after=None, peer_idle=False) -> dict:
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
            idle_proof = None
            try:
                wire = self.idle_wire(robot_id) if peer_idle and not handoff_pending else None
                cancel_res = await self._call(self._cancel_goal(robot_id))
                after_cancel = self._clock() if wire is not None else None
                canceled = _cancel_ack(cancel_res)
                if not canceled and wire is not None and (observed := idle_cancel_owner(cancel_res, after_cancel)):
                    owner, after_cancel = observed
                    for delay in (0., .15, .25):
                        if delay:
                            await asyncio.sleep(delay)
                        idle_proof = await self.measured_idle_stop(robot_id, after_cancel, owner, wire)
                        if idle_proof:
                            canceled = True
                            break
                if not canceled:
                    err = (
                        cancel_res.get("error")
                        if isinstance(cancel_res, dict) and isinstance(cancel_res.get("error"), str) and cancel_res.get("error")
                        else "CANCEL_UNCONFIRMED"
                    )
                    errors.append(err)
            except Exception as exc:  # the halt must try every step whatever one of them raised
                errors.append(error_code(exc))
                canceled = False
            if handoff_pending:
                # A lost handoff reply leaves either Nav2 or the lane controller holding the wheels.
                held = await attempt(self._junction.hold(robot_id))
                canceled = canceled and held
            if canceled and pause_after is not None and not idle_proof:
                try:
                    canceled = await self.measured_stop(robot_id, pause_after) is not None
                    if not canceled:
                        errors.append("TRIP_PAUSE_STOP_UNCONFIRMED")
                except Exception as exc:
                    canceled = False
                    errors.append(error_code(exc))
            sent = {"stop_sent": canceled, **({"pause_proof": idle_proof} if canceled and idle_proof else {})}
            try:
                self._release_queue(robot_id)
            except Exception as exc:  # the stop above is what matters
                errors.append(error_code(exc))
        if errors:
            sent["error"] = errors[-1]
        return sent

    def clear_robot(self, robot_id: str) -> None:
        self.restarted = [t for t in self.restarted if t["robot_id"] != robot_id]
        self.gave_up = [t for t in self.gave_up if t["robot_id"] != robot_id]

    def clear_trip(self, trip_id: str) -> None:
        self.restarted = [t for t in self.restarted if t.get("trip_id") != trip_id]
        self.gave_up = [t for t in self.gave_up if t.get("trip_id") != trip_id]

    async def run_restart(self) -> None:
        """Outside the tick path: retry every ``restart_retry_s`` up to ``restart_attempts``."""
        for _attempt in range(int(self._config.restart_attempts)):
            await self.halt_restarted()
            if not self.restarted:
                return
            await asyncio.sleep(self._config.restart_retry_s)
        _LOG.warning("gave up stopping robots of trips open before the restart: %s",
                     sorted({trip["robot_id"] for trip in self.restarted}))
        seen = {t["trip_id"] for t in self.gave_up}
        self.gave_up.extend(t for t in self.restarted if t["trip_id"] not in seen)
        self.restarted = []

    async def _retry_trip_entry(self, trip: dict, *, handoff_pending: bool | None = None) -> bool:
        """Stop one unresolved trip and persist before mutating in-memory state. Returns True if confirmed."""
        rid = trip["robot_id"]
        lane = False if handoff_pending is True else (trip.get("drive_mode") == "lane")
        place = None if handoff_pending is True else trip.get("next_place")
        hp = bool((trip.get("detail") or {}).get("named_stop_handoff_pending")) if handoff_pending is None else handoff_pending
        if (trip.get("detail") or {}).get("camera_lane_fallback"):
            lane, place, hp = False, None, True
        try:
            if self.dock_owned(trip):
                result = await self.halt_dock(trip)
            else:
                result = await self.halt_robot(rid, lane, place, handoff_pending=hp, **pause_proof_args(trip))
        except Exception:
            _LOG.exception("could not stop robot %s of a trip open before the restart", rid)
            return False
        detail = {**(trip.get("detail") or {}), **result}
        if result.get("stop_sent") and "error" not in result:
            detail.pop("error", None)
        now = self._clock()
        candidate = {**trip, "detail": detail, "updated_at": now}
        try:
            self._store.put_trip(candidate)
        except Exception:
            _LOG.exception("could not persist halt result for %s (%s)", trip.get("trip_id"), rid)
            return False
        trip.update(detail=detail, updated_at=now)
        return not halt_unconfirmed(detail)

    async def _retry_list_in_place(self, attr: str) -> None:
        roster = set(self.roster()) if self.roster is not None else None
        for trip in list(getattr(self, attr)):
            rid, tid = trip["robot_id"], trip["trip_id"]
            if roster is not None and rid not in roster:
                setattr(self, attr, [t for t in getattr(self, attr) if t.get("trip_id") != tid])
                continue
            async with (self._lock_for(rid) if self._lock_for is not None else nullcontext()):
                if not any(t.get("trip_id") == tid for t in getattr(self, attr)):
                    continue
                if self._busy(rid):
                    continue
                if await self._retry_trip_entry(trip):
                    setattr(self, attr, [t for t in getattr(self, attr) if t.get("trip_id") != tid])

    async def halt_restarted(self) -> None:
        """Stop each such robot until it takes it or leaves the roster; a new trip's robot is that trip's."""
        await self._retry_list_in_place("restarted")

    async def halt_unresolved(self) -> list[dict]:
        """Retry active restart halts, exhausted halts, and pending named-stop handoffs for safety-gate confirmation."""
        await self._retry_list_in_place("restarted")
        await self._retry_list_in_place("gave_up")
        for rid, trip in list(self.pending_handoffs.items()):
            async with (self._lock_for(rid) if self._lock_for is not None else nullcontext()):
                if self.pending_handoffs.get(rid) is not trip:
                    continue
                await self._retry_trip_entry(trip, handoff_pending=True)
        out = []
        seen = set()
        for t in (*self.restarted, *self.gave_up):
            if halt_unconfirmed(t.get("detail")) and t["trip_id"] not in seen:
                out.append(t)
                seen.add(t["trip_id"])
        for t in self.pending_handoffs.values():
            if t["trip_id"] not in seen:
                out.append(t)
                seen.add(t["trip_id"])
        return out
