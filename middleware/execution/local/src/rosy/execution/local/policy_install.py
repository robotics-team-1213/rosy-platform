"""Pinned installation compatibility; does not authorize or dispatch policy actions."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re

from rosy.contracts.learning import validate_policy


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


@dataclass(frozen=True, init=False)
class InstallBinding:
    """Trusted installation input, never derived from the candidate under inspection."""
    policy_revision: str
    profile: str
    robot_type: str
    environment: str
    device_profile_revision: str
    camera_profile_revision: str | None
    normalization_sha256: str
    action_names: tuple
    action_limits: tuple
    _owner: bytes
    _cameras: bytes
    _timing: bytes

    def __init__(self, *, policy_revision, profile, robot_type, environment,
                 device_profile_revision, camera_profile_revision, owner, cameras,
                 normalization_sha256, action_names, action_limits, timing):
        values = locals().copy()
        for name in ('policy_revision', 'normalization_sha256'):
            if not isinstance(values[name], str) or not re.fullmatch('[0-9a-f]{64}', values[name]):
                raise ValueError('installation SHA-256 required')
        for name in ('profile', 'robot_type', 'device_profile_revision'):
            if not isinstance(values[name], str) or not values[name] or values[name] != values[name].strip():
                raise ValueError('explicit installed identifier required')
        if environment not in ('sim', 'real'):
            raise ValueError('explicit installation environment required')
        if camera_profile_revision is not None and (not isinstance(camera_profile_revision, str)
                or not camera_profile_revision or camera_profile_revision != camera_profile_revision.strip()):
            raise ValueError('installed camera profile must be an immutable identifier or unknown')
        names = tuple(action_names)
        if not names or len(set(names)) != len(names) or any(not isinstance(n, str) or not n for n in names):
            raise ValueError('explicit installed action order required')
        limits = tuple(tuple(limit) for limit in action_limits)
        if len(limits) != len(names) or any(len(pair) != 2 or any(
                type(v) not in (int, float) or not math.isfinite(v) for v in pair)
                or pair[0] >= pair[1] for pair in limits):
            raise ValueError('finite installed action envelope required')
        if (not isinstance(timing, dict) or set(timing) != {'period_ns', 'max_observation_age_ns', 'max_action_age_ns'}
                or any(type(v) is not int or v <= 0 for v in timing.values())):
            raise ValueError('installed positive timing budgets required')
        for name in ('policy_revision', 'profile', 'robot_type', 'environment', 'device_profile_revision',
                     'camera_profile_revision', 'normalization_sha256'):
            object.__setattr__(self, name, values[name])
        object.__setattr__(self, 'action_names', names)
        object.__setattr__(self, 'action_limits', limits)
        for name, value in (('_owner', owner), ('_cameras', cameras), ('_timing', timing)):
            object.__setattr__(self, name, _encoded(value))

    @property
    def owner(self):
        return json.loads(self._owner)

    @property
    def cameras(self):
        return json.loads(self._cameras)

    @property
    def timing(self):
        return json.loads(self._timing)


def _checked(root, binding, expected_bytes=None):
    file = root / 'policy-artifact.json'
    payload = file.read_bytes()
    if expected_bytes is not None and payload != expected_bytes:
        raise ValueError('installed policy manifest changed')
    doc = validate_policy(json.loads(payload), root=root)
    for name in ('profile', 'robot_type', 'environment', 'device_profile_revision', 'camera_profile_revision'):
        if doc[name] != getattr(binding, name):
            raise ValueError(f'installed {name} binding differs')
    if (doc['revision'] != binding.policy_revision or _encoded(doc['owner']) != binding._owner
            or _encoded(doc['cameras']) != binding._cameras
            or doc['normalization']['sha256'] != binding.normalization_sha256
            or tuple(doc['action']['names']) != binding.action_names):
        raise ValueError('installed policy/owner/camera/normalization/action binding differs')
    if any(lower < admitted[0] or upper > admitted[1]
           for (lower, upper), admitted in zip(doc['action']['limits'], binding.action_limits)):
        raise ValueError('policy action envelope exceeds installed limits')
    if doc['timing']['period_ns'] != binding.timing['period_ns']:
        raise ValueError('policy period differs from installed schedule')
    if any(doc['timing'][name] > maximum for name, maximum in binding.timing.items()):
        raise ValueError('policy timing exceeds installed budget')
    if file.read_bytes() != payload:
        raise ValueError('policy manifest changed during verification')
    return doc, payload


@dataclass(frozen=True)
class InstalledPolicy:
    """File compatibility evidence only; recheck before an authorized owner consumes it."""
    root: Path
    binding: InstallBinding
    _manifest: bytes

    def recheck(self):
        return _checked(self.root, self.binding, self._manifest)[0]


def load_policy(root, binding):
    if not isinstance(binding, InstallBinding):
        raise ValueError('explicit trusted installation binding required')
    root = Path(root).resolve()
    _, payload = _checked(root, binding)
    return InstalledPolicy(root, binding, payload)
