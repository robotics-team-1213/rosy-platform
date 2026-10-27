"""Durable operator notes and source-bound observations; no command authority."""
from contextlib import closing
import json
import re
import sqlite3
import time

from rosy.contracts.motion.characteristics import characteristics_digest, parse_json, validate_characteristics

from .device_profiles import DeviceProfileStore, _text
from .device_load_report import validate_report, analysis_view


def _note(value, field, *, required=False):
    if not isinstance(value, str):
        raise ValueError('expected note text')
    _text(value.replace('\n', ' ').replace('\r', ' ').replace('\t', ' '), field, 2000, required=required)
    return value


def _binding(value):
    if not isinstance(value, dict) or set(value) != {'owner_id', 'sha256'}:
        raise ValueError('expected current registered arm binding')
    _text(value['owner_id'], 'source owner', 128, required=True)
    if not isinstance(value['sha256'], str) or re.fullmatch('[0-9a-f]{64}', value['sha256']) is None:
        raise ValueError('invalid source binding digest')
    return dict(value)


class DeviceCareStore(DeviceProfileStore):
    def __init__(self, path):
        super().__init__(path)
        with closing(self._connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS fleet_device_care (
                    device_id TEXT PRIMARY KEY, source_kind TEXT, source_id TEXT, source_binding_json TEXT,
                    caution TEXT NOT NULL, characteristics_json TEXT, report_json TEXT,
                    received_at REAL, updated_by TEXT NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(source_kind, source_id));
                CREATE TABLE IF NOT EXISTS fleet_device_care_events (
                    id INTEGER PRIMARY KEY, device_id TEXT NOT NULL, kind TEXT NOT NULL,
                    text TEXT NOT NULL, actor TEXT NOT NULL, created_at REAL NOT NULL);
            ''')
            db.execute('BEGIN IMMEDIATE')
            if 'source_binding_json' not in {row['name'] for row in db.execute('PRAGMA table_info(fleet_device_care)')}:
                # Legacy links remain unverified until an operator confirms the current registration.
                db.execute('ALTER TABLE fleet_device_care ADD COLUMN source_binding_json TEXT')

    def _require_profile(self, device_id):
        if self.get_profile(device_id) is None:
            raise ValueError('save the descriptive device profile first')

    def get(self, device_id, *, include_document=True, now=None):
        self._require_profile(device_id)
        with closing(self._connect()) as db:
            row = db.execute('SELECT * FROM fleet_device_care WHERE device_id=?', (device_id,)).fetchone()
            events = db.execute('SELECT kind,text,actor,created_at FROM fleet_device_care_events '
                                'WHERE device_id=? ORDER BY id DESC LIMIT 100', (device_id,)).fetchall()
        result = dict(row) if row else {
            'device_id': device_id, 'source_kind': None, 'source_id': None,
            'caution': '', 'updated_by': None, 'updated_at': None}
        document = json.loads(result.pop('characteristics_json', None) or 'null')
        result['source_binding'] = json.loads(result.pop('source_binding_json', None) or 'null')
        report = json.loads(result.pop('report_json', None) or 'null')
        result['characteristics_summary'] = None if document is None else {
            'revision': document['revision'], 'status': document['status'],
            'sha256': characteristics_digest(document), 'measured_at': document['measured_at'],
            'joint_count': len(document['joints']), 'envelope_count': len(document['envelopes'])}
        if include_document:
            result['characteristics'] = document
        result['latest_analysis'] = analysis_view(report, document, now=time.time() if now is None else now)
        result['events'] = [dict(event) for event in events]
        result['motion_admitted'] = result['automatic_recovery_enabled'] = False
        return result

    def by_source(self, kind, source_id):
        with closing(self._connect()) as db:
            row = db.execute('SELECT device_id FROM fleet_device_care WHERE source_kind=? AND source_id=?',
                             (kind, source_id)).fetchone()
        if row is None:
            return None
        care = self.get(row['device_id'], include_document=False)
        if (care['source_kind'], care['source_id']) != (kind, source_id):
            return None
        return {**self.get_profile(row['device_id']), **care}

    def put(self, device_id, body, *, actor, source_binding=None):
        self._require_profile(device_id)
        if not isinstance(body, dict) or set(body) != {'source_kind', 'source_id', 'caution', 'characteristics'}:
            raise ValueError('expected source_kind, source_id, caution and characteristics')
        kind, source = body['source_kind'], body['source_id']
        if kind is None and source is None:
            pass
        elif kind in ('robot', 'arm') and isinstance(source, str):
            if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', source) is None:
                raise ValueError('invalid source identifier')
        else:
            raise ValueError('expected a registered robot or arm source, or null pair')
        bound = _binding(source_binding) if kind == 'arm' else None
        if kind != 'arm' and source_binding is not None:
            raise ValueError('only arm sources have a registered arm binding')
        caution = _note(body['caution'], 'caution')
        _text(actor, 'actor', 96, required=True)
        document = body['characteristics']
        if isinstance(document, str):
            document = parse_json(document)
        if document is not None:
            document = validate_characteristics(document)
            if (document['binding']['device_id'] != device_id or kind != 'arm'
                    or document['binding']['owner_id'] != bound['owner_id']):
                raise ValueError('characteristics require the same device_id and an arm source')
        encoded = json.dumps(document, sort_keys=True) if document is not None else None
        binding_json = json.dumps(bound, sort_keys=True) if bound is not None else None
        try:
            with closing(self._connect()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT * FROM fleet_device_care WHERE device_id=?', (device_id,)).fetchone()
                changed = old is None or (old['source_kind'], old['source_id'], old['characteristics_json'],
                                          old['source_binding_json']) != (kind, source, encoded, binding_json)
                db.execute('''INSERT INTO fleet_device_care
                    (device_id,source_kind,source_id,caution,characteristics_json,source_binding_json,updated_by,updated_at)
                    VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET
                    source_kind=excluded.source_kind,source_id=excluded.source_id,caution=excluded.caution,
                    characteristics_json=excluded.characteristics_json,source_binding_json=excluded.source_binding_json,
                    updated_by=excluded.updated_by,updated_at=excluded.updated_at''',
                           (device_id, kind, source, caution, encoded, binding_json, actor, time.time()))
                if changed:
                    db.execute('UPDATE fleet_device_care SET report_json=NULL,received_at=NULL WHERE device_id=?',
                               (device_id,))
        except sqlite3.IntegrityError:
            raise ValueError('source is already linked to another profile') from None
        return self.get(device_id)

    @staticmethod
    def _event(db, device_id, kind, text, actor, stamp):
        db.execute('INSERT INTO fleet_device_care_events(device_id,kind,text,actor,created_at) VALUES(?,?,?,?,?)',
                   (device_id, kind, text, actor, stamp))
        db.execute('DELETE FROM fleet_device_care_events WHERE device_id=? AND id NOT IN '
                   '(SELECT id FROM fleet_device_care_events WHERE device_id=? ORDER BY id DESC LIMIT 100)',
                   (device_id, device_id))

    def add_event(self, device_id, body, *, actor):
        self._require_profile(device_id)
        if not isinstance(body, dict) or set(body) != {'kind', 'text'} or body['kind'] not in (
                'fault', 'caution', 'maintenance'):
            raise ValueError('expected fault, caution or maintenance and text')
        _note(body['text'], 'text', required=True)
        _text(actor, 'actor', 96, required=True)
        with closing(self._connect()) as db, db:
            self._event(db, device_id, body['kind'], body['text'], actor, time.time())
        return self.get(device_id)

    def ingest(self, device_id, source_id, report, *, source_binding, now=None):
        now = time.time() if now is None else now
        expected = _binding(source_binding)
        with closing(self._connect()) as db, db:
            # Serialize replacement and ingestion so a rebind cannot admit an old source report.
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM fleet_device_care WHERE device_id=?', (device_id,)).fetchone()
            if row is None or row['source_kind'] != 'arm' or row['source_id'] != source_id:
                raise ValueError('report source does not match this profile')
            if json.loads(row['source_binding_json'] or 'null') != expected:
                raise ValueError('registered source configuration changed; confirm the profile link')
            document = json.loads(row['characteristics_json'] or 'null')
            if document is None or document['binding']['owner_id'] != expected['owner_id']:
                raise ValueError('report owner does not match current source registration')
            report = validate_report(report, document, now=now)
            previous = json.loads(row['report_json'] or 'null')
            if report == previous:
                return {'accepted': True, 'duplicate': True}
            if previous and report['assessed_at'] <= previous['assessed_at']:
                raise ValueError('report time must advance')
            attention = report['status'] == 'hold_for_owner_review'
            if attention and (not previous or previous['reasons'] != report['reasons']):
                self._event(db, device_id, 'analysis', ', '.join(report['reasons']), source_id, now)
            db.execute('UPDATE fleet_device_care SET report_json=?,received_at=? WHERE device_id=?',
                       (json.dumps(report, sort_keys=True), now, device_id))
        return {'accepted': True, 'duplicate': False}
