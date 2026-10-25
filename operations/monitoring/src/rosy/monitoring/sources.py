"""Read registered owner outputs; never call operational gather or repair endpoints."""

import asyncio
from datetime import datetime, timezone
import json
import math
import os
import socket
import ssl
import stat
import time
from urllib.parse import urlsplit

import httpx
from core_common.protocol.monitoring import FleetMonitoringRead

from .models import MonitoringLink, MonitoringNode, MonitoringSnapshot


BODY_LIMIT = 1024 * 1024


class SourceFailure(ValueError):
    def __init__(self, stage):
        self.stage = stage
        super().__init__('monitoring source unavailable')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceFailure('protocol')
        result[key] = value
    return result


def decode(data):
    if len(data) > BODY_LIMIT:
        raise SourceFailure('protocol')
    def invalid(_):
        raise SourceFailure('protocol')
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise SourceFailure('protocol')
        return number
    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=_unique,
                           parse_constant=invalid, parse_float=finite)
    except RecursionError:
        raise SourceFailure('protocol') from None
    if not isinstance(value, dict):
        raise SourceFailure('protocol')
    return value


def _read_file(path):
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise SourceFailure('source')
        return decode(stream.read(BODY_LIMIT + 1))


def _stage(error):
    if isinstance(error, SourceFailure):
        return error.stage
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return 'timeout'
    cause = error
    for _ in range(8):
        if isinstance(cause, ssl.SSLError):
            return 'tls'
        if isinstance(cause, socket.gaierror):
            return 'dns'
        cause = cause.__cause__ or cause.__context__
        if cause is None:
            break
    if isinstance(error, httpx.ConnectError):
        return 'connect'
    if isinstance(error, OSError):
        return 'source'
    return 'protocol'


