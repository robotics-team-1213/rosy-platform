import json
import sqlite3
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_account_authority import authority, ISSUER, CALLBACK, CHALLENGE
from fleet.server.account_authority_routes import install_account_authority_routes
from fleet.server.password_session import COOKIE, StalePasswordCheck


def client_for(authority):
    engine, context, _ = authority
    class Sessions:
        def account_context(self, cookie):
            if cookie != 'test-cookie':
                raise StalePasswordCheck()
            return context
    app = FastAPI()
    install_account_authority_routes(app, sessions=Sessions(), authority=engine)
    return TestClient(app, base_url=ISSUER, follow_redirects=False)


def query(**changes):
    return urlencode({'response_type': 'code', 'client_id': 'robot-app', 'redirect_uri': CALLBACK,
        'scope': 'robot:r1', 'state': 'state-1', 'code_challenge': CHALLENGE,
        'code_challenge_method': 'S256', **changes})


def test_login_return_is_local_and_invalid_clients_are_not_redirected(authority):
    client = client_for(authority)
    response = client.get('/api/fleet/auth/authorize?' + query())
    assert response.status_code == 303
    assert response.headers['location'].startswith('/console/login?return=')
    assert client.get('/api/fleet/auth/authorize?' + query(redirect_uri='https://evil.test')).status_code == 400


def test_normal_cookie_automatically_authorizes_registered_app(authority):
    client = client_for(authority)
    client.cookies.set(COOKIE, 'test-cookie')
    response = client.get('/api/fleet/auth/authorize?' + query())
    assert response.status_code == 302
    assert response.headers['location'].startswith(CALLBACK + '?')
    assert response.headers['cache-control'] == 'no-store'
    jwks = client.get('/api/fleet/auth/keys').json()
    assert 'd' not in jwks['keys'][0]


def test_protocol_input_is_bounded_and_storage_failure_is_safe(authority, monkeypatch):
    client = client_for(authority)
    response = client.post('/api/fleet/auth/token', content='x' * 9000,
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
    assert response.status_code == 413
    assert client.post('/api/fleet/auth/token', json={}).status_code == 415
    def failure(body):
        raise sqlite3.OperationalError('private database path and secret')
    monkeypatch.setattr(authority[0], 'token', failure)
    response = client.post('/api/fleet/auth/token', data={'grant_type': 'refresh_token'})
    assert response.status_code == 503
    assert 'private' not in response.text and 'secret' not in response.text
