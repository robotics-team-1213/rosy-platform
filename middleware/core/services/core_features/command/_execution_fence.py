"""Private D-776 final restriction, never native admission or a device permit.

Only traditional CPython 3.12 is initially supported. The plain slotted boolean
is a monotonic fault REQUEST under that runtime's GIL, not a portable Python
lock-free primitive. STOP commits under the ledger lock. A writer already in
that boundary may finish before the request commits; physical stop is UNKNOWN.
The runtime factory does not install this until native/profile acceptance exists.
Child metadata is declared; raw Nav2 velocity provenance remains UNATTRIBUTED.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import sys
import sysconfig
import threading
import time

from core_common.protocol.native_receipts import BOOT_ID
from core_features.command.arbitration import Mode
from core_features.command._execution_ledger import Ledger, ChildIdentity
from core_features.safety.velocity import finite_velocity

_CURRENT = object()
CONTEXT_CHANGED = object()  # A clean rejection, never a permission to write.
_AUTO = (Mode.NAVIGATION, Mode.DOCKING)


def _supported_runtime():
    return (sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12)
            and not sysconfig.get_config_var('Py_GIL_DISABLED'))


@dataclass(frozen=True)
class _Context:
    parent: object
    child: object
    ledger_epoch: int
    mode: Mode
    mode_epoch: int
    input_epoch: int
    input_stamp: float | None
    map_sample: object = None
    energy_sample: object = None


@dataclass(frozen=True)
class _Receipt:
    context: _Context
    output: object
    linear: float
    angular: float


def install(command, ledger, *, _native_domains=()):
    """One-way install before the very first cycle, including legacy ZERO cycles.

    This validates private ownership, not the identity/profile's field evidence.
    A metadata operation that was already waiting must recheck its owner token
    inside the ledger lock, so it cannot cross installation without the mode lock.
    """
    if (type(ledger) is not Ledger or not _supported_runtime()
            or _native_domains not in ((), ('navigation', 'docking'))):
        return None
    if not command._cycle_lock.acquire(blocking=False):
        return None
    try:
        modes = command._modes
        if not modes._lock.acquire(blocking=False):
            return None
        try:
            if not ledger._lock.acquire(blocking=False):
                return None
            try:
                if (command._cycle_started or command._execution_fence is not None
                        or modes._execution_fence is not None or modes.mode is not Mode.IDLE
                        or command._manual_twist is not None or command._nav_input is not None
                        or command._docking_input is not None or ledger._owner is not None
                        or ledger._current is not None or ledger._used_parents
                        or ledger._used_children or ledger._clock_fault or ledger._boot != BOOT_ID):
                    return None
                fence = Fence(command, ledger, _native_domains)
                ledger._owner = fence
                modes._execution_fence = command._execution_fence = fence
                return fence
            finally:
                ledger._lock.release()
        finally:
            modes._lock.release()
    finally:
        command._cycle_lock.release()


class Fence:
    def __init__(self, command, ledger, native_domains=()):
        self._command, self._ledger = command, ledger
        self._receipt = None
        self._writer_thread = None
        self._native_owners = dict.fromkeys(native_domains)
        self._odometry = None  # Installed by CORE composition; never read by the final writer.
        self._native_map = None  # REQUIRED/CLOSED for an installed native-domain composition.
        self._native_energy = self._energy_owner = None  # REQUIRED/CLOSED for native owners.

    def _energy_sample(self):
        owner = self._native_energy
        return (None if owner is None or owner is not self._energy_owner
                or owner.clock is not self._ledger._clock else owner.peek())

    def _energy_live(self, sample, parent, now):
        if not self._native_owners:
            return True
        owner = self._native_energy
        if (owner is not None and owner is self._energy_owner and owner.clock is self._ledger._clock
                and parent is not None
                and owner.valid(sample, parent.budget, now)):
            return True
        self.request_stop(parent)
        self._ledger._remaining(parent, now=now)
        return False

    def _map_sample(self):
        binding = self._native_map
        return None if binding is None else binding[0].peek()

    def _map_live(self, sample, parent, now):
        """Under the existing boundary: cached values only, no owner/source lock."""
        if not self._native_owners:
            return True  # The separate declared-metadata restriction has no native owner.
        binding = self._native_map
        if (binding is not None and binding[0].valid(sample, parent,
                raw_source=binding[1]._map_evidence, now=now)):
            return True
        self.request_stop(parent)
        self._ledger._remaining(parent, now=now)
        return False

    def request_stop(self, parent=_CURRENT):
        if parent is _CURRENT:
            parent = self._ledger._current
        # Shallow copies share the mutable flag. Only the exact current handle
        # can request it; retired handles already have committed software STOP.
        if parent is not None and parent is self._ledger._current:
            parent.stop_request.requested = True

    @contextmanager
    def _boundary(self, parent=_CURRENT):
        modes = self._command._modes
        if not modes._lock.acquire(blocking=False):
            self.request_stop(parent)
            yield False
            return
        try:
            if not self._ledger._lock.acquire(blocking=False):
                self.request_stop(parent)
                yield False
                return
            try:
                yield True
            finally:
                self._ledger._lock.release()
        finally:
            modes._lock.release()

    def _mutate(self, operation, *args):
        # Actual raw ROS publisher has no owner callbacks. Refuse accidental
        # same-thread metadata reentry instead of committing STOP mid-writer.
        if self._writer_thread == threading.get_ident():
            self.request_stop()
            return None
        with self._command._modes._lock:
            return operation(*args, _owner=self)

    def admit(self, identity, budget):
        ledger = self._ledger
        with self._command._modes._lock, ledger._lock:
            if self._command._modes.mode in (Mode.MANUAL, Mode.EMERGENCY):
                return None
            if not self._native_owners:
                return self._mutate(ledger.admit, identity, budget)
            owner, sample = self._native_energy, self._energy_sample()
            before = ledger._now()
            valid = (owner is not None and owner is self._energy_owner and owner.clock is ledger._clock
                     and owner.admission_open() and owner.valid(sample, budget, before))
            # The valid boot-scoped attempt still consumes its ID and original
            # Budget. An energy denial never returns a positive parent handle.
            parent = self._mutate(ledger.admit, identity, budget)
            if parent is None:
                return None
            now = ledger._now()
            if (not valid or owner is not self._native_energy or owner.clock is not ledger._clock
                    or not owner.admission_open() or not owner.valid(sample, budget, now)
                    or now is None or not budget.adoption_open(now_mono=now, _owner=ledger)):
                ledger.stop(parent, 'execution-energy-admission', _owner=self)
                ledger.retire(parent, _owner=self)
                return None
            return parent

    def _native_authorized(self, child, owner):
        return (type(child) is ChildIdentity and (child.domain not in self._native_owners or
                owner is not None and owner is self._native_owners[child.domain]))

    def attach(self, parent, child, *, _native_owner=None):
        if not self._native_authorized(child, _native_owner):
            return False
        return self._mutate(self._ledger.attach, parent, child)

    def advance(self, parent, expected, replacement, *, _native_owner=None):
        if not self._native_authorized(expected, _native_owner):
            return False
        return self._mutate(self._ledger.advance, parent, expected, replacement)

    def pause(self, parent, child, *, _native_owner=None):
        if not self._native_authorized(child, _native_owner):
            return False
        return self._mutate(self._ledger.pause, parent, child)

    def revoke(self, parent, child, *, _native_owner=None):
        if not self._native_authorized(child, _native_owner):
            return False
        return self._mutate(self._ledger.revoke, parent, child)

    def stop(self, parent, reason):
        self.request_stop(parent)
        return self._mutate(self._ledger.stop, parent, reason)

    def retire(self, parent):
        return self._mutate(self._ledger.retire, parent)

    def observe(self, parent, pose, *, before_mono, after_mono):
        if self._writer_thread == threading.get_ident():
            self.request_stop(parent)
            return False
        with self._command._modes._lock, self._ledger._lock:
            if parent is None or parent is not self._ledger._current:
                return False
            if self._ledger._remaining(parent) is None:
                return False
            accepted = parent.budget.observe(pose, before_mono=before_mono,
                                            after_mono=after_mono, _owner=self._ledger)
            return accepted and self._ledger._remaining(parent) is not None

    def _context(self):
        command, ledger = self._command, self._ledger
        modes = command._modes
        parent, child = ledger._current, ledger._child
        input_stamp = None
        map_sample = None
        energy_sample = None
        if modes.mode in _AUTO:
            domain = 'navigation' if modes.mode is Mode.NAVIGATION else 'docking'
            if parent is None or child is None or child.domain != domain:
                return None
            map_sample = self._map_sample()
            energy_sample = self._energy_sample()
            now = ledger._now()
            if ledger._remaining(parent, now=now) is None:
                return None
            if not self._map_live(map_sample, parent, now):
                return None
            if not self._energy_live(energy_sample, parent, now):
                return None
            if ledger._paused:
                return None
            candidate = command._nav_input if modes.mode is Mode.NAVIGATION else command._docking_input
            if candidate is None or candidate.mode_epoch != modes._epoch:
                return None  # WAIT for this activation's first input; budget still ages above.
            input_stamp = candidate.stamp
        elif modes.mode is Mode.MANUAL:
            self.request_stop(parent)
            ledger._remaining(parent)  # Commit automatic STOP without inhibiting manual.
        else:
            return None
        return _Context(parent, child, ledger._epoch, modes.mode, modes._epoch,
                        command._input_epoch, input_stamp, map_sample, energy_sample)

    def _same(self, ctx):
        command, ledger = self._command, self._ledger
        return (ctx.parent is ledger._current and ctx.child == ledger._child
                and ctx.ledger_epoch == ledger._epoch and ctx.mode is command._modes.mode
                and ctx.mode_epoch == command._modes._epoch
                and ctx.input_epoch == command._input_epoch)

    def _live(self, ctx):
        command, ledger = self._command, self._ledger
        if command._safety.estop:
            return False
        if ctx.mode is Mode.MANUAL:
            return (command._manual_twist is not None
                    and command._manual_mode_epoch == ctx.mode_epoch
                    and not command.watchdog.expired(time.monotonic()))
        now = ledger._now()
        if ledger._remaining(ctx.parent, now=now) is None or ctx.parent.stop_request.requested:
            return False
        if not self._map_live(ctx.map_sample, ctx.parent, now):
            return False
        if not self._energy_live(ctx.energy_sample, ctx.parent, now):
            return False
        # A replacement's fresh stamp cannot conceal expiry of the old selection.
        return (now is not None and ctx.input_stamp is not None
                and 0 <= now - ctx.input_stamp <= command._nav_timeout_s)

    def _discard(self, parent):
        self.request_stop(parent)
        self._command._pending_shadow = None

    def select(self):
        from core_features.command.manager import ZERO
        self._receipt = None
        command = self._command
        with self._boundary() as locked:
            ctx = self._context() if locked else None
            now = (time.monotonic() if ctx is not None and ctx.mode is Mode.MANUAL
                   else self._ledger._now() if locked else None)
        if ctx is None or now is None:
            command._pending_shadow = None
            return ZERO
        try:
            out = command._select_output(now=now)  # Policy/readiness/native bookkeeping outside locks.
        except Exception:
            self._discard(ctx.parent)
            raise
        with self._boundary(ctx.parent) as locked:
            if not locked or not self._live(ctx):
                self._discard(ctx.parent)
                return ZERO
            if not self._same(ctx):
                command._pending_shadow = None
                return ZERO
            self._receipt = _Receipt(ctx, out, out.linear, out.angular)
        return out

    def receipt_for(self, output):
        receipt = self._receipt
        return receipt if receipt is not None and receipt.output is output else None

    def submit(self, receipt, output, payload, submit):
        """Same raw writer, or CONTEXT_CHANGED for a clean one-use rejection."""
        if payload == (0., 0.):
            self._receipt = None
            self._command._pending_shadow = None
            return submit()  # ZERO grants no authority and never waits on metadata locks.
        parent = receipt.context.parent if type(receipt) is _Receipt else None
        with self._boundary(parent) as locked:
            valid = (locked and receipt is not None and receipt is self._receipt
                     and output is receipt.output
                     and payload == (receipt.linear, receipt.angular)
                     and (output.linear, output.angular) == payload
                     and finite_velocity(*payload) and self._live(receipt.context))
            self._receipt = None  # Consumed before every attempt, including rejection/unknown.
            if valid and receipt.context.mode in _AUTO:
                limits = parent.budget._limits
                valid = abs(payload[0]) <= limits.speed_mps and abs(payload[1]) <= limits.angular_speed_rps
            if not valid:
                self._discard(parent)
                return None
            if not self._same(receipt.context):
                self._command._pending_shadow = None
                return CONTEXT_CHANGED
            try:
                self._writer_thread = threading.get_ident()
                result = submit()
                if not result.accepted:
                    self._discard(parent)
                return result
            except Exception:
                self._discard(parent)
                raise
            finally:
                self._writer_thread = None
                if parent is not None and parent.stop_request.requested:
                    self._ledger._remaining(parent)  # Commit after an already-entered writer.
