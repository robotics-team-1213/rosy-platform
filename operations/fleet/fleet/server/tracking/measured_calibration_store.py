"""D-775 purpose-specific preview selection in the existing Fleet calibration DB."""
from contextlib import closing
from copy import deepcopy
import json
import logging
import math
from pathlib import Path
import sqlite3
import threading
import uuid

from core_common.protocol.measured_calibration import bundle_digest, validate_bundle
from .sqlite_policy import configure_connection, enable_wal

_LOG = logging.getLogger(__name__)


class CalibrationChanged(ValueError):
    pass


def validate_limits(limits, bundle):
    if (not isinstance(limits, dict) or set(limits) != {'p95_m', 'max_m'}
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 1e6
                   for v in limits.values()) or limits['p95_m'] > limits['max_m']):
        raise ValueError('explicit positive p95/max survey limits required')
    if any(bundle.floor['validation'][key] > limits[key] for key in limits):
        raise ValueError('independent floor errors exceed approval limits')
    return dict(limits)


class MeasuredCalibrationStore:
    def __init__(self, path: Path | str | None):
        self.path = Path(path) if path is not None else None
        self._records, self._audit = {}, []
        self._lock = threading.RLock()
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as db:
                enable_wal(db)
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS preview_calibrations (
                        source_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS preview_calibration_audit (
                        audit_id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL,
                        source_id TEXT NOT NULL, payload_json TEXT NOT NULL,
                        principal_id TEXT NOT NULL, at REAL NOT NULL);
                ''')

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5.)
        db.row_factory = sqlite3.Row
        return configure_connection(db)

    @staticmethod
    def _decode(payload):
        record = json.loads(payload)
        bundle = validate_bundle(record['bundle'])
        validate_limits(record['limits'], bundle)
        if (bundle.evidence_kind != 'measured' or record['source_id'] != bundle.source_id
                or record['map_id'] != bundle.map_id or record['use'] != 'preview-only'
                or record['purpose'] != 'preview' or record['kind'] != 'measured'
                or not isinstance(record['approved_by'], str) or not record['approved_by']
                or not isinstance(record['calibration_revision'], str)
                or not record['calibration_revision'].startswith('measured-')
                or type(record['approved_at']) not in (float, int)
                or not math.isfinite(record['approved_at']) or record['approved_at'] <= 0):
            raise ValueError('unusable stored preview approval')
        if record.get('record_digest') != bundle_digest(record):
            # record_digest is excluded by the caller when computing its digest below.
            raw = dict(record)
            supplied = raw.pop('record_digest', None)
            if supplied != bundle_digest(raw):
                raise ValueError('stored approval digest mismatch')
        return record

    def get(self, source_id):
        with self._lock:
            if self.path is None:
                return deepcopy(self._records.get(source_id))
            with closing(self._connect()) as db:
                row = db.execute('SELECT payload_json FROM preview_calibrations WHERE source_id=?',
                                  (source_id,)).fetchone()
            try:
                return self._decode(row['payload_json']) if row else None
            except (ValueError, KeyError, TypeError):
                _LOG.warning('unusable measured preview approval for source %s', source_id)
                return None

    def all(self):
        if self.path is None:
            names = sorted(self._records)
        else:
            with closing(self._connect()) as db:
                names = [r[0] for r in db.execute('SELECT source_id FROM preview_calibrations ORDER BY source_id')]
        return [row for name in names if (row := self.get(name)) is not None]

    def approve(self, raw, *, expected_revision, approved_by, approved_at, limits):
        bundle = validate_bundle(raw)
        limits = validate_limits(limits, bundle)
        if bundle.evidence_kind != 'measured':
            raise ValueError('synthetic evidence cannot approve a measured profile')
        if (not isinstance(approved_by, str) or not 1 <= len(approved_by) <= 96
                or type(approved_at) not in (float, int) or not math.isfinite(approved_at) or approved_at <= 0):
            raise ValueError('named approver and finite approval time required')
        record = {'source_id': bundle.source_id, 'map_id': bundle.map_id,
                  'calibration_revision': 'measured-'+uuid.uuid4().hex, 'purpose': 'preview',
                  'kind': 'measured', 'use': 'preview-only', 'persistent': self.path is not None,
                  'bundle': bundle.model_dump(mode='json', by_alias=True), 'limits': limits,
                  'approved_by': approved_by, 'approved_at': approved_at}
        record['record_digest'] = bundle_digest(record)
        self._change(bundle.source_id, expected_revision, record, approved_by, approved_at)
        return deepcopy(record)

    def revoke(self, source_id, *, expected_revision, principal_id, at):
        if (not isinstance(principal_id, str) or not principal_id
                or type(at) not in (int, float) or not math.isfinite(at) or at <= 0):
            raise ValueError('named principal and finite revocation time required')
        removed = self._change(source_id, expected_revision, None, principal_id, at)
        return {'source_id': source_id, 'removed': removed, 'purpose': 'preview'}

    def _change(self, source_id, expected_revision, record, principal, at):
        if expected_revision is not None and (not isinstance(expected_revision, str) or not expected_revision):
            raise ValueError('explicit expected revision required')
        with self._lock:
            if self.path is None:
                current = self._records.get(source_id)
                self._compare(current, expected_revision)
                event = self._event(source_id, current, record, principal, at)
                if record is not None:
                    self._records[source_id] = deepcopy(record)
                else:
                    self._records.pop(source_id, None)
                if event:
                    self._audit.append(event)
            else:
                with closing(self._connect()) as db, db:
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute('SELECT payload_json FROM preview_calibrations WHERE source_id=?',
                                      (source_id,)).fetchone()
                    current = self._decode(row['payload_json']) if row else None
                    self._compare(current, expected_revision)
                    event = self._event(source_id, current, record, principal, at)
                    if record is not None:
                        db.execute('INSERT INTO preview_calibrations VALUES (?,?) '
                                   'ON CONFLICT(source_id) DO UPDATE SET payload_json=excluded.payload_json',
                                   (source_id, json.dumps(record, allow_nan=False)))
                    else:
                        db.execute('DELETE FROM preview_calibrations WHERE source_id=?', (source_id,))
                    if event:
                        db.execute('INSERT INTO preview_calibration_audit '
                                   '(event,source_id,payload_json,principal_id,at) VALUES (?,?,?,?,?)',
                                   (event['event'], source_id, json.dumps(event['record'], allow_nan=False), principal, at))
            return current is not None

    @staticmethod
    def _compare(current, expected):
        if (current['calibration_revision'] if current else None) != expected:
            raise CalibrationChanged('preview calibration changed; reload its revision')

    @staticmethod
    def _event(source, current, record, principal, at):
        if record is None and current is None:
            return None
        return {'event': 'preview.approved' if record else 'preview.revoked', 'source_id': source,
                'record': deepcopy(record or current), 'principal_id': principal, 'at': at}

    def audit_events(self):
        if self.path is None:
            return deepcopy(self._audit)
        with closing(self._connect()) as db:
            rows = db.execute('SELECT * FROM preview_calibration_audit ORDER BY audit_id').fetchall()
        return [{'event': r['event'], 'source_id': r['source_id'], 'record': json.loads(r['payload_json']),
                 'principal_id': r['principal_id'], 'at': r['at']} for r in rows]
