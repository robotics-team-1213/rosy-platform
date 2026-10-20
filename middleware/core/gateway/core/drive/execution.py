"""Private native-owner composition; no public admission or device capability.

Only an explicit pre-cycle installer uses this. The ordinary factory stays
unchanged. Declared map/energy/profile metadata still needs separate admission;
raw Nav2 velocity provenance remains UNATTRIBUTED. No new mode or writer owner.
"""
from dataclasses import dataclass
import inspect
import threading

from core_common.protocol.native_receipts import BOOT_ID
from core_common.protocol.schemas import DockState
from core_features.command.arbitration import Mode
from core_features.command._execution_ledger import Ledger, ChildIdentity
from core_features.command._execution_budget import Limits
from core.drive.execution_source import OriginalOdometrySource
from core_features.navigation.manager import NavGoalSpec, NavigationError
from core_features.navigation.map_evidence import MapEvidence
from core_features.navigation.native_map_adoption import NativeMapEvidence
from core_features.docking.database import DockError
from core_features.docking.model import DockPhase
from core_features.power.execution_energy import PackEnergySource
from core_features.command._execution_energy import EnergyContext
from core.bridge.pack_energy import PackEnergyIngress


def _invocation(arguments):
    result = dict(arguments)
    result.pop('self', None)
    if 'spec' in result:
        spec = result['spec']
        if type(spec) is not NavGoalSpec:
            raise ValueError('exact navigation spec required')
        result['spec'] = (spec.x, spec.y, spec.yaw, spec.frame)
    return result


@dataclass(eq=False)
class _Ticket:
    parent: object
    snapshot: tuple
    expected: dict
    entered: bool = False
    used: bool = False
    invocation: dict | None = None


def install_native_execution(services, ledger, *, source_limits=None):
    """Once, on real empty CoreServices, before any cycle; Dock -> Nav -> fence.

    A partially failed installation remains closed. There is no uninstall or
    fallback to declared child mutation after native owner claims are made.
    """
    from core.services import CoreServices
    if (type(services) is not CoreServices or type(ledger) is not Ledger
            or type(source_limits) is not Limits or source_limits.revision != ledger._profile):
        return None
    nav, dock = services.nav, services.docking
    with dock._lock, nav._lock:
        if (ledger._robot != services.identity.robot_id or ledger._boot != BOOT_ID
                or nav._execution_binding is not None or dock._execution_binding is not None
                or nav.native.generation or dock.native.generation or nav.mapping_active
                or nav._moving_session is not None or nav._admitting is not None
                or nav.native.current is not None or dock.native.current is not None
                or dock.state is not DockState.UNDOCKED):
            return None
        command = services.command
        fence = command._install_execution_restriction(ledger, _native_domains=('navigation', 'docking'))
        if fence is None:
            return None
        # Closed slots were claimed before the fence became visible. A cycle
        # crossing the two installation phases leaves that restriction closed.
        if not command._cycle_lock.acquire(blocking=False):
            return None
        try:
            if command._cycle_started:
                return None
            binding = NativeExecution(services, fence, source_limits)
            nav._execution_binding, dock._execution_binding = binding._navigation, binding._docking
            fence._native_owners = {'navigation': binding._navigation, 'docking': binding._docking}
            return binding
        finally:
            command._cycle_lock.release()


