"""Same-process seat/journal exclusion; cancellation alone never releases control."""

import math
import threading
import time
from .pilot_admission_store import PilotAdmissionStore


class ControlSeatAdmission:
    def __init__(self, owner, store, *, monotonic=time.monotonic):
        self.owner, self.store = owner, store
        self.session_id = owner.session_id
        self._clock = monotonic
        self._last_clock = None
        self._clock_failed = False
        self._lock = threading.RLock()
        self._seat = None
        self._revoked = False
        self._goals = {}
        self._durable = PilotAdmissionStore(store.path, owner.config.workcell_id, owner.config.instance_id)
        self._restart_hold = self._durable.has_pending()

    def _session(self):
        if self._restart_hold:
            raise PermissionError("persistent Pilot dispatch requires exact-goal reconciliation; restart remains HOLD")
        if self.owner.session_id != self.session_id:
            raise PermissionError("owner session changed; admission remains fenced")

    def _expire(self):
        now = self._now()
        if self._seat and now >= self._seat[2]:
            self._seat = None
            self._revoked = True

    def _now(self):
        try:
            now = self._clock()
            valid = math.isfinite(now) and (self._last_clock is None or now >= self._last_clock)
        except Exception:
            valid = False
        if self._clock_failed or not valid:
            self._clock_failed = True
            raise PermissionError("admission clock failed; control remains fenced")
        self._last_clock = now
        return now

    def acquire(self, token, seat_id, *, ttl_s):
        if not math.isfinite(ttl_s) or ttl_s <= 0:
            raise ValueError("seat TTL must be positive and finite")
        return self.owner.run_admission_policy(lambda state: self._acquire(token, seat_id, ttl_s, state))

    def _acquire(self, token, seat_id, ttl_s, state):
        with self._lock:
            self._session()
            self._expire()
            self._reconcile(state)
            if self._seat and self._seat[:2] != (token, seat_id):
                raise PermissionError("seat occupied")
            def claim():
                self._seat = (token, seat_id, self._now() + ttl_s)
            return self.store.run_if_no_unresolved(
                workcell_id=self.owner.config.workcell_id,
                instance_id=self.owner.config.instance_id, operation=claim)

    def reserve_pilot(self, seat_id, command_id):
        with self._lock:
            self._session()
            self._expire()
            if not self._seat or self._seat[1] != seat_id or self._revoked:
                raise PermissionError("seat missing, revoked or expired")
            self._reserve(command_id, seat_id)

    def _reserve(self, command_id, seat_id):
        if command_id in self._goals:
            raise PermissionError("Pilot command id was already reserved")
        self._durable.reserve(command_id, self.session_id)
        self._goals[command_id] = [None, False, seat_id]

    def release(self, token, seat_id):
        with self._lock:
            self._session()
            if not self._seat or self._seat[:2] != (token, seat_id):
                raise PermissionError("seat missing or does not belong to caller")
            self._seat = None
            self._revoked = True

    def expire_seat(self):
        with self._lock:
            try:
                self._expire()
            except PermissionError:
                self._seat = None
                self._revoked = True

    def revoke_expired_seat(self, token, seat_id):
        """HTTP steady-clock expiry is definitive even while the owner sim clock is paused."""
        with self._lock:
            if self._seat is not None and self._seat[:2] == (token, seat_id):
                self._seat = None
                self._revoked = True

    def cleanup_matches(self, seat_id, command_id):
        with self._lock:
            if self._seat is not None and self._seat[1] != seat_id:
                return False
            if command_id is None:
                return True
            goal = self._goals.get(command_id)
            return goal is not None and goal[2] == seat_id

    def note_rejected(self, command_id):
        with self._lock:
            goal = self._goals.get(command_id)
            if goal is not None and goal[0] is None:
                self._durable.update(command_id, self.session_id, None, True)
                goal[1] = True

    def reserve_hold(self, command_id, *, source_command_id):
        with self._lock:
            self._session()
            self._expire()
            source = self._goals.get(source_command_id)
            if (not self._seat or self._revoked or source is None
                    or not source[1] or source[2] != self._seat[1]):
                raise PermissionError("no matching live source seat for gripper hold")
            self._reserve(command_id, self._seat[1])

    def note_goal(self, command_id, kind, goal_id):
        with self._lock:
            goal = self._goals.get(command_id)
            if goal is None:
                return
            if kind == "GOAL_ACCEPTED" and goal_id:
                if goal[0] is None:
                    self._durable.update(command_id, self.session_id, goal_id, False)
                    goal[0] = goal_id
            elif kind == "TERMINAL_RESULT" and goal[0] is not None and goal[0] == goal_id:
                self._durable.update(command_id, self.session_id, goal_id, True)
                goal[1] = True

    def check_command(self, command):
        with self._lock:
            try:
                self._session()
                self._expire()
            except PermissionError:
                return False
            if command.session_id != self.session_id:
                return False
            if command.owner == "pilot_sim":
                return bool(self._seat and not self._revoked and command.command_id in self._goals
                            and self._goals[command.command_id][2] == self._seat[1]
                            and not self._goals[command.command_id][1])
            return not self._seat and not self._revoked

    def run_action_admission(self, operation):
        return self.owner.run_admission_policy(lambda state: self._run_action_admission(state, operation))

    def _run_action_admission(self, state, operation):
        with self._lock:
            self._session()
            self._expire()
            if self._seat:
                raise PermissionError("pilot seat excludes local Action admission")
            self._reconcile(state)
            return operation()

    def _reconcile(self, state):
        if self._revoked:
            if any(not goal[1] for goal in self._goals.values()) or state != "ready":
                raise PermissionError("revoked seat awaits terminal and owner recovery")
            self._durable.clear_completed(self.session_id)
            self._revoked = False
            self._goals.clear()
