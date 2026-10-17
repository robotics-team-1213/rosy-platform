"""Durable charging sessions share ordinary work admission and its SQLite transaction."""
from __future__ import annotations

from contextlib import closing, contextmanager
import json

from core_common.protocol.station_charging import ChargeSessionStatus
from fleet.server.dispatch_admission import reserve
from fleet.server.charge_departure_store import ChargeDepartureStore


_TRANSITIONS = {
    'RETURN_RESERVED': {'RETURNING', 'HOLD', 'CANCELED'},
    'RETURNING': {'DOCKING', 'HOLD', 'CANCELED'},
    'DOCKING': {'CHARGE_CONFIRMING', 'HOLD', 'CANCELED'},
    'CHARGE_CONFIRMING': {'CHARGING', 'CHARGED_HOLD', 'HOLD', 'CANCELED'},
    'CHARGING': {'CHARGED_HOLD', 'HOLD', 'CANCELED'},
    'CHARGED_HOLD': {'CHARGING', 'DEPARTURE_CHECK', 'HOLD', 'CANCELED'},
    'DEPARTURE_CHECK': {'UNDOCKING', 'CHARGED_HOLD', 'HOLD', 'CANCELED'},
    'UNDOCKING': {'WORK_AVAILABLE', 'HOLD', 'CANCELED'},
    'HOLD': set(), 'CANCELED': set(), 'WORK_AVAILABLE': set(),
}
_IDENTITY = ('session_id', 'robot_id', 'station_id', 'battery_id', 'boot_id',
             'pose_revision', 'map_id', 'map_revision', 'attempt_id')


def retain_charge_claims_for_stop(connection):
    """A process/site stop cannot prove that a dock or its robot is physically free."""
    connection.execute("""UPDATE fleet_action_claims SET phase='UNKNOWN', lease_until=NULL
                          WHERE owner_kind='charge_session'""")


