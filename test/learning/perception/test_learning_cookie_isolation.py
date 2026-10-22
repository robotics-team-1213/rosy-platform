"""Same-host Learning ports keep signed sessions and both OAuth bindings independent."""
import base64
from contextlib import contextmanager
import hashlib
from http.cookiejar import CookieJar
import json
import ssl
import subprocess
import threading
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import build_opener, HTTPCookieProcessor, HTTPSHandler, HTTPRedirectHandler, Request

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from browser_harness import free_port
from core_common.protocol.account_access import sign_access
from core_common.protocol.account_client import AccountClient
from learning_collaboration import Collaboration, COOKIE, BINDING
from learning_oauth import OAuth
from learning_rosy_accounts import RosyAccounts
from review_app import make_server
from test_learning_accounts import accounts  # noqa: F401 — isolated encrypted account configuration
from test_learning_oauth import Provider
from test_review_app import open_store


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Authority:
    def __init__(self, pem, subject, client):
        self.pem, self.subject, self.client = pem, subject, client
        self.challenge, self.active = '', True

    def __call__(self, endpoint, fields):
        if endpoint == 'introspect':
            return {'active': self.active}
        if endpoint == 'revoke':
            self.active = False
            return {}
        if endpoint == 'userinfo':
            return {'account_id': self.subject, 'login': self.subject, 'display_name': self.subject}
        assert endpoint == 'token' and fields['client_id'] == self.client
        assert base64.urlsafe_b64encode(hashlib.sha256(fields['code_verifier'].encode()).digest()).rstrip(b'=').decode() == self.challenge
        now = int(time.time())
        return {'token_type': 'Bearer', 'refresh_token': 'fixture-' + self.client,
            'access_token': sign_access({'iss': 'https://account.example.test', 'aud': 'project:one',
                'sub': self.subject, 'sid': 'family-' + self.client, 'jti': 'cookie-isolation-' + self.client,
                'rev': 1, 'iat': now, 'exp': now + 300,
                'grants': [{'resource': 'project:one', 'capabilities': ['learning.view', 'learning.import']}]},
                self.pem, key_id='fixture')}


