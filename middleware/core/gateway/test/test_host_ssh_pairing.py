"""SSH registration cannot borrow ordinary operator or plaintext admission."""

from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest


@pytest.mark.parametrize('scheme,role,confirmed,status', [
    ('http', 'admin', True, 403), ('https', 'operator', True, 403),
    ('https', 'admin', False, 200), ('https', 'admin', True, 200),
])
def test_api_relays_only_https_administrator(core_client, monkeypatch, scheme, role, confirmed, status):
    import core_api_web.api.v1.host as module
    calls = []

    class Agent:
        def __init__(self, **options):
            assert options['socket_path'] == '/run/rosy-host/ssh-pairing.sock'

        def request(self, command, **params):
            calls.append((command, params))
            return SimpleNamespace(reachable=True, ok=params['confirmed'], code='OK', detail='', recovery='', data={})

    monkeypatch.setattr(module, 'HostAgentClient', Agent)
    original, _ = core_client(config_overrides={'network': {'tls': {'cert_file': '/ca', 'key_file': '/key'}}})
    client = TestClient(original.app, base_url=scheme + '://robot.local')
    response = client.post('/api/v1/host/ssh/pair', json={'public_key': 'public-test-key', 'confirmed': confirmed},
                           headers={'Authorization': 'Bearer rosy-dev-' + role})
    assert response.status_code == status
    assert bool(calls) is (scheme == 'https' and role == 'admin')
    if calls:
        assert calls[0][0] == 'ssh.register_key' and calls[0][1]['confirmed'] is confirmed
