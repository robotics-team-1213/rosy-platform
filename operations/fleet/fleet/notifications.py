"""D-661 team notifications in the Fleet journal; channel receipt is not incident success."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
import yaml

from fleet.stuck.handoff import judgment_revision


class _RedactProviderURL(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        cleaned = re.sub(r'https://(?:discord\.com/api/webhooks/|hooks\.slack\.com/services/|api\.telegram\.org/bot)[^\s"\']+',
                         '[notification destination redacted]', message)
        if cleaned != message:
            record.msg, record.args = cleaned, ()
        return True


logging.getLogger('httpx').addFilter(_RedactProviderURL())


@dataclass(frozen=True)
class Channel:
    kind: str
    endpoint: str = field(repr=False)
    chat_id: str | int | None = field(default=None, repr=False)

    def __post_init__(self):
        if not isinstance(self.endpoint, str):
            raise ValueError('invalid notification destination')
        patterns = {
            'discord': ('discord.com', r'/api/webhooks/[0-9]+/[A-Za-z0-9_.-]+'),
            'slack': ('hooks.slack.com', r'/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+'),
            'telegram': ('api.telegram.org', r'/bot[0-9]+:[A-Za-z0-9_-]+/sendMessage'),
        }
        target = urlsplit(self.endpoint)
        expected = patterns.get(self.kind)
        if (expected is None or target.scheme != 'https' or target.netloc != expected[0]
                or target.query or target.fragment or not re.fullmatch(expected[1], target.path)
                or (self.kind == 'telegram' and (type(self.chat_id) not in (str, int)
                    or not re.fullmatch(r'-?[0-9]+|@[A-Za-z0-9_]+', str(self.chat_id))))):
            raise ValueError('invalid notification destination')

    @property
    def fingerprint(self):
        return hashlib.sha256((self.endpoint + '\0' + str(self.chat_id or '')).encode()).hexdigest()


@dataclass(frozen=True)
class NotificationConfig:
    console_url: str
    channels: tuple[Channel, ...]

    def __post_init__(self):
        if not isinstance(self.console_url, str):
            raise ValueError('invalid notification Console URL')
        target = urlsplit(self.console_url)
        if (target.scheme != 'https' or not target.hostname or target.username or target.password
                or target.query or target.fragment or target.path != '/console'):
            raise ValueError('notification Console URL must be an HTTPS /console without credentials')
        if not self.channels or len({channel.kind for channel in self.channels}) != len(self.channels):
            raise ValueError('configure one destination per notification channel')

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

    def enqueue(self, connection, receipt):
        if self.config is None or receipt['necessity'] == 'DO_NOT_INTERVENE':
            return
        request = receipt['request']
        rid, sid = request.get('subject_id'), request.get('case_id')
        if not all(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', value) for value in (rid, sid)):
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
                (rid, sid, revision, kind, channel.kind, channel.fingerprint, payload, now, now + 600, now))
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
        routes = {channel.kind: channel.fingerprint for channel in config.channels}
        with closing(self._log._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute("UPDATE fleet_notification_outbox SET state='UNKNOWN', last_code='WORKER_OUTCOME_UNKNOWN' WHERE state='SENDING' AND last_attempt_at <= ?", (now - 30,))
            connection.execute("UPDATE fleet_notification_outbox SET state='EXPIRED', last_code='DELIVERY_EXPIRED' WHERE state IN ('PENDING','RETRY') AND expires_at <= ?", (now,))
            rows = connection.execute("SELECT * FROM fleet_notification_outbox WHERE state IN ('PENDING','RETRY') AND next_attempt_at <= ? ORDER BY event_id", (now,)).fetchall()
            for row in rows:
                invalid = routes.get(row['channel']) != row['route_hash']
                if row['kind'] == 'OPEN':
                    episode = connection.execute('SELECT closed_at FROM fleet_line_stuck_episodes WHERE robot_id=? AND stuck_id=?', (row['robot_id'], row['stuck_id'])).fetchone()
                    current = connection.execute('SELECT assessment FROM fleet_judgment_current WHERE robot_id=?', (row['robot_id'],)).fetchone()
                    receipt = json.loads(current['assessment']) if current else None
                    owner = connection.execute('SELECT 1 FROM fleet_incident_claims WHERE robot_id=? AND stuck_id=?', (row['robot_id'], row['stuck_id'])).fetchone()
                    invalid |= (episode is None or episode['closed_at'] is not None or receipt is None
                                or receipt['request'].get('case_id') != row['stuck_id']
                                or judgment_revision(receipt) != row['judgment_revision'] or owner is not None)
                    if not invalid and not 0 <= now - receipt['evaluated_at'] <= 3:
                        continue
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

    def finish(self, row, state, code, *, now, provider_id=None, retry_after=60):
        if state == 'RETRY' and (row['attempts'] >= 3 or now + retry_after >= row['expires_at']):
            state = 'FAILED'
        with closing(self._log._connect()) as connection, connection:
            connection.execute('''UPDATE fleet_notification_outbox SET state=?, last_code=?, provider_id=?,
                next_attempt_at=?, delivered_at=? WHERE event_id=? AND state='SENDING' AND attempt_id=?''',
                (state, code, provider_id, now + retry_after, now if state == 'SENT' else None,
                 row['event_id'], row['attempt_id']))


class NotificationWorker:
    def __init__(self, outbox, config, http, *, snapshot=None, clock=time.time):
        self.outbox, self.config, self.http = outbox, config, http
        self.snapshot, self.clock = snapshot, clock

    async def run_once(self):
        if self.snapshot is not None:
            await self.snapshot()
        for _ in self.config.channels:
            row = await asyncio.to_thread(self.outbox.claim_due, self.clock(), self.config)
            if row is None:
                break
            channel = next(channel for channel in self.config.channels if channel.kind == row['channel'])
            facts = json.loads(row['payload'])
            text = (f"ROSY {facts['kind']} · {facts['robot_id']} · {facts['stuck_id']}\n"
                    f"{facts.get('necessity', '관측 종료')} · {facts['reason']}\n"
                    f"담당: {facts['owner'] or '미인수'} · 관측: {facts['observed_at']} · 통지 기한: {facts['expires_at']}\n"
                    f"검토 알림 · 조치 허가/실제 해소는 별도 확인\n{facts['console_link']}")
            payload = {'content': text, 'allowed_mentions': {'parse': []}, 'flags': 4}
            params = {'wait': 'true'} if channel.kind == 'discord' else None
            if channel.kind == 'slack':
                payload = {'text': text, 'blocks': [{'type': 'section', 'text': {'type': 'plain_text', 'text': text}}],
                           'unfurl_links': False, 'unfurl_media': False}
            elif channel.kind == 'telegram':
                payload = {'chat_id': channel.chat_id, 'text': text, 'link_preview_options': {'is_disabled': True}}
            state, code, provider_id, retry_after = 'UNKNOWN', 'PROVIDER_OUTCOME_UNKNOWN', None, 60
            try:
                response = await self.http.post(channel.endpoint, json=payload, params=params,
                                                timeout=5, follow_redirects=False)
                if response.status_code == 429:
                    state, code = 'RETRY', 'PROVIDER_RATE_LIMIT'
                    delay = response.headers.get('Retry-After', '60')
                    if channel.kind == 'telegram':
                        delay = response.json().get('parameters', {}).get('retry_after', delay)
                    try:
                        delay = float(delay)
                        retry_after = max(60, delay) if math.isfinite(delay) else 60
                    except (ValueError, TypeError):
                        pass
                elif response.status_code == 200:
                    if channel.kind == 'slack' and response.text.strip() == 'ok':
                        state, code = 'SENT', 'PROVIDER_ACCEPTED'
                    elif channel.kind == 'discord':
                        provider_id = response.json().get('id')
                        if isinstance(provider_id, str) and re.fullmatch(r'[0-9]{1,32}', provider_id):
                            state, code = 'SENT', 'PROVIDER_ACCEPTED'
                        else:
                            provider_id = None
                    elif channel.kind == 'telegram':
                        body = response.json()
                        value = (body.get('result') or {}).get('message_id')
                        if body.get('ok') is True and type(value) is int and value >= 0:
                            provider_id, state, code = str(value), 'SENT', 'PROVIDER_ACCEPTED'
                elif 400 <= response.status_code < 500:
                    state, code = 'FAILED', 'PROVIDER_REFUSED'
            except (httpx.ConnectError, httpx.ConnectTimeout):
                state, code = 'RETRY', 'PROVIDER_UNREACHABLE'
            except asyncio.CancelledError:
                await asyncio.shield(asyncio.to_thread(self.outbox.finish, row, 'UNKNOWN', 'WORKER_CANCELLED', now=self.clock()))
                raise
            except (httpx.HTTPError, OSError, ValueError, TypeError, AttributeError):
                pass
            await asyncio.to_thread(self.outbox.finish, row, state, code, now=self.clock(),
                                    provider_id=provider_id, retry_after=retry_after)

    async def run(self):
        while True:
            try:
                await self.run_once()
            except Exception as error:
                logging.getLogger(__name__).warning('notification scan failed (%s)', type(error).__name__)
            await asyncio.sleep(1)
