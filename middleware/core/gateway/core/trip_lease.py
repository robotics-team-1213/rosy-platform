"""D-541: the Fleet trip lease — CORE knows a Fleet trip holds this robot.

Lives beside services.py, not in core_features (whose size verdict asks for no growth).

One robot, at most one trip lease. The holder (the CORE token that opened it,
Fleet's own enrolment credential) renews it within ``ttl_s`` on CORE's
monotonic clock. While it lives, motion and mode writes from any other token
are refused 409 ``TRIP_LEASED`` (``common.require_calibration_owner``); stop
requests stay open to everyone.

The lease stores no drive mode: the owner's lane <-> free switches keep it.
It ends on IDLE / MANUAL / DOCKING / EMERGENCY (mode listener), takeover,
release and expiry. Takeover, expiry and a non-owner cancel also halt the
robot to IDLE through ``halt`` (set by the CORE wiring); this object itself
commands nothing (D-2). Memory only: a CORE restart has no lease.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from core_common.protocol.trip_lease import MAX_TTL_S, MIN_TTL_S, TripLeaseError
from core_features.command.arbitration import Mode

LEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
MAX_NAME_LENGTH = 64
MAX_TRIP_ID_LENGTH = 128
#: How long the snapshot keeps ``trip_lease_ended`` after an end, so every reader
#: (1 Hz heartbeat, 10 Hz /ws/state, polls) sees it once. Cleared by the next open.
ENDED_VISIBLE_S = 10.0
#: ``trip_lease.renewed`` at the 0.5 s renew rate would flush the event ring;
#: one event per lease per this many seconds is enough for an audit trail.
RENEWED_EVENT_EVERY_S = 30.0
log = logging.getLogger(__name__)
#: Reasons that also halt the robot to IDLE (the others already left the mode).
HALTING_REASONS = frozenset({"expired", "taken_over"})
#: Ended lease ids kept so a renew of a lost lease is refused (D-541 7) long after the display window.
# ponytail: bounded FIFO; a Fleet that waits past this many later ends could reopen an old id.
ENDED_IDS_KEPT = 1024


@dataclass
class _Lease:
    lease_id: str
    trip_id: str
    holder: str
    operator_name: str
    owner_id: str
    ttl_s: float
    origin: str
    since: str
    renewed_mono: float
    event_mono: float
    warned: set = field(default_factory=set)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


class TripLeaseManager:
    def __init__(self, events: Any, *, monotonic: Callable[[], float] = time.monotonic,
                 clock: Callable[[], float] = time.time) -> None:
        self._events = events
        self._monotonic = monotonic
        self._clock = clock
        # Events and ``halt`` run after this lock is released: halt changes the mode,
        # whose listener calls end() back in here.
        self._lock = threading.Lock()
        self._lease: Optional[_Lease] = None
        self._ended: Optional[tuple[float, dict]] = None
        self._ended_ids: OrderedDict[str, dict] = OrderedDict()
        #: ``halt(reason)``: stop line-follow / navigation and go IDLE. Wired by CORE.
        self.halt: Callable[[str], None] = lambda reason: None

    # --- lease -------------------------------------------------------------

    def open(self, *, lease_id: str, trip_id: str, holder: str, operator_name: str,
             ttl_s: float, owner_id: str, origin: str = "",
             refuse: Callable[[], Optional[TripLeaseError]] = lambda: None) -> tuple[dict, bool]:
        """Open, or renew when the same token sends the same ``lease_id``.

        ``refuse`` is the open-time check (calibration, MANUAL, E-stop); it is not
        asked on a renew. Returns ``(lease, renewed)``.
        """
        lease_id = str(lease_id or "")
        trip_id = str(trip_id or "").strip()
        holder = str(holder or "").strip()
        operator_name = str(operator_name or "").strip()
        if not LEASE_ID_PATTERN.match(lease_id):
            raise TripLeaseError("VALIDATION_ERROR", "lease_id must match ^[A-Za-z0-9_.:-]{1,64}$")
        if not 1 <= len(trip_id) <= MAX_TRIP_ID_LENGTH:
            raise TripLeaseError("VALIDATION_ERROR", f"trip_id must be 1-{MAX_TRIP_ID_LENGTH} characters")
        for name, value in (("holder", holder), ("operator_name", operator_name)):
            if not 1 <= len(value) <= MAX_NAME_LENGTH:
                raise TripLeaseError("VALIDATION_ERROR", f"{name} must be 1-{MAX_NAME_LENGTH} characters")
        ttl = float(ttl_s)
        if not MIN_TTL_S <= ttl <= MAX_TTL_S:
            raise TripLeaseError("VALIDATION_ERROR", f"ttl_s must be within {MIN_TTL_S:g}..{MAX_TTL_S:g}")
        self.expire_due()
        with self._lock:
            lost = self._lease is None and lease_id in self._ended_ids
        if lost:
            # D-541 7: a lost lease is never renewed into a new one; Fleet ends the trip.
            raise TripLeaseError("NOT_FOUND", "this trip lease has ended", self._ended_for(lease_id))
        checked = self.current() is None
        if checked:
            # Outside our lock: the check reads other managers that publish events.
            refused = refuse()
            if refused is not None:
                raise refused
        renew_event = None
        with self._lock:
            now = self._monotonic()
            current = self._lease
            if current is not None:
                if current.owner_id != owner_id or current.lease_id != lease_id:
                    raise TripLeaseError("TRIP_LEASED", "a Fleet trip lease is active",
                                         self._public(current, now))
                current.renewed_mono = now
                current.ttl_s = ttl
                public = self._public(current, now)
                if now - current.event_mono >= RENEWED_EVENT_EVERY_S:
                    current.event_mono = now
                    renew_event = public
                renewed = True
            elif not checked or lease_id in self._ended_ids:
                raise TripLeaseError("MODE_CONFLICT", "the trip lease changed meanwhile; retry")
            else:
                current = self._lease = _Lease(
                    lease_id=lease_id, trip_id=trip_id, holder=holder,
                    operator_name=operator_name, owner_id=owner_id, ttl_s=ttl,
                    origin=origin, since=_iso(self._clock()), renewed_mono=now, event_mono=now)
                self._ended = None
                public = self._public(current, now)
                renewed = False
        p = public
        if not renewed:
            self._events.publish("trip_lease.opened", source="trip_lease", data={
                "lease_id": p["lease_id"], "trip_id": p["trip_id"], "holder": p["holder"],
                "operator_name": p["operator_name"], "ttl_s": ttl})
        elif renew_event is not None:
            self._events.publish("trip_lease.renewed", source="trip_lease", data={
                "lease_id": p["lease_id"], "trip_id": p["trip_id"], "ttl_s": ttl})
        return public, renewed

    def release(self, lease_id: str, by_id: str) -> dict:
        """The owner's normal end. Does not stop the robot (Fleet already did)."""
        self.expire_due()
        with self._lock:
            current = self._lease
            if current is None or current.lease_id != lease_id:
                raise TripLeaseError("NOT_FOUND", "no such active trip lease", self._ended_for(lease_id))
            if current.owner_id != by_id:
                raise TripLeaseError("FORBIDDEN", "only the lease owner can release it",
                                     self._public(current, self._monotonic()))
        return self.end("released", by="owner", lease_id=lease_id) or {}

    def takeover(self, lease_id: str, *, by_id: str, by: str, reason: str = "") -> dict:
        """D-541 4: a non-owner ends the lease; CORE halts the robot to IDLE."""
        self.expire_due()
        with self._lock:
            current = self._lease
            if current is None or current.lease_id != lease_id:
                raise TripLeaseError("NOT_FOUND", "no such active trip lease", self._ended_for(lease_id))
            if current.owner_id == by_id:
                raise TripLeaseError("VALIDATION_ERROR", "the owner releases with DELETE, not takeover")
        ended = self.end("taken_over", by=by, lease_id=lease_id, note=reason)
        if ended is None:
            raise TripLeaseError("NOT_FOUND", "no such active trip lease", self._ended_for(lease_id))
        return ended

    def end(self, reason: str, *, by: str = "", lease_id: Optional[str] = None,
            halt: Optional[bool] = None, note: str = "") -> Optional[dict]:
        """End the live lease (only ``lease_id`` when given). Returns the ended record or None.

        ``halt`` defaults to the reason (expiry and takeover stop the robot).
        """
        with self._lock:
            current = self._lease
            if current is None or (lease_id is not None and current.lease_id != lease_id):
                return None
            self._lease = None
            now = self._monotonic()
            ended = {"lease_id": current.lease_id, "reason": reason, "by": by}
            self._ended = (now, ended)
            self._ended_ids[current.lease_id] = ended
            while len(self._ended_ids) > ENDED_IDS_KEPT:
                self._ended_ids.popitem(last=False)
            public = self._public(current, now)
        data = {"lease_id": public["lease_id"], "trip_id": public["trip_id"], "holder": public["holder"],
                "operator_name": public["operator_name"], "reason": reason, "by": by, "note": note}
        if reason == "released":
            self._events.publish("trip_lease.ended", severity="info", source="trip_lease", data=data)
        else:
            self._events.publish("trip_lease.ended", severity="warning", source="trip_lease", data=data)
        if halt if halt is not None else reason in HALTING_REASONS:
            try:
                self.halt(reason)
            except Exception:  # the lease is already gone; the 5 Hz timer must keep running
                log.exception("trip lease halt failed (%s)", reason)
        return ended

    def expire_due(self) -> None:
        """Timer hook (5 Hz): a lease not renewed within ``ttl_s`` ends and halts the robot.

        Readers never expire the lease themselves: until this runs, a lapsed lease
        still refuses non-owners (safe side), and the halt never runs inside a
        request that holds the localization gate.
        """
        with self._lock:
            current = self._lease
            lapsed = (current is not None
                      and self._monotonic() - current.renewed_mono >= current.ttl_s)
            lease_id = current.lease_id if lapsed else None
        if lease_id is not None:
            self.end("expired", by="core", lease_id=lease_id)

    # --- readers -----------------------------------------------------------

    def current(self) -> Optional[dict]:
        with self._lock:
            return self._public(self._lease, self._monotonic()) if self._lease is not None else None

    def ended(self) -> Optional[dict]:
        """``trip_lease_ended`` for the snapshot, for ENDED_VISIBLE_S after the end."""
        with self._lock:
            if self._ended is None or self._monotonic() - self._ended[0] > ENDED_VISIBLE_S:
                return None
            return dict(self._ended[1])

    def owns(self, token_id: str) -> bool:
        with self._lock:
            return self._lease is not None and self._lease.owner_id == token_id

    def blocking(self, token_id: str) -> Optional[dict]:
        """The live lease when ``token_id`` is not its owner, else None."""
        with self._lock:
            current = self._lease
            if current is None or current.owner_id == token_id:
                return None
            return self._public(current, self._monotonic())

    def note_use(self, token_id: str, origin: Optional[str], what: str) -> None:
        """D-541 1: the owner token seen outside Fleet -> one ``trip_lease.shared_token`` warning.

        ``origin`` None means the use itself is foreign (owner-token teleop: a trip never teleops).
        """
        with self._lock:
            current = self._lease
            if current is None or current.owner_id != token_id:
                return
            if origin is not None and origin == current.origin:
                return
            key = (what, origin)
            if key in current.warned:
                return
            current.warned.add(key)
            public = self._public(current, self._monotonic())
        self._events.publish("trip_lease.shared_token", severity="warning", source="trip_lease", data={
            "lease_id": public["lease_id"], "trip_id": public["trip_id"], "holder": public["holder"],
            "use": what, "origin": origin or ""})

    # --- internals ---------------------------------------------------------

    def _ended_for(self, lease_id: str) -> Optional[dict]:
        ended = self._ended_ids.get(lease_id)
        return {"ended": dict(ended)} if ended is not None else None

    def _public(self, lease: _Lease, now: float) -> dict:
        return {
            "lease_id": lease.lease_id,
            "trip_id": lease.trip_id,
            "holder": lease.holder,
            "operator_name": lease.operator_name,
            "since": lease.since,
            "expires_in_s": round(max(0.0, lease.ttl_s - (now - lease.renewed_mono)), 1),
        }


