"""Durable advisory runs in the existing Fleet DB; no model-turn or command dispatch."""
import asyncio
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from rosy.decision.deliberation import canonical
from .sqlite_policy import configure_connection


class DeliberationJournal:
    def __init__(self, path):
        self.path = Path(path)
        with closing(self._connect()) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_deliberation_runs (
                subject_id TEXT NOT NULL, case_id TEXT NOT NULL, generation TEXT NOT NULL,
                input_hash TEXT NOT NULL, input_json TEXT NOT NULL, result_json TEXT,
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
                return json.loads(row['result_json']) if row['result_json'] else {
                    'state': 'HOLD', 'reason': 'RESTART_OR_INFLIGHT_UNKNOWN', 'choice': None,
                    'calls': 0, 'action_admissible': False}
            conn.execute('INSERT INTO fleet_deliberation_runs VALUES (?, ?, ?, ?, ?, NULL)',
                         (problem.subject_id, problem.case_id, problem.generation,
                          problem.digest, canonical(asdict(problem))))
        return None

    def read(self, problem):
        with closing(self._connect()) as conn:
            row = conn.execute('SELECT result_json FROM fleet_deliberation_runs WHERE subject_id=? AND case_id=? AND generation=?',
                               (problem.subject_id, problem.case_id, problem.generation)).fetchone()
        return json.loads(row['result_json']) if row and row['result_json'] else None

    async def run(self, problem, supervisor, providers, *, current):
        previous = self.begin(problem)
        if previous is not None:
            return previous
        try:
            result = await supervisor.run(problem, providers, current=current)
        except asyncio.CancelledError:
            # Pending durable row remains UNKNOWN; another process must not replay its provider submission.
            raise
        with closing(self._connect()) as conn, conn:
            conn.execute('UPDATE fleet_deliberation_runs SET result_json=? WHERE subject_id=? AND case_id=? AND generation=?',
                         (canonical(result), problem.subject_id, problem.case_id, problem.generation))
        return result
