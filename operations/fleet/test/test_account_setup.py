"""Account setup is a cookie-only administrator view, never a provisioning API."""
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from test_password_session import _accounts, _app, _client, _login, ORIGIN, TYPED

PATH = '/api/fleet/auth/setup'
CLIENTS = '/api/fleet/auth/clients'
CALLBACK = 'https://pilot.example.test/account/callback'


def attach_authority(app):
    from fleet.server.account_authority import AccountAuthority
    pem = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption())
    sessions = app.state.password_sessions
    app.state.account_authority = AccountAuthority(
        sessions.path, issuer='https://account.example.test', private_key=pem, key_id='key-1',
        clients={'pilot': {'redirect_uris': [CALLBACK], 'resources': ['robot:fixture']}},
        resolve_family=lambda db, family: sessions.context_by_family(family, db=db),
        revoke_family=lambda db, family: sessions.revoke_family(family, db=db))
    return app.state.account_authority


@pytest.mark.parametrize('role,expected', [('viewer', 403), ('operator', 403), ('policy-admin', 200)])
def test_legacy_setup_requires_policy_admin_cookie(tmp_path, role, expected):
    app, _ = _app(tmp_path, logins=_accounts(role=role))
    client = _client(app)
    assert client.get(PATH, headers=ORIGIN).status_code == 401
    assert _login(client).status_code == 204
    response = client.get(PATH, headers=ORIGIN)
    assert response.status_code == expected
    if expected == 200:
        assert response.json() == {'configured': False, 'issuer': None, 'clients': []}
        assert response.headers['cache-control'] == 'no-store'
        assert client.get(PATH).status_code == 403
        assert client.get(PATH, headers={'Origin': 'https://elsewhere.test'}).status_code == 403
        assert client.get(PATH, headers={'Sec-Fetch-Site': 'same-origin'}).status_code == 200


def test_managed_setup_uses_live_grant_and_only_public_registration(tmp_path):
    app, _ = _app(tmp_path)
    sessions = app.state.password_sessions
    sessions.bootstrap_accounts('alice', 'test-site')
    client = _client(app)
    assert _login(client).status_code == 204
    attach_authority(app)
    response = client.get(PATH, headers=ORIGIN)
    assert response.status_code == 200
    assert response.json() == {'configured': True, 'issuer': 'https://account.example.test',
                              'clients': [{'client_id': 'pilot', 'redirect_uris': [CALLBACK],
                                           'resources': ['robot:fixture'], 'label': 'pilot', 'home_url': '',
                                           'enabled': True, 'revision': 1}]}
    assert 'PRIVATE' not in response.text and 'private_key' not in response.text
    from fleet.server.password_session import COOKIE
    sessions.revoke(client.cookies.get(COOKIE))
    assert client.get(PATH, headers=ORIGIN).status_code == 401


def test_manager_registers_and_stops_a_client_without_restart(tmp_path):
    app, _ = _app(tmp_path)
    app.state.password_sessions.bootstrap_accounts('alice', 'test-site')
    client = _client(app)
    assert _login(client).status_code == 204
    authority = attach_authority(app)
    body = {'client_id': 'monitoring', 'redirect_uris': [CALLBACK], 'resources': ['site:test-site']}
    assert client.post(CLIENTS, json=body).status_code == 403, 'cross-origin registration'
    made = client.post(CLIENTS, json=body, headers=ORIGIN)
    assert made.status_code == 201 and made.json()['revision'] == 1
    assert 'monitoring' in authority.clients
    assert client.post(CLIENTS, json=body, headers=ORIGIN).status_code == 422
    assert client.post(CLIENTS, json={**body, 'client_id': 'x', 'extra': 1}, headers=ORIGIN).status_code == 422
    assert client.post(CLIENTS, json={**body, 'client_id': 'x', 'resources': ['site:*']}, headers=ORIGIN).status_code == 422
    assert client.patch(CLIENTS + '/monitoring', json={'revision': 9, 'enabled': False}, headers=ORIGIN).status_code == 409
    assert client.patch(CLIENTS + '/missing', json={'revision': 1, 'enabled': False}, headers=ORIGIN).status_code == 404
    stopped = client.patch(CLIENTS + '/monitoring', json={'revision': 1, 'enabled': False}, headers=ORIGIN)
    assert stopped.status_code == 200 and stopped.json()['enabled'] is False
    assert 'monitoring' not in authority.clients
    listed = {row['client_id']: row['enabled'] for row in client.get(PATH, headers=ORIGIN).json()['clients']}
    assert listed == {'monitoring': False, 'pilot': True}


def test_registry_refuses_non_managers_and_an_unconfigured_authority(tmp_path):
    from fleet.server.password_session import COOKIE
    app, _ = _app(tmp_path)
    sessions = app.state.password_sessions
    sessions.bootstrap_accounts('alice', 'test-site')
    client = _client(app)
    assert _login(client).status_code == 204
    body = {'client_id': 'monitoring', 'redirect_uris': [CALLBACK], 'resources': ['site:test-site']}
    assert client.post(CLIENTS, json=body, headers=ORIGIN).status_code == 409
    attach_authority(app)
    sessions.create_account(client.cookies.get(COOKIE), login='bob', principal_id='bob', role='viewer',
                            password=TYPED, grants=[])
    assert _login(client, login='bob').status_code == 204
    value, _ = sessions.change_password(client.cookies.get(COOKIE), 'fixture-password-final-3874')
    client.cookies.clear()
    client.cookies.set(COOKIE, value)
    assert client.post(CLIENTS, json=body, headers=ORIGIN).status_code == 403
    assert client.patch(CLIENTS + '/pilot', json={'revision': 1, 'enabled': False}, headers=ORIGIN).status_code == 403


def test_managed_policy_role_without_account_grant_cannot_read_setup(tmp_path):
    app, _ = _app(tmp_path, logins=_accounts(role='policy-admin'))
    sessions = app.state.password_sessions
    sessions.bootstrap_accounts('alice', 'test-site')
    client = _client(app)
    assert _login(client).status_code == 204
    from fleet.server.password_session import COOKIE
    manager = client.cookies.get(COOKIE)
    sessions.create_account(manager, login='bob', principal_id='bob', role='policy-admin',
                            password=TYPED, grants=[])
    assert _login(client, login='bob').status_code == 204
    assert client.get(PATH, headers=ORIGIN).status_code == 403
    value, _ = sessions.change_password(client.cookies.get(COOKIE), 'fixture-password-final-3874')
    client.cookies.clear()
    client.cookies.set(COOKIE, value)
    assert client.get(PATH, headers=ORIGIN).status_code == 403
