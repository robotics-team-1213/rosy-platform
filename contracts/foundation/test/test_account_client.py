import pytest
from http.client import BadStatusLine, IncompleteRead, LineTooLong
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


def test_media_session_check_does_not_use_offline_or_ten_second_grace(receiver):
    from hashlib import sha256
    client, _, _, active = receiver
    cookie = session(client)
    session_id = sha256(cookie.encode()).hexdigest()
    assert hasattr(client, 'media_session_active'), 'D-789 needs strict online session revalidation'
    assert client.media_session_active(session_id) is True
    active[0] = 'offline'
    assert client.media_session_active(session_id) is False
    active[0] = True
    assert client.media_session_active(session_id) is True
    active[0] = False
    assert client.media_session_active(session_id) is False


def test_expired_flow_and_external_return_are_refused(receiver):
    client, clock, _, _ = receiver
    for target in ['//evil.test', 'https://evil.test', '/pilot?token=secret', '/api/stop']:
        with pytest.raises(ValueError):
            client.start(target)
    flow, _ = client.start('/pilot')
    clock[0] += 601
    with pytest.raises(AccountDenied):
        client.finish(flow, 'state', 'code')


def test_renewal_is_saved_before_introspection_timeout(receiver):
    client, clock, calls, active = receiver
    cookie = session(client)
    clock[0] += 270
    active[0] = 'offline'
    assert client.resolve(cookie)
    refresh_count = sum(path == 'token' for path, _ in calls)
    assert client.resolve(cookie) is None
    assert sum(path == 'token' for path, _ in calls) == refresh_count
    active[0] = True
    assert client.resolve(cookie)


def test_logout_retries_revocation_after_outage(receiver):
    client, _, calls, _ = receiver
    cookie = session(client)
    original = client.post
    def offline(path, fields):
        raise AccountUnavailable()
    client.post = offline
    with pytest.raises(AccountUnavailable):
        client.logout(cookie)
    assert client.resolve(cookie) is None
    client.post = original
    client.retry_revocations()
    assert calls[-1][0] == 'revoke'


def test_pending_revocation_survives_receiver_reopen(receiver):
    original, _, calls, active = receiver
    settings = dict(issuer=original.issuer, client_id=original.client_id,
        resource=original.resource, callback=original.callback,
        public_keys=original.public_keys, encryption_key=Fernet.generate_key(),
        clock=original.clock, post=original.post)
    client = AccountClient(original.path, **settings)
    cookie = session(client)
    assert client.resolve(cookie)

    def unavailable(endpoint, fields):
        raise AccountUnavailable()

    client.post = unavailable
    with pytest.raises(AccountUnavailable):
        client.logout(cookie)
    assert client.resolve(cookie) is None
    assert active[0] is True
    assert b'fresh-secret' not in client.path.read_bytes()

    reopened = AccountClient(client.path, **settings)
    assert reopened.resolve(cookie) is None
    reopened.retry_revocations()
    assert active[0] is False
    revocations = sum(endpoint == 'revoke' for endpoint, _ in calls)
    reopened.retry_revocations()
    assert sum(endpoint == 'revoke' for endpoint, _ in calls) == revocations


def test_expired_refresh_cannot_change_account_identity(receiver):
    client, clock, _, _ = receiver
    cookie = session(client)
    clock[0] += 301
    private, public = keys()
    client.public_keys['other-key'] = public
    client.post = lambda endpoint, fields: {'active':True} if endpoint == 'introspect' else {'access_token':sign_access({**claims(), 'sub':'different-account',
        'iat':clock[0], 'exp':clock[0]+300}, private, key_id='other-key'),
        'refresh_token':'different-refresh-token-long-enough', 'token_type':'Bearer'}
    assert client.resolve(cookie) is None


def test_bearer_requires_initial_online_check_and_rechecks_at_ten_seconds(receiver):
    client, clock, _, active = receiver
    token = client.post('token', {})['access_token']
    active[0] = 'offline'
    with pytest.raises(AccountUnavailable): client.verify_bearer(token)
    active[0] = True
    assert client.verify_bearer(token)
    active[0] = False
    clock[0] += 10
    with pytest.raises(AccountDenied): client.verify_bearer(token)


def test_profile_is_live_bound_and_profile_failure_keeps_auth(receiver):
    client, clock, calls, active = receiver
    cookie = session(client)
    subject = client.resolve(cookie).sub
    original = client.post
    profile = {'account_id': subject, 'login': 'alice', 'display_name': 'Alice'}
    def post(endpoint, fields):
        if endpoint == 'userinfo':
            if profile.get('offline'):
                raise AccountUnavailable()
            return dict(profile)
        return original(endpoint, fields)
    client.post = post
    assert client.profile_url == 'https://account.example.test/console/profile'
    assert client.profile(cookie) == profile
    profile['display_name'] = 'Updated'
    assert client.profile(cookie)['display_name'] == 'Updated'
    profile['account_id'] = 'another-account'
    assert client.profile(cookie) is None
    assert client.resolve(cookie).sub == subject
    profile['offline'] = True
    assert client.profile(cookie) is None
    assert client.resolve(cookie).sub == subject
    assert client.profile('unknown') is None