class ChargeStore(ChargeDepartureStore):
    def __init__(self, tasks):
        self.tasks = tasks
        with closing(tasks._connect()) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS fleet_charge_sessions (
                    session_id TEXT PRIMARY KEY,
                    robot_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    authority_epoch INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_charge_history (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_charge_operations (
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    correlation_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    status TEXT NOT NULL,
                    operation_id TEXT,
                    PRIMARY KEY(session_id, kind)
                );
                CREATE TABLE IF NOT EXISTS fleet_charge_returns (
                    session_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_charge_departures (
                    session_id TEXT PRIMARY KEY,
                    permit_json TEXT NOT NULL,
                    receipt_json TEXT
                );
                CREATE TABLE IF NOT EXISTS fleet_charge_departure_renewals (
                    session_id TEXT PRIMARY KEY,
                    permit_json TEXT NOT NULL
                );
            ''')

    @contextmanager
    def _write(self):
        with closing(self.tasks._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            yield db

    @staticmethod
    def _row(db, session_id):
        return db.execute('SELECT * FROM fleet_charge_sessions WHERE session_id=?', (session_id,)).fetchone()

    @staticmethod
    def _value(row):
        return ChargeSessionStatus.model_validate_json(row['payload_json']) if row else None

    @staticmethod
    def _save(db, value):
        payload = value.model_dump_json()
        db.execute('UPDATE fleet_charge_sessions SET payload_json=? WHERE session_id=?', (payload, value.session_id))
        db.execute('INSERT INTO fleet_charge_history(session_id, payload_json) VALUES (?, ?)',
                   (value.session_id, payload))

    def reserve(self, session: ChargeSessionStatus) -> ChargeSessionStatus:
        session = ChargeSessionStatus.model_validate(session.model_dump())
        if session.state != 'RETURN_RESERVED' or session.operation_id is not None:
            raise ValueError('CHARGE_RESERVATION_REQUIRED')
        with self._write() as db:
            previous = self._value(self._row(db, session.session_id))
            if previous is not None:
                if any(getattr(previous, key) != getattr(session, key) for key in _IDENTITY):
                    raise ValueError('CHARGE_IDENTITY_CONFLICT')
                return previous
            control = db.execute('SELECT * FROM fleet_dispatch_control WHERE control_id=1').fetchone()
            if not control['dispatch_enabled']:
                raise ValueError('CHARGE_DISPATCH_CLOSED')
            if not reserve(db, owner_kind='charge_session', owner_id=session.session_id,
                           generation=control['generation'], phase='CLAIMED',
                           resources=[('robot', session.robot_id), ('station', session.station_id)]):
                raise ValueError('CHARGE_RESOURCE_BUSY')
            db.execute('''INSERT INTO fleet_charge_sessions
                          (session_id, robot_id, generation, authority_epoch, payload_json) VALUES (?, ?, ?, ?, ?)''',
                       (session.session_id, session.robot_id, control['generation'], control['authority_epoch'],
                        session.model_dump_json()))
            self._save(db, session)
        return session

    def transition(self, session_id: str, *, expected_state: str, next_state: str, attempt_id: str,
                   now: float, reason: str, operation_id: str | None = None,
                   intent_kind: str | None = None, correlation_id: str | None = None) -> ChargeSessionStatus:
        with self._write() as db:
            row = self._row(db, session_id)
            current = self._value(row)
            if current is None or current.state != expected_state:
                raise ValueError('CHARGE_STATE_CONFLICT')
            if current.attempt_id != attempt_id:
                raise ValueError('CHARGE_ATTEMPT_CONFLICT')
            if next_state not in _TRANSITIONS[current.state]:
                raise ValueError('CHARGE_TRANSITION_FORBIDDEN')
            if next_state == 'WORK_AVAILABLE':
                raise ValueError('CHARGE_DEPARTURE_RECEIPT_REQUIRED')
            if next_state not in ('HOLD', 'CANCELED') and not self._admitted(db, row, current):
                raise ValueError('CHARGE_DISPATCH_CLOSED')
            if now < current.updated_at:
                raise ValueError('CHARGE_CLOCK_REVERSED')
            if intent_kind is not None:
                if {'return': 'RETURNING', 'dock': 'DOCKING', 'undock': 'UNDOCKING'}.get(intent_kind) != next_state:
                    raise ValueError('CHARGE_OPERATION_STAGE_CONFLICT')
                if not isinstance(correlation_id, str) or not correlation_id.strip() or operation_id is not None:
                    raise ValueError('CHARGE_OPERATION_INTENT_REQUIRED')
                db.execute('''INSERT INTO fleet_charge_operations
                              (session_id, kind, correlation_id, state, status) VALUES (?, ?, ?, ?, 'PREPARED')''',
                           (session_id, intent_kind, correlation_id, next_state))
            if next_state in ('HOLD', 'CANCELED') and operation_id is None:
                operation_id = current.operation_id
            value = ChargeSessionStatus.model_validate(current.model_dump() | {
                'state': next_state, 'updated_at': now, 'reason': reason, 'operation_id': operation_id})
            self._save(db, value)
            phase = 'UNKNOWN' if next_state in ('HOLD', 'CANCELED') else 'HELD'
            db.execute('''UPDATE fleet_action_claims SET phase=?
                          WHERE owner_kind='charge_session' AND owner_id=? AND generation=?''',
                       (phase, session_id, row['generation']))
        return value

    def operation_intent(self, session_id):
        with closing(self.tasks._connect()) as db:
            row = db.execute('''SELECT * FROM fleet_charge_operations WHERE session_id=?
                                ORDER BY rowid DESC LIMIT 1''', (session_id,)).fetchone()
            return dict(row) if row else None

    def acknowledge_operation(self, session_id, *, correlation_id, operation_id, now):
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError('CHARGE_OPERATION_ID_REQUIRED')
        with self._write() as db:
            intent = db.execute('''SELECT * FROM fleet_charge_operations
                                   WHERE session_id=? AND correlation_id=?''', (session_id, correlation_id)).fetchone()
            current = self._value(self._row(db, session_id))
            if (intent is None or intent['status'] != 'PREPARED' or current.state != intent['state']
                    or current.operation_id is not None or now < current.updated_at):
                raise ValueError('CHARGE_OPERATION_ACK_CONFLICT')
            value = ChargeSessionStatus.model_validate(current.model_dump() | {
                'operation_id': operation_id, 'updated_at': now, 'reason': 'CHARGE_OPERATION_ACKNOWLEDGED'})
            db.execute("UPDATE fleet_charge_operations SET operation_id=?, status='ACKNOWLEDGED' WHERE correlation_id=?",
                       (operation_id, correlation_id))
            self._save(db, value)
            return value

    def operation_unknown(self, session_id):
        with self._write() as db:
            db.execute("UPDATE fleet_charge_operations SET status='UNKNOWN' WHERE session_id=? AND status='PREPARED'",
                       (session_id,))

    def prepare_return(self, session_id, *, correlation_id, plan_id, lease_id):
        """One-shot durable submission identity, before any lease or motion RPC."""
        if any(not isinstance(v, str) or not v.strip() for v in (correlation_id, plan_id, lease_id)):
            raise ValueError('CHARGE_RETURN_ID_REQUIRED')
        with self._write() as db:
            row = self._row(db, session_id)
            current = self._value(row)
            intent = db.execute("SELECT * FROM fleet_charge_operations WHERE session_id=? AND kind='return'",
                                (session_id,)).fetchone()
            if (current is None or current.state != 'RETURNING' or current.operation_id is not None
                    or intent is None or intent['status'] != 'PREPARED'
                    or intent['correlation_id'] != correlation_id or not self._admitted(db, row, current)):
                raise ValueError('CHARGE_RETURN_INTENT_CONFLICT')
            if db.execute('SELECT 1 FROM fleet_charge_returns WHERE session_id=?', (session_id,)).fetchone():
                raise ValueError('CHARGE_RETURN_ALREADY_PREPARED')
            value = {key: getattr(current, key) for key in _IDENTITY} | {
                'correlation_id': correlation_id, 'plan_id': plan_id, 'lease_id': lease_id, 'phase': 'PREPARED'}
            db.execute('INSERT INTO fleet_charge_returns VALUES (?, ?)', (session_id, json.dumps(value)))
            return value

    def return_context(self, session_id):
        with closing(self.tasks._connect()) as db:
            row = db.execute('SELECT payload_json FROM fleet_charge_returns WHERE session_id=?',
                             (session_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def bind_return_owner(self, session_id, context, *, owner_generation):
        """Freeze the measured native epoch before the first return grant."""
        if type(owner_generation) is not int or owner_generation < 0:
            raise ValueError('CHARGE_RETURN_NATIVE_OWNER_INVALID')
        with self._write() as db:
            row = self._row(db, session_id)
            current = self._value(row)
            found = db.execute('SELECT payload_json FROM fleet_charge_returns WHERE session_id=?',
                               (session_id,)).fetchone()
            value = json.loads(found[0]) if found else None
            keys = (*_IDENTITY, 'correlation_id', 'plan_id', 'lease_id')
            if (current is None or current.state != 'RETURNING' or not self._admitted(db, row, current)
                    or value is None or value['phase'] != 'PREPARED'
                    or 'expected_owner_generation' in value
                    or any(value[key] != context.get(key) for key in keys)
                    or any(value[key] != getattr(current, key) for key in _IDENTITY)):
                raise ValueError('CHARGE_RETURN_NATIVE_OWNER_CONFLICT')
            value['expected_owner_generation'] = owner_generation
            db.execute('UPDATE fleet_charge_returns SET payload_json=? WHERE session_id=?',
                       (json.dumps(value), session_id))
            return value

    def return_phase(self, session_id, *, expected, next_phase, refusal_code=None):
        allowed = {'PREPARED': {'SUBMITTED', 'UNKNOWN'}, 'SUBMITTED': {'FINISH_PENDING', 'UNKNOWN'},
                   'FINISH_PENDING': {'FINISHED', 'UNKNOWN'}, 'FINISHED': set(), 'UNKNOWN': set()}
        if expected == 'FINISH_PENDING' and refusal_code == 'STATION_RETURN_STANDSTILL_REQUIRED':
            allowed['FINISH_PENDING'].add('SUBMITTED')
        with self._write() as db:
            row = db.execute('SELECT payload_json FROM fleet_charge_returns WHERE session_id=?',
                             (session_id,)).fetchone()
            value = json.loads(row[0]) if row else None
            if value is None or value['phase'] != expected or next_phase not in allowed.get(expected, ()):
                raise ValueError('CHARGE_RETURN_PHASE_CONFLICT')
            value['phase'] = next_phase
            db.execute('UPDATE fleet_charge_returns SET payload_json=? WHERE session_id=?',
                       (json.dumps(value), session_id))
            return value

    @staticmethod
    def _admitted(db, row, session):
        control = db.execute('SELECT * FROM fleet_dispatch_control WHERE control_id=1').fetchone()
        if (not control['dispatch_enabled'] or row['generation'] != control['generation']
                or row['authority_epoch'] != control['authority_epoch']):
            return False
        claims = db.execute('''SELECT resource_kind, resource_id FROM fleet_action_claims
                               WHERE owner_kind='charge_session' AND owner_id=? AND generation=?''',
                            (session.session_id, row['generation'])).fetchall()
        return {(r['resource_kind'], r['resource_id']) for r in claims} == {
            ('robot', session.robot_id), ('station', session.station_id)}

    def admitted(self, session_id: str) -> bool:
        with closing(self.tasks._connect()) as db:
            row = self._row(db, session_id)
            return row is not None and self._admitted(db, row, self._value(row))

    def admitted_session(self, session_id: str, *, states) -> ChargeSessionStatus | None:
        """One read transaction binds the session state to its retained claims and fence."""
        with closing(self.tasks._connect()) as db:
            db.execute('BEGIN')
            row = self._row(db, session_id)
            value = self._value(row)
            return (value if value is not None and value.state in states
                    and self._admitted(db, row, value) else None)

    def get(self, session_id: str) -> ChargeSessionStatus | None:
        with closing(self.tasks._connect()) as db:
            return self._value(self._row(db, session_id))

    def list(self) -> list[ChargeSessionStatus]:
        with closing(self.tasks._connect()) as db:
            return [self._value(row) for row in db.execute('SELECT * FROM fleet_charge_sessions ORDER BY session_id')]

    def history(self, session_id: str) -> list[ChargeSessionStatus]:
        with closing(self.tasks._connect()) as db:
            rows = db.execute('''SELECT payload_json FROM fleet_charge_history
                                 WHERE session_id=? ORDER BY event_id''', (session_id,)).fetchall()
        return [self._value(row) for row in rows]