class SourceReader:
    def __init__(self, cache, credentials, *, transport=None):
        self.cache, self.credentials, self.transport = cache, credentials, transport
        self.verify = ssl.create_default_context(cafile=cache.config.ca_bundle)
        self._files = {}

    async def _file(self, source):
        task = self._files.get(source.id)
        if task is None:
            if len(self._files) >= 8:
                raise SourceFailure('timeout')
            task = asyncio.create_task(asyncio.to_thread(_read_file, source.path))
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            self._files[source.id] = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._files.pop(source.id, None)

    async def _get(self, client, url):
        async with client.stream('GET', url) as response:
            if response.status_code in {401, 403}:
                raise SourceFailure('auth')
            if response.status_code != 200:
                raise SourceFailure('http')
            if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                raise SourceFailure('protocol')
            data = bytearray()
            async for chunk in response.aiter_raw():
                data.extend(chunk)
                if len(data) > BODY_LIMIT:
                    raise SourceFailure('protocol')
            return decode(data)

    def _metadata(self, source, *, captured=None, ttl=15, age=0.0):
        wall = self.cache._wall()
        captured = captured or wall
        delta = (wall - captured).total_seconds()
        if delta < -1 or not math.isfinite(age) or age < 0:
            raise SourceFailure('protocol')
        age = max(age, delta, 0.0)
        remaining = max(0.0, ttl - age)
        return dict(site_id=source.site_id, origin_collector=self.cache.config.collector_id,
                    origin_source=source.id, sample_id=captured.isoformat().replace('+', ':'),
                    sampled_at=captured, age_s=float(age), valid_for_s=ttl, remaining_s=float(remaining),
                    report_remaining_s=15.0, freshness='fresh' if remaining else 'stale')

    def _node(self, source, health, metadata, *, kind=None, suffix=None):
        kind = kind or {'core': 'robot', 'fleet': 'fleet', 'http': 'service'}.get(source.kind, 'host')
        return MonitoringNode(id=f'{source.site_id}:{kind}:{suffix or source.id}', kind=kind,
                              label=(suffix or source.label or source.id)[:80], reported_health=health, **metadata)

    def _probe(self, source, *, site, target, elapsed, stage='none'):
        metadata = self._metadata(source)
        metadata['site_id'] = site
        return MonitoringLink(id=f'{site}:probe:{self.cache.config.collector_id}:{source.id}',
                              source_id=f'{site}:collector:{self.cache.config.collector_id}',
                              target_id=target, kind='probe', expected=True, reachable=stage == 'none',
                              failure_stage=stage, duration_ms=float(elapsed * 1000),
                              transport=urlsplit(source.url).scheme if source.url else 'file',
                              reason_code=None if stage == 'none' else f'MONITORING_{stage.upper()}',
                              **metadata)

    def _host(self, source, data):
        row = data.get(source.selector) if source.kind == 'host_guard' else data
        if not isinstance(row, dict) or type(row.get('time')) is not int or row['time'] <= 0:
            raise SourceFailure('protocol')
        captured = datetime.fromtimestamp(row['time'], timezone.utc)
        ttl = 900 if source.kind == 'host_guard' else 2100
        metadata = self._metadata(source, captured=captured, ttl=ttl)
        if source.kind == 'host_state':
            if not all(isinstance(row.get(key), list) for key in ('fixed', 'drift', 'awaiting_approval', 'errors')):
                raise SourceFailure('protocol')
            health = 'ERROR' if row['errors'] else 'WARNING' if row['drift'] or row['awaiting_approval'] else 'OK'
            return [self._node(source, health, metadata)], []
        verdict = row.get('state')
        if not isinstance(verdict, str):
            raise SourceFailure('protocol')
        health = {'ok': 'OK', 'load-high': 'WARNING', 'bad': 'ERROR', 'error': 'ERROR',
                  'quiet': 'UNKNOWN', 'unreachable': 'UNKNOWN'}.get(verdict)
        if health is None:
            raise SourceFailure('protocol')
        node = self._node(source, health, metadata)
        reachable = (None if row.get('source') == 'local' or verdict in {'quiet', 'error'}
                     else verdict != 'unreachable')
        link = MonitoringLink(id=f'{source.site_id}:reported:{self.cache.config.collector_id}:{source.id}',
                              source_id=f'{source.site_id}:collector:{self.cache.config.collector_id}',
                              target_id=node.id, kind='reported', expected=True, reachable=reachable,
                              failure_stage='none' if reachable is True else 'unknown', duration_ms=None,
                              **metadata)
        return [node], [link]

    def _fleet(self, source, data):
        value = FleetMonitoringRead.model_validate(data)
        current = self._metadata(source)
        nodes, links = [self._node(source, 'UNKNOWN', current)], []
        if value.sampled_at is None:
            return nodes, links
        for row in value.robots:
            metadata = self._metadata(source, captured=value.sampled_at,
                                      age=max(value.cache_age_s, row.state_age_s or 0.0))
            node = self._node(source, 'UNKNOWN', metadata, kind='robot', suffix=f'{source.id}:{row.robot_id}')
            nodes.append(node)
            # Fleet's legacy name means an HTTP 401, not a TLS handshake failure.
            stage = {'tls-refused': 'auth', 'protocol': 'protocol'}.get(row.link, 'unknown')
            links.append(MonitoringLink(
                id=f'{source.site_id}:reported:{self.cache.config.collector_id}:{source.id}:{row.robot_id}',
                source_id=nodes[0].id, target_id=node.id, kind='reported', expected=True,
                reachable=row.reachable, failure_stage=stage if row.link == 'tls-refused' else
                'none' if row.reachable is True else stage,
                duration_ms=None, reason_code=row.reason_code, **metadata))
        return nodes, links

    async def poll(self, source):
        started, wall = time.monotonic(), self.cache._wall()
        nodes, links, complete = [], [], False
        scopes = source.peer_sites if source.kind == 'peer' else (source.site_id,)
        kind = {'core': 'robot', 'fleet': 'fleet', 'http': 'service', 'peer': 'collector'}.get(source.kind, 'host')
        stage = 'none'
        try:
            async with asyncio.timeout(3):
                if source.path is not None:
                    nodes, links = self._host(source, await self._file(source))
                else:
                    try:
                        token = self.credentials.source_token(source.id)
                    except ValueError:
                        raise SourceFailure('auth') from None
                    headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity'}
                    if token is not None:
                        headers['Authorization'] = f'Bearer {token}'
                    async with httpx.AsyncClient(verify=self.verify, trust_env=False, follow_redirects=False,
                                                timeout=3.0, headers=headers, transport=self.transport) as client:
                        base = source.url.rstrip('/')
                        if source.kind == 'peer':
                            data = await self._get(client, base + '/api/monitoring/v1/snapshot')
                            snapshot = MonitoringSnapshot.model_validate(data)
                            self.cache.receive_peer(source.id, snapshot, request_started_at=wall,
                                                    elapsed_s=time.monotonic() - started)
                        elif source.kind == 'core':
                            identity = await self._get(client, base + '/api/v1/system/info')
                            data = await self._get(client, base + '/api/v1/diagnostics')
                            health = data.get('health')
                            if (identity.get('robot_id') != source.id or not isinstance(health, str)
                                    or health not in {'OK', 'WARNING', 'ERROR', 'UNKNOWN'}):
                                raise SourceFailure('protocol')
                            nodes = [self._node(source, health, self._metadata(source))]
                        elif source.kind == 'fleet':
                            nodes, links = self._fleet(source, await self._get(client, base + '/api/fleet/monitoring'))
                        else:
                            await self._get(client, source.url)
                            nodes = [self._node(source, 'UNKNOWN', self._metadata(source))]
                complete = source.kind != 'peer'
        except (SourceFailure, httpx.HTTPError, OSError, ValueError, OverflowError, TimeoutError) as error:
            stage = _stage(error)
            nodes, links = [], []
        elapsed = time.monotonic() - started
        for site in scopes:
            links.append(self._probe(source, site=site, target=f'{site}:{kind}:{source.id}', elapsed=elapsed, stage=stage))
        self.cache.update_local(source.id, nodes=nodes, links=links, complete=complete)
