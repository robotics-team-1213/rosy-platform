"""Adapters read existing owner outputs, preserving capture times and privacy."""

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from rosy.monitoring.cache import ObservationCache, ObservationRejected
from rosy.monitoring.config import MonitoringConfig, load_credentials
from rosy.monitoring.sources import SourceReader
from rosy.monitoring.store import MonitoringStore, StoreUnavailable
from test_cache import Clock, runtime, peer


def source_context(source):
    config = MonitoringConfig(collector_id='observer', site_id='site-a',
                              readers=[{'principal_id': 'operator', 'token_env': 'READ', 'sites': ['site-a']}],
                              sources=[dict(id='target', site_id='site-a', **source)])
    clock = Clock()
    cache = ObservationCache(config, monotonic=clock.monotonic, utcnow=clock.utcnow)
    creds = load_credentials(config, {'READ': 'r' * 32, 'UPSTREAM': 'u' * 32})
    return config, cache, creds, clock


@pytest.mark.parametrize('kind', ['http', 'fleet'])
def test_registered_composite_graph_ids_fit_before_collecting(kind):
    site = 's' * 64
    with pytest.raises(ValidationError):
        MonitoringConfig(collector_id='c' * 96, site_id=site,
                         readers=[{'principal_id': 'reader', 'token_env': 'READ', 'sites': [site]}],
                         sources=[{'id': 't' * 96, 'label': 'target', 'site_id': site,
                                   'kind': kind, 'url': 'https://example.invalid'}])


def test_long_valid_source_alias_can_create_initial_inventory():
    cfg, cache, credentials, clock = source_context({'kind': 'http', 'url': 'https://example.invalid'})
    raw = cfg.model_dump(mode='json')
    raw['sources'][0]['id'] = 't' * 96
    validated = MonitoringConfig.model_validate(raw)
    inventory = ObservationCache(validated).snapshot(frozenset({'site-a'}))
    target = next(node for node in inventory.nodes if node.kind == 'service')
    assert target.id.endswith('t' * 96) and target.label == 't' * 80


def test_fleet_legacy_tls_refused_preserves_owner_auth_failure():
    cfg, cache, creds, clock = source_context({'kind': 'fleet', 'url': 'https://fleet.invalid'})
    paths = []
    def answer(request):
        paths.append(request.url.path)
        body = {'schema_version': 1, 'sampled_at': clock.utcnow().isoformat(), 'cache_age_s': 0.0,
                'robots': [{'robot_id': 'robot1', 'link': 'tls-refused', 'reachable': True,
                            'reason_code': 'PAIRING_REQUIRED', 'state_age_s': None}]}
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))
    asyncio.run(SourceReader(cache, creds, transport=httpx.MockTransport(answer)).poll(cfg.sources[0]))
    snapshot = cache.snapshot(frozenset({'site-a'}))
    reported = next(link for link in snapshot.links if link.kind == 'reported')
    assert paths == ['/api/fleet/monitoring']
    assert reported.reachable is True and reported.failure_stage == 'auth'
    assert reported.reason_code == 'PAIRING_REQUIRED' and reported.last_success_at is None


def test_fleet_restart_without_a_cache_retains_last_observations_as_stale():
    cfg, cache, credentials, clock = source_context({'kind': 'fleet', 'url': 'https://fleet.invalid'})
    body = {'sampled_at': clock.utcnow().isoformat(), 'cache_age_s': 0.0,
            'robots': [{'robot_id': 'robot1', 'link': 'up', 'reachable': True,
                        'reason_code': None, 'state_age_s': 0.0}]}
    def answer(request):
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))
    reader = SourceReader(cache, credentials, transport=httpx.MockTransport(answer))
    asyncio.run(reader.poll(cfg.sources[0]))
    clock.advance(16)
    body = {'sampled_at': None, 'cache_age_s': None, 'robots': []}
    asyncio.run(reader.poll(cfg.sources[0]))
    snapshot = cache.snapshot(frozenset({'site-a'}))
    robot = next(node for node in snapshot.nodes if node.kind == 'robot')
    reported = next(link for link in snapshot.links if link.kind == 'reported')
    assert robot.freshness == 'stale' and reported.freshness == 'stale'
    assert next(link for link in snapshot.links if link.kind == 'probe').reachable is True
    clock.advance(1)
    body = {'sampled_at': clock.utcnow().isoformat(), 'cache_age_s': 0.0, 'robots': []}
    asyncio.run(reader.poll(cfg.sources[0]))
    assert not any(node.kind == 'robot' for node in cache.snapshot(frozenset({'site-a'})).nodes)


