"""D-1024 3 / D-793 2: device side of Fleet's pushed execution lease (SIM owner; no real-owner admission changes).

Fleet's PolicyApprovals sends ``{lease_id, episode_id, workcell_id, policy_digest, rig_revision, calibration_revision,
ttl_s, seq, window_remaining_s}`` every half period inside an approval window. The device converts ``ttl_s`` to an
owner-monotonic lease when it receives it, and derives the episode's absolute deadline once, from the first grant's
``window_remaining_s``; no lease ever passes that deadline, so a delayed grant cannot outlive the window. ``seq`` must
strictly increase within the episode, so a replayed grant is refused. Every refusal, a missing renewal, a clock fault or a
Fleet HOLD latches this receiver closed and HOLDs the owner session; nothing re-arms and nothing survives a restart.
The OwnerPolicySession keeps all of its own checks (scope, expiry, freshness, stop fence); this module only feeds it.

End of window: Fleet's last renewals can ask for no more than the episode deadline already granted. Such a grant is
accepted as a no-op (the lease is never lengthened, so it is not an error and not a HOLD); the lease then runs out at the
deadline and the watchdog poll holds the session.

NOT WIRED (2026-11-14): no production composition builds this receiver; SimPolicyChain still takes only
FleetLeaseConsumer. The wiring commit needs its own D-430 review and an end-to-end chain test, and must settle that the
receiver exists before Fleet's first push (Fleet mints a new lease and episode id at every approval) and that a later
approval is a new episode with a new receiver, never a rearm. A restarted receiver resets _seq and _deadline_ns, so
the wiring commit must latch a receiver for an episode it already saw, or Fleet must mint a new episode id per receiver.
"""
import math
import threading

from .omx_policy import PolicyLease
from .policy_lease import LeaseScope

MAX_LEASE_S = 2.0  # D-793 2: lease at most 2 s
_GRANT = frozenset({'lease_id', 'episode_id', 'workcell_id', 'policy_digest', 'rig_revision',
                    'calibration_revision', 'ttl_s', 'seq', 'window_remaining_s'})
MAX_WINDOW_S = 30 * 60  # D-793 2


