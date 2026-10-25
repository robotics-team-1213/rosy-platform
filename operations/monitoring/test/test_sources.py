"""Adapters read existing owner outputs, preserving capture times and privacy."""

import asyncio
import json

import httpx

from rosy.monitoring.cache import ObservationCache
from rosy.monitoring.config import MonitoringConfig, load_credentials
from rosy.monitoring.sources import SourceReader
from test_cache import Clock


def setup(source):
    config = MonitoringConfig(collector_id='observer', site_id='site-a',
                              readers=[{'principal_id': 'operator', 'token_env': 'READ', 'sites': ['site-a']}],
                              sources=[dict(id='target', site_id='site-a', **source)])
    clock = Clock()
    cache = ObservationCache(config, monotonic=clock.monotonic, utcnow=clock.utcnow)
    creds = load_credentials(config, {'READ': 'r' * 32, 'UPSTREAM': 'u' * 32})
    return config, cache, creds, clock


def test_core_reads_only_identity_and_owner_diagnostics():
    cfg, cache, creds, clock = setup({'kind': 'core', 'url': 'https://core.invalid', 'token_env': 'UPSTREAM'})
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


def test_redirect_auth_and_malformed_sources_are_public_failure_codes():
    for status, body, expected in [(302, b'private redirect', 'http'), (401, b'secret auth', 'auth'),
                                    (200, b'{"health":"OK","health":"ERROR"}', 'protocol')]:
        cfg, cache, creds, clock = setup({'kind': 'http', 'url': 'https://private.invalid/health'})
        requests = []
        def answer(request):
            requests.append(request)
            return httpx.Response(status, stream=httpx.ByteStream(body), headers={'location': 'https://another.invalid'})
        asyncio.run(SourceReader(cache, creds, transport=httpx.MockTransport(answer)).poll(cfg.sources[0]))
        value = cache.snapshot(frozenset({'site-a'}))
        assert len(requests) == 1 and value.links[0].failure_stage == expected
        assert not any(secret in value.model_dump_json() for secret in ('private.invalid', 'secret auth', 'private redirect'))


def test_host_guard_retains_owner_capture_and_does_not_invent_network_stage(tmp_path):
    path = tmp_path / 'status.json'
    cfg, cache, creds, clock = setup({'kind': 'host_guard', 'path': str(path), 'selector': 'ai'})
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
    cfg, cache, creds, clock = setup({'kind': 'host_state', 'path': str(path)})
    path.write_text(json.dumps({'time': int(clock.utcnow().timestamp())}))
    asyncio.run(SourceReader(cache, creds).poll(cfg.sources[0]))
    value = cache.snapshot(frozenset({'site-a'}))
    assert next(n for n in value.nodes if n.kind == 'host').reported_health == 'UNKNOWN'
    assert value.links[0].failure_stage == 'protocol'


def test_file_failure_preserves_previous_report_until_stale(tmp_path):
    path = tmp_path / 'status.json'
    cfg, cache, creds, clock = setup({'kind': 'host_guard', 'path': str(path), 'selector': 'ai'})
    path.write_text(json.dumps({'ai': {'time': int(clock.utcnow().timestamp()), 'state': 'bad'}}))
    reader = SourceReader(cache, creds)
    asyncio.run(reader.poll(cfg.sources[0]))
    path.unlink()
    clock.advance(16)
    asyncio.run(reader.poll(cfg.sources[0]))
    host = next(n for n in cache.snapshot(frozenset({'site-a'})).nodes if n.kind == 'host')
    assert host.reported_health == 'ERROR' and host.freshness == 'stale'
