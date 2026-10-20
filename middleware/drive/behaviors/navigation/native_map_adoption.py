"""Finite sampled native map owner, not simultaneous native state or motion authority.

ROS clients mint nonces before sending. Callback work serializes here; the final
predicate only reads cached immutable values and plain fields on the supported
GIL runtime enforced by the final Fence. It takes no source/owner lock or clock.
"""
from dataclasses import dataclass, field
import threading

from core_features.navigation.map_evidence import MapEvidence
from core_features.navigation.native_map_reply import Consumer, NativeReply, finite

ROLES = ('amcl', 'static_layer')


@dataclass(eq=False)
class _Session:
    parent: object
    source: MapEvidence
    observation: object
    frozen: tuple | None = None
    samples: tuple = ()
    consumed: bool = False


@dataclass(eq=False)
class _Round:
    session: _Session
    entered_at: float
    first_before: float | None = None
    tickets: dict = field(default_factory=dict)
    used: set = field(default_factory=set)
    replies: dict = field(default_factory=dict)


@dataclass(frozen=True, eq=False)
class _Ticket:
    owner: object
    round: _Round
    role: str
    nonce: bytes
    before: float


@dataclass(frozen=True, eq=False)
class _Sample:
    parent: object
    source: MapEvidence
    observation: object
    tuple: tuple
    first_before: float
    expires_at: float
    session: _Session


