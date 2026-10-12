"""Opt-in incident reservation ledger. No provider, observation or robot dispatch."""
from contextlib import closing, contextmanager
from dataclasses import asdict
import json
import math
from pathlib import Path
import sqlite3
import time

from rosy.decision.deliberation import canonical, identifier
from .contract import CaseBudget, CaseScope, micros, sha256, summary_json
from .receipt import checked_receipt
from ..routing import profile_route
from fleet.server.sqlite_policy import configure_connection


class IncidentCaseStore:
    def __init__(self, path, *, clock=time.time, max_cases=1000):
        if not callable(clock) or type(max_cases) is not int or not 1 <= max_cases <= 10000:
            raise ValueError('INVALID_CASE_STORE')
        self.path, self.clock, self.max_cases = Path(path), clock, max_cases
        with self._transaction() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_incident_v2_cases (
                subject_id TEXT NOT NULL, case_id TEXT NOT NULL, scope_json TEXT NOT NULL,
                budget_json TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('ACTIVE','HOLD','NOT_NEEDED')),
                reason TEXT NOT NULL, calls INTEGER NOT NULL, observations INTEGER NOT NULL,
                spent_micros INTEGER NOT NULL, reserved_micros INTEGER NOT NULL,
                PRIMARY KEY(subject_id,case_id))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_incident_v2_attempts (
                subject_id TEXT NOT NULL, case_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
                input_hash TEXT NOT NULL, observation_revision TEXT NOT NULL, kind TEXT NOT NULL,
                worker_id TEXT NOT NULL, state TEXT NOT NULL, role TEXT,
                reserved_micros INTEGER NOT NULL, actual_micros INTEGER, summary_json TEXT,
                PRIMARY KEY(subject_id,case_id,attempt_id),
                FOREIGN KEY(subject_id,case_id) REFERENCES fleet_incident_v2_cases(subject_id,case_id))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_incident_v2_closures (
                subject_id TEXT NOT NULL, case_id TEXT NOT NULL, receipt_json TEXT NOT NULL,
                PRIMARY KEY(subject_id,case_id),
                FOREIGN KEY(subject_id,case_id) REFERENCES fleet_incident_v2_cases(subject_id,case_id))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_incident_v2_origins (
                subject_id TEXT NOT NULL, case_id TEXT NOT NULL, observation_revision TEXT NOT NULL,
                PRIMARY KEY(subject_id,case_id),
                FOREIGN KEY(subject_id,case_id) REFERENCES fleet_incident_v2_cases(subject_id,case_id))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_incident_v2_creators (
                subject_id TEXT NOT NULL, case_id TEXT NOT NULL, worker_id TEXT NOT NULL,
                PRIMARY KEY(subject_id,case_id),
                FOREIGN KEY(subject_id,case_id) REFERENCES fleet_incident_v2_cases(subject_id,case_id))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_incident_v2_handoff_queues (
                subject_id TEXT NOT NULL, case_id TEXT NOT NULL, queued_at REAL NOT NULL,
                PRIMARY KEY(subject_id,case_id),
                FOREIGN KEY(subject_id,case_id) REFERENCES fleet_incident_v2_cases(subject_id,case_id))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_incident_v2_model_receipts (
                subject_id TEXT NOT NULL, case_id TEXT NOT NULL, attempt_id TEXT NOT NULL, receipt_json TEXT NOT NULL,
                PRIMARY KEY(subject_id,case_id,attempt_id),
                FOREIGN KEY(subject_id,case_id,attempt_id)
                REFERENCES fleet_incident_v2_attempts(subject_id,case_id,attempt_id))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_incident_v2_profile_routes (
                owner_id TEXT NOT NULL, policy_revision TEXT NOT NULL, current TEXT NOT NULL,
                previous TEXT, revision INTEGER NOT NULL, PRIMARY KEY(owner_id,policy_revision))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_incident_v2_assignments (
                subject_id TEXT NOT NULL, case_id TEXT NOT NULL, route_revision INTEGER NOT NULL,
                PRIMARY KEY(subject_id,case_id),
                FOREIGN KEY(subject_id,case_id) REFERENCES fleet_incident_v2_cases(subject_id,case_id))''')

    @contextmanager
    def _transaction(self):
        with closing(configure_connection(sqlite3.connect(self.path, timeout=5))) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN IMMEDIATE')
            yield conn

    @staticmethod
    def _key(scope):
        if type(scope) is not CaseScope:
            raise ValueError('EXPLICIT_CASE_SCOPE_REQUIRED')
        return scope.subject_id, scope.case_id

    def _case(self, conn, scope, *, active=False):
        row = conn.execute('SELECT * FROM fleet_incident_v2_cases WHERE subject_id=? AND case_id=?', self._key(scope)).fetchone()
        if row is None or row['scope_json'] != canonical(asdict(scope)):
            raise ValueError('CASE_SCOPE_CHANGED_OR_MISSING')
        result = {**dict(row), **json.loads(row['budget_json'])}
        if active:
            now = self.clock()
            if (type(now) not in (int, float) or not math.isfinite(now)
                    or result['state'] != 'ACTIVE' or not result['started_at'] <= now < result['deadline']):
                raise ValueError('CASE_NOT_ACTIVE_OR_EXPIRED')
        return result

    def begin_case(self, scope, budget, *, connection=None, initial_revision=None, worker_id=None, routed=False):
        if type(routed) is not bool: raise ValueError('EXPLICIT_ROUTING_MODE_REQUIRED')
        if initial_revision is not None: identifier(initial_revision)
        if worker_id is not None: identifier(worker_id)
        if connection is not None:
            if (type(connection) is not sqlite3.Connection or not connection.in_transaction
                    or not any(row[1] == 'main' and Path(row[2]).resolve() == self.path.resolve()
                               for row in connection.execute('PRAGMA database_list'))):
                raise ValueError('CALLER_TRANSACTION_REQUIRED')
            return self._begin_case(connection, scope, budget, initial_revision, worker_id, routed)
        with self._transaction() as conn:
            return self._begin_case(conn, scope, budget, initial_revision, worker_id, routed)

    def _begin_case(self, conn, scope, budget, initial_revision, worker_id, routed):
        if type(budget) is not CaseBudget:
            raise ValueError('EXPLICIT_CASE_BUDGET_REQUIRED')
        key, scope_json, budget_json = self._key(scope), canonical(asdict(scope)), canonical(asdict(budget))
        prior = conn.execute('SELECT * FROM fleet_incident_v2_cases WHERE subject_id=? AND case_id=?', key).fetchone()
        if prior is not None:
            if prior['scope_json'] != scope_json or prior['budget_json'] != budget_json:
                raise ValueError('CASE_SCOPE_OR_BUDGET_CHANGED')
        else:
            route = profile_route(conn, scope.owner_id, scope.policy_revision) if routed else None
            if routed and (route is None or route['current'] != scope.profile_sha256):
                raise ValueError('CASE_PROFILE_NOT_SELECTED')
            if conn.execute('SELECT COUNT(*) FROM fleet_incident_v2_cases').fetchone()[0] >= self.max_cases:
                raise ValueError('CASE_CAPACITY')
            conn.execute('INSERT INTO fleet_incident_v2_cases VALUES (?,?,?,?,?,?,?,?,?,?)',
                         (*key, scope_json, budget_json, 'ACTIVE', 'OPEN', 0, 0, 0, 0))
            if initial_revision is not None:
                conn.execute('INSERT INTO fleet_incident_v2_origins VALUES (?,?,?)', (*key, initial_revision))
            if worker_id is not None:
                conn.execute('INSERT INTO fleet_incident_v2_creators VALUES (?,?,?)', (*key, worker_id))
            if routed:
                conn.execute('INSERT INTO fleet_incident_v2_assignments VALUES (?,?,?)', (*key, route['revision']))
        return self._case(conn, scope)

    def assignment(self, scope):
        with self._transaction() as conn:
            self._case(conn, scope)
            row = conn.execute('SELECT route_revision FROM fleet_incident_v2_assignments '
                               'WHERE subject_id=? AND case_id=?', self._key(scope)).fetchone()
            return row[0] if row else None

    def requires_resume_admission(self, scope, worker_id):
        with self._transaction() as conn:
            self._case(conn, scope)
            return conn.execute("SELECT 1 FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? AND kind='model' AND state='COMPLETED' AND worker_id!=? LIMIT 1",
                                (*self._key(scope), worker_id)).fetchone() is not None

    def pending_handoffs(self):
        with self._transaction() as conn:
            return tuple(CaseScope(**json.loads(row[0])) for row in conn.execute('''
                SELECT c.scope_json FROM fleet_incident_v2_cases c LEFT JOIN fleet_incident_v2_handoff_queues q
                USING(subject_id,case_id) WHERE c.state='HOLD' AND q.queued_at IS NULL
                AND c.reason NOT IN ('RESOLVED_OBSERVED','INCIDENT_HUMAN_OWNED')'''))

    def final_summary(self, scope):
        with self._transaction() as conn:
            case = self._case(conn, scope)
            row = conn.execute('SELECT observation_revision FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? ORDER BY rowid DESC LIMIT 1', self._key(scope)).fetchone()
            if row is None:
                row = conn.execute('SELECT observation_revision FROM fleet_incident_v2_origins WHERE subject_id=? AND case_id=?', self._key(scope)).fetchone()
            return {**{key: case[key] for key in ('reason', 'calls', 'observations', 'spent_micros', 'reserved_micros')},
                    'profile_sha256': scope.profile_sha256, 'observation_revision': row[0] if row else None}

    def handoff_queued(self, scope):
        with self._transaction() as conn:
            if self._case(conn, scope)['state'] != 'HOLD': raise ValueError('FINAL_REVIEW_NOT_PENDING')
            conn.execute('INSERT OR IGNORE INTO fleet_incident_v2_handoff_queues VALUES (?,?,?)', (*self._key(scope), self.clock()))

    def active_scopes(self):
        with self._transaction() as conn:
            return tuple(CaseScope(**json.loads(row[0])) for row in conn.execute(
                "SELECT scope_json FROM fleet_incident_v2_cases WHERE state='ACTIVE'"))

    def observed_closure(self, scope, proof=None):
        from ..closure import ObservedClosure
        with self._transaction() as conn:
            case = self._case(conn, scope)
            if proof is not None:
                if (type(proof) is not ObservedClosure or proof.scope != scope or case['state'] != 'ACTIVE'
                        or proof.requested_at != case['started_at']
                        or not proof.requested_at < proof.observed_at <= self.clock()
                        or not proof.requested_at < proof.closed_at <= self.clock()
                        or proof.action_credit not in ('NONE', 'UNVERIFIED')
                        or conn.execute("SELECT 1 FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? AND state IN ('RESERVED','SUBMITTING')", self._key(scope)).fetchone()):
                    raise ValueError('TRUSTED_OBSERVED_CLOSURE_REQUIRED')
                body = canonical({**asdict(proof), 'state': 'RESOLVED_OBSERVED'})
                conn.execute('INSERT INTO fleet_incident_v2_closures VALUES (?,?,?)', (*self._key(scope), body))
                conn.execute("UPDATE fleet_incident_v2_cases SET state='HOLD',reason='RESOLVED_OBSERVED' WHERE subject_id=? AND case_id=?", self._key(scope))
            row = conn.execute('SELECT receipt_json FROM fleet_incident_v2_closures WHERE subject_id=? AND case_id=?', self._key(scope)).fetchone()
            return json.loads(row[0]) if row else None

    def case(self, scope):
        with self._transaction() as conn:
            return self._case(conn, scope)

    def attempt(self, scope, attempt_id):
        identifier(attempt_id)
        with self._transaction() as conn:
            self._case(conn, scope)
            row = conn.execute('SELECT * FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? AND attempt_id=?',
                               (*self._key(scope), attempt_id)).fetchone()
            return dict(row) if row else None

    def reserve(self, scope, *, attempt_id, input_hash, observation_revision, kind, max_cost_usd, worker_id, role=None):
        for value in (attempt_id, observation_revision, worker_id):
            identifier(value)
        sha256(input_hash)
        if kind not in ('model', 'observation') or (kind == 'observation' and max_cost_usd != 0):
            raise ValueError('INVALID_ATTEMPT_KIND_OR_COST')
        cost = micros(max_cost_usd)
        with self._transaction() as conn:
            case = self._case(conn, scope, active=True)
            key = self._key(scope)
            limits = dict(case.get('role_limits', ()))
            if kind == 'observation' and role is not None or kind == 'model' and limits and role not in limits:
                raise ValueError('CASE_MODEL_ROLE_REQUIRED')
            if kind == 'model' and role in limits and conn.execute(
                    'SELECT COUNT(*) FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? AND role=?',
                    (*key, role)).fetchone()[0] >= limits[role]:
                raise ValueError('CASE_ROLE_BUDGET_EXHAUSTED')
            if conn.execute('SELECT 1 FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? AND attempt_id=?',
                            (*key, attempt_id)).fetchone():
                raise ValueError('ATTEMPT_ALREADY_RESERVED')
            if conn.execute("SELECT 1 FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? AND state IN ('RESERVED','SUBMITTING')", key).fetchone():
                raise ValueError('CASE_ATTEMPT_INFLIGHT')
            count, limit = ('calls', 'max_calls') if kind == 'model' else ('observations', 'max_observations')
            if case[count] >= case[limit] or case['spent_micros'] + case['reserved_micros'] + cost > micros(case['max_cost_usd'], ceiling=False):
                raise ValueError('CASE_BUDGET_EXHAUSTED')
            conn.execute(f'UPDATE fleet_incident_v2_cases SET {count}={count}+1,reserved_micros=reserved_micros+? WHERE subject_id=? AND case_id=?', (cost, *key))
            conn.execute('INSERT INTO fleet_incident_v2_attempts VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL)',
                         (*key, attempt_id, input_hash, observation_revision, kind, worker_id, 'RESERVED', role, cost))
            return {'attempt_id': attempt_id, 'state': 'RESERVED', 'reserved_micros': cost}

    def mark_submitting(self, scope, attempt_id, *, worker_id):
        identifier(attempt_id), identifier(worker_id)
        with self._transaction() as conn:
            self._case(conn, scope, active=True)
            if conn.execute("UPDATE fleet_incident_v2_attempts SET state='SUBMITTING' WHERE subject_id=? AND case_id=? AND attempt_id=? AND worker_id=? AND state='RESERVED'",
                            (*self._key(scope), attempt_id, worker_id)).rowcount != 1:
                raise ValueError('ATTEMPT_NOT_RESERVED_BY_WORKER')
            return {'attempt_id': attempt_id, 'state': 'SUBMITTING'}

    def complete(self, scope, attempt_id, *, worker_id, state, actual_cost_usd, summary, model_receipt=None):
        identifier(attempt_id), identifier(worker_id)
        if state not in ('COMPLETED', 'REJECTED', 'UNKNOWN'):
            raise ValueError('INVALID_ATTEMPT_TERMINAL')
        raw = summary_json(summary)
        try:
            actual = micros(actual_cost_usd) if actual_cost_usd is not None else None
        except ValueError:
            actual = None
        if actual is None:
            state = 'UNKNOWN'
        with self._transaction() as conn:
            self._case(conn, scope)
            key = self._key(scope)
            row = conn.execute('SELECT * FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? AND attempt_id=?', (*key, attempt_id)).fetchone()
            if row is None or row['state'] != 'SUBMITTING' or row['worker_id'] != worker_id:
                raise ValueError('ATTEMPT_NOT_SUBMITTING_BY_WORKER')
            trace = None
            if model_receipt is not None and state != 'UNKNOWN':
                try:
                    checked_receipt(scope, {**dict(row), 'state': state, 'actual_micros': actual}, model_receipt)
                    trace = model_receipt.payload_json
                except ValueError:
                    state, raw = 'REJECTED', summary_json({'reason': 'MODEL_TRACE_REJECTED'})
            conn.execute('UPDATE fleet_incident_v2_attempts SET state=?,actual_micros=?,summary_json=? WHERE subject_id=? AND case_id=? AND attempt_id=?', (state, actual, raw, *key, attempt_id))
            if trace is not None:
                conn.execute('INSERT INTO fleet_incident_v2_model_receipts VALUES (?,?,?,?)', (*key, attempt_id, trace))
            if actual is not None:
                released = min(actual, row['reserved_micros']) if state == 'UNKNOWN' else row['reserved_micros']
                conn.execute('UPDATE fleet_incident_v2_cases SET spent_micros=spent_micros+?,reserved_micros=reserved_micros-? WHERE subject_id=? AND case_id=?', (actual, released, *key))
            reason = ('COST_OVERRUN' if actual is not None and actual > row['reserved_micros'] else
                      'PROVIDER_OUTCOME_UNKNOWN' if state == 'UNKNOWN' else None)
            if reason:
                conn.execute("UPDATE fleet_incident_v2_cases SET state='HOLD',reason=? WHERE subject_id=? AND case_id=?", (reason, *key))
            return {'attempt_id': attempt_id, 'state': state, 'actual_micros': actual, 'summary_json': raw}

    def recover(self, scope):
        with self._transaction() as conn:
            self._case(conn, scope)
            key = self._key(scope)
            count = conn.execute("UPDATE fleet_incident_v2_attempts SET state='UNKNOWN',summary_json=? WHERE subject_id=? AND case_id=? AND state IN ('RESERVED','SUBMITTING')",
                                 (summary_json({'reason': 'RESTART_OUTCOME_UNKNOWN'}), *key)).rowcount
            if count:
                conn.execute("UPDATE fleet_incident_v2_cases SET state='HOLD',reason='RESTART_OUTCOME_UNKNOWN' WHERE subject_id=? AND case_id=?", key)
            return count

    def cancel_owned(self, worker_id, *, submitted_attempt_ids):
        """Cancel only this worker after its DB tasks finish; submission proof is trusted runtime state."""
        identifier(worker_id)
        result = []
        with self._transaction() as conn:
            rows = conn.execute("SELECT * FROM fleet_incident_v2_attempts WHERE worker_id=? AND state IN ('RESERVED','SUBMITTING')", (worker_id,)).fetchall()
            for row in rows:
                key = row['subject_id'], row['case_id']
                submitted = row['attempt_id'] in submitted_attempt_ids
                conn.execute('UPDATE fleet_incident_v2_attempts SET state=?,actual_micros=?,summary_json=? WHERE subject_id=? AND case_id=? AND attempt_id=?',
                    ('UNKNOWN' if submitted else 'REJECTED', None if submitted else 0,
                     summary_json({'reason': 'WORKER_CANCELLED'}), *key, row['attempt_id']))
                conn.execute("UPDATE fleet_incident_v2_cases SET state='HOLD',reason='WORKER_CANCELLED',reserved_micros=reserved_micros-? WHERE subject_id=? AND case_id=?",
                             (0 if submitted else row['reserved_micros'], *key))
                scope_json = conn.execute('SELECT scope_json FROM fleet_incident_v2_cases WHERE subject_id=? AND case_id=?', key).fetchone()[0]
                scope = CaseScope(**json.loads(scope_json))
                if scope not in result: result.append(scope)
            # A cancelled terminal commit may already be known. Keep its receipt and stop the unresolved case.
            completed = conn.execute('''SELECT c.scope_json FROM fleet_incident_v2_cases c
                WHERE c.state='ACTIVE' AND (EXISTS (SELECT 1 FROM fleet_incident_v2_attempts a
                    WHERE a.subject_id=c.subject_id AND a.case_id=c.case_id AND a.worker_id=?)
                    OR EXISTS (SELECT 1 FROM fleet_incident_v2_creators o
                    WHERE o.subject_id=c.subject_id AND o.case_id=c.case_id AND o.worker_id=?))
                AND NOT EXISTS (SELECT 1 FROM fleet_incident_v2_attempts a
                    WHERE a.subject_id=c.subject_id AND a.case_id=c.case_id AND a.worker_id!=?
                    AND a.state IN ('RESERVED','SUBMITTING'))''', (worker_id, worker_id, worker_id)).fetchall()
            for row in completed:
                scope = CaseScope(**json.loads(row[0]))
                conn.execute("UPDATE fleet_incident_v2_cases SET state='HOLD',reason='WORKER_CANCELLED' WHERE subject_id=? AND case_id=?", self._key(scope))
                if scope not in result: result.append(scope)
        return tuple(result)

    def close_case(self, scope, *, state, reason):
        raw = summary_json({'reason': reason})
        if state not in ('HOLD', 'NOT_NEEDED'):
            raise ValueError('UNADMITTED_CASE_OUTCOME')
        with self._transaction() as conn:
            case = self._case(conn, scope)
            if case['state'] != 'ACTIVE' or (state == 'NOT_NEEDED' and (case['calls'] or case['observations'])):
                raise ValueError('CASE_CANNOT_CLOSE')
            conn.execute('UPDATE fleet_incident_v2_cases SET state=?,reason=? WHERE subject_id=? AND case_id=?',
                         (state, json.loads(raw)['reason'], *self._key(scope)))
            return self._case(conn, scope)