class NativeExecution:
    def __init__(self, services, fence, source_limits):
        self.services, self.fence = services, fence
        fence._odometry = OriginalOdometrySource(services.state, fence._ledger, source_limits)
        services.nav._map_evidence = MapEvidence(robot_id=services.identity.robot_id, boot_id=BOOT_ID)
        self._staging = None
        self._map_claimed = False
        self._energy_claimed = False
        self._source_limits = source_limits
        self._navigation = _NativeBinding(self, services.nav, 'navigation', NavigationError)
        self._docking = _NativeBinding(self, services.docking, 'docking', DockError)

    def install_energy_source(self, source):
        """One pre-cycle claim, no voltage fallback or active-profile replacement."""
        command, ledger = self.services.command, self.fence._ledger
        with self.services.docking._lock, self.services.nav._lock:
            if not command._cycle_lock.acquire(blocking=False):
                return None
            try:
                if command._cycle_started or self._energy_claimed:
                    return None
                self._energy_claimed = True
                if (type(source) is not PackEnergySource
                        or source._clock is not ledger._clock
                        or source.profile.robot_id != ledger._robot
                        or source.profile.boot_id != ledger._boot
                        or source.profile.revision != ledger._profile
                        or source.profile.whole_load_w != self._source_limits.whole_load_w
                        or command._execution_fence is not self.fence
                        or self.services.nav._execution_binding is not self._navigation
                        or self.services.docking._execution_binding is not self._docking
                        or self.fence._native_energy is not None):
                    return None
                context = EnergyContext(source, ledger._clock)
                self.fence._native_energy = self.fence._energy_owner = context
                return PackEnergyIngress(self.fence, context)
            finally:
                command._cycle_lock.release()

    def install_map_evidence(self, evidence):
        """One pre-cycle attempt; a failed claim leaves REQUIRED/CLOSED forever.

        Trusted private factory supplies the single transport's exact owner.
        Final checks use the real nav holder, never a caller's source getter.
        """
        command = self.services.command
        with self.services.docking._lock, self.services.nav._lock:
            if not command._cycle_lock.acquire(blocking=False):
                return False
            try:
                if command._cycle_started or self._map_claimed:
                    return False
                self._map_claimed = True
                if (type(evidence) is not NativeMapEvidence
                        or self.services.nav._execution_binding is not self._navigation
                        or self.services.docking._execution_binding is not self._docking
                        or command._execution_fence is not self.fence
                        or self.fence._native_map is not None):
                    return False
                self.fence._native_map = (evidence, self.services.nav)
                return True
            finally:
                command._cycle_lock.release()

    def source_snapshot(self):
        return self.fence._odometry.snapshot()

    def map_snapshot(self):
        return self.services.nav._map_evidence.snapshot()

    def _live(self, parent):
        ledger = self.fence._ledger
        with self.services.modes._lock, ledger._lock:
            sample = self.fence._map_sample()
            energy_sample = self.fence._energy_sample()
            now = ledger._now()
            return (parent is not None and parent is ledger._current
                    and ledger._remaining(parent, now=now) is not None
                    and self.fence._map_live(sample, parent, now)
                    and self.fence._energy_live(energy_sample, parent, now))

    def _invoke(self, binding, method, parent, args, kwargs):
        # Existing mode owner prepares NAVIGATION; this adapter cannot take it.
        with self.services.docking._lock, self.services.nav._lock:
            if (binding._ticket is not None or not self._live(parent)
                    or any(owner._parent is not None for owner in (self._navigation, self._docking))
                    or self.fence._writer_thread == threading.get_ident()
                    or binding.domain == 'navigation' and self.services.modes.mode is not Mode.NAVIGATION):
                raise binding.error('CAPABILITY_NOT_SUPPORTED', 'native execution entry unavailable')
            bound = inspect.signature(method).bind(*args, **kwargs)
            bound.apply_defaults()
            ticket = _Ticket(parent, (binding.owner.native.current, binding.owner.native.generation), {})
            bound.arguments['_execution_ticket'] = ticket
            ticket.expected = _invocation(bound.arguments)
            binding._ticket = ticket
            try:
                return method(*bound.args, **bound.kwargs)
            except Exception:
                if ticket.entered:
                    binding._fault(parent)
                raise
            finally:
                if binding._ticket is ticket:
                    binding._ticket = None

    def navigation(self, parent, spec, **kwargs):
        return self._invoke(self._navigation, self.services.nav.goal, parent, (spec,), kwargs)

    def dock(self, parent, dock_id=None, **kwargs):
        return self._invoke(self._docking, self.services.docking.dock, parent, (dock_id,), kwargs)

    def undock(self, parent, **kwargs):
        return self._invoke(self._docking, self.services.docking.undock, parent, (), kwargs)

    def _stage(self):
        dock, binding = self.services.docking, self._docking
        if (not dock._lock._is_owned() or not dock.active or dock.phase is not DockPhase.STAGING
                or binding._child is None or dock.native.current is None
                or dock.native.current.run_id != binding._child.run_id
                or dock.native.generation != binding._child.generation
                or not self._live(binding._parent)):
            raise NavigationError('CAPABILITY_NOT_SUPPORTED', 'no bound docking staging run')
        self._staging = (binding._parent, binding._child)

    def _staging_live(self):
        if self._staging is None:
            return False
        parent, child = self._staging
        ledger = self.fence._ledger
        with self.services.modes._lock, ledger._lock:
            return (self.services.modes.mode is Mode.DOCKING and ledger._current is parent
                    and ledger._child == child and not ledger._paused
                    and self._live(parent))

    def _clear_staging(self, parent=None):
        # All token writers and unscoped callbacks serialize under Nav. Called
        # by the Dock owner before its phase changes: Dock -> Nav, never reverse.
        with self.services.nav._lock:
            if parent is None or self._staging is not None and self._staging[0] is parent:
                self._staging = None