class NativeMapEvidence:
    def __init__(self, *, source, parent, consumers, clock, stop, max_parents=64, max_queries=65536):
        if (type(consumers) is not tuple or len(consumers) != 2
                or any(type(v) is not Consumer for v in consumers)
                or {v.role for v in consumers} != set(ROLES)
                or consumers[0].provider is consumers[1].provider
                or not all(callable(v) for v in (source, parent, clock, stop))
                or any(type(v) is not int or not 0 < v <= 65536 for v in (max_parents, max_queries))):
            raise ValueError('bounded native map owner binding required')
        self._source, self._parent, self._clock, self._stop = source, parent, clock, stop
        self._profiles = {v.role: v for v in consumers}
        self._max_parents, self._max_queries = max_parents, max_queries
        self._sessions, self._nonces = {}, set()
        self._active = self._pending = None
        self._closed = False
        self._last_clock, self._clock_bad = None, False
        self._lock = threading.RLock()

    def _now(self):
        try:
            now = self._clock()
            if not finite(now) or self._last_clock is not None and now < self._last_clock:
                self._clock_bad = True
            if not self._clock_bad:
                self._last_clock = now
                return now
        except Exception:
            self._clock_bad = True
        return None

    def _fault(self, session):
        if session is not None and not session.consumed:
            session.consumed, session.samples = True, ()
            if self._pending is not None and self._pending.session is session:
                self._pending = None
            # The trusted composition supplies nonblocking exact-parent STOP.
            # Never substitute the current/new parent in a late callback.
            try:
                self._stop(session.parent)
            except Exception:
                pass  # Cache already closed; no positive evidence survives.

    def _same_source(self, session):
        try:
            return (self._parent() is session.parent and self._source() is session.source
                and session.source.snapshot() is session.observation)
        except Exception:
            return False

    def begin(self):
        with self._lock:
            if self._closed:
                return None
            try:
                parent, source = self._parent(), self._source()
            except Exception:
                self._fault(self._active)
                return None
            if parent is None:
                return None
            if self._active is not None and self._active.parent is not parent:
                self._fault(self._active)
            session = self._sessions.get(parent)
            if session is None:
                observation = source.snapshot() if type(source) is MapEvidence else None
                if len(self._sessions) >= self._max_parents:
                    self._stop(parent)
                    return None
                session = self._sessions[parent] = _Session(parent, source, observation)
                if observation is None:
                    self._fault(session)
                    return None
            self._active = session
            source_ok = self._same_source(session)
            now = self._now()
            if (session.consumed or now is None or not source_ok
                    or self._pending is not None
                    or session.frozen is not None and
                        (not session.samples or now >= session.samples[-1].expires_at)):
                self._fault(session)
                return None
            self._pending = _Round(session, now)
            return self._pending

    def _round_live(self, round_, now):
        return (not self._closed and round_ is self._pending and not round_.session.consumed
            and now is not None
            and 0 <= now - (round_.first_before if round_.first_before is not None else round_.entered_at) <= .25
            and (round_.session.frozen is None or round_.session.samples
                and now < round_.session.samples[-1].expires_at))

    def issue(self, round_, role, provider, nonce):
        with self._lock:
            if type(round_) is not _Round or round_ is not self._pending:
                return None
            source_ok = self._same_source(round_.session)
            now = self._now()
            profile = self._profiles.get(role) if type(role) is str else None
            if (not source_ok or not self._round_live(round_, now) or profile is None or provider is not profile.provider
                    or role in round_.tickets or type(nonce) is not bytes or len(nonce) != 16
                    or not any(nonce) or nonce in self._nonces or len(self._nonces) >= self._max_queries):
                self._fault(round_.session)
                return None
            self._nonces.add(nonce)
            if round_.first_before is None:
                round_.first_before = now
            ticket = _Ticket(self, round_, role, nonce, now)
            round_.tickets[role] = ticket
            return ticket

    def fail(self, ticket):
        with self._lock:
            if (type(ticket) is _Ticket and ticket.owner is self
                    and ticket.round.tickets.get(ticket.role) is ticket):
                self._fault(ticket.round.session)
            return False

    def close(self):
        """One-way transport shutdown invalidates even a completed cached pair."""
        with self._lock:
            self._closed = True
            self._fault(self._active)

    def reply(self, ticket, provider, reply):
        with self._lock:
            if type(ticket) is not _Ticket or ticket.owner is not self:
                return False
            round_, session = ticket.round, ticket.round.session
            if round_.tickets.get(ticket.role) is not ticket:
                return False
            reused = ticket.role in round_.used
            round_.used.add(ticket.role)  # Consume before ANY validation/result.
            source_ok = self._same_source(session)
            now = self._now()
            profile = self._profiles[ticket.role]
            if (reused or provider is not profile.provider or not source_ok or not self._round_live(round_, now)
                    or now < ticket.before or type(reply) is not NativeReply
                    or not reply.matches(profile, ticket.nonce, session.observation)
                    or session.frozen is not None and
                        reply.signature != session.frozen[ROLES.index(ticket.role)]):
                self._fault(session)
                return False
            # Validation and source callbacks may have crossed the query deadline.
            # No callback or blocking validation follows this final bracket.
            now = self._now()
            if not self._round_live(round_, now):
                self._fault(session)
                return False
            round_.replies[ticket.role] = reply.signature
            if len(round_.replies) == 2:
                frozen = tuple(round_.replies[role] for role in ROLES)
                if session.frozen is None:
                    session.frozen = frozen
                retained = tuple(s for s in session.samples if now < s.expires_at)
                if len(retained) >= 4:
                    self._fault(session)
                    return False
                sample = _Sample(session.parent, session.source, session.observation, session.frozen,
                    round_.first_before, round_.first_before + .5, session)
                session.samples = retained + (sample,)
                self._pending = None
            return True

    def sample(self, parent):
        with self._lock:
            session = self._active
            if session is None or session.parent is not parent or session.consumed:
                return None
            source_ok = self._same_source(session)
            now = self._now()
            if not source_ok or now is None:
                self._fault(session)
                return None
            if not session.samples:
                return None  # First pair is still pending, never positive evidence.
            sample = session.samples[-1]
            if not self.valid(sample, parent, raw_source=session.source, now=now):
                self._fault(session)
                return None
            return sample

    def peek(self):
        """Cached identity only, no validation, lock, clock or source callback.

        The Fence must validate this retained identity with its own fresh clock
        and actual current raw source. A later peek never renews a selection.
        """
        session = self._active
        samples = () if session is None else session.samples
        return samples[-1] if samples else None

    def valid(self, sample, parent, *, raw_source, now):
        """Cached predicate only: no locks, callbacks, clock, hash or RMW wait.

        Caller must pass the currently installed raw source and final clock.
        Selection retains THIS sample, so later polls cannot extend its deadline.
        """
        return (not self._closed and type(sample) is _Sample and sample.session is self._active
            and sample.parent is parent and not sample.session.consumed and not self._clock_bad
            and any(sample is item for item in sample.session.samples)
            and sample.tuple is sample.session.frozen and raw_source is sample.source
            and raw_source._current is sample.observation
            and finite(now) and sample.first_before <= now < sample.expires_at)
