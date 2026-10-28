"""Bounded same-user, same-host latest observations; no discovery or ROS transport.

Channel names are opaque registration keys. Files are not recording queues.
"""
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import time

MAX_PAYLOAD = 1024 * 1024
MAX_HEADER = 16384


def interrupt_on_termination(signum, frame):
    """Let native service owners release devices and write terminal health on SIGTERM."""
    raise KeyboardInterrupt


class SnapshotChannel:
    def __init__(self, channel, *, root=None):
        if not isinstance(channel, str) or not channel or len(channel) > 512:
            raise ValueError('explicit observation channel required')
        self.channel = channel
        root = Path(root or os.environ.get('ROSY_OBSERVATION_DIR') or
                    Path.home() / '.local/state/rosy/observations')
        self.path = root / (sha256(channel.encode()).hexdigest() + '.snapshot')

    def write(self, kind, payload, *, captured_at, quality=None):
        if (kind not in ('jpeg', 'joints') or not isinstance(payload, bytes)
                or not 0 < len(payload) <= MAX_PAYLOAD
                or type(captured_at) not in (int, float)
                or not math.isfinite(captured_at) or captured_at <= 0):
            raise ValueError('invalid native observation')
        header = json.dumps(dict(schema='rosy.local-observation.v1', channel=self.channel,
                                 kind=kind, captured_at=captured_at, monotonic=time.monotonic(),
                                 quality=quality), allow_nan=False).encode()
        if len(header) > MAX_HEADER:
            raise ValueError('observation metadata too large')
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as output:
                temporary = Path(output.name)
                output.write(struct.pack('!I', len(header)) + header + payload)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def read(self, *, wall=None, monotonic=None):
        try:
            with self.path.open('rb') as source:
                size = struct.unpack('!I', source.read(4))[0]
                if not 0 < size <= MAX_HEADER:
                    return None
                header = json.loads(source.read(size))
                payload = source.read(MAX_PAYLOAD + 1)
            if (header['schema'] != 'rosy.local-observation.v1'
                    or header['channel'] != self.channel or header['kind'] not in ('jpeg', 'joints')
                    or not 0 < len(payload) <= MAX_PAYLOAD):
                return None
            stamp, receipt = header['captured_at'], header['monotonic']
            if (type(stamp) not in (int, float) or type(receipt) not in (int, float)
                    or not math.isfinite(stamp) or not math.isfinite(receipt)
                    or not -.25 <= (time.time() if wall is None else wall) - stamp <= 2
                    or not 0 <= (time.monotonic() if monotonic is None else monotonic) - receipt <= 2):
                return None
            return dict(header, payload=payload)
        except (OSError, ValueError, TypeError, KeyError, struct.error, RecursionError):
            return None