class _NativeBinding:
    def __init__(self, composition, owner, domain, error):
        self.composition, self.owner, self.domain, self.error = composition, owner, domain, error
        self.fence = composition.fence
        self._ticket = self._parent = self._child = None
        self._activated = False

    def _fault(self, parent=None):
        target = self._parent if parent is None else parent
        if target is not None:
            self.fence.stop(target, 'native-execution-fault')
            if target is self.fence._ledger._current:
                self._clear_input()
        self._parent = self._child = None
        self._activated = False
        if self.domain == 'docking':
            self.composition._clear_staging(target)

    def _clear_input(self):
        command = self.composition.services.command
        if self.domain == 'navigation':
            command.clear_navigation()
        else:
            command.clear_docking()

    def _admission_open(self):
        ticket = self._ticket
        mode = self.composition.services.modes.mode
        return (ticket is not None and ticket.entered and not ticket.used
                and _invocation(ticket.invocation) == ticket.expected
                and (self.owner.native.current, self.owner.native.generation) == ticket.snapshot
                and self.composition._live(ticket.parent)
                and (mode is Mode.NAVIGATION if self.domain == 'navigation'
                     else mode in (Mode.IDLE, Mode.NAVIGATION, Mode.DOCKING)))

    def check(self, event, *args):
        if event == 'entry':
            actual = args[0]
            ticket = self._ticket
            if (ticket is None or actual['_execution_ticket'] is not ticket or ticket.entered
                    or _invocation(actual) != ticket.expected
                    or (self.owner.native.current, self.owner.native.generation) != ticket.snapshot
                    or not self.composition._live(ticket.parent)):
                raise self.error('CAPABILITY_NOT_SUPPORTED', 'bound one-use native entry required')
            ticket.entered, ticket.invocation = True, actual
        elif event == 'unsupported':
            raise self.error('CAPABILITY_NOT_SUPPORTED', 'native execution profile does not support this entry')
        elif event == 'cancel':
            self._fault()
        elif event == 'ready':
            if not self._admission_open():
                self._fault(self._ticket.parent if self._ticket is not None else None)
                raise self.error('CAPABILITY_NOT_SUPPORTED', 'native admission expired or changed')
        elif event == 'phase':
            self.composition._clear_staging()
        elif event == 'activate':
            if self.domain != 'docking' or not self.owner.active:
                self._fault()
                raise RuntimeError('native activation state mismatch')
            self._activated = True
            self._sync()
        elif event == 'staging':
            self.composition._stage()
        elif event == 'callback':
            return args[0] is not None or self.composition._staging_live()
        else:
            self._fault()
            raise RuntimeError('unknown native execution checkpoint')
        return True

    def mutate(self, method, *args, **kwargs):
        native = self.owner.native
        before, generation = native.current, native.generation
        action = method.__name__
        if action == 'admit':
            ticket = self._ticket
            if (not self._admission_open()
                    or self.domain == 'docking' and self.composition.services.modes.mode is not Mode.DOCKING
                    or args[0] != (ticket.expected['kind'] if self.domain == 'navigation'
                                   else 'dock' if 'dock_id' in ticket.expected else 'undock')):
                self._fault(ticket.parent if ticket is not None else None)
                raise self.error('CAPABILITY_NOT_SUPPORTED', 'native admission ticket consumed or changed')
            ticket.used, self._parent = True, ticket.parent
        elif action == 'update':
            if before is None or before.run_id != args[0] or before.phase == 'TERMINAL':
                return method(*args, **kwargs)  # Exact stale/no-op receipt, no other execution affected.
        elif action != '_advance_generation':
            self._fault()
            raise RuntimeError('unsupported native mutation')
        try:
            if self.domain == 'docking':
                self.composition._clear_staging()
            if self._child is not None and not self.fence.pause(
                    self._parent, self._child, _native_owner=self):
                raise RuntimeError('native child could not close before mutation')
            result = method(*args, **kwargs)
            if (native.generation != generation + 1 or
                    action in ('admit', 'update') and native.current is not result or
                    action == '_advance_generation' and native.current is not before):
                raise RuntimeError('actual native receipt mutation mismatch')
            self._sync()
            return result
        except Exception:
            self._fault()
            raise

    def _sync(self):
        current, parent = self.owner.native.current, self._parent
        if current is None or parent is None:
            return
        if not self.composition._live(parent):
            self._fault()
            raise RuntimeError('native execution evidence or parent expired before receipt synchronization')
        if current.phase == 'TERMINAL':
            if current.result != 'SUCCEEDED':
                self._fault()
            else:
                if parent is self.fence._ledger._current:
                    self._clear_input()
                if self._child is not None and not self.fence.revoke(
                        parent, self._child, _native_owner=self):
                    self._fault()
                    raise RuntimeError('terminal native child could not close')
                self._parent = self._child = None
                self._activated = False
                if self.domain == 'docking':
                    self.composition._clear_staging(parent)
            return
        if current.reason is not None:
            self._fault()
            return
        if (self.domain == 'navigation' and current.phase != 'RUNNING'
                or self.domain == 'docking' and not self._activated):
            return
        child = ChildIdentity(self.domain, current.boot_id, current.run_id, self.owner.native.generation)
        if self._child is None:
            self._clear_input()  # Require a candidate received after this run's activation.
        accepted = (self.fence.attach(parent, child, _native_owner=self) if self._child is None
                    else self.fence.advance(parent, self._child, child, _native_owner=self))
        if not accepted:
            self._fault()
            raise RuntimeError('actual native child could not attach or advance')
        self._child = child
