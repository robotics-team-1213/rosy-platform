"""D-776 private boot-scoped lifecycle restrictions, without motion authority.

One trusted CORE owner must retain one ledger for its whole boot. Construction
does not establish that ownership. Native admission must separately validate
current map/facts/task context, exact native receipts, measured stop and energy.
The runtime factory does not install this yet. The private final fence claims
one ledger and uses nonblocking entry; ordinary metadata methods still block.
Readbacks and declared child identities are not proof of native admission.
"""

from dataclasses import dataclass, field
import threading
import time
from uuid import UUID

from core_features.command._execution_budget import Budget, Remaining, _finite

_READ_CLOCK = object()


def _text(value):
    return type(value) is str and 0 < len(value) <= 128 and value == value.strip()


@dataclass(frozen=True)
class ExecutionIdentity:
    robot_id: str
    boot_id: UUID
    parent_id: UUID
    profile_revision: str
    map_id: str
    map_revision: str
    odom_frame: str
    odom_epoch: str
    context_digest: str

    def __post_init__(self):
        text = (self.robot_id, self.profile_revision, self.map_id,
                self.map_revision, self.odom_frame, self.odom_epoch)
        if (not all(_text(v) for v in text) or type(self.boot_id) is not UUID
                or type(self.parent_id) is not UUID or type(self.context_digest) is not str
                or len(self.context_digest) != 64
                or any(c not in "0123456789abcdef" for c in self.context_digest)):
            raise ValueError("invalid execution identity")


@dataclass(frozen=True)
class ChildIdentity:
    domain: str
    boot_id: UUID
    run_id: UUID
    generation: int

    def __post_init__(self):
        if (type(self.domain) is not str or self.domain not in ("navigation", "docking")
                or type(self.boot_id) is not UUID or type(self.run_id) is not UUID
                or type(self.generation) is not int or not 0 < self.generation < 2**63):
            raise ValueError("invalid native child identity")

    @property
    def run_key(self):
        return self.domain, self.boot_id, self.run_id


@dataclass(frozen=True, eq=False)
class _Parent:
    identity: ExecutionIdentity
    budget: Budget
    stop_request: object = field(default_factory=lambda: _StopRequest(), repr=False)


class _StopRequest:
    """Plain monotonic store, only used outside locks on a supported GIL build.

    This is a request, NOT the committed budget STOP or a physical stop ACK.
    No Condition/Event lock, reset, property setter or reference destructor.
    """
    __slots__ = ('requested',)

    def __init__(self):
        self.requested = False


@dataclass(frozen=True)
class Status:
    state: str
    parent: ExecutionIdentity | None
    child: ChildIdentity | None
    epoch: int
    remaining: Remaining | None
    reason: str | None


