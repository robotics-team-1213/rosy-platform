"""CORE's optional observation/action port over one authorized, watchdog-bound session."""
import base64
from dataclasses import asdict
from datetime import datetime, timezone
import math
import secrets
import threading

from core_common.protocol.schemas import LocalStopRequest, StopRequestSource
from .omx_policy import OwnerPolicySession, PolicyCandidate


class CoreArmPolicyPort:
    def __init__(self, session, *, capture, principal):
        if (not isinstance(session, OwnerPolicySession) or session._runtime_binding is None
                or not callable(capture) or not isinstance(principal, str) or not principal.strip()):
            raise ValueError('watchdog-bound owner session, trusted capture and principal required')
        self.session, self.capture, self.principal = session, capture, principal
        self._pending = None
        self._lock = threading.RLock()

    def _authorize(self, principal):
        if principal != self.principal:
            raise PermissionError('arm policy belongs to another principal')

    def policy(self, principal):
        self._authorize(principal)
        self.session.poll()
        doc = self.session.policy.recheck()
        if len(doc['cameras']) != 1:
            raise ValueError('one installed RGB camera required')
        camera = doc['cameras'][0]
        return dict(policy_revision=doc['revision'], simulation=True,
                    joint_names=doc['joint_names'], units='rad',
                    camera=dict(name=camera['name'], shape=camera['source_shape']))

    def observation(self, principal, policy_revision):
        with self._lock:
            self._authorize(principal)
            if policy_revision != self.session.lease.policy_revision:
                raise ValueError('installed policy revision differs')
            self._pending = None
            self.session.poll()
            if self.session.owner.state != 'ready':
                raise BlockingIOError('previous arm goal is still active')
            rgb, camera = self.capture()
            source = self.session.capture_inference_input(rgb, camera)
            observation_id = secrets.token_urlsafe(24)
            self._pending = (observation_id, source, policy_revision)
            return dict(observation_id=observation_id, policy_revision=policy_revision,
                        positions=dict(zip(source.joint_names, source.positions)),
                        camera=dict(name=camera.name, shape=list(source.camera_shape),
                                    rgb_base64=base64.b64encode(source.rgb).decode('ascii')))

    def submit(self, principal, *, observation_id, policy_revision, positions):
        with self._lock:
            self._authorize(principal)
            pending, self._pending = self._pending, None
            if pending is None or (observation_id, policy_revision) != (pending[0], pending[2]):
                raise ValueError('unknown, replaced or consumed observation')
            source = pending[1]
            if (set(positions) != set(source.joint_names)
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in positions.values())):
                raise ValueError('exact installed joint names and finite rad targets required')
            # Capture time conservatively charges inference and network delay to action age.
            candidate = PolicyCandidate(source.lease_id, source.episode_id, policy_revision,
                source.sequence, source.observed_at_ns,
                max(source.observed_at_ns, source.camera_received_at_ns),
                tuple(positions[name] for name in source.joint_names),
                (source.frame_sha256,), (source.camera_received_at_ns,))
            return asdict(self.session.submit(candidate))

    def stop(self):
        with self._lock:
            self._pending = None
            identity = self.session.lease.identity
            request = LocalStopRequest(workcell_id=identity.workcell_id, instance_id=identity.instance_id,
                authority_epoch=identity.authority_epoch, dispatch_generation=identity.dispatch_generation,
                requested_at=datetime.now(timezone.utc), reason='CORE_OPERATOR_STOP')

            def cancel_session():
                try:
                    self.session.poll()
                except PermissionError:
                    pass  # The closed fence latches HOLD and cancels the session's own command.

            latch = self.session.fence.trip(request, source=StopRequestSource.OPERATOR_LOCAL,
                                           cancel_active=cancel_session)
            return dict(local_stop=latch.model_dump(mode='json'),
                        hold_reason=self.session.hold_reason, physical_stop_verified=False)
