"""Fleet-owned installation versions. Proposals never grant return authority (D-772)."""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from core_common.protocol.station_charging import StationPoseRecord

from .sqlite_policy import configure_connection, enable_wal


class StationStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            enable_wal(db)
            db.executescript('''
                CREATE TABLE IF NOT EXISTS station_installations (
                    station_id TEXT NOT NULL,
                    pose_revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (station_id, pose_revision)
                );
                CREATE TABLE IF NOT EXISTS station_installation_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    station_id TEXT NOT NULL,
                    pose_revision INTEGER NOT NULL,
                    event TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
            ''')
        if os.name != 'nt':
            self.path.chmod(0o600)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        return configure_connection(db)

    @contextmanager
    def _write(self):
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            yield db

    @staticmethod
    def _current(db, station_id):
        row = db.execute('''SELECT payload_json FROM station_installations
                            WHERE station_id=? ORDER BY pose_revision DESC LIMIT 1''', (station_id,)).fetchone()
        return StationPoseRecord.model_validate_json(row['payload_json']) if row else None

    @staticmethod
    def _save(db, record, *, event, reason):
        db.execute('''INSERT INTO station_installations VALUES (?, ?, ?)
                      ON CONFLICT(station_id, pose_revision) DO UPDATE SET payload_json=excluded.payload_json''',
                   (record.station_id, record.pose_revision, record.model_dump_json()))
        db.execute('''INSERT INTO station_installation_audit(station_id, pose_revision, event, reason)
                      VALUES (?, ?, ?, ?)''', (record.station_id, record.pose_revision, event, reason))

    def propose(self, record: StationPoseRecord) -> StationPoseRecord:
        record = StationPoseRecord.model_validate(record.model_dump())
        if record.status != 'CANDIDATE':
            raise ValueError('STATION_CANDIDATE_REQUIRED')
        with self._write() as db:
            current = self._current(db, record.station_id)
            revision = 1 if current is None else current.pose_revision + 1
            if current is not None and current.status != 'INVALID':
                self._save(db, current.model_copy(update={'status': 'INVALID'}),
                           event='invalidated', reason='REPLACED')
            proposed = record.model_copy(update={'pose_revision': revision})
            self._save(db, proposed, event='proposed', reason='OBSERVATION_CANDIDATE')
        return proposed

    def confirm(self, station_id: str, *, expected_revision: int) -> StationPoseRecord:
        with self._write() as db:
            current = self._current(db, station_id)
            if (current is None or current.pose_revision != expected_revision
                    or current.status != 'CANDIDATE'):
                raise ValueError('STATION_VERSION_CONFLICT')
            confirmed = StationPoseRecord.model_validate(current.model_dump() | {'status': 'VALID'})
            self._save(db, confirmed, event='confirmed', reason='APPROACH_VERIFIED')
        return confirmed

    def invalidate(self, station_id: str, *, expected_revision: int, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 128:
            raise ValueError('INVALID_REASON')
        with self._write() as db:
            current = self._current(db, station_id)
            if current is None or current.pose_revision != expected_revision:
                raise ValueError('STATION_VERSION_CONFLICT')
            if current.status != 'INVALID':
                self._save(db, current.model_copy(update={'status': 'INVALID'}), event='invalidated', reason=reason)

    def get(self, station_id: str) -> StationPoseRecord | None:
        with closing(self._connect()) as db:
            return self._current(db, station_id)

    def refresh(self, observation: StationPoseRecord, *, expected_revision: int) -> StationPoseRecord:
        """Renew evidence for the same target; never change coordinates under one version."""
        with self._write() as db:
            current = self._current(db, observation.station_id)
            if (current is None or current.status != 'VALID' or current.pose_revision != expected_revision
                    or observation.captured_at <= current.captured_at
                    or any(getattr(current, key) != getattr(observation, key) for key in (
                        'source_id', 'source_epoch', 'calibration_revision', 'map_id', 'map_revision'))):
                raise ValueError('STATION_VERSION_CONFLICT')
            refreshed = StationPoseRecord.model_validate(current.model_dump() | {
                'captured_at': observation.captured_at, 'valid_until': observation.valid_until,
                'uncertainty_m': observation.uncertainty_m, 'uncertainty_rad': observation.uncertainty_rad})
            self._save(db, refreshed, event='observed', reason='STABLE_TARGET')
        return refreshed

    def list(self) -> list[StationPoseRecord]:
        with closing(self._connect()) as db:
            ids = [row[0] for row in db.execute('SELECT DISTINCT station_id FROM station_installations ORDER BY station_id')]
            return [self._current(db, station_id) for station_id in ids]

    def history(self, station_id: str) -> list[StationPoseRecord]:
        with closing(self._connect()) as db:
            rows = db.execute('''SELECT payload_json FROM station_installations
                                 WHERE station_id=? ORDER BY pose_revision''', (station_id,)).fetchall()
        return [StationPoseRecord.model_validate_json(row['payload_json']) for row in rows]

    def audit(self, station_id: str) -> list[dict]:
        with closing(self._connect()) as db:
            return [dict(row) for row in db.execute('''SELECT pose_revision, event, reason
                       FROM station_installation_audit WHERE station_id=? ORDER BY audit_id''', (station_id,))]
