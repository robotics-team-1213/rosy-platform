"""Synthetic 937 backend and real AccountClient with a fake central receiver."""
from hashlib import sha256
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
import threading
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core_common.protocol.account_access import sign_access
from core_common.protocol.account_client import AccountClient, AccountUnavailable
import legacy_review_account as module


@pytest.fixture
def app(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption())
    public = private.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
    state = {'caps': ['learning.view', 'learning.edit', 'learning.approve'],
             'active': True, 'offline': False, 'clock': 1000, 'writes': [], 'gets': [], 'drop': False}
    def central(endpoint, fields):
        if state['offline']:
            raise AccountUnavailable()
        if endpoint == 'introspect':
            return {'active': state['active']}
        if endpoint == 'revoke':
            state['revoked'] = True
            return {}
        if endpoint == 'userinfo':
            return {'account_id': 'human-937', 'login': 'reviewer', 'display_name': '<script>alert(1)</script>'}
        claims = {'iss': 'https://account.example.test', 'aud': 'project:937', 'sub': 'human-937',
                  'sid': 'central-session', 'jti': 'x' * 32, 'rev': 1, 'iat': state['clock'],
                  'exp': state['clock'] + 300,
                  'grants': [{'resource': 'project:937', 'capabilities': state['caps']}]}
        return {'access_token': sign_access(claims, private_pem, key_id='test'),
                'refresh_token': 'refresh-secret-for-test-only', 'token_type': 'Bearer'}
    account = AccountClient(tmp_path / 'sessions.db', issuer='https://account.example.test',
                            client_id='937', resource='project:937',
                            callback='https://review.example.test/api/account/callback', public_keys={'test': public},
                            encryption_key=Fernet.generate_key(), clock=lambda: state['clock'], post=central,
                            destinations=('/',))
    class Backend(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            state['gets'].append(self.path)
            body = b'<html><body>original human content</body></html>' if self.path == '/' else b'original-bytes'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html' if self.path == '/' else 'application/octet-stream')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            with sqlite3.connect(tmp_path / 'audit.db') as db:
                assert db.execute('SELECT outcome FROM review_audit ORDER BY id DESC').fetchone()[0] == 'intent'
            state['writes'].append((dict(self.headers), body))
            if state['drop']:
                self.close_connection = True
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
    backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
    monkeypatch.setattr(module, 'BACKEND', backend.server_address)
    server = module.ReviewServer(0, origin='https://review.example.test', account=account,
                                 audit_db=tmp_path / 'audit.db')
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (backend, server)]
    for thread in threads:
        thread.start()
    def request(path='/', method='GET', body=None, cookie=None, **headers):
        connection = HTTPConnection(*server.server_address, timeout=10)
        request_headers = {'Host': server.host, **headers}
        if cookie:
            request_headers['Cookie'] = cookie
        if method == 'POST':
            request_headers.setdefault('Origin', server.origin)
            request_headers.setdefault('Content-Type', 'application/json')
        connection.request(method, path, body, request_headers)
        response = connection.getresponse()
        result = (response.status, response.getheaders(), response.read())
        connection.close()
        return result
    def login():
        status, headers, _ = request('/api/account/login')
        assert status == 303
        flow = next(value.split(';')[0] for key, value in headers if key == 'Set-Cookie')
        target = dict(headers)['Location']
        state_value = parse_qs(urlsplit(target).query)['state'][0]
        status, headers, body = request('/api/account/callback?code=valid-code&state=' + state_value, cookie=flow)
        assert status == 303 and dict(headers)['Location'] == '/'
        assert b'refresh' not in body
        return next(value.split(';')[0] for key, value in headers
                    if key == 'Set-Cookie' and value.startswith(server.session_cookie + '='))
    yield server, state, request, login, tmp_path
    for running in (server, backend):
        running.shutdown()
        running.server_close()
    for thread in threads:
        thread.join(5)


