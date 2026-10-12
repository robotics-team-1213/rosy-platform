"""Durable, read-only model questions; the original operator receipt stays immutable."""
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import math
import re
import sqlite3
import time

from fastapi import HTTPException
from rosy.decision.deliberation import Problem, canonical, identifier


def status_snapshot(snapshot):
    rows = snapshot.get('robots') if type(snapshot) is dict else None
    if type(rows) is not list or len(rows) > 15:
        raise ValueError('CHANNEL_STATUS_LIMIT')
    selected = []
    for row in rows:
        if type(row) is not dict or row.get('online') is not None and type(row.get('online')) is not bool:
            raise ValueError('CHANNEL_STATUS_INVALID')
        rid = identifier(row.get('robot_id'))
        state = row.get('state') if row.get('online') is True else None
        state = state if type(state) is dict else {}
        safety = state.get('safety') or {}
        line = state.get('line_follow') or {}
        selected.append({'robot_id': rid, 'online': row.get('online'),
            'mode': state.get('mode'), 'estop': safety.get('estop') if type(safety) is dict else None,
            'line_state': line.get('state') if type(line) is dict else None})
    if len({r['robot_id'] for r in selected}) != len(selected):
        raise ValueError('CHANNEL_STATUS_INVALID')
    return {'robots': sorted(selected, key=lambda r: r['robot_id'])}


def status_problem(receipt, snapshot, *, now):
    selected = status_snapshot(snapshot)
    values = [r['online'] for r in selected['robots']]
    state = ('empty' if not values else 'unknown' if None in values else
             'online' if all(values) else 'offline' if not any(values) else 'mixed')
    question = re.sub(r'<@!?[0-9]{17,20}>', '', receipt['content']).strip()
    digest = hashlib.sha256(canonical(selected).encode()).hexdigest()
    refs = tuple('robot:' + r['robot_id'] + ':' + ('unknown' if r['online'] is None
                 else 'online' if r['online'] else 'offline') for r in selected['robots'])
    return Problem('fleet', receipt['request_id'], digest, 'fleet_status', now,
        (*refs, 'snapshot:' + digest[:16]), ('human', 'reobserve'), 'READ_ONLY_QUERY',
        goal=question, facts_json=canonical({'state': state}))


