"""Private SIM execution facts, not an Action grant, D-18 receipt or replay API.

Composition supplies observe as the existing ROS transport event sink. A command
intent is committed before transport; only accepted server callbacks establish a
driver goal UUID. Reopening permits inspection, never automatic resubmission.
"""
from collections.abc import Mapping
from contextlib import closing
from dataclasses import fields, is_dataclass, asdict
import json
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
            if db.execute('PRAGMA user_version').fetchone()[0] not in {0, 1}:
                raise RuntimeError('unsupported policy execution journal version')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS policy_commands (
                    command_id TEXT PRIMARY KEY, intent TEXT NOT NULL,
                    intent_key TEXT NOT NULL UNIQUE, driver_goal_id TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS policy_goal_events (
                    command_id TEXT NOT NULL REFERENCES policy_commands(command_id),
                    sequence INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(command_id,sequence));
            ''')
            if {row[1] for row in db.execute('PRAGMA table_info(policy_commands)')} != {
                    'command_id', 'intent', 'intent_key', 'driver_goal_id'}:
                raise RuntimeError('unsupported policy command table')
            self._schema(db)
            db.execute('PRAGMA user_version=1')

    @staticmethod
    def _schema(db):
        # Same column names are insufficient: removing UNIQUE would permit
        # replay after restart. Verify the actual SQLite constraints as well.
        expected_columns = {
            'policy_commands': [('command_id', 'TEXT', 0, 1), ('intent', 'TEXT', 1, 0),
                                ('intent_key', 'TEXT', 1, 0), ('driver_goal_id', 'TEXT', 0, 0)],
            'policy_goal_events': [('command_id', 'TEXT', 1, 1), ('sequence', 'INTEGER', 1, 2),
                                   ('payload', 'TEXT', 1, 0)],
        }
        expected_indexes = {'policy_commands': {('command_id',), ('intent_key',), ('driver_goal_id',)},
                            'policy_goal_events': {('command_id', 'sequence')}}
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

    def _connect(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def prepare(self, lease, candidate, command):
        # This records the already validated session's inputs. It creates no
        # authority and does not claim the lease's Action exists in ActionStore.
        if ((candidate.lease_id, candidate.episode_id, candidate.policy_revision) !=
                (lease.lease_id, lease.episode_id, lease.policy_revision)
                or command.session_id != lease.owner_session_id
                or command.source_state_sequence != candidate.sequence
                or tuple(command.positions[name] for name in command.joint_names) != candidate.positions):
            raise ValueError('policy execution intent scope differs')
        payload = _json(dict(lease=lease, candidate=candidate, command=command,
                             policy_revision=lease.policy_revision))
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