def test_login_profile_cookie_and_unchanged_assets(app):
    server, state, request, login, _ = app
    assert request('/')[0:1] == (303,)
    assert dict(request('/')[1])['Location'] == '/api/account/login'
    assert request('/api/data')[0] == 401
    status, headers, _ = request('/api/account/login')
    cookie = next(value for key, value in headers if key == 'Set-Cookie')
    assert all(flag in cookie for flag in ['Secure', 'HttpOnly', 'SameSite=Lax', 'Path=/'])
    session = login()
    body = request('/', cookie=session)[2]
    assert b'original human content' in body and b'/api/account/logout' in body
    assert b'<script>alert' not in body
    profile = json.loads(request('/api/account/session', cookie=session)[2])
    assert profile['account_id'] == 'human-937'
    for path in ['/api/data', '/reviews.csv', '/image/0/frame.jpg', '/mask/0/m.png', '/rawmask/0/m.png', '/info/0/i.json']:
        assert request(path, cookie=session)[2] == b'original-bytes'
    assert not state['writes']


@pytest.mark.parametrize('path', ['/secrets', '/api/data?url=http://evil', '//evil/',
                                  '/image/0/..', '/image/0/%2e%2e', '/image/-1/x',
                                  '/image/0/a/b', '/image/0/a?x=1', '/image/0/a%2fb'])
def test_backend_path_allowlist(app, path):
    _, state, request, login, _ = app
    session = login()
    assert request(path, cookie=session)[0] in (400, 404)
    assert state['gets'] == []


def test_host_origin_validation_and_no_token_identity_forwarding(app):
    server, state, request, login, _ = app
    assert request('/api/account/login', Host='evil.test')[0] == 421
    session = login()
    body = json.dumps({'index': 0, 'status': 'fix', 'note': 'human note'}).encode()
    assert request('/api/review', 'POST', body, session, Origin='https://evil.test')[0] == 403
    assert not state['writes']
    assert request('/api/review', 'POST', body, session,
                   Authorization='Bearer attacker', **{'X-Account-Id': 'forged'})[0] == 200
    headers, forwarded = state['writes'][0]
    assert forwarded == body
    assert headers['Origin'] == 'http://' + headers['Host']
    assert 'Cookie' not in headers and 'Authorization' not in headers and 'X-Account-Id' not in headers


@pytest.mark.parametrize('caps,status,expected', [
    (['learning.view'], 'fix', 403), (['learning.view', 'learning.edit'], 'ok', 403),
    (['learning.view', 'learning.approve'], 'fix', 403),
    (['learning.view', 'learning.edit'], 'hold', 200),
    (['learning.view', 'learning.edit'], 'pending', 200),
    (['learning.view', 'learning.approve'], 'ok', 200),
    (['learning.manage'], 'fix', 403)])
def test_explicit_capability_per_status(app, caps, status, expected):
    _, state, request, login, _ = app
    state['caps'] = caps
    session = login()
    result = request('/api/review', 'POST', json.dumps({'index': 0, 'status': status, 'note': ''}), session)
    assert result[0] == expected
    assert len(state['writes']) == (expected == 200)


@pytest.mark.parametrize('review', [[], {'index': True, 'status': 'ok', 'note': ''},
    {'index': -1, 'status': 'ok', 'note': ''}, {'index': 0, 'status': 'unknown', 'note': ''},
    {'index': 0, 'status': 'fix', 'note': 'a' * 4001},
    {'index': 0, 'status': 'ok', 'note': '', 'account_id': 'spoof'}])
def test_invalid_review_is_never_forwarded(app, review):
    _, state, request, login, _ = app
    assert request('/api/review', 'POST', json.dumps(review), login())[0] == 400
    assert not state['writes']


def test_size_audit_and_unknown_no_retry(app):
    _, state, request, login, directory = app
    session = login()
    assert request('/api/review', 'POST', b'x' * 20001, session)[0] == 413
    body = b'{"index":3,"status":"ok","note":"human"}'
    assert request('/api/review', 'POST', body, session)[0] == 200
    state['drop'] = True
    assert request('/api/review', 'POST', body, session)[0] == 502
    assert len(state['writes']) == 2
    with sqlite3.connect(directory / 'audit.db') as db:
        rows = db.execute('SELECT account_id,resource,body_sha256,outcome FROM review_audit ORDER BY id').fetchall()
    assert rows == [('human-937', 'project:937', sha256(body).hexdigest(), outcome)
                    for outcome in ['success', 'unknown']]