class ChannelModelJobs:
    def __init__(self, journal, profile_set_hash, *, clock=time.time):
        if (type(profile_set_hash) is not str or re.fullmatch('[0-9a-f]{64}', profile_set_hash) is None
                or journal.reply_outbox is None):
            raise ValueError('CHANNEL_MODEL_JOURNAL_REQUIRED')
        self.journal, self.profile_set_hash, self.clock = journal, profile_set_hash, clock
        with closing(journal._connect()) as conn, conn:
            conn.executescript('''CREATE TABLE IF NOT EXISTS fleet_channel_model_jobs (
                request_id TEXT PRIMARY KEY, receipt_hash TEXT NOT NULL, route_hash TEXT NOT NULL,
                profile_set_hash TEXT NOT NULL, input_hash TEXT NOT NULL, problem_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL,
                deadline REAL NOT NULL, result_json TEXT, completed_at REAL);
                CREATE TABLE IF NOT EXISTS fleet_channel_model_attempts (
                request_id TEXT NOT NULL, role TEXT NOT NULL, state TEXT NOT NULL,
                submitted_at REAL NOT NULL, result_json TEXT, known_cost_usd REAL,
                PRIMARY KEY(request_id,role));''')

    def _row(self, conn, request_id):
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM fleet_channel_model_jobs WHERE request_id=?', (request_id,)).fetchone()
        if row is None: raise HTTPException(404, detail='CHANNEL_MODEL_NOT_FOUND')
        return dict(row)

    def _receipt(self, conn, row, *, active=True):
        item = conn.execute("SELECT receipt FROM fleet_channel_requests WHERE json_extract(receipt,'$.request_id')=?",
                            (row['request_id'],)).fetchone()
        if item is None: raise HTTPException(404, detail='CHANNEL_REQUEST_NOT_FOUND')
        receipt = json.loads(item[0])
        self.journal.current_receipt(receipt)
        if (receipt['content_hash'] != row['receipt_hash']
                or hashlib.sha256(receipt['content'].encode()).hexdigest() != row['receipt_hash']
                or self.journal.reply_outbox.route_hash() != row['route_hash']
                or active and (row['profile_set_hash'] != self.profile_set_hash or self.clock() >= row['deadline'])):
            raise HTTPException(409, detail='CHANNEL_MODEL_SCOPE_CHANGED')
        return receipt

    def stage(self, receipt, problem, snapshot):
        if (type(problem) is not Problem or problem.domain != 'fleet_status'
                or problem != status_problem(receipt, snapshot, now=problem.observed_at)):
            raise ValueError('CHANNEL_MODEL_INPUT_REQUIRED')
        now = self.clock()
        if not math.isfinite(now) or not 0 <= now - problem.observed_at <= 3:
            raise ValueError('CHANNEL_MODEL_STALE_INPUT')
        row = dict(request_id=receipt['request_id'], receipt_hash=receipt['content_hash'],
            route_hash=self.journal.reply_outbox.route_hash(), profile_set_hash=self.profile_set_hash,
            input_hash=problem.digest, problem_json=canonical(asdict(problem)),
            snapshot_json=canonical(status_snapshot(snapshot)), state='PENDING', created_at=now, deadline=now+60)
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            self._receipt(conn, row)
            conn.execute('''INSERT OR IGNORE INTO fleet_channel_model_jobs
                (request_id,receipt_hash,route_hash,profile_set_hash,input_hash,problem_json,snapshot_json,
                 state,created_at,deadline) VALUES (:request_id,:receipt_hash,:route_hash,:profile_set_hash,
                 :input_hash,:problem_json,:snapshot_json,:state,:created_at,:deadline)''', row)
            existing = self._row(conn, receipt['request_id'])
            if existing['receipt_hash'] != row['receipt_hash'] or existing['profile_set_hash'] != self.profile_set_hash:
                raise HTTPException(409, detail='CHANNEL_MODEL_SCOPE_CHANGED')
            return self._view(existing)

    def reserve(self, request_id, role):
        if role not in ('primary', 'reviewer'): raise ValueError('CHANNEL_MODEL_ROLE_INVALID')
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = self._row(conn, request_id)
            self._receipt(conn, row)
            if row['state'] not in ('PENDING', 'RUNNING'):
                raise HTTPException(409, detail='CHANNEL_MODEL_ALREADY_FINISHED')
            if role == 'reviewer':
                previous = conn.execute('SELECT state,known_cost_usd FROM fleet_channel_model_attempts '
                                        "WHERE request_id=? AND role='primary'", (request_id,)).fetchone()
                if previous is None or previous[0] not in ('RESULT', 'FAILED') or previous[1] is None:
                    raise HTTPException(409, detail='CHANNEL_MODEL_PRIOR_UNKNOWN')
            try:
                conn.execute('INSERT INTO fleet_channel_model_attempts VALUES (?,?,?, ?,NULL,NULL)',
                             (request_id, role, 'SUBMITTED', self.clock()))
            except sqlite3.IntegrityError:
                raise HTTPException(409, detail='CHANNEL_MODEL_ROLE_SPENT') from None
            conn.execute("UPDATE fleet_channel_model_jobs SET state='RUNNING' WHERE request_id=?", (request_id,))
            return {'request_id': request_id, 'role': role, 'input_hash': row['input_hash'],
                    'profile_set_hash': row['profile_set_hash'], 'deadline': row['deadline']}

    def record_attempt(self, request_id, role, *, state, result, known_cost_usd, input_hash, profile_set_hash):
        if (state not in ('RESULT', 'FAILED', 'UNKNOWN') or type(result) is not dict
                or known_cost_usd is not None and (type(known_cost_usd) not in (int,float)
                or not math.isfinite(known_cost_usd) or known_cost_usd < 0)
                or state != 'UNKNOWN' and known_cost_usd is None):
            raise ValueError('CHANNEL_MODEL_RECEIPT_INVALID')
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = self._row(conn, request_id)
            # Spent resources remain evidence after expiry or account revocation; this grants no authority.
            if row['input_hash'] != input_hash or row['profile_set_hash'] != profile_set_hash:
                raise HTTPException(409, detail='CHANNEL_MODEL_ATTEMPT_CHANGED')
            changed = conn.execute('''UPDATE fleet_channel_model_attempts SET state=?,result_json=?,known_cost_usd=?
                WHERE request_id=? AND role=? AND state IN ('SUBMITTED','UNKNOWN') ''',
                (state,canonical(result),known_cost_usd,request_id,role)).rowcount
            if changed != 1:
                raise HTTPException(409, detail='CHANNEL_MODEL_ATTEMPT_CHANGED')

    def finish(self, request_id, *, state, result, summary):
        if (state not in ('ANSWERED','HOLD','UNKNOWN') or type(result) is not dict
                or type(summary) is not str or not 1 <= len(summary) <= 1600 or '\x00' in summary):
            raise ValueError('CHANNEL_MODEL_RESULT_INVALID')
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = self._row(conn, request_id)
            receipt = self._receipt(conn, row)
            if row['state'] not in ('PENDING','RUNNING'):
                raise HTTPException(409, detail='CHANNEL_MODEL_ALREADY_FINISHED')
            conn.execute('UPDATE fleet_channel_model_jobs SET state=?,result_json=?,completed_at=? WHERE request_id=?',
                         (state,canonical(result),self.clock(),request_id))
            self.journal.reply_outbox.enqueue(conn, receipt, 'DELIBERATION', summary)
            return self._view(self._row(conn, request_id))

    def recover(self):
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.row_factory = sqlite3.Row
            for item in conn.execute("SELECT * FROM fleet_channel_model_jobs WHERE state='RUNNING'").fetchall():
                row = dict(item)
                conn.execute("UPDATE fleet_channel_model_jobs SET state='UNKNOWN',completed_at=? WHERE request_id=?",
                             (self.clock(),row['request_id']))
                conn.execute("UPDATE fleet_channel_model_attempts SET state='UNKNOWN' WHERE request_id=? AND state='SUBMITTED'",
                             (row['request_id'],))
                try: receipt = self._receipt(conn,row,active=False)
                except HTTPException: continue
                self.journal.reply_outbox.enqueue(conn,receipt,'DELIBERATION',
                    f"ROSY 읽기 전용 판단 · {row['request_id']}\n모델 결과 불명 · 자동 재호출하지 않습니다. 장치 명령을 보내지 않았습니다.")

    def read(self, request_id, principal):
        with closing(self.journal._connect()) as conn:
            row = self._row(conn,request_id)
            receipt = self._receipt(conn,row,active=False)
            if principal != receipt['principal_id']: raise HTTPException(403,detail='CHANNEL_OWNER_REQUIRED')
            return self._view(row)

    @staticmethod
    def _view(row):
        return {k:row[k] for k in ('request_id','state','profile_set_hash','input_hash','created_at','deadline','completed_at')} | {
            'result':json.loads(row['result_json']) if row['result_json'] else None,'action_admissible':False}