@pytest.mark.parametrize('failure', ['storage', 'clock'])
def test_peer_local_rejection_is_not_misreported_as_a_remote_protocol_error(runtime, tmp_path, monkeypatch, failure):
    from datetime import timedelta
    original, clock = runtime
    store = MonitoringStore(tmp_path / 'monitoring.sqlite3', original.config.collector_id)
    cache = ObservationCache(original.config, monotonic=clock.monotonic, utcnow=clock.utcnow, store=store)
    message = peer(clock)
    if failure == 'clock':
        message = message.model_copy(update={'produced_at': clock.utcnow() - timedelta(seconds=5)})
    save = store.save
    pending_failure = [failure == 'storage']
    def unavailable(key, *args, **kwargs):
        if key[0] == 'peer' and pending_failure[0]:
            pending_failure[0] = False
            raise StoreUnavailable()
        return save(key, *args, **kwargs)
    monkeypatch.setattr(store, 'save', unavailable)
    def answer(request):
        return httpx.Response(200, stream=httpx.ByteStream(message.model_dump_json().encode()))
    credentials = load_credentials(original.config, {'READ': 'r' * 32})
    reader = SourceReader(cache, credentials, transport=httpx.MockTransport(answer))
    with pytest.raises(StoreUnavailable if failure == 'storage' else ObservationRejected) as rejected:
        asyncio.run(reader.poll(original.config.sources[1]))
    if failure == 'clock':
        assert rejected.value.reason_code == 'MONITORING_CLOCK'
    assert not cache._peers
    message = peer(clock)
    asyncio.run(reader.poll(original.config.sources[1]))
    snapshot = cache.snapshot(frozenset({'site-b'}))
    assert next(node for node in snapshot.nodes if node.kind == 'host').reported_health == 'OK'


def test_core_reads_only_identity_and_owner_diagnostics():
    cfg, cache, creds, clock = source_context({'kind': 'core', 'url': 'https://core.invalid', 'token_env': 'UPSTREAM'})
    requests = []
    def answer(request):
        requests.append(request)
        data = {'robot_id': 'target'} if request.url.path.endswith('/info') else {'health': 'ERROR'}
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(data).encode()))
    reader = SourceReader(cache, creds, transport=httpx.MockTransport(answer))
    asyncio.run(reader.poll(cfg.sources[0]))
    result = cache.snapshot(frozenset({'site-a'}))
    assert [req.url.path for req in requests] == ['/api/v1/system/info', '/api/v1/diagnostics']
    assert all(req.headers['authorization'] == 'Bearer ' + 'u' * 32 for req in requests)
    assert next(n for n in result.nodes if n.kind == 'robot').reported_health == 'ERROR'
    assert result.links[0].reachable is True and result.links[0].transport == 'https'


@pytest.mark.parametrize(('status', 'body', 'expected'), [
    (302, b'private redirect', 'http'), (401, b'secret auth', 'auth'),
    (200, b'{"health":"OK","health":"ERROR"}', 'protocol'),
    (200, b'{"value":1e9999}', 'protocol'),
    (200, b'{"value":' + b'[' * 1200 + b'0' + b']' * 1200 + b'}', 'protocol'),
    (200, '{"value":1}'.encode('utf-16'), 'protocol'),
    (200, b'{"value":"' + b'[' * 1200 + b'"}', 'none'),
], ids=['redirect', 'auth', 'duplicate', 'nonfinite', 'depth', 'encoding', 'quoted-brackets'])
def test_redirect_auth_and_malformed_sources_are_public_failure_codes(status, body, expected):
    cfg, cache, creds, clock = source_context({'kind': 'http', 'url': 'https://private.invalid/health'})
    requests = []
    def answer(request):
        requests.append(request)
        return httpx.Response(status, stream=httpx.ByteStream(body), headers={'location': 'https://another.invalid'})
    asyncio.run(SourceReader(cache, creds, transport=httpx.MockTransport(answer)).poll(cfg.sources[0]))
    value = cache.snapshot(frozenset({'site-a'}))
    assert len(requests) == 1 and value.links[0].failure_stage == expected
    assert not any(secret in value.model_dump_json() for secret in ('private.invalid', 'secret auth', 'private redirect'))


