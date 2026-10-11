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
                     f"ROSY 요청 접수 · {receipt['request_id']}\nFleet Console에서 확인합니다. 실행 승인 전입니다.")

    def enqueue(self, conn, receipt, kind, content):
        request_id = receipt['request_id']
        nonce = hashlib.sha256(f'{request_id}:{kind}'.encode()).hexdigest()[:24]
        now = self.clock()
        # Same connection makes receipt and its reply intent one durable commit.
        conn.execute('''INSERT OR IGNORE INTO fleet_channel_reply_outbox
            (request_id, kind, nonce, principal_id, message_id, route_hash, content,
             next_attempt_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                     (request_id, kind, nonce, receipt['principal_id'], receipt['message_id'], self.route_hash(),
                      content, now, now + 600))

    def observe_results(self):
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'fleet_channel_workflow', 'fleet_tasks'} <= tables:
                return
            rows = conn.execute('''SELECT r.receipt, t.status, w.work_id
                FROM fleet_channel_workflow w JOIN fleet_channel_requests r
                  ON json_extract(r.receipt, '$.request_id')=w.request_id
                JOIN fleet_tasks t ON t.task_id=w.work_id
                WHERE w.state='LINKED' AND t.status IN ('COMPLETED','FAILED','HOLD','CANCELED','EXPIRED','UNKNOWN')
                  AND NOT EXISTS (SELECT 1 FROM fleet_channel_reply_outbox o
                    WHERE o.request_id=w.request_id AND o.kind='TASK:' || t.status)
                ORDER BY t.updated_at LIMIT 50''').fetchall()
            for receipt, status, task_id in rows:
                receipt = json.loads(receipt)
                self.enqueue(conn, receipt, 'TASK:' + status,
                             f"ROSY 작업 원장 · {receipt['request_id']}\nTask {task_id} · {status}"
                             + ('\n실행 결과 미확인입니다. Console에서 확인하세요.' if status == 'UNKNOWN' else ''))

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
                    self.journal.operator(row['principal_id'])
                except HTTPException:
                    current = False
                else:
                    current = row['route_hash'] == self.route_hash()
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
            self.outbox.journal.operator(row['principal_id'])
            if row['route_hash'] != self.outbox.route_hash() or self.clock() >= row['expires_at']:
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
