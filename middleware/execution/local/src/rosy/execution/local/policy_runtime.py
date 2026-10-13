"""Private, steady-clock SIM composition over one existing OMX owner/runtime."""
import math
import threading

from omx_adapter.command_owner import ArmCommandOwner
from .policy_source import capture_source


class PolicyRuntimeBinding:
    def __init__(self, session, runtime):
        self.session, self.runtime, self.owner = session, runtime, session.owner
        if (type(self.owner) is not ArmCommandOwner or not session.enabled
                or session._execution_journal is None or runtime.owner is not self.owner
                or runtime.action_port is not self.owner._action_port
                or runtime.monotonic is not session._clock
                or self.owner._monotonic is not session._clock
                or runtime.owner_clock != 'steady'
                or self.owner.config.allowed_owners != ('learned_policy',)
                or self.owner.state != 'ready'):
            raise ValueError('dedicated same-owner steady SIM runtime required')
        period = runtime.poll_period_s
        doc = session.policy.recheck()
        budget = min(session._ttl, doc['timing']['max_observation_age_ns'], doc['timing']['max_action_age_ns'])
        if type(period) not in (int, float) or not math.isfinite(period) or not 0 < period*1e9 <= budget/2:
            raise ValueError('runtime poll period exceeds policy/lease budget')
        self._config = self.owner.config
        self._port = runtime.action_port
        self._clock = runtime.monotonic
        self._period = period
        self._timing = doc['timing']
        self._fault = threading.Event()
        self._local = threading.local()
        header, payloads = capture_source(session.policy, self.owner)
        self.source_revision = session._execution_journal.store_source(header, payloads)
        runtime.bind_policy_driver(self)

    def _current(self):
        return (self.runtime.owner is self.owner and self.session.owner is self.owner
                and self.owner.config is self._config and self.runtime.action_port is self._port
                and self.owner._action_port is self._port and self.runtime.monotonic is self._clock
                and self.session._clock is self._clock and self.owner._monotonic is self._clock
                and self.runtime.owner_clock == 'steady' and self.runtime.poll_period_s == self._period
                and self.runtime._policy_binding is self and self.owner._control_admission is self)

    def guard(self):
        if self._fault.is_set() or not self._current():
            self._fault.set()
            self.session._fail('policy_runtime_binding_or_callback_fault')

    def check_command(self, command):
        candidate = getattr(self._local, 'candidate', None)
        if (getattr(self._local, 'command', None) is not command or candidate is None
                or self._fault.is_set() or self.session.hold_reason or not self._current()):
            return False
        try:
            now = self._clock()
            if type(now) not in (int, float) or not math.isfinite(now):
                return False
            ns = int(now*1e9)
            return (self.session.lease.issued_at_ns <= ns < self.session.lease.expires_at_ns
                    and 0 <= ns-candidate.observed_at_ns <= self._timing['max_observation_age_ns']
                    and 0 <= ns-candidate.produced_at_ns <= self._timing['max_action_age_ns'])
        except Exception:
            return False

    def check_after_submission(self, command):
        if not self.check_command(command):
            return False
        try:
            # Submit retains session/owner serialization. Recheck the complete
            # trusted authority/install/stop/camera boundary after transport I/O.
            doc, now, cameras = self.session._guard()
            candidate = self._local.candidate
            self.session._source(candidate, doc, now)
            self.session._camera_source(candidate, doc, now, cameras)
            now = self.session._now()
            self.session._lease_time(self.session.lease, now)
            if any(not 0 <= now-stamp <= self._timing['max_observation_age_ns']
                   for stamp in candidate.camera_received_at_ns):
                return False
            return self.check_command(command)
        except Exception:
            self._fault.set()
            return False

    def adopt(self, snapshot):
        # Called during the native owner's serialized attach transaction, with
        # the session lock already held. Do not validate/deliver it a second time.
        if snapshot is None or snapshot is not self.owner._joint_state:
            raise ValueError('already accepted owner snapshot required before attach')
        self.session._snapshot = snapshot
        self.session._history[snapshot.sequence] = snapshot

    def prepare(self, command):
        self.guard()
        self.runtime.register_phase_event_sink(command.command_id, self._event)

    def abandon(self, command):
        self.runtime.unregister_phase_event_sink(command.command_id)

    def _event(self, event):
        try:
            return self.session._execution_journal.observe(event)
        except Exception:
            # Do not acquire the session/owner lock from the ROS callback: fast
            # callbacks may run while submit holds them. The post-I/O admission
            # check and scheduled policy poll consume this one-way fault latch.
            self._fault.set()
            raise

    def submit(self, command, candidate):
        self.guard()
        self._local.command, self._local.candidate = command, candidate
        try:
            return self.runtime._submit_policy(command, self)
        finally:
            self._local.command = self._local.candidate = None

    def observe(self, snapshot):
        self.guard()
        self.session.observe(snapshot)

    def poll(self):
        try:
            self.guard()
            return self.session.poll()
        except Exception:
            self._fault.set()
            # This dedicated owner admits only learned_policy; no other owner's
            # active command is canceled by this composition.
            return self.owner.preempt('policy_session_hold')
