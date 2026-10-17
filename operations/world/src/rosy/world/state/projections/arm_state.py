"""D-782 §3 current OMX arm state: observed facts only, never a prediction. Stdlib only.

Joint and gripper values come from the existing arm owner's observation in normalized units (five joints
-100..100, gripper 0..100). The owner remains the single joint writer; this projection only reads. Object state
has no live observer yet, so it is reported as `unobserved` rather than guessed.
"""
from dataclasses import dataclass
import math
import threading

OBJECT_UNOBSERVED = 'unobserved'


def _require(value, message):
    if not value:
        raise ValueError('arm state: ' + message)


@dataclass(frozen=True)
class ArmState:
    sample_id: str
    observed_at_ns: int
    rig_revision: str
    calibration_revision: str
    joints: tuple
    object_state: str = OBJECT_UNOBSERVED

    def __post_init__(self):
        _require(all(isinstance(v, str) and v and v == v.strip()
                     for v in (self.sample_id, self.rig_revision, self.calibration_revision)),
                 'explicit sample and revisions required')
        _require(type(self.observed_at_ns) is int and 0 <= self.observed_at_ns < 2**63, 'integer nanoseconds')
        joints = tuple(self.joints)
        _require(len(joints) == 6 and all(type(v) in (int, float) and math.isfinite(v) for v in joints),
                 'six finite normalized values required')
        _require(all(-100 <= v <= 100 for v in joints[:5]) and 0 <= joints[5] <= 100, 'normalized range')
        object.__setattr__(self, 'joints', tuple(float(v) for v in joints))
        _require(self.object_state == OBJECT_UNOBSERVED, 'no live object observer is accepted yet')

    def age_s(self, now_ns):
        return (now_ns - self.observed_at_ns) / 1e9


class ArmStateTracker:
    """Latest observed arm state per workcell instance. Refuses replayed clocks and revision changes."""

    def __init__(self, rig_revision, calibration_revision):
        self.rig_revision, self.calibration_revision = rig_revision, calibration_revision
        self._lock, self._latest = threading.Lock(), None

    def observe(self, sample_id, observed_at_ns, joints):
        state = ArmState(sample_id=sample_id, observed_at_ns=observed_at_ns, rig_revision=self.rig_revision,
                         calibration_revision=self.calibration_revision, joints=joints)
        with self._lock:
            _require(self._latest is None or observed_at_ns > self._latest.observed_at_ns,
                     'replayed or reversed observation')
            self._latest = state
        return state

    def current(self, now_ns, max_age_s):
        """The latest state if it is fresh, else None. Staleness is never bridged by extrapolation."""
        with self._lock:
            state = self._latest
        if state is None or not 0 <= state.age_s(now_ns) <= max_age_s:
            return None
        return state