def test_logout_local_first_pending_revoke_and_revocation(app):
    server, state, request, login, _ = app
    session = login()
    state['offline'] = True
    assert request('/api/account/logout', 'POST', b'', session)[0] == 303
    assert request('/api/data', cookie=session)[0] == 401
    with server.account.transaction() as db:
        assert db.execute('SELECT count(*) FROM app_account_revocations').fetchone()[0] == 1
    state['offline'] = False
    server.account.retry_revocations()
    assert state['revoked']
    with server.account.transaction() as db:
        assert db.execute('SELECT count(*) FROM app_account_revocations').fetchone()[0] == 0
    session = login()
    state['active'] = False
    state['clock'] += 11
    assert request('/api/data', cookie=session)[0] == 401


@pytest.mark.parametrize('query', ['code=a&state=b&state=c', 'code=a&code=b&state=c',
                                  'code=a&state=', 'code=a', 'code=a&state=b&next=https://evil'])
def test_callback_strict_parameters(app, query):
    _, _, request, _, _ = app
    assert request('/api/account/callback?' + query)[0] == 400


def test_callback_browser_binding_and_replay(app):
    _, _, request, _, _ = app
    _, headers, _ = request('/api/account/login')
    state = parse_qs(urlsplit(dict(headers)['Location']).query)['state'][0]
    flow = next(value.split(';')[0] for key, value in headers if key == 'Set-Cookie')
    callback = '/api/account/callback?code=a&state=' + state
    assert request(callback)[0] == 400
    assert request(callback, cookie=flow)[0] == 303
    assert request(callback, cookie=flow)[0] == 400


def test_upstream_timeout_is_audited_without_retry(app, monkeypatch):
    _, state, request, login, directory = app
    session = login()
    attempts = []
    class TimeoutConnection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            attempts.append(args)
            raise TimeoutError('possibly committed upstream')

        def close(self):
            pass
    monkeypatch.setattr(module, 'HTTPConnection', TimeoutConnection)
    body = b'{"index":0,"status":"fix","note":"human"}'
    assert request('/api/review', 'POST', body, session)[0] == 502
    assert len(attempts) == 1 and state['writes'] == []
    with sqlite3.connect(directory / 'audit.db') as db:
        assert db.execute('SELECT outcome FROM review_audit').fetchall() == [('unknown',)]


def test_restart_marks_unfinished_intent_unknown_and_retains_private_state(app):
    server, _, _, _, directory = app
    with sqlite3.connect(directory / 'audit.db') as db:
        db.execute('INSERT INTO review_audit(account_id,resource,body_sha256,created,outcome) '
                   'VALUES(?,?,?,?,?)', ('human-937', 'project:937', '0' * 64, 1000, 'intent'))
    restarted = module.ReviewServer(0, origin=server.origin, account=server.account,
                                    audit_db=directory / 'audit.db')
    restarted.server_close()
    with sqlite3.connect(directory / 'audit.db') as db:
        assert db.execute('SELECT outcome FROM review_audit').fetchall() == [('unknown',)]
    assert (directory / 'audit.db').stat().st_mode & 0o077 == 0


def test_private_config_and_project_binding(app):
    server, _, _, _, directory = app
    config = directory / 'wrapper.json'
    config.write_text('{}')
    config.chmod(0o644)
    with pytest.raises(ValueError):
        module.private_file(config)
    config.chmod(0o600)
    assert module.private_file(config) == config
    for origin in ['http://review.example.test', 'https://review.example.test/path', 'https://evil.test']:
        with pytest.raises(ValueError):
            module.ReviewServer(0, origin=origin, account=server.account, audit_db=directory / 'other.db')