@contextmanager
def learning_apps(tmp_path, accounts):
    cert, tls_key = tmp_path / 'cert.pem', tmp_path / 'tls.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(tls_key),
                    '-out', str(cert), '-days', '1', '-subj', '/CN=localhost'], check=True, capture_output=True)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.load_cert_chain(cert, tls_key)
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    apps = []
    try:
        for index, owner in enumerate(['alice', 'bob']):
            folder = tmp_path / f'app-{index}'; folder.mkdir()
            port = free_port(); origin = f'https://127.0.0.1:{port}'
            client = f'learning-{index}'; subject = 'central-' + owner
            authority = Authority(pem, subject, client)
            receiver = AccountClient(folder / 'receiver.sqlite', issuer='https://account.example.test',
                client_id=client, resource='project:one', callback=origin + '/api/account/callback',
                public_keys={'fixture': public}, encryption_key=Fernet.generate_key(), post=authority,
                destinations=('/accounts', '/'))
            config = accounts.config()
            config.update(public_origin=origin, account_subjects={subject:owner},
                oauth={'client_id':'client', 'redirect_uri':origin + '/oauth/huggingface/callback'})
            managed = RosyAccounts(folder / 'learning.sqlite', accounts.key_path, config, receiver=receiver)
            review = folder / 'review'; review.mkdir()
            provider = Provider()
            server = make_server(open_store(review), port, accounts=managed, oauth=OAuth(managed, transport=provider))
            server.socket = tls.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            apps.append((origin, authority, provider, receiver, server, thread))
        yield apps
    finally:
        for _, _, _, _, server, thread in apps:
            server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_signed_sessions_and_pending_bindings_survive_another_learning_port(tmp_path, accounts):
    jar = CookieJar()
    # Two fixed HTTPS origins on one hostname share the browser cookie jar, including ports.
    context = ssl._create_unverified_context()
    browser = build_opener(HTTPCookieProcessor(jar), HTTPSHandler(context=context), NoRedirect())

    def request(origin, path, body=None, token=None):
        headers = {'Origin':origin}
        if token is not None:
            headers['X-Pinky-Token'] = token
        if body is not None:
            headers['Content-Type'] = 'application/json'
        req = Request(origin + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            response = browser.open(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.code, response.headers, json.loads(raw) if raw else None

    with learning_apps(tmp_path, accounts) as apps:
        flows = []
        for origin, authority, *_ in apps:
            status, headers, _ = request(origin, '/api/account/login?return=/accounts')
            assert status == 303
            query = parse_qs(urlsplit(headers['Location']).query)
            authority.challenge = query['code_challenge'][0]
            flows.append(query)
        # Completing the first flow after starting the second must still verify its own PKCE binding.
        for (origin, *_), query in zip(apps, flows):
            status, _, _ = request(origin, '/api/account/callback?' + urlencode({'state':query['state'][0], 'code':'fixture'}))
            assert status == 303
        sessions = [request(app[0], '/api/accounts/session') for app in apps]
        assert [result[0] for result in sessions] == [200, 200]
        assert [result[2]['user_id'] for result in sessions] == ['alice', 'bob']
        assert sessions[0][2]['account_session'] != sessions[1][2]['account_session']
        assert sessions[0][2]['token'] != sessions[1][2]['token']
        # An app's CSRF proof cannot authorize HF binding at another app.
        assert request(apps[1][0], '/api/accounts/oauth', {'purpose':'link'}, sessions[0][2]['token'])[0] == 403

        hf_flows = []
        for app, session in zip(apps, sessions):
            status, headers, body = request(app[0], '/api/accounts/oauth', {'purpose':'link'}, session[2]['token'])
            assert status == 200
            hf_flows.append(parse_qs(urlsplit(body['url']).query))
            assert 'HttpOnly' in headers['Set-Cookie'] and 'Secure' in headers['Set-Cookie']
        assert len([cookie for cookie in jar if cookie.name.startswith(BINDING)]) == 2
        for index, (app, query) in enumerate(zip(apps, hf_flows)):
            now = int(time.time())
            app[2].claims = {'iss':'https://huggingface.co', 'aud':'client', 'sub':f'hf-owner-{index}',
                'exp':now + 300, 'iat':now, 'nonce':query['nonce'][0]}
            status, _, _ = request(app[0], '/oauth/huggingface/callback?' + urlencode({'state':query['state'][0], 'code':'fixture'}))
            assert status == 303
        assert [request(app[0], '/api/accounts/session')[2]['connections'][0]['subject'] for app in apps] == ['hf-owner-0', 'hf-owner-1']

        assert request(apps[0][0], '/api/accounts/logout', {}, sessions[0][2]['token'])[0] == 200
        assert request(apps[0][0], '/api/accounts/session')[0] == 401
        remaining = request(apps[1][0], '/api/accounts/session')
        assert remaining[0] == 200 and remaining[2]['user_id'] == 'bob'
        assert apps[0][1].active is False and apps[1][1].active is True
        # A genuine receiver session in the old unsuffixed cookie is never a fallback.
        session_cookie = next(cookie for cookie in jar if cookie.name.startswith(COOKIE))
        jar.clear(session_cookie.domain, session_cookie.path, session_cookie.name)
        session_cookie.name = COOKIE
        jar.set_cookie(session_cookie)
        assert request(apps[1][0], '/api/accounts/session')[0] == 401


def test_cookie_namespace_includes_project_and_legacy_mode_stays_compatible():
    from types import SimpleNamespace
    app = object.__new__(Collaboration)
    app.receiver = True; app.origin = 'https://learning.example.test:9444'
    app.accounts = SimpleNamespace(project_id='one')
    first = app.cookie_name(COOKIE)
    app.accounts.project_id = 'two'
    assert app.cookie_name(COOKIE) != first
    app.receiver = None
    assert app.cookie_name(COOKIE) == COOKIE