class PushLeaseReceiver:
    def __init__(self, scope, *, monotonic, policy_digest, max_duration_ns=1_000_000_000):
        if (not isinstance(scope, LeaseScope) or not callable(monotonic)
                or type(max_duration_ns) is not int or not 0 < max_duration_ns <= int(MAX_LEASE_S * 1e9)
                or not isinstance(policy_digest, str) or len(policy_digest) != 64
                or any(c not in '0123456789abcdef' for c in policy_digest)):
            raise ValueError('trusted scope, clock, lowercase policy digest and lease budget <= 2 s required')
        self.scope, self.monotonic, self.policy_digest = scope, monotonic, policy_digest
        self.max_duration_ns = max_duration_ns
        self._lock, self._deliver_lock = threading.RLock(), threading.Lock()
        self._first = threading.Condition(self._lock)
        self._current = self._session = None
        self._closed, self._last_now, self.hold_reason = False, None, ''
        self._seq, self._deadline_ns = 0, None

    def _now(self):
        value = self.monotonic()
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value < 2**63 / 1e9:
            raise PermissionError('invalid owner clock')
        now = int(value * 1e9)
        if self._closed or (self._last_now is not None and now < self._last_now):
            self._closed = True
            raise PermissionError('push lease authority is permanently closed')
        self._last_now = now
        return now

    def _lease_from(self, grant, now):
        scope = self.scope
        if not isinstance(grant, dict) or set(grant) != _GRANT:
            raise ValueError('exact lease grant required')
        ttl = grant['ttl_s']
        if (type(ttl) not in (int, float) or not math.isfinite(ttl) or not 0 < ttl <= MAX_LEASE_S
                or int(ttl * 1e9) > self.max_duration_ns or int(ttl * 1e9) < 1):
            raise ValueError('lease ttl outside the installed budget')
        if (grant['workcell_id'] != scope.identity.workcell_id or grant['policy_digest'] != self.policy_digest
                or grant['rig_revision'] != scope.rig_revision
                or grant['calibration_revision'] != scope.calibration_revision):
            raise PermissionError('grant scope differs from the installed policy scope')
        seq, remaining = grant['seq'], grant['window_remaining_s']
        if type(seq) is not int or seq <= self._seq:
            raise PermissionError('grant sequence did not increase (replay)')
        if (type(remaining) not in (int, float) or not math.isfinite(remaining)
                or not 0 < remaining <= MAX_WINDOW_S):
            raise ValueError('window remaining outside (0, 30 min]')
        deadline = now + int(remaining * 1e9)
        if self._deadline_ns is not None:  # a delayed grant computes a later deadline; the earlier one stands
            deadline = min(self._deadline_ns, deadline)
        expires = min(now + int(ttl * 1e9), deadline)
        if expires <= now:
            raise PermissionError('episode deadline reached')
        self._pending_state = (seq, deadline)
        return PolicyLease(grant['lease_id'], grant['episode_id'], scope.policy_revision, scope.identity,
                           now, expires, scope.owner_session_id)

    def deliver(self, grant):
        """True only when the lease was accepted and, once a session is attached, renewed on it; otherwise HOLD."""
        with self._deliver_lock:
            try:
                with self._lock:
                    now = self._now()
                    lease = self._lease_from(grant, now)
                    current = self._current
                    if current is not None and (lease.lease_id, lease.episode_id) != (
                            current.lease_id, current.episode_id):
                        raise PermissionError('lease or episode changed inside one window')
                    self._seq, self._deadline_ns = self._pending_state
                    if current is not None and lease.expires_at_ns <= current.expires_at_ns:
                        return True  # capped at the window end already: nothing to extend, never a longer lease
                    self._current, session = lease, self._session
                    self._first.notify_all()
                if session is not None:
                    session.renew(lease)
                return True
            except Exception:
                self.hold('lease_delivery_failed')
                return False

    def hold(self, reason):
        with self._lock:
            self._closed = True
            session = self._session
            self.hold_reason = self.hold_reason or reason
            self._first.notify_all()
        if session is not None:
            session.hold(reason)

    def acquire(self, timeout_s=2.0):
        """The first pushed lease, for the session constructor; none arriving in time closes this receiver."""
        with self._first:
            if not self._first.wait_for(lambda: self._current is not None or self._closed, timeout_s):
                self._closed = True
            if self._closed or self._current is None:
                raise PermissionError('no pushed lease: push authority closed')
            try:
                if self._now() >= self._current.expires_at_ns:
                    self._closed = True
            except PermissionError:
                self._closed = True
            if self._closed:
                raise PermissionError('pushed lease already expired: push authority closed')
            return self._current

    def attach(self, session):
        """Bind the session built from ``acquire()``; its lease must be the receiver's current one."""
        with self._lock:
            if (self._closed or self._session is not None or session.lease.lease_id != self._current.lease_id
                    or session.lease.episode_id != self._current.episode_id):
                raise PermissionError('push receiver cannot bind this session')
            self._session = session

    def authority(self, lease):
        """authority_current for the session: same lease and episode as the pushed one, unexpired, never rearmed."""
        with self._lock:
            try:
                now, current = self._now(), self._current
                if (current is None or (lease.lease_id, lease.episode_id, lease.identity)
                        != (current.lease_id, current.episode_id, current.identity)
                        or not current.issued_at_ns <= now < current.expires_at_ns
                        or not lease.issued_at_ns <= now < lease.expires_at_ns):
                    if current is not None and now >= current.expires_at_ns:
                        self._closed = True  # an expired lease closes the receiver for good
                    return False
                return True
            except Exception:
                self._closed = True
                return False
