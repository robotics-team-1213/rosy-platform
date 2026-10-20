"""Approved POSIX adapter facts, original evidence leases and durable replay fences."""
import asyncio
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import threading
from typing import Annotated, Literal

from pydantic import Field, model_validator

from core_common.protocol.station_charging import (
    BatteryEnergyEvidence, Contract, Identifier, Nonnegative, Number, Positive, TimedEvidence,
)

MAX_BYTES = 65536
Sequence = Annotated[int, Field(strict=True, ge=0)]


class ChargeFactProfile(Contract):
    robot_id: Identifier
    battery_id: Identifier
    source_id: Identifier
    source_epoch: Identifier
    map_id: Identifier
    map_revision: Identifier
    writer_uid: Sequence
    max_age_s: Positive
    still_s: Positive
    linear_limit_m_s: Positive
    angular_limit_rad_s: Positive


class ChargeFactFrame(TimedEvidence):
    robot_id: Identifier
    battery_id: Identifier
    boot_id: Identifier
    source_id: Identifier
    source_epoch: Identifier
    sequence: Sequence
    map_id: Identifier
    map_revision: Identifier
    odom_epoch: Identifier
    mode: Literal['IDLE', 'NAVIGATION', 'DOCKING', 'MANUAL', 'EMERGENCY']
    safety_latched: bool
    dock_state: Literal['UNDOCKED', 'DOCKING', 'DOCKED', 'CHARGING', 'UNDOCKING', 'DOCK_FAILED']
    measured_linear_m_s: Number
    measured_angular_rad_s: Number
    still_since: Nonnegative | None
    battery_energy: BatteryEnergyEvidence

    @model_validator(mode='after')
    def original_sample_order(self):
        if (self.battery_energy.battery_id != self.battery_id
                or self.battery_energy.captured_at > self.captured_at
                or self.still_since is not None and self.still_since > self.captured_at):
            raise ValueError('measurement scope/time differs')
        return self


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode('utf-8')).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _constant(_):
    raise ValueError('nonfinite JSON value')


