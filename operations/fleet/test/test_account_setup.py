"""Account setup is a cookie-only administrator view, never a provisioning API."""
from types import SimpleNamespace

import pytest

from test_password_session import _accounts, _app, _client, _login, ORIGIN, TYPED

PATH = '/api/fleet/auth/setup'


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
    app.state.account_authority = SimpleNamespace(
        issuer='https://account.example.test', private_key='SECRET',
        clients={'pilot': {'redirect_uris': ['https://pilot.example.test/account/callback'],
                           'resources': ['robot:fixture']}})
    response = client.get(PATH, headers=ORIGIN)
    assert response.status_code == 200
    assert response.json() == {'configured': True, 'issuer': 'https://account.example.test',
                              'clients': [{'client_id': 'pilot',
                                           'redirect_uris': ['https://pilot.example.test/account/callback'],
                                           'resources': ['robot:fixture']}]}
    assert 'SECRET' not in response.text
    from fleet.server.password_session import COOKIE
    sessions.revoke(client.cookies.get(COOKIE))
    assert client.get(PATH, headers=ORIGIN).status_code == 401


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
    assert _login(client, login='bob', password=TYPED).status_code == 204
    assert client.get(PATH, headers=ORIGIN).status_code == 403
    value, _ = sessions.change_password(client.cookies.get(COOKIE), 'fixture-password-final-3874')
    client.cookies.clear()
    client.cookies.set(COOKIE, value)
    assert client.get(PATH, headers=ORIGIN).status_code == 403