def build_trip_lease(events, state, modes, safety, line_follow, command, nav) -> TripLeaseManager:
    trip_lease = TripLeaseManager(events)
    state.set_trip_lease_provider(lambda: (trip_lease.current(), trip_lease.ended()))

    def end_on_mode(old: Mode, new: Mode) -> None:
        # D-541 5: the owner's lane <-> free stays in NAVIGATION; every other mode ends the trip.
        if new is not Mode.NAVIGATION:
            trip_lease.end("estop" if new is Mode.EMERGENCY else "mode_left", by=f"mode:{new.value}")
    modes.change_listeners.append(end_on_mode)
    safety.estop_listeners.append(lambda: trip_lease.end("estop", by="safety"))

    def halt(reason: str) -> None:
        """D-541 4-6: expiry, takeover and a non-owner stop leave the robot IDLE."""
        try:
            if line_follow.active:
                status = line_follow.stop(reason=f"trip_lease_{reason}")
                command.clear_navigation()
                state.set_line_follow(status)
            nav.cancel(source=f"trip_lease:{reason}")
        except Exception:  # a failed stop must still leave NAVIGATION: IDLE sends nothing to the wheels
            log.exception("trip lease halt: stopping line-follow/navigation failed (%s)", reason)
        ok, _ = modes.transition(Mode.IDLE, expect=Mode.NAVIGATION)
        if ok:
            command.clear_navigation()
            events.publish("mode.changed", source="trip_lease",
                           data={"from": Mode.NAVIGATION.value, "to": Mode.IDLE.value, "by": "trip_lease"})
    trip_lease.halt = halt
    return trip_lease