class ChargeFactSource:
    def __init__(self, *, path, tasks, profile, clock, monotonic):
        self.path = Path(path).absolute()
        self.tasks, self.clock, self.monotonic = tasks, clock, monotonic
        self.profile = ChargeFactProfile.model_validate(profile.model_dump())
        # Changing a path or operating limit cannot reset an existing source's replay fence.
        self.key = _hash({k: getattr(self.profile, k) for k in ('robot_id', 'source_id', 'source_epoch')})
        self._lock = threading.Lock()
        self._first, self._clock_fault = True, False
        self._times = self._sequence = self._deadline = None
        self._battery_lease = None
        self._blocked = -1

    async def snapshot(self, robot_id):
        return await asyncio.to_thread(self._read, robot_id)

    def _file(self):
        if not all(hasattr(os, name) for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK')):
            raise ValueError('approved POSIX file transport required')
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        directory = os.open(self.path.parent, flags | os.O_DIRECTORY)
        try:
            parent = os.fstat(directory)
            if parent.st_uid != self.profile.writer_uid or parent.st_mode & 0o022:
                raise ValueError('unapproved measurement directory')
            descriptor = os.open(self.path.name, flags, dir_fd=directory)
            try:
                before = os.fstat(descriptor)
                if (not stat.S_ISREG(before.st_mode) or before.st_uid != self.profile.writer_uid
                        or before.st_mode & 0o022 or before.st_nlink != 1 or before.st_size > MAX_BYTES):
                    raise ValueError('unapproved measurement file')
                payload = os.read(descriptor, MAX_BYTES+1)
                after = os.fstat(descriptor)
                fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
                if len(payload) != before.st_size or any(getattr(before, k) != getattr(after, k) for k in fields):
                    raise ValueError('measurement changed during read')
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)
        return json.loads(payload.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)

    def _time(self, minimum=None):
        before = self.monotonic()
        now, after = self.clock(), self.monotonic()
        valid = all(type(v) in (float, int) and math.isfinite(v) and v >= 0 for v in (now, before, after))
        if (not valid or after < before
                or self._times is not None and (now < self._times[0] or before < self._times[1])
                or minimum is not None and now < minimum):
            self._clock_fault = True
        if self._clock_fault:
            raise ValueError('measurement clock is unverified')
        self._times = now, after
        return now, before, after

    def _checked_frame(self, payload, now, robot_id):
        frame = ChargeFactFrame.model_validate(payload, context={'now': now})
        keys = ('robot_id', 'battery_id', 'source_id', 'source_epoch', 'map_id', 'map_revision')
        if robot_id != self.profile.robot_id or any(getattr(frame, k) != getattr(self.profile, k) for k in keys):
            raise ValueError('unapproved measurement scope')
        BatteryEnergyEvidence.model_validate(frame.battery_energy.model_dump(), context={'now': now})
        expiry = min(frame.valid_until, frame.captured_at+self.profile.max_age_s,
                     frame.battery_energy.valid_until, frame.battery_energy.captured_at+self.profile.max_age_s)
        if not now < expiry:
            raise ValueError('measurement age exceeded')
        return frame, expiry

    def _read(self, robot_id):
        with self._lock:
            try:
                with closing(self.tasks._connect()) as db:
                    db.execute('''CREATE TABLE IF NOT EXISTS fleet_charge_source_watermarks (
                        source_key TEXT PRIMARY KEY, sequence INTEGER NOT NULL, frame_hash TEXT NOT NULL,
                        motion_at REAL NOT NULL, battery_at REAL NOT NULL, battery_hash TEXT NOT NULL,
                        blocked_sequence INTEGER NOT NULL, last_utc REAL NOT NULL)''')
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute('SELECT * FROM fleet_charge_source_watermarks WHERE source_key=?',
                                     (self.key,)).fetchone()
                    try:
                        _, read_started, _ = self._time(row['last_utc'] if row else None)
                        payload = self._file()
                        now, _, mono = self._time()
                        frame, expiry = self._checked_frame(payload, now, robot_id)
                        digest, battery_hash = _hash(frame.model_dump()), _hash(frame.battery_energy.model_dump())
                        if frame.sequence <= max(self._blocked, row['blocked_sequence'] if row else -1):
                            raise ValueError('measurement was retired')
                        if row:
                            old = row['sequence']
                            if (frame.sequence < old or frame.captured_at < row['motion_at']
                                    or frame.battery_energy.captured_at < row['battery_at']
                                    or frame.battery_energy.captured_at == row['battery_at']
                                        and battery_hash != row['battery_hash']):
                                raise ValueError('measurement replay or capture changed')
                            if self._first and (frame.sequence <= old or frame.captured_at <= row['motion_at']
                                                or frame.battery_energy.captured_at <= row['battery_at']):
                                raise ValueError('new process requires new original measurements')
                            if frame.sequence == old:
                                if digest != row['frame_hash'] or frame.sequence != self._sequence:
                                    raise ValueError('same measurement changed')
                            elif frame.captured_at <= row['motion_at']:
                                raise ValueError('sequence cannot manufacture motion capture')
                        battery_at = frame.battery_energy.captured_at
                        if self._battery_lease and battery_at == self._battery_lease[0]:
                            if battery_hash != self._battery_lease[1]:
                                raise ValueError('same battery capture changed')
                            battery_deadline = self._battery_lease[2]
                        else:
                            if self._battery_lease and battery_at < self._battery_lease[0]:
                                raise ValueError('original battery capture reversed')
                            battery_expiry = min(frame.battery_energy.valid_until,
                                                 battery_at+self.profile.max_age_s)
                            battery_deadline = read_started+(battery_expiry-now)
                            self._battery_lease = battery_at, battery_hash, battery_deadline
                        deadline = self._deadline if frame.sequence == self._sequence else read_started+(expiry-now)
                        deadline = min(deadline, battery_deadline)
                        if deadline is None or not mono < deadline:
                            raise ValueError('original monotonic deadline exceeded')
                        db.execute('''INSERT INTO fleet_charge_source_watermarks VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(source_key) DO UPDATE SET sequence=excluded.sequence,
                            frame_hash=excluded.frame_hash, motion_at=excluded.motion_at,
                            battery_at=excluded.battery_at, battery_hash=excluded.battery_hash,
                            blocked_sequence=excluded.blocked_sequence, last_utc=excluded.last_utc''',
                            (self.key, frame.sequence, digest, frame.captured_at, frame.battery_energy.captured_at,
                             battery_hash, max(self._blocked, row['blocked_sequence'] if row else -1), now))
                        db.commit()  # No fact may escape before its durable replay fence exists.
                        now, _, mono = self._time()
                        self._checked_frame(payload, now, robot_id)
                        if not mono < deadline:
                            raise ValueError('measurement expired before use')
                    except Exception:
                        # An invalid read retires the last accepted frame, never an untrusted incoming sequence.
                        db.rollback()
                        current = db.execute('SELECT * FROM fleet_charge_source_watermarks WHERE source_key=?',
                                             (self.key,)).fetchone()
                        if current:
                            self._blocked = max(self._blocked, current['sequence'])
                            observed = self.clock()
                            observed = observed if type(observed) in (int, float) and math.isfinite(observed) else 0.
                            db.execute('''UPDATE fleet_charge_source_watermarks SET blocked_sequence=?, last_utc=?
                                          WHERE source_key=?''',
                                       (self._blocked, max(current['last_utc'], observed), self.key))
                            db.commit()
                        raise
                self._first, self._sequence, self._deadline = False, frame.sequence, deadline
                result = frame.model_dump(exclude={'source_id', 'source_epoch', 'sequence',
                    'measured_linear_m_s', 'measured_angular_rad_s', 'still_since'})
                result['valid_until'] = min(expiry, now+(deadline-mono))
                result['safe_work_boundary'] = (not frame.safety_latched and frame.mode in ('IDLE', 'DOCKING')
                    and frame.still_since is not None and frame.captured_at-frame.still_since >= self.profile.still_s
                    and abs(frame.measured_linear_m_s) <= self.profile.linear_limit_m_s
                    and abs(frame.measured_angular_rad_s) <= self.profile.angular_limit_rad_s)
                return result
            except Exception:
                self._blocked = max(self._blocked, self._sequence if self._sequence is not None else -1)
                raise ValueError('CHARGE_SOURCE_UNAVAILABLE') from None
