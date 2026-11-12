"""D-661 team notifications in the Fleet journal; channel receipt is not incident success."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import yaml
from core_common.notification_channels import Channel, send_channel

from fleet.incidents.handoff import judgment_revision
from fleet.incidents.final_review import final_current, final_facts, managed_case
from fleet.incidents.notification_client import (
    RemoteNotificationSink,
    build_delivery_request,
    should_run_embedded_notification_worker,
)


@dataclass(frozen=True)
class NotificationConfig:
    console_url: str
    channels: tuple[Channel, ...]
    remote_url: str | None = field(default=None, compare=False)
    owner_token: str | None = field(default=None, repr=False, compare=False)
    remote_sink: RemoteNotificationSink | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if not isinstance(self.console_url, str):
            raise ValueError('invalid notification Console URL')
        target = urlsplit(self.console_url)
        if (target.scheme != 'https' or not target.hostname or target.username or target.password
                or target.query or target.fragment or target.path != '/console'):
            raise ValueError('notification Console URL must be an HTTPS /console without credentials')
        if not self.channels or len({channel.kind for channel in self.channels}) != len(self.channels):
            raise ValueError('configure one destination per notification channel')

    def route_revision(self, channel):
        return hashlib.sha256((self.console_url + '\0' + channel.fingerprint).encode()).hexdigest()

    @classmethod
    def load(cls, path: Path):
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) != {'console_url', 'channels'} or not isinstance(data['channels'], list):
            raise ValueError('invalid notification configuration')
        channels = []
        for row in data['channels']:
            if (not isinstance(row, dict) or set(row) - {'kind', 'endpoint_env', 'chat_id'}
                    or not isinstance(row.get('endpoint_env'), str)
                    or not re.fullmatch(r'[A-Z][A-Z0-9_]*', row['endpoint_env'])):
                raise ValueError('notification destinations require an endpoint environment variable')
            endpoint = os.environ.get(row['endpoint_env'])
            if not endpoint:
                raise ValueError('configured notification endpoint is missing')
            channels.append(Channel(row.get('kind'), endpoint, row.get('chat_id')))
        return cls(data['console_url'], tuple(channels))


class NotificationOutbox:
    def __init__(self, log):
        self._log = log
        self.config: NotificationConfig | None = None
        self._prepare_receipt = None
        with closing(log._connect()) as connection, connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS fleet_notification_outbox (
                event_id INTEGER PRIMARY KEY, robot_id TEXT NOT NULL, stuck_id TEXT NOT NULL,
                judgment_revision TEXT NOT NULL, kind TEXT NOT NULL, channel TEXT NOT NULL,
                route_hash TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL,
                expires_at REAL NOT NULL, next_attempt_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'PENDING', last_code TEXT, provider_id TEXT,
                last_attempt_at REAL, attempt_id TEXT, delivered_at REAL,
                UNIQUE(robot_id, stuck_id, judgment_revision, kind, channel, route_hash))''')
            connection.execute('CREATE INDEX IF NOT EXISTS fleet_notification_due ON fleet_notification_outbox(state, next_attempt_at)')

    def set_automation(self, prepare_receipt):
        if not callable(prepare_receipt):
            raise ValueError('EXPLICIT_AUTOMATION_PREPARER_REQUIRED')
        self._prepare_receipt = prepare_receipt

    def enqueue_final(self, scope, summary, *, now):
        with closing(self._log._connect()) as connection, connection:
            facts = final_facts(connection, scope, summary, now)
            if self.config is None:
                return False
            revision = hashlib.sha256(facts['scope_json'].encode()).hexdigest()
            self._insert(connection, scope.subject_id, scope.case_id, revision, 'FINAL_REVIEW', now, facts)
            return True

    def enqueue(self, connection, receipt):
        now = receipt['evaluated_at']
        connection.execute('DELETE FROM fleet_notification_outbox WHERE created_at < ?', (now - 7 * 86400,))
        request = receipt['request']
        rid, sid = request.get('subject_id'), request.get('case_id')
        if not all(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', value) for value in (rid, sid)):
            return
        prepared = self._prepare_receipt(connection, receipt) if self._prepare_receipt else False
        parent = managed_case(connection, rid, sid)
        if prepared is True or parent is not None and parent['state'] in ('ACTIVE', 'HOLD'):
            connection.execute("UPDATE fleet_notification_outbox SET state='SUPERSEDED', last_code='AUTOMATION_MANAGED' WHERE robot_id=? AND stuck_id=? AND kind='OPEN' AND state IN ('PENDING','RETRY')", (rid, sid))
            return
        if self.config is None or receipt['necessity'] == 'DO_NOT_INTERVENE':
            return
        now = receipt['evaluated_at']
        self._insert(connection, rid, sid, judgment_revision(receipt), 'OPEN', now,
                     {'necessity': receipt['necessity'], 'reason': receipt['reason'],
                      'observed_at': now, 'shadow': True})

    def closed(self, connection, rid, sid, *, now, reason):
        connection.execute("UPDATE fleet_notification_outbox SET state='SUPERSEDED', last_code='INCIDENT_CLOSED' WHERE robot_id=? AND stuck_id=? AND kind='OPEN' AND state IN ('PENDING','RETRY')", (rid, sid))
        if self.config is not None and connection.execute(
                'SELECT 1 FROM fleet_notification_outbox WHERE robot_id=? AND stuck_id=? LIMIT 1', (rid, sid)).fetchone():
            self._insert(connection, rid, sid, reason, 'CLOSED', now,
                         {'reason': reason, 'observed_at': now, 'action_credit': 'UNVERIFIED'})

    def _insert(self, connection, rid, sid, revision, kind, now, facts):
        owner = connection.execute('SELECT principal_id FROM fleet_incident_claims WHERE robot_id=? AND stuck_id=?',
                                   (rid, sid)).fetchone()
        link = self.config.console_url + '?' + urlencode({'inbox': '1', 'robot': rid, 'incident': sid})
        payload = json.dumps({**facts, 'robot_id': rid, 'stuck_id': sid, 'kind': kind,
                              'owner': owner['principal_id'] if owner else None, 'expires_at': now + 600,
                              'console_link': link}, allow_nan=False)
        for channel in self.config.channels:
            connection.execute('''INSERT OR IGNORE INTO fleet_notification_outbox (
                robot_id, stuck_id, judgment_revision, kind, channel, route_hash, payload,
                created_at, expires_at, next_attempt_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (rid, sid, revision, kind, channel.kind, self.config.route_revision(channel), payload, now, now + 600, now))
        connection.execute('DELETE FROM fleet_notification_outbox WHERE created_at < ?', (now - 7 * 86400,))

    def rows(self, limit=100, *, robot_id=None, stuck_id=None):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('notification limit must be between 1 and 1000')
        with closing(self._log._connect()) as connection:
            where, params = ('', []) if robot_id is None else (' WHERE robot_id=? AND stuck_id=?', [robot_id, stuck_id])
            rows = connection.execute('''SELECT event_id, robot_id, stuck_id, kind, channel, state,
                created_at, expires_at, next_attempt_at, attempts, last_code, provider_id, delivered_at
                FROM fleet_notification_outbox''' + where + ' ORDER BY event_id DESC LIMIT ?', (*params, limit)).fetchall()
        return [dict(row) for row in rows]

    def claim_due(self, now, config):
        routes = {channel.kind: config.route_revision(channel) for channel in config.channels}
        with closing(self._log._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute("UPDATE fleet_notification_outbox SET state='UNKNOWN', last_code='WORKER_OUTCOME_UNKNOWN' WHERE state='SENDING' AND last_attempt_at <= ?", (now - 30,))
            connection.execute("UPDATE fleet_notification_outbox SET state='EXPIRED', last_code='DELIVERY_EXPIRED' WHERE state IN ('PENDING','RETRY') AND expires_at <= ?", (now,))
            rows = connection.execute("SELECT * FROM fleet_notification_outbox WHERE state IN ('PENDING','RETRY') AND next_attempt_at <= ? ORDER BY event_id", (now,)).fetchall()
            for row in rows:
                invalid = routes.get(row['channel']) != row['route_hash']
                if row['kind'] == 'OPEN':
                    parent = managed_case(connection, row['robot_id'], row['stuck_id'])
                    invalid |= parent is not None and parent['state'] in ('ACTIVE', 'HOLD')
                    episode = connection.execute('SELECT closed_at FROM fleet_line_stuck_episodes WHERE robot_id=? AND stuck_id=?', (row['robot_id'], row['stuck_id'])).fetchone()
                    current = connection.execute('SELECT assessment FROM fleet_judgment_current WHERE robot_id=?', (row['robot_id'],)).fetchone()
                    receipt = json.loads(current['assessment']) if current else None
                    owner = connection.execute('SELECT 1 FROM fleet_incident_claims WHERE robot_id=? AND stuck_id=?', (row['robot_id'], row['stuck_id'])).fetchone()
                    invalid |= (episode is None or episode['closed_at'] is not None or receipt is None
                                or receipt['request'].get('case_id') != row['stuck_id']
                                or judgment_revision(receipt) != row['judgment_revision'] or owner is not None)
                    if not invalid and not 0 <= now - receipt['evaluated_at'] <= 3:
                        continue
                elif row['kind'] == 'FINAL_REVIEW':
                    current = final_current(connection, row['robot_id'], row['stuck_id'],
                                            json.loads(row['payload'])['scope_json'], now)
                    if not invalid and current is None:
                        continue
                    invalid |= current is False
                if invalid:
                    connection.execute("UPDATE fleet_notification_outbox SET state='SUPERSEDED', last_code='INCIDENT_OR_ROUTE_CHANGED' WHERE event_id=?", (row['event_id'],))
                    continue
                recent = connection.execute('SELECT MAX(last_attempt_at) FROM fleet_notification_outbox WHERE channel=?', (row['channel'],)).fetchone()[0]
                if recent is not None and now - recent < 60:
                    continue
                attempt_id = uuid.uuid4().hex
                connection.execute("UPDATE fleet_notification_outbox SET state='SENDING', attempts=attempts+1, last_attempt_at=?, attempt_id=? WHERE event_id=?",
                                   (now, attempt_id, row['event_id']))
                return {**dict(row), 'state': 'SENDING', 'attempts': row['attempts'] + 1, 'attempt_id': attempt_id}
        return None

    def defer(self, row, *, now):
        with closing(self._log._connect()) as connection, connection:
            connection.execute("UPDATE fleet_notification_outbox SET state='PENDING', attempts=attempts-1, next_attempt_at=?, last_attempt_at=NULL, last_code='AWAITING_FRESH_OBSERVATION' WHERE event_id=? AND state='SENDING' AND attempt_id=?",
                               (now + 1, row['event_id'], row['attempt_id']))

    def finish(self, row, state, code, *, now, provider_id=None, retry_after=60):
        if state == 'RETRY' and (row['attempts'] >= 3 or now + retry_after >= row['expires_at']):
            state = 'FAILED'
        with closing(self._log._connect()) as connection, connection:
            connection.execute('''UPDATE fleet_notification_outbox SET state=?, last_code=?, provider_id=?,
                next_attempt_at=?, delivered_at=? WHERE event_id=? AND state='SENDING' AND attempt_id=?''',
                (state, code, provider_id, now + retry_after, now if state == 'SENT' else None,
                 row['event_id'], row['attempt_id']))


class NotificationWorker:
    def __init__(self, outbox, config, http, *, board, snapshot=None, clock=time.time,
                 sink: RemoteNotificationSink | None = None):
        self.outbox, self.config, self.http = outbox, config, http
        self.board = board
        self.snapshot, self.clock = snapshot, clock
        self.sink = sink

    @staticmethod
    def _render_text(row, facts) -> str:
        text = (f"ROSY {facts['kind']} · {facts['robot_id']} · {facts['stuck_id']}\n"
                f"{facts.get('necessity', '관측 종료')} · {facts['reason']}\n"
                f"담당: {facts['owner'] or '미인수'} · 관측: {facts['observed_at']} · 통지 기한: {facts['expires_at']}\n"
                f"검토 알림 · 조치 허가/실제 해소는 별도 확인\n{facts['console_link']}")
        if row['kind'] == 'FINAL_REVIEW':
            text += (f"\n자동 처리: 호출 {facts['calls']} · 관측 {facts['observations']}"
                     f" · 비용 상태 {facts['cost_status']} · 기록/예약 microUSD "
                     f"{facts['spent_micros']}/{facts['reserved_micros']}"
                     f"\n프로파일 {facts['profile_sha256']} · 관측 {facts['observation_revision']}"
                     f"\n정책 원래 {facts['original_policy_revision']} · 현재 {facts['current_policy_revision']}")
        return text

    async def _verify_dequeued(self, row, facts) -> bool:
        if self.clock() >= row['expires_at']:
            await asyncio.to_thread(self.outbox.finish, row, 'EXPIRED', 'DELIVERY_EXPIRED_BEFORE_HTTP', now=self.clock())
            return False
        # Event-loop state is checked after dequeue; no await separates this check and HTTP entry.
        if row['kind'] in ('OPEN', 'FINAL_REVIEW'):
            receipt = self.board.judgment_view(row['robot_id'])
            with closing(self.outbox._log._connect()) as connection:
                parent = managed_case(connection, row['robot_id'], row['stuck_id'])
                ledger_current = (final_current(connection, row['robot_id'], row['stuck_id'], facts['scope_json'],
                                                self.clock(), receipt=receipt) if row['kind'] == 'FINAL_REVIEW'
                                  else parent is None or parent['state'] not in ('ACTIVE', 'HOLD'))
            if (ledger_current is None and self.board.is_open(row['robot_id'], row['stuck_id'])
                    and (row['robot_id'], row['stuck_id']) not in self.board._handoff_pending):
                await asyncio.to_thread(self.outbox.defer, row, now=self.clock())
                return False
            if (not self.board.is_open(row['robot_id'], row['stuck_id']) or receipt is None
                    or not ledger_current or row['kind'] == 'OPEN' and judgment_revision(receipt) != row['judgment_revision']
                    or (row['robot_id'], row['stuck_id']) in self.board._handoff_pending):
                await asyncio.to_thread(self.outbox.finish, row, 'SUPERSEDED', 'INCIDENT_CHANGED_BEFORE_HTTP', now=self.clock())
                return False
        return True

    async def verify_delivery_owner(self, _profile, request) -> bool | None:
        if self.clock() >= request.expires_at:
            return False
        if request.kind in ('OPEN', 'FINAL_REVIEW'):
            receipt = self.board.judgment_view(request.subject_id)
            if not self.board.is_open(request.subject_id, request.occurrence_id):
                return False
            if (request.subject_id, request.occurrence_id) in self.board._handoff_pending or receipt is None:
                return False
            with closing(self.outbox._log._connect()) as connection:
                owner = connection.execute(
                    'SELECT 1 FROM fleet_incident_claims WHERE robot_id=? AND stuck_id=?',
                    (request.subject_id, request.occurrence_id),
                ).fetchone()
                if owner is not None:
                    return False
                if request.kind == 'OPEN':
                    parent = managed_case(connection, request.subject_id, request.occurrence_id)
                    if parent is not None and parent['state'] in ('ACTIVE', 'HOLD'):
                        return False
                    if judgment_revision(receipt) != request.revision:
                        return False
        return True

    async def forward_once(self, sink: RemoteNotificationSink | None = None):
        target_sink = sink or self.sink
        if target_sink is None:
            raise ValueError('remote notification sink required')
        if self.snapshot is not None:
            await self.snapshot()
        for _ in self.config.channels:
            row = await asyncio.to_thread(self.outbox.claim_due, self.clock(), self.config)
            if row is None:
                break
            facts = json.loads(row['payload'])
            if not await self._verify_dequeued(row, facts):
                continue
            payload = build_delivery_request(row, facts)
            try:
                receipt_data = await asyncio.to_thread(target_sink.submit_delivery, payload)
            except asyncio.CancelledError:
                await asyncio.shield(asyncio.to_thread(self.outbox.finish, row, 'UNKNOWN', 'WORKER_CANCELLED', now=self.clock()))
                raise
            except Exception:
                await asyncio.to_thread(self.outbox.finish, row, 'UNKNOWN', 'REMOTE_DELIVERY_UNKNOWN', now=self.clock())
                continue
            remote_state = receipt_data.get('state') if isinstance(receipt_data, dict) else None
            remote_id = receipt_data.get('notification_id') if isinstance(receipt_data, dict) else None
            if remote_state in ('PENDING', 'RETRY', 'SENDING', 'SENT') and remote_id == payload['notification_id']:
                await asyncio.to_thread(
                    self.outbox.finish,
                    row,
                    'SENT',
                    'REMOTE_ACCEPTED',
                    now=self.clock(),
                    provider_id=remote_id,
                )
            elif remote_state in ('EXPIRED', 'SUPERSEDED', 'FAILED'):
                await asyncio.to_thread(
                    self.outbox.finish,
                    row,
                    remote_state,
                    f'REMOTE_{remote_state}',
                    now=self.clock(),
                    provider_id=remote_id,
                )
            else:
                await asyncio.to_thread(
                    self.outbox.finish,
                    row,
                    'UNKNOWN',
                    'REMOTE_DELIVERY_UNKNOWN',
                    now=self.clock(),
                    provider_id=remote_id,
                )

    async def run_once(self):
        if self.sink is not None:
            await self.forward_once(self.sink)
            return
        if self.snapshot is not None:
            await self.snapshot()
        for _ in self.config.channels:
            row = await asyncio.to_thread(self.outbox.claim_due, self.clock(), self.config)
            if row is None:
                break
            channel = next(channel for channel in self.config.channels if channel.kind == row['channel'])
            facts = json.loads(row['payload'])
            text = self._render_text(row, facts)
            if not await self._verify_dequeued(row, facts):
                continue
            try:
                state, code, provider_id, retry_after = await send_channel(self.http, channel, text)
            except asyncio.CancelledError:
                await asyncio.shield(asyncio.to_thread(self.outbox.finish, row, 'UNKNOWN', 'WORKER_CANCELLED', now=self.clock()))
                raise
            await asyncio.to_thread(self.outbox.finish, row, state, code, now=self.clock(),
                                    provider_id=provider_id, retry_after=retry_after)

    async def run(self):
        if not should_run_embedded_notification_worker(
            getattr(self.config, 'remote_url', None) or os.environ.get('ROSY_NOTIFICATIONS_URL')
        ):
            return
        while True:
            try:
                await self.run_once()
            except Exception as error:
                logging.getLogger(__name__).warning('notification scan failed (%s)', type(error).__name__)
            await asyncio.sleep(1)
