"""Fleet-owned Discord reply journal in the existing tasks database."""
import hashlib
import json
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
        request_id = receipt['request_id']
        nonce = hashlib.sha256(f'{request_id}:RECEIVED'.encode()).hexdigest()[:24]
        now = self.clock()
        # Same connection makes receipt and its reply intent one durable commit.
        conn.execute('''INSERT OR IGNORE INTO fleet_channel_reply_outbox
            (request_id, kind, nonce, principal_id, message_id, route_hash, content,
             next_attempt_at, expires_at) VALUES (?, 'RECEIVED', ?, ?, ?, ?, ?, ?, ?)''',
            (request_id, nonce, receipt['principal_id'], receipt['message_id'], self.route_hash(),
             f'ROSY 요청 접수 · {request_id}\nFleet Console에서 확인합니다. 실행 승인 전입니다.', now, now + 600))

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
