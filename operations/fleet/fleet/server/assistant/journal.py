"""Atomic Console request state in the existing Fleet database."""
from contextlib import closing
import json
import time

from fastapi import HTTPException
from core_common.protocol.assistant import AssistantResult, AssistantMessage


class AssistantJournal:
    def __init__(self, connect, *, clock=time.time):
        self.connect, self.clock = connect, clock
        with closing(connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS fleet_assistant_requests (
                principal_id TEXT NOT NULL, request_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL, message_json TEXT NOT NULL,
                state TEXT NOT NULL, created_at REAL NOT NULL, completed_at REAL,
                result_json TEXT, kind TEXT, PRIMARY KEY(principal_id, request_id))''')
            db.execute('''CREATE INDEX IF NOT EXISTS fleet_assistant_history
                ON fleet_assistant_requests(principal_id, conversation_id, created_at)''')

    @staticmethod
    def result(row):
        message = json.loads(row['message_json'])
        result = json.loads(row['result_json']) if row['result_json'] else {}
        return AssistantResult(request_id=row['request_id'], conversation_id=row['conversation_id'],
            text=message['text'], state=row['state'], created_at=row['created_at'],
            completed_at=row['completed_at'], **result)

    def submit(self, principal, message, *, admitted):
        raw = json.dumps(message.model_dump(), sort_keys=True, ensure_ascii=False)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM fleet_assistant_requests WHERE principal_id=? AND request_id=?',
                             (principal, message.request_id)).fetchone()
            if row:
                if AssistantMessage.model_validate_json(row['message_json']) != message:
                    raise HTTPException(409, detail='ASSISTANT_REQUEST_CHANGED')
                return self.result(row), False
            total, active = db.execute('''SELECT COUNT(*), COALESCE(SUM(state IN ('PENDING','RUNNING')),0)
                FROM fleet_assistant_requests WHERE principal_id=?''', (principal,)).fetchone()
            site_active = db.execute("SELECT COUNT(*) FROM fleet_assistant_requests WHERE state IN ('PENDING','RUNNING')").fetchone()[0]
            if total >= 1000 or active or site_active >= 64:
                raise HTTPException(429, detail='ASSISTANT_LIMIT')
            state = 'PENDING' if admitted else 'HOLD'
            result = None if admitted else json.dumps({'reason':'ASSISTANT_NOT_ADMITTED',
                'response':('The assistant is not connected. Use the existing Fleet controls.' if message.locale == 'en-US'
                    else '관제 AI 연결이 준비되지 않았습니다. 기존 관제 기능을 이용해 주세요.')})
            now = self.clock()
            db.execute('''INSERT INTO fleet_assistant_requests
                (principal_id,request_id,conversation_id,message_json,state,created_at,completed_at,result_json,kind)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (principal, message.request_id, message.conversation_id, raw, state, now,
                 None if admitted else now, result, None))
        return self.read(principal, message.request_id), True

    def read(self, principal, request_id):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM fleet_assistant_requests WHERE principal_id=? AND request_id=?',
                             (principal, request_id)).fetchone()
            if row is None:
                raise HTTPException(404, detail='ASSISTANT_NOT_FOUND')
            return self.result(row)

    def history(self, principal, conversation_id):
        with closing(self.connect()) as db:
            rows = db.execute('''SELECT * FROM fleet_assistant_requests
                WHERE principal_id=? AND conversation_id=? ORDER BY created_at DESC,rowid DESC LIMIT 40''',
                (principal, conversation_id)).fetchall()
            return [self.result(row) for row in reversed(rows)]

    def turns(self, principal, message):
        with closing(self.connect()) as db:
            rows = db.execute('''SELECT message_json,result_json FROM fleet_assistant_requests
                WHERE principal_id=? AND conversation_id=? AND kind='CHAT' AND state='ANSWERED'
                AND completed_at BETWEEN ? AND ? ORDER BY completed_at DESC,rowid DESC LIMIT 4''',
                (principal, message.conversation_id, self.clock()-120, self.clock())).fetchall()
        turns = []
        for row in reversed(rows):
            old = json.loads(row['message_json'])
            if old['selected_robot_id'] == message.selected_robot_id:
                turns.append({'question':old['text'], 'response':json.loads(row['result_json'])['response']})
        return turns

    def message(self, principal, request_id):
        from core_common.protocol.assistant import AssistantMessage
        with closing(self.connect()) as db:
            row = db.execute('SELECT message_json FROM fleet_assistant_requests WHERE principal_id=? AND request_id=?',
                             (principal, request_id)).fetchone()
            if row is None:
                raise HTTPException(404, detail='ASSISTANT_NOT_FOUND')
            return AssistantMessage.model_validate_json(row[0])

    def start(self, principal, request_id):
        with closing(self.connect()) as db, db:
            return db.execute("""UPDATE fleet_assistant_requests SET state='RUNNING'
                WHERE principal_id=? AND request_id=? AND state='PENDING'""", (principal, request_id)).rowcount == 1

    def control(self, principal, request_id):
        result = self.read(principal, request_id)
        with closing(self.connect()) as db:
            kind = db.execute('SELECT kind FROM fleet_assistant_requests WHERE principal_id=? AND request_id=?',
                              (principal, request_id)).fetchone()[0]
        if result.state != 'ANSWERED' or kind != 'CONTROL':
            raise HTTPException(409, detail='ASSISTANT_CONTROL_REQUIRED')
        return result, self.message(principal, request_id)

    def finish(self, principal, request_id, *, state, response=None, reason=None, facts=(), kind=None):
        if state not in ('ANSWERED', 'HOLD', 'UNKNOWN'):
            raise ValueError('ASSISTANT_TERMINAL_STATE_REQUIRED')
        result = json.dumps({'response':response, 'reason':reason,
                             'facts':[f.model_dump() for f in facts]}, ensure_ascii=False)
        with closing(self.connect()) as db, db:
            db.execute('''UPDATE fleet_assistant_requests SET state=?, completed_at=?, result_json=?, kind=?
                WHERE principal_id=? AND request_id=? AND state='RUNNING' ''',
                (state, self.clock(), result, kind, principal, request_id))

    def recover(self):
        with closing(self.connect()) as db, db:
            db.execute('''UPDATE fleet_assistant_requests SET state='UNKNOWN',completed_at=?,result_json=?
                WHERE state IN ('PENDING','RUNNING')''', (self.clock(), json.dumps({
                    'reason':'ASSISTANT_RESTARTED', 'response':'처리 결과를 확인하지 못했습니다. 자동 재요청하지 않습니다.'})))
