"""Immutable inference data only; no ROS, SDK, issuer or execution authority."""
from dataclasses import dataclass
import hashlib
import math


def _text(value):
    if not isinstance(value,str) or not value or value!=value.strip():raise ValueError('trimmed identity required')


def _ns(value):
    if type(value) is not int or not 0<=value<2**63:raise ValueError('integer owner-monotonic nanoseconds required')


def _vector(values,size=None,positive=False):
    values=tuple(values)
    if (not values or (size is not None and len(values)!=size)
            or any(type(v) not in (float,int) or not math.isfinite(v) or (positive and v<=0) for v in values)):
        raise ValueError('finite numerical vector with declared dimensions required')
    return values


@dataclass(frozen=True)
class InferenceObservation:
    episode_id: str
    lease_id: str
    joint_names: tuple
    positions: tuple
    sequence: int
    observed_at_ns: int
    camera_identity: str
    camera_calibration_sha256: str
    camera_shape: tuple
    camera_received_at_ns: int
    rgb: bytes

    def __post_init__(self):
        for value in (self.episode_id,self.lease_id,self.camera_identity):_text(value)
        for value in (self.sequence,self.observed_at_ns,self.camera_received_at_ns):_ns(value)
        names=tuple(self.joint_names)
        for name in names:_text(name)
        if not names or len(set(names))!=len(names):raise ValueError('distinct ordered joints required')
        object.__setattr__(self,'joint_names',names)
        object.__setattr__(self,'positions',_vector(self.positions,len(names)))
        sha=self.camera_calibration_sha256
        if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('known calibration SHA256 required')
        shape=tuple(self.camera_shape)
        if len(shape)!=3 or shape[0]!=3 or any(type(v) is not int or not 1<=v<=4096 for v in shape):
            raise ValueError('declared RGB CHW dimensions required')
        object.__setattr__(self,'camera_shape',shape)
        if not isinstance(self.rgb,(bytes,bytearray,memoryview)):raise ValueError('RGB uint8 byte buffer required')
        rgb=bytes(self.rgb)
        if len(rgb)!=math.prod(shape):raise ValueError('RGB byte count differs from dimensions')
        object.__setattr__(self,'rgb',rgb)

    @property
    def frame_sha256(self):return hashlib.sha256(self.rgb).hexdigest()


@dataclass(frozen=True)
class InferenceResult:
    policy_revision: str
    source: InferenceObservation
    positions: tuple
    produced_at_ns: int
    returned_at_ns: int
    chunk_index: int
    consumed_current: bool

    def candidate_fields(self):
        """Existing local Python candidate fields; this is not a public wire API."""
        return dict(lease_id=self.source.lease_id,episode_id=self.source.episode_id,
            policy_revision=self.policy_revision,sequence=self.source.sequence,
            observed_at_ns=self.source.observed_at_ns,produced_at_ns=self.produced_at_ns,
            positions=self.positions,camera_frames=(self.source.frame_sha256,),
            camera_received_at_ns=(self.source.camera_received_at_ns,))

