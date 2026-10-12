"""Read CORE's public effective law without camera access to private CORE config."""
from datetime import datetime, timezone
import json
import math
import os
import stat

from .sensing.perception.drivable.drivable_steer import DrivableSteer

STATUS_INPUTS_PATH = '/run/rosy/status-inputs.json'
# CORE writes at 1 Hz; allow two delayed writes plus its whole-second timestamp.
MAX_AGE_S = 3.0
LAW_KEYS = ('cruise_speed', 'max_linear', 'steering_gain', 'min_confidence')


def native_law_required(environ):
    # Older camera units may lack the deployment flag, but still have this private HOME.
    return environ.get('ROSY_DEPLOYMENT') == 'device' or environ.get('HOME') == '/var/lib/rosy/camera'


def configure_drivable_law(node, readonly):
    raw = {}
    for key, default in zip(LAW_KEYS, (.08, .10, .8, .35)):
        node.declare_parameter('core_'+key, default, readonly)
        raw[key] = node.get_parameter('core_'+key).value
    node._drivable_required = node._paint_worker is not None and node._paint_worker.target == 'drivable'
    node._native_core_law = CoreLawInput() if node._drivable_required and native_law_required(os.environ) else None
    node._drivable_steer = DrivableSteer.from_config(raw) if node._drivable_required and node._native_core_law is None else None


def refresh_drivable_law(node):
    if node._native_core_law is not None:
        previous = node._drivable_steer
        node._drivable_steer = node._native_core_law.read(STATUS_INPUTS_PATH, os.environ.get('ROSY_NAMESPACE', '').strip('/'))
        if node._drivable_steer is not previous:
            node._lane_keeper.reset()


class CoreLawInput:
    def __init__(self):
        self.steer = self._key = self._written = None

    def _drop(self):
        if self.steer is not None:
            self.steer.reset()
        self.steer = self._key = None

    def read(self, path, robot_id, *, now=None, owner_uid=None):
        try:
            if owner_uid is None:
                import pwd
                owner_uid = pwd.getpwnam('rosy-core').pw_uid
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid
                        or info.st_mode & 0o022 or info.st_size > 65536):
                    raise ValueError('untrusted CORE law handover')
                data = json.loads(stream.read(65537))
            if (not isinstance(data, dict) or data.get('schema') != 2 or not robot_id
                    or data.get('robot_id') != robot_id):
                raise ValueError('CORE law identity mismatch')
            process = data.get('core_process_id')
            if type(process) is not int or process <= 0:
                raise ValueError('CORE process identity missing')
            written = datetime.fromisoformat(data['written_at'])
            age = ((now or datetime.now(timezone.utc)) - written).total_seconds()
            if written.tzinfo is None or not 0. <= age <= MAX_AGE_S:
                raise ValueError('CORE law handover stale')
            if self._written is not None and written < self._written:
                raise ValueError('CORE handover time moved backwards')
            raw = data['line_follow_steering_law']
            if (not isinstance(raw, dict) or set(raw) != set(LAW_KEYS)
                    or any(type(raw[k]) not in (int, float) or not math.isfinite(raw[k]) for k in LAW_KEYS)
                    or not 0. < raw['cruise_speed'] <= raw['max_linear'] <= .10
                    or raw['steering_gain'] <= 0. or not 0. < raw['min_confidence'] <= 1.):
                raise ValueError('invalid CORE effective steering law')
            key = (process, tuple(raw[k] for k in LAW_KEYS))
            if key != self._key:
                self._drop()
                self.steer = DrivableSteer.from_config(raw)
                self._key = key
            self._written = written
            return self.steer
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            self._drop()
            return None
