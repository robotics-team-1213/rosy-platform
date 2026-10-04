"""Only approved absence policy can choose a directory WSS endpoint."""
from dataclasses import replace
from pathlib import Path

import pytest

from core_features.fleet_agent.discovery import (
    DiscoveryConflict, DiscoveryUnavailable, approved_profile, locate_fleet,
)
from test_fleet_discovery_cache import Cache, candidate

URL = 'wss://fleet.vpn.example.test:9443/ws/robots'


def test_absence_uses_explicit_directory_with_same_ca_and_identity(tmp_path):
    ca = tmp_path / 'ca.pem'
    ca.write_text('fixture')
    calls = []
    location = locate_fleet('fleet-a.local', ca, cache=Cache([]),
                            approved_directory_url=URL, probe=lambda *a: calls.append(a))
    assert location == 'https://fleet-a.local:9443'
    assert location.address == 'fleet.vpn.example.test' and location.port == 9443
    assert calls == [({'hostname': 'fleet-a.local', 'address': 'fleet.vpn.example.test', 'port': 9443},
                      'fleet-a.local', ca)]
    with pytest.raises(DiscoveryUnavailable):
        locate_fleet('fleet-a.local', ca, cache=Cache([]), probe=lambda *a: None)


@pytest.mark.parametrize('rows', [
    [candidate(tls='none')],
    [replace(candidate(), addresses=())],
    [candidate(), replace(candidate(), port=8443)],
    [candidate(), candidate(tls='none')],
])
def test_bad_matching_hint_never_becomes_absence_fallback(tmp_path, rows):
    ca = tmp_path / 'ca.pem'
    ca.write_text('fixture')
    with pytest.raises(DiscoveryConflict):
        locate_fleet('fleet-a.local', ca, cache=Cache(rows), approved_directory_url=URL,
                     probe=lambda *a: pytest.fail('bad hint must not reach any peer'))


@pytest.mark.parametrize('error', [ValueError('health 401'), ValueError('health 403'),
                                 ValueError('wrong role')])
def test_present_hint_health_failure_never_probes_directory(tmp_path, error):
    ca = tmp_path / 'ca.pem'
    ca.write_text('fixture')
    calls = []
    def reject(row, *a):
        calls.append(row['address'])
        raise error
    with pytest.raises(ValueError):
        locate_fleet('fleet-a.local', ca, cache=Cache([candidate()]),
                     approved_directory_url=URL, probe=reject)
    assert calls == ['192.168.1.20']


@pytest.mark.parametrize('url', ['ws://fleet.test/ws/robots', 'wss://user:pass@fleet.test/ws/robots',
                               'wss://fleet.test/other', 'wss://fleet.test/ws/robots?x=1',
                               'wss://fleet.test/ws/robots#x', 'wss://fleet.test:0/ws/robots',
                               'wss://fleet.test/ws/robots?', 'wss://fleet.test/ws/robots#',
                               'wss://fleet.test:/ws/robots', 'wss://bad%20host/ws/robots'])
def test_invalid_directory_profile_rejected_before_discovery(url):
    with pytest.raises(ValueError):
        approved_profile({'discovery': {'expected_hostname': 'fleet-a.local',
            'ca_file': str(Path('/ca.pem').resolve()), 'allow_dns_fallback': True,
            'approved_directory_url': url}})


def test_fallback_requires_explicit_boolean_and_approved_url():
    base = {'expected_hostname': 'fleet-a.local', 'ca_file': str(Path('/ca.pem').resolve())}
    for delta in ({'allow_dns_fallback': True}, {'approved_directory_url': URL},
                  {'allow_dns_fallback': 'true', 'approved_directory_url': URL}):
        with pytest.raises(ValueError):
            approved_profile({'discovery': {**base, **delta}})
    profile = approved_profile({'discovery': {**base, 'allow_dns_fallback': True,
                                             'approved_directory_url': URL}})
    assert profile['approved_directory_url'] == URL


@pytest.mark.parametrize('status,body,identity_ok', [
    (200, b'{"status":"ok","role":"fleet"}', True),
    (401, b'{}', True), (403, b'{}', True),
    (200, b'{"status":"ok","role":"foreign"}', True),
    (200, b'{"status":"ok"}', False),
])
def test_directory_real_tls_health_gate_sends_no_credentials(tmp_path, status, body, identity_ok):
    import importlib.util
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import ssl
    import threading
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location('directory_test_pki', root / 'tools/development_link.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    certificates = fixture.provision(tmp_path / 'fixture', site='fleet-a', robots=[('rosy_01', 'fixture-robot.local')])
    received, names = [], []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append((self.path, self.headers.get('Host'), self.headers.get('Authorization')))
            self.send_response(status)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_a): pass
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificates / 'site-chain.pem', certificates / 'site-key.pem')
    context.set_servername_callback(lambda _sock, name, _ctx: names.append(name))
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    hostname = 'fleet-a.local' if identity_ok else 'foreign.local'
    url = f'wss://127.0.0.1:{server.server_port}/ws/robots'
    try:
        if identity_ok and status == 200 and b'foreign' not in body:
            location = locate_fleet(hostname, certificates / 'ca.pem', cache=Cache([]), approved_directory_url=url)
            assert location.address == '127.0.0.1'
        else:
            with pytest.raises((ValueError, ssl.SSLCertVerificationError)):
                locate_fleet(hostname, certificates / 'ca.pem', cache=Cache([]), approved_directory_url=url)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
    assert names == [hostname]
    assert received == ([('/healthz', hostname, None)] if identity_ok else [])


def test_agent_directory_transport_preserves_session_token_and_tls(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import websockets
    import core_features.fleet_agent.agent as module
    from test_fleet_agent_discovery_priority import Events, config
    ca = tmp_path / 'ca.pem'
    ca.write_text('fixture')
    cfg = config(ca, discovery={'expected_hostname': 'fleet-a.local', 'ca_file': str(ca),
                               'allow_dns_fallback': True, 'approved_directory_url': URL})
    events, probes, connections, tokens = Events(), [], [], []
    def resolve(host, cafile, **kwargs):
        return locate_fleet(host, cafile, cache=Cache([]), probe=lambda *a: probes.append(a), **kwargs)
    class Socket:
        async def __aenter__(self): return self
        async def __aexit__(self, *_a): return None
    def connect(url, **options):
        assert probes  # Health gate precedes any session transport.
        connections.append((url, options))
        return Socket()
    class Agent(module.FleetAgent):
        async def _session(self, _ws, token):
            tokens.append(token)
            self.enabled = False
            return None
    agent = Agent(None, events, cfg, SimpleNamespace())
    context = object()
    monkeypatch.setattr(module, 'locate_fleet', resolve)
    monkeypatch.setattr(module.ssl, 'create_default_context', lambda **kw: context)
    monkeypatch.setattr(websockets, 'connect', connect)
    async def exercise():
        agent.start()
        await asyncio.wait_for(agent._task, 2)
    asyncio.run(exercise())
    assert connections == [('wss://fleet-a.local:9443/ws/robots', {'ssl': context, 'proxy': None,
        'host': 'fleet.vpn.example.test', 'port': 9443, 'server_hostname': 'fleet-a.local'})]
    assert tokens == ['approved-token'] and events.cleaned
