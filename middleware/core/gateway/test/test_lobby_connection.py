"""Game-style discovery admission stays explicit and never grants administrator."""

import pytest


@pytest.mark.parametrize('deployment,mode,allowed', [
    ('development', 'development', True), ('development', 'paired', False),
    ('device', 'development', False), ('production', 'development', False),
    ('', 'development', False),
])
def test_development_admission_requires_both_switches(core_client, monkeypatch, deployment, mode, allowed):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('ROSY_DEPLOYMENT', deployment)
    original, svc = core_client(config_overrides={'network': {'connection_mode': mode}})
    client = TestClient(original.app, base_url='http://192.168.1.10', client=('192.168.1.20', 1234))
    info = client.get('/api/v1/auth/connection')
    assert info.status_code == 200
    assert info.json()['mode'] == ('development' if allowed else 'paired')
    response = client.post('/api/v1/auth/development-session')
    assert response.status_code == (201 if allowed else 403)
    if allowed:
        body = response.json()
        assert body['role'] == 'operator' and body['expires_at']
        headers = {'Authorization': 'Bearer ' + body['token']}
        assert client.get('/api/v1/auth/whoami', headers=headers).status_code == 200
        assert client.post('/api/v1/auth/enrollment-codes', headers=headers, json={}).status_code == 403
        assert client.post('/api/v1/auth/logout', headers=headers).status_code == 204
        assert client.get('/api/v1/auth/whoami', headers=headers).status_code == 401


def test_public_client_cannot_probe_or_join_development(core_client, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('ROSY_DEPLOYMENT', 'development')
    original, _ = core_client(config_overrides={'network': {'connection_mode': 'development'}})
    client = TestClient(original.app, client=('8.8.8.8', 1234))
    assert client.get('/api/v1/auth/connection').status_code == 403
    assert client.post('/api/v1/auth/development-session').status_code == 403


def test_join_budget_is_bounded(core_client, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('ROSY_DEPLOYMENT', 'development')
    original, _ = core_client(config_overrides={'network': {'connection_mode': 'development'}})
    client = TestClient(original.app, base_url='http://192.168.1.10', client=('192.168.1.20', 1234))
    for _ in range(5):
        assert client.post('/api/v1/auth/development-session').status_code == 201
    assert client.post('/api/v1/auth/development-session').status_code == 429


def test_expired_sessions_do_not_exhaust_admission(core_client, monkeypatch):
    from fastapi.testclient import TestClient
    from core_api_web.api.deps import auth_entries, new_token_record, stored_token_entries
    monkeypatch.setenv('ROSY_DEPLOYMENT', 'development')
    original, svc = core_client(config_overrides={'network': {'connection_mode': 'development'}})
    svc.config['auth']['tokens'] = stored_token_entries([
        new_token_record('expired-session-' + str(i), 'operator', 'old',
                         source='pair-development', expires_at='2020-01-01T00:00:00+00:00') for i in range(8)])
    assert len(auth_entries(svc.config)) == 8
    client = TestClient(original.app, base_url='http://192.168.1.10', client=('192.168.1.20', 1234))
    assert client.post('/api/v1/auth/development-session').status_code == 201


def test_switching_mode_immediately_revokes_code_free_session(core_client, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('ROSY_DEPLOYMENT', 'development')
    original, svc = core_client(config_overrides={'network': {'connection_mode': 'development'}})
    client = TestClient(original.app, base_url='http://192.168.1.10', client=('192.168.1.20', 1234))
    token = client.post('/api/v1/auth/development-session').json()['token']
    headers = {'Authorization': 'Bearer ' + token}
    svc.config['network']['connection_mode'] = 'paired'
    assert client.get('/api/v1/auth/whoami', headers=headers).status_code == 401


@pytest.mark.parametrize('headers', [{'Host': 'attacker.example'}, {'Origin': 'http://attacker.example'},
                                     {'Origin': 'http://['}])
def test_foreign_authority_cannot_acquire_operator_token(core_client, monkeypatch, headers):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('ROSY_DEPLOYMENT', 'development')
    original, _ = core_client(config_overrides={'network': {'connection_mode': 'development'}})
    client = TestClient(original.app, base_url='http://192.168.1.10', client=('192.168.1.20', 1234))
    assert client.post('/api/v1/auth/development-session', headers=headers).status_code == 403
