"""Bounded, explicit-path motor evidence files; no serial or CORE service dependency."""
import json
import math
import os
from pathlib import Path
import stat
import time
from uuid import uuid4

from .protocol.motor_health import MotorHealthResponse, MotorHealthSample

MAX_BYTES = 256_000
REASONS = {'hardware error', 'temperature limit', 'voltage limit', 'control failure',
           'session ended', 'operator interruption', 'following error', 'overload risk',
           'stale telemetry', 'alignment deadline', 'cleanup unconfirmed'}


def write_motor_health_snapshot(path, row):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path or path.is_symlink():
        raise ValueError('motor health requires an explicit canonical file')
    encoded = json.dumps(row, allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_BYTES:
        raise ValueError('motor health file exceeds size budget')
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as handle:
            handle.write(encoded)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_motor_health_snapshot(path, owner, *, now=None):
    """Return the sanitized DTO and ORIGINAL source capture, never file mtime."""
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path or path.is_symlink():
        raise ValueError('motor health requires an explicit canonical file')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError('invalid motor health file')
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('oversize motor health file')
    row = json.loads(raw)
    now = time.time() if now is None else now
    def age(stamp):
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or not 0 < stamp <= now + .25:
            raise ValueError('invalid motor health source clock')
        return max(0., now - stamp)
    captured = row['observed_at']
    source_age = age(captured)
    if row['owner_id'] != owner or row['schema_version'] != 'rosy.motor-health.v1':
        raise ValueError('motor health owner mismatch')
    motors, seen = [], set()
    for value in row['motors']:
        value = dict(value)
        sample_age = age(value.pop('observed_at'))
        if sample_age + 1e-6 < source_age:
            raise ValueError('motor sample newer than source')
        motor = MotorHealthSample(**value, sample_age_s=sample_age)
        key = motor.group, motor.id
        if key in seen:
            raise ValueError('duplicate motor identity')
        seen.add(key)
        motors.append(motor)
    status, expected, reasons = row['status'], row['expected_motor_count'], row['stop_reasons']
    if (status not in ('active', 'fault', 'ended') or type(expected) is not int or not 0 <= expected <= 128
            or len(motors) > expected or not isinstance(reasons, list)
            or any(reason not in REASONS for reason in reasons)):
        raise ValueError('invalid motor health lifecycle or coverage')
    evidence = ('disconnected' if status in ('fault', 'ended') else
                'unavailable' if not motors or len(motors) != expected else
                'delayed' if max(m.sample_age_s for m in motors) > 2 else 'fresh')
    event = row.get('terminal_at', captured) if status in ('fault', 'ended') else captured
    age(event)
    if event < captured:
        raise ValueError('terminal event cannot predate its last measurement')
    return MotorHealthResponse(evidence=evidence, status=status, owner_id=owner, session_id=row['session_id'],
                              sample_age_s=source_age, motors=motors, stop_reasons=reasons), event