def test_profile_drops_response_when_local_session_is_logged_out(receiver):
    client, _, _, _ = receiver
    cookie = session(client)
    subject = client.resolve(cookie).sub
    original = client.post
    def post(endpoint, fields):
        if endpoint == 'userinfo':
            client.logout(cookie)
            return {'account_id':subject, 'login':'alice', 'display_name':'Old'}
        return original(endpoint, fields)
    client.post = post
    assert client.profile(cookie) is None


@pytest.mark.parametrize('elapsed', [11, 270])
def test_profile_never_introspects_or_renews_and_denial_keeps_session(receiver, elapsed):
    client, clock, calls, _ = receiver
    cookie = session(client)
    subject = client.resolve(cookie).sub
    clock[0] += elapsed
    calls.clear()
    denied = [False]
    def post(endpoint, fields):
        calls.append(endpoint)
        assert endpoint == 'userinfo'
        if denied[0]:
            raise AccountDenied('Profile refused')
        return {'account_id':subject, 'login':'alice', 'display_name':'Alice'}
    client.post = post
    with client.transaction() as db:
        before = tuple(db.execute('SELECT * FROM app_account_sessions').fetchone())
    assert client.profile(cookie)['account_id'] == subject
    assert calls == ['userinfo']
    denied[0] = True
    assert client.profile(cookie) is None
    with client.transaction() as db:
        assert tuple(db.execute('SELECT * FROM app_account_sessions').fetchone()) == before
    clock[0] += 301
    calls.clear()
    assert client.profile(cookie) is None
    assert calls == []


def test_profile_transport_timeout_is_shorter_than_auth(receiver, monkeypatch):
    from core_common.protocol import account_client
    client, _, _, _ = receiver
    timeouts = []
    class Opener:
        def open(self, request, *, timeout):
            timeouts.append(timeout)
            raise TimeoutError()
    monkeypatch.setattr(account_client, 'build_opener', lambda *args: Opener())
    for endpoint in ('userinfo', 'introspect', 'token'):
        with pytest.raises(AccountUnavailable):
            client._post(endpoint, {'token':'test'})
    assert timeouts == [1, 3, 3]


@pytest.fixture(params=[IncompleteRead, BadStatusLine, LineTooLong])
def broken_http(request, monkeypatch):
    from core_common.protocol import account_client
    calls = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, limit):
            raise IncompleteRead(b'refresh-token-secret', 100)
    class Opener:
        def open(self, req, *, timeout):
            calls.append(req.full_url)
            if request.param is IncompleteRead:
                return Response()
            raise request.param('refresh-token-secret')
    monkeypatch.setattr(account_client, 'build_opener', lambda *args: Opener())
    return calls


@pytest.mark.parametrize('endpoint', ['token', 'introspect', 'revoke', 'userinfo'])
def test_http_protocol_failure_is_sanitized_unavailable(receiver, broken_http, endpoint):
    client, _, _, _ = receiver
    with pytest.raises(AccountUnavailable) as error:
        client._post(endpoint, {'token': 'refresh-token-secret'})
    assert error.value.args == ()
    assert error.value.__suppress_context__


def test_uncertain_http_refresh_erases_session_without_reusing_refresh(receiver, broken_http):
    client, clock, _, _ = receiver
    cookie = session(client)
    clock[0] += 270
    client.post = client._post
    assert client.resolve(cookie) is None
    with client.transaction() as db:
        assert db.execute('SELECT count(*) FROM app_account_sessions').fetchone()[0] == 0
    assert client.resolve(cookie) is None
    assert broken_http == [client.issuer + '/api/fleet/auth/token']


def test_http_revoke_failure_preserves_pending_retry_until_recovery(receiver, broken_http):
    client, _, calls, _ = receiver
    cookie = session(client)
    original = client.post
    client.post = client._post
    with pytest.raises(AccountUnavailable):
        client.logout(cookie)
    assert client.resolve(cookie) is None
    with client.transaction() as db:
        pending = tuple(db.execute('SELECT * FROM app_account_revocations').fetchone())
    with pytest.raises(AccountUnavailable):
        client.retry_revocations()
    with client.transaction() as db:
        assert tuple(db.execute('SELECT * FROM app_account_revocations').fetchone()) == pending
    client.post = original
    client.retry_revocations()
    assert calls[-1][0] == 'revoke'
    with client.transaction() as db:
        assert db.execute('SELECT count(*) FROM app_account_revocations').fetchone()[0] == 0
