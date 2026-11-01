"""Durable advisory runs in the existing Fleet DB; no model-turn or command dispatch."""
import asyncio
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from rosy.decision.deliberation import canonical
from fleet.server.context_log import active
from fleet.server.sqlite_policy import configure_connection


class DeliberationJournal:
    def __init__(self, path, *, max_rows=1000, context_log=None):
        if type(max_rows) is not int or not 1 <= max_rows <= 10000:
            raise ValueError('invalid finite journal capacity')
        self.max_rows = max_rows
        self.path = Path(path)
        # D-796: an injected sink wins; otherwise the console-configured one (if any). Never
        # the source of truth: a mirror failure is swallowed and the ledger stays unchanged.
        self.context_log = context_log if context_log is not None else active()
        with closing(self._connect()) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_deliberation_runs (
                subject_id TEXT NOT NULL, case_id TEXT NOT NULL, generation TEXT NOT NULL,
                input_hash TEXT NOT NULL, input_json TEXT NOT NULL, result_json TEXT,
                terminal INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(subject_id, case_id, generation))''')

    def _connect(self):
        conn = configure_connection(sqlite3.connect(self.path, timeout=5))
        conn.row_factory = sqlite3.Row
        return conn

    def begin(self, problem):
        with closing(self._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM fleet_deliberation_runs WHERE subject_id=? AND case_id=? AND generation=?',
                               (problem.subject_id, problem.case_id, problem.generation)).fetchone()
            if row:
                if row['input_hash'] != problem.digest:
                    raise ValueError('DELIBERATION_CONTENT_CHANGED')
                return json.loads(row['result_json']) if row['terminal'] else {
                    'state': 'HOLD', 'reason': 'RESTART_OR_INFLIGHT_UNKNOWN', 'choice': None,
                    'calls': None, 'cost_usd': None, 'cost_complete': False, 'action_admissible': False}
            if conn.execute('SELECT 1 FROM fleet_deliberation_runs WHERE subject_id=? AND case_id=?',
                            (problem.subject_id, problem.case_id)).fetchone():
                return {'state': 'HOLD', 'reason': 'BUSY_OR_BUDGET_EXHAUSTED', 'choice': None,
                        'calls': 0, 'action_admissible': False}
            if conn.execute('SELECT COUNT(*) FROM fleet_deliberation_runs').fetchone()[0] >= self.max_rows:
                raise ValueError('DELIBERATION_CAPACITY')
            conn.execute('INSERT INTO fleet_deliberation_runs VALUES (?, ?, ?, ?, ?, NULL, 0)',
                         (problem.subject_id, problem.case_id, problem.generation,
                          problem.digest, canonical(asdict(problem))))
        return None

    def read(self, problem):
        with closing(self._connect()) as conn:
            row = conn.execute('SELECT result_json FROM fleet_deliberation_runs WHERE subject_id=? AND case_id=? AND generation=?',
                               (problem.subject_id, problem.case_id, problem.generation)).fetchone()
        return json.loads(row['result_json']) if row and row['result_json'] else None

    def write(self, problem, result, terminal):
        with closing(self._connect()) as conn, conn:
            conn.execute('UPDATE fleet_deliberation_runs SET result_json=?, terminal=? '
                         'WHERE subject_id=? AND case_id=? AND generation=? AND terminal=0',
                         (canonical(result), int(terminal), problem.subject_id, problem.case_id, problem.generation))

    def _mirror(self, problem, result):
        # D-796: mirror only the terminal run this process produced; ContextLog
        # swallows its own failures so the ledger transaction is never affected.
        if self.context_log is None:
            return
        self.context_log.record_run(
            subject_id=problem.subject_id, case_id=problem.case_id,
            generation=problem.generation, policy_id=result.get('policy_id', 'deliberation-v1'),
            result=result)

    async def run(self, problem, supervisor, providers, *, current):
        policy_id = getattr(supervisor, 'policy_id', 'deliberation-v1')
        if policy_id not in ('deliberation-v1', 'conditional-review-v1', 'conditional-cooperation-v1'):
            raise ValueError('unsupported evaluation policy')
        evaluation_key = (supervisor.evaluation_key(problem, providers)
                          if policy_id == 'conditional-cooperation-v1' else None)
        def fresh():
            try:
                return current() is True and 0 <= supervisor.clock() - problem.observed_at <= 3
            except Exception:
                return False
        def stale(result):
            return {**result, 'state': 'HOLD', 'reason': 'STALE_OR_CHANGED', 'choice': None}
        previous = await asyncio.to_thread(self.begin, problem)
        if previous is not None:
            if previous.get('reason') == 'RESTART_OR_INFLIGHT_UNKNOWN':
                return previous if fresh() else stale(previous)
            if previous.get('policy_id', 'deliberation-v1') != policy_id:
                return {**previous, 'state': 'HOLD', 'reason': 'EVALUATION_POLICY_CHANGED',
                        'choice': None, 'action_admissible': False}
            if evaluation_key is not None and previous.get('evaluation_key') != evaluation_key:
                return {**previous, 'state': 'HOLD', 'reason': 'EVALUATION_CONFIGURATION_CHANGED',
                        'choice': None, 'action_admissible': False}
            return previous if fresh() else stale(previous)
        async def record(result):
            await asyncio.to_thread(self.write, problem,
                {**result, 'policy_id': policy_id, **({'evaluation_key': evaluation_key} if evaluation_key else {})}, False)
        try:
            result = await supervisor.run(problem, providers, current=current, record=record)
        except asyncio.CancelledError:
            # Pending durable row remains UNKNOWN; another process must not replay its provider submission.
            raise
        if not fresh():
            result = stale(result)
        result = {**result, 'policy_id': policy_id}
        if evaluation_key is not None:
            result['evaluation_key'] = evaluation_key
        await asyncio.to_thread(self.write, problem, result, True)
        await asyncio.to_thread(self._mirror, problem, result)
        return result if fresh() else stale(result)