@pytest.mark.parametrize('body', [[], {'ai': {'time': 1792886400, 'state': []}}])
def test_malformed_host_report_cannot_raise_out_of_collection(tmp_path, body):
    path = tmp_path / 'status.json'
    cfg, cache, credentials, clock = source_context({'kind': 'host_guard', 'path': str(path), 'selector': 'ai'})
    path.write_text(json.dumps(body))
    asyncio.run(SourceReader(cache, credentials).poll(cfg.sources[0]))
    value = cache.snapshot(frozenset({'site-a'}))
    assert value.links[0].failure_stage == 'protocol'


def test_non_scalar_core_health_is_a_protocol_failure():
    cfg, cache, credentials, clock = source_context({'kind': 'core', 'url': 'https://core.invalid'})
    def answer(request):
        data = {'robot_id': 'target'} if request.url.path.endswith('/info') else {'health': []}
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(data).encode()))
    asyncio.run(SourceReader(cache, credentials, transport=httpx.MockTransport(answer)).poll(cfg.sources[0]))
    assert cache.snapshot(frozenset({'site-a'})).links[0].failure_stage == 'protocol'


def test_host_guard_retains_owner_capture_and_does_not_invent_network_stage(tmp_path):
    path = tmp_path / 'status.json'
    cfg, cache, creds, clock = source_context({'kind': 'host_guard', 'path': str(path), 'selector': 'ai'})
    stamp = int(clock.utcnow().timestamp()) - 100
    path.write_text(json.dumps({'ai': {'time': stamp, 'state': 'unreachable', 'resources': {'secret': 'omit'}}}))
    reader = SourceReader(cache, creds)
    asyncio.run(reader.poll(cfg.sources[0]))
    first = cache.snapshot(frozenset({'site-a'}))
    clock.advance(4)
    asyncio.run(reader.poll(cfg.sources[0]))
    second = cache.snapshot(frozenset({'site-a'}))
    host = next(n for n in second.nodes if n.kind == 'host')
    assert host.age_s >= 104 and host.valid_for_s == 900
    assert host.sampled_at == next(n for n in first.nodes if n.kind == 'host').sampled_at
    reported = next(link for link in second.links if link.kind == 'reported')
    assert reported.reachable is False and reported.failure_stage == 'unknown'
    assert next(link for link in second.links if link.kind == 'probe').transport == 'file'
    assert 'secret' not in second.model_dump_json()


def test_host_state_missing_required_results_is_not_healthy(tmp_path):
    path = tmp_path / 'status.json'
    cfg, cache, creds, clock = source_context({'kind': 'host_state', 'path': str(path)})
    path.write_text(json.dumps({'time': int(clock.utcnow().timestamp())}))
    asyncio.run(SourceReader(cache, creds).poll(cfg.sources[0]))
    value = cache.snapshot(frozenset({'site-a'}))
    assert next(n for n in value.nodes if n.kind == 'host').reported_health == 'UNKNOWN'
    assert value.links[0].failure_stage == 'protocol'


def test_file_failure_preserves_previous_report_until_stale(tmp_path):
    path = tmp_path / 'status.json'
    cfg, cache, creds, clock = source_context({'kind': 'host_guard', 'path': str(path), 'selector': 'ai'})
    path.write_text(json.dumps({'ai': {'time': int(clock.utcnow().timestamp()), 'state': 'bad'}}))
    reader = SourceReader(cache, creds)
    asyncio.run(reader.poll(cfg.sources[0]))
    path.unlink()
    clock.advance(16)
    asyncio.run(reader.poll(cfg.sources[0]))
    host = next(n for n in cache.snapshot(frozenset({'site-a'})).nodes if n.kind == 'host')
    assert host.reported_health == 'ERROR' and host.freshness == 'stale'


def test_real_http_stream_and_stopped_upstream_preserve_owner_verdict():
    from http.server import BaseHTTPRequestHandler
    from threading import Thread
    from browser_harness import safe_http_server

    paths = []
    class Owner(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            body = json.dumps({'robot_id': 'target'} if self.path.endswith('/info') else {'health': 'ERROR'}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = safe_http_server(Owner)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg, cache, creds, clock = source_context({'kind': 'core', 'url': f'http://127.0.0.1:{server.server_port}'})
    reader = SourceReader(cache, creds)
    try:
        asyncio.run(reader.poll(cfg.sources[0]))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert paths == ['/api/v1/system/info', '/api/v1/diagnostics']
    clock.advance(16)
    asyncio.run(reader.poll(cfg.sources[0]))
    value = cache.snapshot(frozenset({'site-a'}))
    robot = next(n for n in value.nodes if n.kind == 'robot')
    assert robot.reported_health == 'ERROR' and robot.freshness == 'stale'
    assert value.links[0].failure_stage == 'connect'
