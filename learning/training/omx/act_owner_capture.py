"""Explicit study composition. No issuer, scheduler, submit, reset or activation.

The caller supplies a trusted immutable RGB capture. Metadata/hash equality is
integrity, not proof that this caller or capture device is authorized.
"""
from dataclasses import dataclass
import hashlib
import json

from act_inference import ACTInference, InferenceObservation
from rosy.execution.local.omx_policy import CameraSnapshot, OwnerPolicySession, PolicyCandidate


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class CapturedRGB:
    """One exact metadata/frame pair; RGB is HWC interleaved uint8 bytes."""
    metadata: CameraSnapshot
    rgb: bytes

    def __post_init__(self):
        if type(self.metadata) is not CameraSnapshot:
            raise ValueError('exact owner CameraSnapshot required')
        if not isinstance(self.rgb, (bytes, bytearray, memoryview)):
            raise ValueError('immutable RGB byte capture required')
        raw = bytes(self.rgb)
        shape = self.metadata.source_shape
        if (shape[0] != 3 or len(raw) != shape[0]*shape[1]*shape[2]
                or hashlib.sha256(raw).hexdigest() != self.metadata.frame_sha256):
            raise ValueError('captured RGB differs from original owner metadata')
        object.__setattr__(self, 'rgb', raw)


def infer_for_owner(engine, session, captured):
    """Return original-provenance candidate; existing owner must submit it.

    Capture is coherent under the existing owner lock. Inference is outside
    that lock so source observations/watchdog can continue. No age is refreshed.
    Queued actions retain their first source; owner history/final guards decide
    whether they remain admissible. A returned candidate is not a grant.
    """
    if (type(engine) is not ACTInference or type(session) is not OwnerPolicySession
            or type(captured) is not CapturedRGB or engine._clock is not session._clock):
        raise ValueError('exact explicit ACT/owner/capture with same owner clock required')
    with session._lock:
        doc = session.policy.recheck()
        if _encoded(engine.metadata) != _encoded(doc):
            raise ValueError('inference model and installed owner policy differ')
        lease = session.lease
        state, cameras = session.capture_observation()
        if len(cameras) != 1 or cameras[0] != captured.metadata:
            raise ValueError('RGB capture is not the exact guarded camera observation')
        camera = cameras[0]
        names = tuple(doc['joint_names'])
        observation = InferenceObservation(lease.episode_id, lease.lease_id, names,
            tuple(state.positions[name] for name in names), state.sequence,
            int(state.received_at*1e9), camera.identity, camera.calibration_sha256,
            camera.source_shape, camera.received_at_ns, captured.rgb)
    result = engine.infer(observation)
    with session._lock:
        if session.lease is not lease or _encoded(engine.metadata) != _encoded(session.policy.recheck()):
            raise ValueError('lease or installed model changed during inference')
    return PolicyCandidate(**result.candidate_fields()), result
