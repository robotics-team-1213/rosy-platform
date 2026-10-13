"""Fleet-owned Discord reply journal in the existing tasks database."""
import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from contextlib import closing
from uuid import uuid4

from fastapi import HTTPException


class ChannelReplyOutbox:
    def __init__(self, journal, *, clock=time.time):
        self.journal, self.clock = journal, clock
        with closing(journal._connect()) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_channel_reply_outbox (
                request_id TEXT NOT NULL, kind TEXT NOT NULL, nonce TEXT NOT NULL,
                principal_id TEXT NOT NULL, message_id TEXT NOT NULL, route_hash TEXT NOT NULL,
                content TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING',
                attempts INTEGER NOT NULL DEFAULT 0, attempt_id TEXT,
                next_attempt_at REAL NOT NULL, last_attempt_at REAL, expires_at REAL NOT NULL,
                provider_id TEXT, PRIMARY KEY(request_id, kind))''')

    def route_hash(self):
        cfg = self.journal.config
        value = (cfg.guild_id, cfg.channel_id, cfg.bot_id, sorted(cfg.users.items()))
        return hashlib.sha256(json.dumps(value).encode()).hexdigest()

    def received(self, conn, receipt):
        self.enqueue(conn, receipt, 'RECEIVED',
                     f"ROSY 요청 접수 · {receipt['request_id']}\n요청을 받았습니다. 처리 상태는 Fleet Console에서도 확인할 수 있습니다.")

    def enqueue(self, conn, receipt, kind, content):
        self.journal.current_receipt(receipt)
        self._insert(conn, receipt, kind, content, 'PENDING')

    def _insert(self, conn, receipt, kind, content, state):
        request_id = receipt['request_id']
        nonce = hashlib.sha256(f'{request_id}:{kind}'.encode()).hexdigest()[:24]
        now = self.clock()
        # Same connection makes receipt and its reply intent one durable commit.
        conn.execute('''INSERT OR IGNORE INTO fleet_channel_reply_outbox
            (request_id, kind, nonce, principal_id, message_id, route_hash, content,
             state, next_attempt_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                     (request_id, kind, nonce, receipt['principal_id'], receipt['message_id'], self.route_hash(),
                      content, state, now, now + 600))

    def observe_results(self):
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'fleet_channel_workflow' not in tables:
                return
            for kind, table, key, states in (
                ('task', 'fleet_tasks', 'task_id', ('COMPLETED', 'FAILED', 'HOLD', 'CANCELED', 'EXPIRED', 'UNKNOWN')),
                ('mission', 'fleet_missions', 'mission_id', ('ACTION_SUCCEEDED', 'GOAL_CONFIRMED', 'HOLD')),
                ('cell_job', 'fleet_cell_jobs', 'mission_id', ('ACTION_SUCCEEDED', 'GOAL_CONFIRMED', 'HOLD')),
            ):
                if table not in tables:
                    continue
                prefix = kind.upper() + ':'
                placeholders = ','.join('?' for _ in states)
                rows = conn.execute(f'''SELECT r.receipt, t.status, w.work_id
                    FROM fleet_channel_workflow w JOIN fleet_channel_requests r
                      ON json_extract(r.receipt, '$.request_id')=w.request_id
                    JOIN {table} t ON t.{key}=w.work_id
                    WHERE w.state='LINKED' AND w.work_kind=? AND t.status IN ({placeholders})
                      AND NOT EXISTS (SELECT 1 FROM fleet_channel_reply_outbox o
                        WHERE o.request_id=w.request_id AND o.kind=? || t.status)
                    ORDER BY t.updated_at LIMIT 50''', (kind, *states, prefix)).fetchall()
                self._results(conn, rows, prefix, 'Task' if kind == 'task' else kind)
            if {'fleet_channel_incidents', 'fleet_line_stuck_episodes', 'fleet_incident_claims'} <= tables:
                rows = conn.execute('''SELECT r.receipt, 'CLOSED', w.work_id
                    FROM fleet_channel_workflow w JOIN fleet_channel_requests r
                      ON json_extract(r.receipt, '$.request_id')=w.request_id
                    JOIN fleet_channel_incidents i ON i.request_id=w.request_id
                    JOIN fleet_line_stuck_episodes e USING(robot_id, stuck_id)
                    JOIN fleet_incident_claims c USING(robot_id, stuck_id)
                    WHERE w.state='LINKED' AND w.work_kind='incident' AND e.closed_at IS NOT NULL
                      AND c.principal_id=r.principal_id
                      AND NOT EXISTS (SELECT 1 FROM fleet_channel_reply_outbox o
                        WHERE o.request_id=w.request_id AND o.kind='INCIDENT:CLOSED')
                    ORDER BY e.closed_at LIMIT 50''').fetchall()
                self._results(conn, rows, 'INCIDENT:', '사건')

    def _results(self, conn, rows, prefix, label):
        for receipt, status, work_id in rows:
            receipt = json.loads(receipt)
            try:
                self.journal.current_receipt(receipt)
            except HTTPException:
                self._insert(conn, receipt, prefix + status, '', 'SUPERSEDED')
                continue
            note = ('\n사건 종료 관측입니다. 장치·목표 성공은 별도 확인합니다.' if prefix == 'INCIDENT:' else
                    '\n실행 결과 미확인입니다. Console에서 확인하세요.' if status == 'UNKNOWN' else
                    '\n장치 동작 완료 · 목표 확인 대기입니다.' if status == 'ACTION_SUCCEEDED' else '')
            self.enqueue(conn, receipt, prefix + status,
                         f"ROSY 작업 원장 · {receipt['request_id']}\n{label} {work_id} · {status}" + note)

    def current(self, row, conn=None):
        if conn is None:
            with closing(self.journal._connect()) as connection:
                return self.current(row, connection)
        receipt = conn.execute("SELECT receipt FROM fleet_channel_requests WHERE principal_id=? "
                               "AND json_extract(receipt, '$.request_id')=?",
                               (row['principal_id'], row['request_id'])).fetchone()
        if receipt is None:
            raise HTTPException(403, detail='CHANNEL_OWNER_CHANGED')
        receipt = json.loads(receipt[0])
        self.journal.current_receipt(receipt)
        return row['route_hash'] == self.route_hash() and row['message_id'] == receipt['message_id']

    def claim(self, *, now):
        with closing(self.journal._connect()) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE fleet_channel_reply_outbox SET state='UNKNOWN' "
                         "WHERE state='SENDING' AND last_attempt_at <= ?", (now - 30,))
            conn.execute("UPDATE fleet_channel_reply_outbox SET state='EXPIRED' "
                         "WHERE state IN ('PENDING','RETRY') AND expires_at <= ?", (now,))
            rows = conn.execute("SELECT * FROM fleet_channel_reply_outbox WHERE "
                                "state IN ('PENDING','RETRY') AND next_attempt_at <= ? "
                                "ORDER BY next_attempt_at LIMIT 50", (now,)).fetchall()
            for row in rows:
                try:
                    current = self.current(row, conn)
                except HTTPException:
                    current = False
                if not current:
                    conn.execute("UPDATE fleet_channel_reply_outbox SET state='SUPERSEDED' "
                                 "WHERE request_id=? AND kind=?", (row['request_id'], row['kind']))
                    continue
                attempt_id = uuid4().hex
                conn.execute("UPDATE fleet_channel_reply_outbox SET state='SENDING', "
                             "attempts=attempts+1, attempt_id=?, last_attempt_at=? "
                             "WHERE request_id=? AND kind=?", (attempt_id, now, row['request_id'], row['kind']))
                return {**dict(row), 'state': 'SENDING', 'attempt_id': attempt_id,
                        'attempts': row['attempts'] + 1, 'last_attempt_at': now}
        return None

    def finish(self, row, *, state, provider_id, now):
        if state not in {'SENT', 'RETRY', 'FAILED', 'UNKNOWN'}:
            raise ValueError('invalid Discord delivery outcome')
        if state == 'RETRY' and (row['attempts'] >= 3 or now + 60 >= row['expires_at']):
            state = 'FAILED'
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('''UPDATE fleet_channel_reply_outbox
                SET state=?, provider_id=?, next_attempt_at=?
                WHERE request_id=? AND kind=? AND state='SENDING' AND attempt_id=?''',
                         (state, provider_id, now + 60, row['request_id'], row['kind'], row['attempt_id']))

    def rows(self, principal):
        self.journal.operator(principal)
        with closing(self.journal._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('''SELECT request_id, kind, state, attempts, provider_id
                FROM fleet_channel_reply_outbox WHERE principal_id=? ORDER BY rowid DESC LIMIT 50''',
                                (principal,)).fetchall()
        return [dict(row) for row in rows]


class ChannelReplyWorker:
    def __init__(self, outbox, sender, *, clock=time.time):
        self.outbox, self.sender, self.clock = outbox, sender, clock

    async def run_once(self):
        await asyncio.to_thread(self.outbox.observe_results)
        row = await asyncio.to_thread(self.outbox.claim, now=self.clock())
        if row is None:
            return
        result = {'state': 'UNKNOWN', 'provider_id': None}
        try:
            if not self.outbox.current(row) or self.clock() >= row['expires_at']:
                raise ValueError('Discord reply scope expired or changed')
            result = await self.sender.send(message_id=row['message_id'], nonce=row['nonce'], content=row['content'])
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self.outbox.finish, row, now=self.clock(), **result))
            raise
        except (HTTPException, OSError, ValueError):
            pass
        await asyncio.to_thread(self.outbox.finish, row, now=self.clock(), **result)

    async def run(self):
        while True:
            try:
                await self.run_once()
            except Exception as error:
                logging.getLogger(__name__).warning('Discord reply scan failed (%s)', type(error).__name__)
            await asyncio.sleep(1)
