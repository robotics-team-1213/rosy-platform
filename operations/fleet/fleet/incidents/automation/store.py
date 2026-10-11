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
                worker_id TEXT NOT NULL, state TEXT NOT NULL,
                reserved_micros INTEGER NOT NULL, actual_micros INTEGER, summary_json TEXT,
                PRIMARY KEY(subject_id,case_id,attempt_id),
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

    def begin_case(self, scope, budget):
        if type(budget) is not CaseBudget:
            raise ValueError('EXPLICIT_CASE_BUDGET_REQUIRED')
        key, scope_json, budget_json = self._key(scope), canonical(asdict(scope)), canonical(asdict(budget))
        with self._transaction() as conn:
            prior = conn.execute('SELECT * FROM fleet_incident_v2_cases WHERE subject_id=? AND case_id=?', key).fetchone()
            if prior is not None:
                if prior['scope_json'] != scope_json or prior['budget_json'] != budget_json:
                    raise ValueError('CASE_SCOPE_OR_BUDGET_CHANGED')
            else:
                if conn.execute('SELECT COUNT(*) FROM fleet_incident_v2_cases').fetchone()[0] >= self.max_cases:
                    raise ValueError('CASE_CAPACITY')
                conn.execute('INSERT INTO fleet_incident_v2_cases VALUES (?,?,?,?,?,?,?,?,?,?)',
                             (*key, scope_json, budget_json, 'ACTIVE', 'OPEN', 0, 0, 0, 0))
            return self._case(conn, scope)

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

    def reserve(self, scope, *, attempt_id, input_hash, observation_revision, kind, max_cost_usd, worker_id):
        for value in (attempt_id, observation_revision, worker_id):
            identifier(value)
        sha256(input_hash)
        if kind not in ('model', 'observation') or (kind == 'observation' and max_cost_usd != 0):
            raise ValueError('INVALID_ATTEMPT_KIND_OR_COST')
        cost = micros(max_cost_usd)
        with self._transaction() as conn:
            case = self._case(conn, scope, active=True)
            key = self._key(scope)
            if conn.execute('SELECT 1 FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? AND attempt_id=?',
                            (*key, attempt_id)).fetchone():
                raise ValueError('ATTEMPT_ALREADY_RESERVED')
            if conn.execute("SELECT 1 FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? AND state IN ('RESERVED','SUBMITTING')", key).fetchone():
                raise ValueError('CASE_ATTEMPT_INFLIGHT')
            count, limit = ('calls', 'max_calls') if kind == 'model' else ('observations', 'max_observations')
            if case[count] >= case[limit] or case['spent_micros'] + case['reserved_micros'] + cost > micros(case['max_cost_usd'], ceiling=False):
                raise ValueError('CASE_BUDGET_EXHAUSTED')
            conn.execute(f'UPDATE fleet_incident_v2_cases SET {count}={count}+1,reserved_micros=reserved_micros+? WHERE subject_id=? AND case_id=?', (cost, *key))
            conn.execute('INSERT INTO fleet_incident_v2_attempts VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL)',
                         (*key, attempt_id, input_hash, observation_revision, kind, worker_id, 'RESERVED', cost))
            return {'attempt_id': attempt_id, 'state': 'RESERVED', 'reserved_micros': cost}

    def mark_submitting(self, scope, attempt_id, *, worker_id):
        identifier(attempt_id), identifier(worker_id)
        with self._transaction() as conn:
            self._case(conn, scope, active=True)
            if conn.execute("UPDATE fleet_incident_v2_attempts SET state='SUBMITTING' WHERE subject_id=? AND case_id=? AND attempt_id=? AND worker_id=? AND state='RESERVED'",
                            (*self._key(scope), attempt_id, worker_id)).rowcount != 1:
                raise ValueError('ATTEMPT_NOT_RESERVED_BY_WORKER')
            return {'attempt_id': attempt_id, 'state': 'SUBMITTING'}

    def complete(self, scope, attempt_id, *, worker_id, state, actual_cost_usd, summary):
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
            conn.execute('UPDATE fleet_incident_v2_attempts SET state=?,actual_micros=?,summary_json=? WHERE subject_id=? AND case_id=? AND attempt_id=?', (state, actual, raw, *key, attempt_id))
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
