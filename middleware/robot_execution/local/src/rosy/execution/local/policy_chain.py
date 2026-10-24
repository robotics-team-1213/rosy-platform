"""Explicit default-disabled SIM Fleet lease -> owner runtime -> CORE composition."""
import threading

from .core_arm_policy import CoreArmPolicyPort
from .omx_policy import OwnerPolicySession
from .policy_install import InstalledPolicy
from .policy_journal import PolicyExecutionJournal
from .policy_lease import FleetLeaseConsumer, MAX_HTTP_TIMEOUT_S

SIM_POLICY_ENVIRONMENT = 'sim'


class SimPolicyChain:
    def __init__(self, *, policy, runtime, fence, consumer, journal, owner_identity,
                 camera_current, capture, principal, installed_rig_revision, enabled=False):
        if enabled is not True:
            raise PermissionError('SIM policy chain defaults disabled')
        if (not isinstance(policy, InstalledPolicy) or type(consumer) is not FleetLeaseConsumer
                or not isinstance(journal, PolicyExecutionJournal)
                or not all(callable(value) for value in (owner_identity, camera_current, capture))):
            raise ValueError('installed policy, scoped consumer and trusted SIM providers required')
        doc, scope, owner = policy.recheck(), consumer.scope, runtime.owner
        cfg = owner.config
        # D-854 §3: one or more installed cameras; the owner checks each frame against the installed order.
        if (doc['environment'] != SIM_POLICY_ENVIRONMENT or not doc['cameras']
                or doc['revision'] != scope.policy_revision
                or (cfg.workcell_id, cfg.instance_id) != (scope.identity.workcell_id, scope.identity.instance_id)
                or scope.owner_session_id != owner.session_id
                or not isinstance(installed_rig_revision, str) or not installed_rig_revision.strip()
                or scope.rig_revision != installed_rig_revision
                or scope.calibration_revision != cfg.calibration_revision
                or cfg.allowed_owners != ('learned_policy',) or owner.state != 'ready'
                or runtime.owner_clock != 'steady' or runtime.monotonic is not consumer.monotonic
                or runtime._policy_binding is not None):
            raise ValueError('dedicated ready SIM owner, installed pin and original clock required')
        self.consumer, self.session = consumer, None
        self._stop, self._lifecycle = threading.Event(), threading.Lock()
        self._worker = None
        try:
            lease = consumer.acquire()
            self.session = OwnerPolicySession(policy, owner, fence, lease,
                authority_current=consumer.authority, owner_identity=owner_identity,
                monotonic=runtime.monotonic, camera_current=camera_current,
                execution_journal=journal, max_lease_duration_ns=consumer.max_duration_ns, enabled=True)
            self.session.bind_runtime(runtime)
            self.port = CoreArmPolicyPort(self.session, capture=capture, principal=principal)
        except BaseException:
            consumer.close()
            self._hold()
            raise

    def _hold(self):
        if self.session is not None:
            try:
                self.session.poll()
            except PermissionError:
                pass  # Existing session fault latches HOLD and cancels its own active goal.

    def start(self):
        with self._lifecycle:
            if self._worker is not None or self._stop.is_set():
                raise PermissionError('SIM policy worker cannot be restarted')
            self.session.poll()
            self._worker = threading.Thread(target=self._run, name='omx-sim-policy-lease')
            self._worker.start()
        return self

    def _run(self):
        try:
            while not self._stop.is_set():
                remaining = self.session.lease.expires_at_ns/1e9-self.consumer.monotonic()
                wait = max(0, min(self.consumer.max_duration_ns/4e9, remaining-3*MAX_HTTP_TIMEOUT_S))
                if self._stop.wait(wait) or self.session.hold_reason:
                    break
                self.consumer.renew(self.session)
        except Exception:
            pass  # The consumer has already latched closed; no retry or automatic recovery.
        finally:
            self.consumer.close()
            self._stop.set()
            self._hold()

    def close(self):
        self.consumer.close()
        self._stop.set()
        if hasattr(self, 'port'):
            self.port.stop()
        else:
            self._hold()
        # Stop reaches the owner before waiting for a bounded in-flight HTTP request.
        with self._lifecycle:
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(2)
            if worker.is_alive():
                raise RuntimeError('own SIM lease worker did not exit')

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()