class Ledger:
    """Retain consumed IDs until a new CORE boot; never FIFO-evict or resume.

    An ACTIVE readback describes a live budget; without an attached child it
    still has no candidate to restrict. Even with a child it is not a permit.
    Retirement records explicit STOP metadata, never measured physical stop.
    """

    def __init__(self, *, robot_id, boot_id, profile_revision, max_parents,
                 max_children, clock=time.monotonic):
        if (not _text(robot_id) or type(boot_id) is not UUID or not _text(profile_revision)
                or any(type(v) is not int or v <= 0 for v in (max_parents, max_children))
                or not callable(clock)):
            raise ValueError("invalid execution ledger scope")
        self._robot = robot_id
        self._boot = boot_id
        self._profile = profile_revision
        self._max_parents = max_parents
        self._max_children = max_children
        self._clock = clock
        self._last_clock = None
        self._clock_fault = False
        self._lock = threading.RLock()
        self._used_parents = set()
        self._used_children = set()
        self._generations = {}
        self._current = None
        self._child = None
        self._paused = False
        self._epoch = 0
        self._owner = None

    def _authorized(self, owner):
        return self._owner is None or owner is self._owner

    def _now(self):
        if self._clock_fault:
            return None
        try:
            now = self._clock()
        except Exception:
            now = None
        if (not _finite(now) or now < 0
                or (self._last_clock is not None and now < self._last_clock)):
            self._clock_fault = True
            self._epoch += 1
            if self._current is not None:
                self._current.stop_request.requested = True
                self._current.budget.stop("ledger-clock", _owner=self)
            return None
        self._last_clock = now
        return now

    def _remaining(self, parent, *, now=_READ_CLOCK):
        if parent is None or parent is not self._current:
            return None
        before_reason, before_epoch = parent.budget.reason, self._epoch
        if parent.stop_request.requested and parent.budget.reason is None:
            if not parent.budget.stop("execution-fault-request", _owner=self):
                return None
            self._epoch += 1
        if now is _READ_CLOCK:
            now = self._now()
        remaining = None if now is None else parent.budget.remaining(now_mono=now, _owner=self)
        if remaining is None:
            if parent.budget.reason is None:
                parent.stop_request.requested = True
            elif before_reason is None and before_epoch == self._epoch:
                self._epoch += 1
        return remaining

    def admit(self, identity, budget, *, _owner=None):
        with self._lock:
            if (not self._authorized(_owner) or type(identity) is not ExecutionIdentity or identity.robot_id != self._robot
                    or identity.boot_id != self._boot or self._current is not None
                    or identity.parent_id in self._used_parents
                    or len(self._used_parents) >= self._max_parents or self._clock_fault):
                return None
            # A valid boot-scoped attempt consumes the ID even when its facts,
            # budget, profile or transport deadline fail subsequent checks.
            self._used_parents.add(identity.parent_id)
            scope = (identity.profile_revision, identity.odom_frame, identity.odom_epoch)
            if (type(budget) is not Budget or identity.profile_revision != self._profile
                    or budget.scope != scope):
                return None
            if self._owner is not None and not budget._claim(self):
                return None
            now = self._now()
            if now is None or not budget.adoption_open(now_mono=now, _owner=self):
                return None
            # Recheck after validation; neither delay nor adoption restarts the window.
            final = self._now()
            if final is None or not budget.adoption_open(now_mono=final, _owner=self):
                return None
            self._current = _Parent(identity, budget)
            self._child = None
            self._paused = False
            self._epoch += 1
            return self._current

    def attach(self, parent, child, *, _owner=None):
        with self._lock:
            if (not self._authorized(_owner) or self._remaining(parent) is None or type(child) is not ChildIdentity
                    or child.boot_id != self._boot or self._child is not None
                    or child.run_key in self._used_children
                    or len(self._used_children) >= self._max_children
                    or child.generation <= self._generations.get(child.domain, 0)):
                return False
            if self._remaining(parent) is None:
                return False
            self._used_children.add(child.run_key)
            self._generations[child.domain] = child.generation
            self._child = child
            self._paused = False
            self._epoch += 1
            return True

    def advance(self, parent, expected, replacement, *, _owner=None):
        """Update a still-attached run's phase generation, never reattach a run.

        The native owner must separately verify the actual transition under its
        own mutation boundary. This method accepts declared metadata only.
        """
        with self._lock:
            if (not self._authorized(_owner) or self._remaining(parent) is None or type(expected) is not ChildIdentity
                    or type(replacement) is not ChildIdentity or self._child != expected
                    or replacement.run_key != expected.run_key
                    or replacement.generation <= self._generations.get(expected.domain, 0)):
                return False
            if self._remaining(parent) is None:
                return False
            self._generations[expected.domain] = replacement.generation
            self._child = replacement
            self._paused = False
            self._epoch += 1
            return True

    def pause(self, parent, child, *, _owner=None):
        """Close an attached run during its owner's actual mutation; keep all consumption."""
        with self._lock:
            if (not self._authorized(_owner) or self._remaining(parent) is None
                    or type(child) is not ChildIdentity or self._child != child):
                return False
            if not self._paused:
                self._paused = True
                self._epoch += 1
            return True

    def revoke(self, parent, child, *, _owner=None):
        with self._lock:
            if (not self._authorized(_owner) or self._remaining(parent) is None or type(child) is not ChildIdentity
                    or self._child != child):
                return False
            self._child = None
            self._paused = False
            self._epoch += 1
            return True

    def stop(self, parent, reason, *, _owner=None):
        with self._lock:
            if not self._authorized(_owner) or parent is None or parent is not self._current:
                return False
            if parent.budget.reason is None:
                parent.stop_request.requested = True
                if not parent.budget.stop(reason, _owner=self):
                    return False
                self._epoch += 1
            return True

    def retire(self, parent, *, _owner=None):
        with self._lock:
            if (not self._authorized(_owner) or parent is None or parent is not self._current or parent.budget.reason is None):
                return False
            self._current = self._child = None
            self._paused = False
            self._epoch += 1
            return True

    def read(self):
        with self._lock:
            remaining = self._remaining(self._current)
            if self._current is None:
                return Status("REQUIRED_WAIT", None, None, self._epoch, None,
                              "ledger-clock" if self._clock_fault else None)
            state = ("ACTIVE" if remaining is not None else
                     "STOPPED" if self._current.budget.reason is not None else "STOP_REQUESTED")
            return Status(state,
                          self._current.identity, self._child, self._epoch,
                          remaining, self._current.budget.reason)
