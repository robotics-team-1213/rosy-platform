"""Private SIM execution facts, not an Action grant, D-18 receipt or replay API.

Composition supplies observe as the existing ROS transport event sink. A command
intent is committed before transport; only accepted server callbacks establish a
driver goal UUID. Reopening permits inspection, never automatic resubmission.
"""
from collections.abc import Mapping
from contextlib import closing
from dataclasses import fields, is_dataclass, asdict
import json
import hashlib
from pathlib import Path
import sqlite3

from omx_adapter.ros_goal_contract import RosGoalEvent


def _plain(value):
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _json(value):
    return json.dumps(_plain(value), sort_keys=True, separators=(',', ':'), allow_nan=False)


class PolicyExecutionJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            if db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower() != 'wal':
                raise RuntimeError('policy execution journal requires WAL')
            if db.execute('PRAGMA user_version').fetchone()[0] not in {0, 1, 2}:
                raise RuntimeError('unsupported policy execution journal version')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS policy_commands (
                    command_id TEXT PRIMARY KEY, intent TEXT NOT NULL,
                    intent_key TEXT NOT NULL UNIQUE, driver_goal_id TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS policy_goal_events (
                    command_id TEXT NOT NULL REFERENCES policy_commands(command_id),
                    sequence INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(command_id,sequence));
                CREATE TABLE IF NOT EXISTS policy_sources (
                    revision TEXT PRIMARY KEY, header TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS policy_source_files (
                    revision TEXT NOT NULL REFERENCES policy_sources(revision),
                    path TEXT NOT NULL, payload BLOB NOT NULL, PRIMARY KEY(revision,path));
            ''')
            if {row[1] for row in db.execute('PRAGMA table_info(policy_commands)')} != {
                    'command_id', 'intent', 'intent_key', 'driver_goal_id'}:
                raise RuntimeError('unsupported policy command table')
            self._schema(db)
            db.execute('PRAGMA user_version=2')

    @staticmethod
    def _schema(db):
        # Same column names are insufficient: removing UNIQUE would permit
        # replay after restart. Verify the actual SQLite constraints as well.
        expected_columns = {
            'policy_commands': [('command_id', 'TEXT', 0, 1), ('intent', 'TEXT', 1, 0),
                                ('intent_key', 'TEXT', 1, 0), ('driver_goal_id', 'TEXT', 0, 0)],
            'policy_goal_events': [('command_id', 'TEXT', 1, 1), ('sequence', 'INTEGER', 1, 2),
                                   ('payload', 'TEXT', 1, 0)],
            'policy_sources': [('revision', 'TEXT', 0, 1), ('header', 'TEXT', 1, 0)],
            'policy_source_files': [('revision', 'TEXT', 1, 1), ('path', 'TEXT', 1, 2),
                                    ('payload', 'BLOB', 1, 0)],
        }
        expected_indexes = {'policy_commands': {('command_id',), ('intent_key',), ('driver_goal_id',)},
                            'policy_goal_events': {('command_id', 'sequence')},
                            'policy_sources': {('revision',)},
                            'policy_source_files': {('revision', 'path')}}
        for table, expected in expected_columns.items():
            columns = list(db.execute('PRAGMA table_info(' + table + ')'))
            if [(row[1], row[2], row[3], row[5]) for row in columns] != expected:
                raise RuntimeError('unsupported policy journal columns or primary key')
            indexes = list(db.execute('PRAGMA index_list(' + table + ')'))
            actual = set()
            for row in indexes:
                if row[2] != 1 or row[4] != 0:
                    raise RuntimeError('unsupported policy journal index')
                name = row[1].replace('"', '""')
                actual.add(tuple(item[2] for item in db.execute('PRAGMA index_info("' + name + '")')))
            if actual != expected_indexes[table] or len(indexes) != len(actual):
                raise RuntimeError('missing or unsupported policy journal unique constraint')
        if list(db.execute('PRAGMA foreign_key_list(policy_commands)')):
            raise RuntimeError('unsupported policy command foreign key')
        foreign = list(db.execute('PRAGMA foreign_key_list(policy_goal_events)'))
        if len(foreign) != 1 or foreign[0][2:] != (
                'policy_commands', 'command_id', 'command_id', 'NO ACTION', 'NO ACTION', 'NONE'):
            raise RuntimeError('missing or unsupported policy event foreign key')
        if list(db.execute('PRAGMA foreign_key_list(policy_sources)')):
            raise RuntimeError('unsupported policy source foreign key')
        foreign = list(db.execute('PRAGMA foreign_key_list(policy_source_files)'))
        if len(foreign) != 1 or foreign[0][2:] != (
                'policy_sources', 'revision', 'revision', 'NO ACTION', 'NO ACTION', 'NONE'):
            raise RuntimeError('missing or unsupported policy source file foreign key')

    def _connect(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def prepare(self, lease, candidate, command, *, source_revision=None):
        # This records the already validated session's inputs. It creates no
        # authority and does not claim the lease's Action exists in ActionStore.
        if ((candidate.lease_id, candidate.episode_id, candidate.policy_revision) !=
                (lease.lease_id, lease.episode_id, lease.policy_revision)
                or command.session_id != lease.owner_session_id
                or command.source_state_sequence != candidate.sequence
                or tuple(command.positions[name] for name in command.joint_names) != candidate.positions):
            raise ValueError('policy execution intent scope differs')
        intent = dict(lease=lease, candidate=candidate, command=command, policy_revision=lease.policy_revision)
        if source_revision is not None:
            with closing(self._connect()) as db:
                header = self._source_header(db, source_revision)
                if header['policy_revision'] != lease.policy_revision:
                    raise ValueError('source snapshot differs from policy lease')
            intent['source_revision'] = source_revision
        payload = _json(intent)
        key = _json(dict(identity=lease.identity, episode_id=lease.episode_id,
                         policy_revision=lease.policy_revision, sequence=candidate.sequence))
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('INSERT INTO policy_commands(command_id,intent,intent_key) VALUES (?,?,?)',
                           (command.command_id, payload, key))
                db.commit()
            except Exception:
                db.rollback()
                raise

    def observe(self, event):
        if not isinstance(event, RosGoalEvent):
            raise ValueError('original typed ROS goal event required')
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                command = db.execute('SELECT intent,driver_goal_id FROM policy_commands WHERE command_id=?',
                                     (event.command_id,)).fetchone()
                if command is None:
                    raise ValueError('callback has no committed policy command intent')
                intent, goal = json.loads(command[0]), command[1]
                if event.phase_id != intent['command']['phase_id']:
                    raise ValueError('callback phase differs from original command')
                previous = db.execute('SELECT payload FROM policy_goal_events WHERE command_id=? '
                                      'ORDER BY sequence DESC LIMIT 1', (event.command_id,)).fetchone()
                last = json.loads(previous[0]) if previous else None
                if event.sequence != (last['sequence'] + 1 if last else 1):
                    raise ValueError('callback sequence is not the next original event')
                if last and (event.observed_at_monotonic_s < last['observed_at_monotonic_s'] or
                             last['kind'] in {'TERMINAL_RESULT', 'TERMINAL_UNKNOWN',
                                              'GOAL_REJECTED', 'GOAL_ACCEPTANCE_UNKNOWN'}):
                    raise ValueError('callback follows terminal or regresses clock')
                if last is None:
                    if event.kind not in {'GOAL_ACCEPTED', 'GOAL_REJECTED', 'GOAL_ACCEPTANCE_UNKNOWN'}:
                        raise ValueError('first callback must establish acceptance outcome')
                    if event.kind == 'GOAL_ACCEPTED':
                        db.execute('UPDATE policy_commands SET driver_goal_id=? WHERE command_id=?',
                                   (event.goal_id, event.command_id))
                elif event.kind in {'GOAL_ACCEPTED', 'GOAL_REJECTED', 'GOAL_ACCEPTANCE_UNKNOWN'} or event.goal_id != goal:
                    raise ValueError('callback changes original accepted goal identity')
                db.execute('INSERT INTO policy_goal_events VALUES (?,?,?)',
                           (event.command_id, event.sequence, _json(asdict(event))))
                db.commit()
                return True  # Existing registered runtime sinks require durable True.
            except Exception:
                db.rollback()
                raise

    def read(self, command_id):
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            row = db.execute('SELECT intent,driver_goal_id FROM policy_commands WHERE command_id=?',
                             (command_id,)).fetchone()
            if row is None:
                raise KeyError(command_id)
            events = db.execute('SELECT payload FROM policy_goal_events WHERE command_id=? ORDER BY sequence',
                                (command_id,)).fetchall()
            return dict(intent=json.loads(row[0]), driver_goal_id=row[1],
                        events=[json.loads(event[0]) for event in events])

    @staticmethod
    def _source_header(db, revision):
        row = db.execute('SELECT header FROM policy_sources WHERE revision=?', (revision,)).fetchone()
        if row is None or hashlib.sha256(row[0].encode('utf-8')).hexdigest() != revision:
            raise ValueError('source snapshot missing or corrupt')
        return json.loads(row[0])

    def store_source(self, header, payloads):
        refs = header['files']
        if {ref['path'] for ref in refs} != set(payloads) or len(refs) != len(payloads):
            raise ValueError('source file coverage differs')
        for ref in refs:
            raw = payloads[ref['path']]
            if type(raw) is not bytes or len(raw) != ref['bytes'] or hashlib.sha256(raw).hexdigest() != ref['sha256']:
                raise ValueError('source payload differs')
        encoded = _json(header)
        revision = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                existing = db.execute('SELECT header FROM policy_sources WHERE revision=?', (revision,)).fetchone()
                if existing is None:
                    db.execute('INSERT INTO policy_sources VALUES (?,?)', (revision, encoded))
                    for path, raw in payloads.items():
                        db.execute('INSERT INTO policy_source_files VALUES (?,?,?)', (revision, path, raw))
                else:
                    # Existing source storage must be exact; never overwrite corruption.
                    old = dict(db.execute('SELECT path,payload FROM policy_source_files WHERE revision=?',
                                          (revision,)))
                    if existing[0] != encoded or old != payloads:
                        raise ValueError('existing source snapshot differs')
                db.commit()
            except Exception:
                db.rollback()
                raise
        return revision

    def read_source(self, revision):
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            header = self._source_header(db, revision)
            payloads = dict(db.execute('SELECT path,payload FROM policy_source_files WHERE revision=?', (revision,)))
            if {ref['path'] for ref in header['files']} != set(payloads) or len(header['files']) != len(payloads):
                raise ValueError('source snapshot file coverage differs')
            for ref in header['files']:
                raw = payloads[ref['path']]
                if len(raw) != ref['bytes'] or hashlib.sha256(raw).hexdigest() != ref['sha256']:
                    raise ValueError('stored source snapshot corrupt')
            return dict(header=header, payloads=payloads)
