import pytest
from cryptography.fernet import Fernet

from core_common.protocol.account_client import AccountClient, AccountUnavailable, AccountDenied
from core_common.protocol.account_access import sign_access
from test_account_access import keys, claims


@pytest.fixture
def receiver(tmp_path):
    private, public = keys()
    clock = [1000]
    calls = []
    active = [True]
    def post(path, fields):
        calls.append((path, fields))
        if path == 'introspect':
            if active[0] == 'offline':
                raise AccountUnavailable()
            return {'active': active[0]}
        if path == 'revoke':
            active[0] = False
            return {}
        return {'access_token': sign_access({**claims(), 'iat': clock[0], 'exp': clock[0]+300},
                private, key_id='key-1'), 'refresh_token': 'fresh-secret-32-character-token-value', 'token_type': 'Bearer'}
    client = AccountClient(tmp_path/'sessions.sqlite', issuer='https://account.example.test',
        client_id='robot-app', resource='robot:r1', callback='https://r1.test/api/account/callback',
        public_keys={'key-1':public}, encryption_key=Fernet.generate_key(), clock=lambda: clock[0], post=post)
    return client, clock, calls, active


def session(client):
    from urllib.parse import parse_qs, urlsplit
    cookie, url = client.start('/pilot')
    state = parse_qs(urlsplit(url).query)['state'][0]
    return client.finish(cookie, state, 'auth-code')[0]


def test_flow_is_browser_bound_one_use_and_secrets_are_encrypted(receiver):
    from urllib.parse import parse_qs, urlsplit
    client, _, calls, _ = receiver
    flow, url = client.start('/pilot')
    state = parse_qs(urlsplit(url).query)['state'][0]
    with pytest.raises(AccountDenied):
        client.finish('other-browser', state, 'auth-code')
    cookie, target = client.finish(flow, state, 'auth-code')
    assert target == '/pilot'
    assert client.resolve(cookie).sub == 'account-1'
    with pytest.raises(AccountDenied):
        client.finish(flow, state, 'auth-code')
    assert b'fresh-secret' not in client.path.read_bytes()
    assert calls[0][1]['code_verifier']
    assert client.resolve('invented') is None


def test_revocation_and_offline_expiry(receiver):
    client, clock, _, active = receiver
    cookie = session(client)
    assert client.resolve(cookie)
    clock[0] += 21
    active[0] = False
    assert client.resolve(cookie) is None
    active[0] = True
    cookie = session(client)
    active[0] = 'offline'
    clock[0] += 21
    assert client.resolve(cookie)
    clock[0] += 300
    assert client.resolve(cookie) is None


def test_logout_erases_local_session_and_revokes_family(receiver):
    client, _, calls, _ = receiver
    cookie = session(client)
    client.logout(cookie)
    assert client.resolve(cookie) is None
    assert any(path == 'revoke' for path, _ in calls)


def test_expired_flow_and_external_return_are_refused(receiver):
    client, clock, _, _ = receiver
    for target in ['//evil.test', 'https://evil.test', '/pilot?token=secret', '/api/stop']:
        with pytest.raises(ValueError):
            client.start(target)
    flow, _ = client.start('/pilot')
    clock[0] += 601
    with pytest.raises(AccountDenied):
        client.finish(flow, 'state', 'code')
