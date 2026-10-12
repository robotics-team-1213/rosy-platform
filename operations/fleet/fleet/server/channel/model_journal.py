"""Shared durable model attempts; concrete owners validate their own input contract."""
from contextlib import closing
import hashlib
import json
import math
import re
import sqlite3
import time
from fastapi import HTTPException
from rosy.decision.deliberation import canonical


class ModelJobsJournal:
    tables = ('fleet_channel_model_jobs', 'fleet_channel_model_attempts', 'fleet_channel_model_activation')
    reply_kind = "DELIBERATION"
    invalid_reply = '입력 또는 관측을 검증하지 못해 보류했습니다. 한 줄 128자 이내 상태 질문을 보내주세요. 실행 승인 아님.'

    def __init__(self, journal, profile_set_hash, *, clock=time.time):
        if (type(profile_set_hash) is not str or re.fullmatch('[0-9a-f]{64}', profile_set_hash) is None
                or journal.reply_outbox is None):
            raise ValueError('CHANNEL_MODEL_JOURNAL_REQUIRED')
        self.journal, self.profile_set_hash, self.clock = journal, profile_set_hash, clock
        with closing(journal._connect()) as conn, conn:
            conn.executescript(f'''CREATE TABLE IF NOT EXISTS {self.tables[0]} (
                request_id TEXT PRIMARY KEY, receipt_hash TEXT NOT NULL, route_hash TEXT NOT NULL,
                profile_set_hash TEXT NOT NULL, input_hash TEXT NOT NULL, problem_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL,
                deadline REAL NOT NULL, result_json TEXT, completed_at REAL);
                CREATE TABLE IF NOT EXISTS {self.tables[1]} (
                request_id TEXT NOT NULL, role TEXT NOT NULL, state TEXT NOT NULL,
                submitted_at REAL NOT NULL, result_json TEXT, known_cost_usd REAL,
                PRIMARY KEY(request_id,role));''')
            conn.execute(f'CREATE TABLE IF NOT EXISTS {self.tables[2]} (id INTEGER PRIMARY KEY,at REAL NOT NULL)')
            conn.execute(f'INSERT OR IGNORE INTO {self.tables[2]} VALUES (1,?)',(clock(),))

    def pending_receipts(self):
        with closing(self.journal._connect()) as conn:
            rows=conn.execute(f'''SELECT r.receipt FROM fleet_channel_requests r
                LEFT JOIN {self.tables[0]} j ON j.request_id=json_extract(r.receipt,'$.request_id')
                WHERE j.state='PENDING' OR (j.request_id IS NULL AND
                    julianday(json_extract(r.receipt,'$.received_at')) >
                    julianday((SELECT at FROM {self.tables[2]} WHERE id=1),'unixepoch'))
                ORDER BY r.rowid LIMIT 10''').fetchall()
            return [json.loads(r[0]) for r in rows]

    def _row(self, conn, request_id):
        conn.row_factory = sqlite3.Row
        row = conn.execute(f'SELECT * FROM {self.tables[0]} WHERE request_id=?', (request_id,)).fetchone()
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
        self.validate_input(receipt, problem, snapshot)
        now = self.clock()
        if not math.isfinite(now) or not 0 <= now - problem.observed_at <= 3:
            raise ValueError('CHANNEL_MODEL_STALE_INPUT')
        row = dict(request_id=receipt['request_id'], receipt_hash=receipt['content_hash'],
            route_hash=self.journal.reply_outbox.route_hash(), profile_set_hash=self.profile_set_hash,
            input_hash=problem.digest, problem_json=self.serialize_input(problem),
            snapshot_json=canonical(self.input_basis(snapshot)), state='PENDING', created_at=now, deadline=now+60)
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            original=self._receipt(conn,row)
            if original!=receipt:raise HTTPException(409,detail='CHANNEL_RECEIPT_CHANGED')
            conn.execute(f'''INSERT OR IGNORE INTO {self.tables[0]}
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
                previous = conn.execute(f'SELECT state,known_cost_usd FROM {self.tables[1]} '
                                        "WHERE request_id=? AND role='primary'", (request_id,)).fetchone()
                if previous is None or previous[0] not in ('RESULT', 'FAILED') or previous[1] is None:
                    raise HTTPException(409, detail='CHANNEL_MODEL_PRIOR_UNKNOWN')
            try:
                conn.execute(f'INSERT INTO {self.tables[1]} VALUES (?,?,?, ?,NULL,NULL)',
                             (request_id, role, 'SUBMITTED', self.clock()))
            except sqlite3.IntegrityError:
                raise HTTPException(409, detail='CHANNEL_MODEL_ROLE_SPENT') from None
            conn.execute(f"UPDATE {self.tables[0]} SET state='RUNNING' WHERE request_id=?", (request_id,))
            return {'request_id': request_id, 'role': role, 'input_hash': row['input_hash'],
                    'profile_set_hash': row['profile_set_hash'], 'deadline': row['deadline']}

    def reject(self, receipt):
        now=self.clock()
        row=dict(request_id=receipt['request_id'],receipt_hash=receipt['content_hash'],
            route_hash=self.journal.reply_outbox.route_hash(),profile_set_hash=self.profile_set_hash,
            input_hash=receipt['content_hash'],created_at=now,deadline=now+60)
        with closing(self.journal._connect()) as conn,conn:
            conn.execute('BEGIN IMMEDIATE')
            original=self._receipt(conn,row)
            if original!=receipt:raise HTTPException(409,detail='CHANNEL_RECEIPT_CHANGED')
            # Named parameters keep the immutable receipt and response in one transaction.
            row['result']=canonical({'reason':'STATUS_INPUT_INVALID','action_admissible':False})
            changed=conn.execute(f'''INSERT OR IGNORE INTO {self.tables[0]}
                VALUES (:request_id,:receipt_hash,:route_hash,:profile_set_hash,:input_hash,'{{}}','{{}}',
                    'HOLD',:created_at,:deadline,:result,:created_at)''',row).rowcount
            if changed:
                self.journal.reply_outbox.enqueue(conn,receipt,self.reply_kind,
                    f"ROSY 검토 · {receipt['request_id']}\n{self.invalid_reply}")

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
            changed = conn.execute(f'''UPDATE {self.tables[1]} SET state=?,result_json=?,known_cost_usd=?
                WHERE request_id=? AND role=? AND state IN ('SUBMITTED','UNKNOWN') ''',
                (state,canonical(result),known_cost_usd,request_id,role)).rowcount
            if changed != 1:
                raise HTTPException(409, detail='CHANNEL_MODEL_ATTEMPT_CHANGED')

    def finish(self, request_id, *, state, result, summary, observation_guard=None):
        if (state not in ('ANSWERED','HOLD','UNKNOWN') or type(result) is not dict
                or type(summary) is not str or not 1 <= len(summary) <= 1600 or '\x00' in summary):
            raise ValueError('CHANNEL_MODEL_RESULT_INVALID')
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = self._row(conn, request_id)
            receipt = self._receipt(conn, row)
            if observation_guard is not None:
                try:current=observation_guard() is True
                except (ValueError,TypeError,KeyError):current=False
                if not current:raise HTTPException(409,detail='CHANNEL_OBSERVATION_CHANGED')
            if row['state'] not in ('PENDING','RUNNING'):
                raise HTTPException(409, detail='CHANNEL_MODEL_ALREADY_FINISHED')
            conn.execute(f'UPDATE {self.tables[0]} SET state=?,result_json=?,completed_at=? WHERE request_id=?',
                         (state,canonical(result),self.clock(),request_id))
            self.journal.reply_outbox.enqueue(conn, receipt, self.reply_kind, summary)
            return self._view(self._row(conn, request_id))

    def recover(self):
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.row_factory = sqlite3.Row
            for item in conn.execute(f"SELECT * FROM {self.tables[0]} WHERE state='RUNNING'").fetchall():
                row = dict(item)
                conn.execute(f"UPDATE {self.tables[0]} SET state='UNKNOWN',completed_at=? WHERE request_id=?",
                             (self.clock(),row['request_id']))
                conn.execute(f"UPDATE {self.tables[1]} SET state='UNKNOWN' WHERE request_id=? AND state='SUBMITTED'",
                             (row['request_id'],))
                try: receipt = self._receipt(conn,row,active=False)
                except HTTPException: continue
                self.journal.reply_outbox.enqueue(conn,receipt,self.reply_kind,
                    f"ROSY 읽기 전용 판단 · {row['request_id']}\n모델 결과 불명 · 자동 재호출하지 않습니다. 장치 명령을 보내지 않았습니다.")

    def read(self, request_id, principal):
        with closing(self.journal._connect()) as conn:
            row = self._row(conn,request_id)
            receipt = self._receipt(conn,row,active=False)
            if principal != receipt['principal_id']: raise HTTPException(403,detail='CHANNEL_OWNER_REQUIRED')
            return self._view(row)

    def peek(self, request_id):
        with closing(self.journal._connect()) as conn:
            return self._row(conn,request_id)

    def guard(self, request_id):
        with closing(self.journal._connect()) as conn:
            row=self._row(conn,request_id)
            self._receipt(conn,row)
            if row['state'] not in ('PENDING','RUNNING'):
                raise HTTPException(409,detail='CHANNEL_MODEL_ALREADY_FINISHED')

    def abandon(self, request_id, *, state, reason):
        if state not in ('HOLD','UNKNOWN','SUPERSEDED') or type(reason) is not str or len(reason)>128:
            raise ValueError('CHANNEL_MODEL_TERMINAL_INVALID')
        with closing(self.journal._connect()) as conn,conn:
            conn.execute(f'UPDATE {self.tables[0]} SET state=?,result_json=?,completed_at=? '
                         "WHERE request_id=? AND state IN ('PENDING','RUNNING')",
                         (state,canonical({'reason':reason,'action_admissible':False}),self.clock(),request_id))
            conn.execute(f"UPDATE {self.tables[1]} SET state='UNKNOWN' WHERE request_id=? AND state='SUBMITTED'",
                         (request_id,))

    @staticmethod
    def _view(row):
        return {k:row[k] for k in ('request_id','state','profile_set_hash','input_hash','created_at','deadline','completed_at')} | {
            'result':json.loads(row['result_json']) if row['result_json'] else None,'action_admissible':False}
