import json
import sqlite3
from urllib.parse import urlencode, parse_qs, urlsplit

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


def test_userinfo_is_access_bound_live_and_no_store(authority):
    from test_account_authority import get_code, exchange
    engine, context, families = authority
    context.update(login='alice', display_name='Alice')
    families[context['session_family']].update(login='alice', display_name='Alice')
    token = json.loads(exchange(engine, get_code(engine, context))[1])['access_token']
    client = client_for(authority)
    response = client.post('/api/fleet/auth/userinfo', data={'token':token})
    assert response.status_code == 200
    assert response.json() == {'account_id':context['account_id'], 'login':'alice', 'display_name':'Alice'}
    assert response.headers['cache-control'] == 'no-store'
    families[context['session_family']]['display_name'] = 'Updated'
    assert client.post('/api/fleet/auth/userinfo', data={'token':token}).json()['display_name'] == 'Updated'
    assert client.post('/api/fleet/auth/userinfo', data={'token':'bad'}).status_code == 401
    families.clear()
    assert client.post('/api/fleet/auth/userinfo', data={'token':token}).status_code == 401


def test_userinfo_storage_failure_is_503(authority, monkeypatch):
    client = client_for(authority)
    def fail(token):
        raise sqlite3.OperationalError('secret database')
    monkeypatch.setattr(authority[0], 'userinfo', fail)
    response = client.post('/api/fleet/auth/userinfo', data={'token':'test'})
    assert response.status_code == 503 and 'secret' not in response.text


def test_denied_browser_authorization_recovers_in_login_but_api_stays_403(authority):
    engine, context, families = authority
    families[context['session_family']]['grants'] = []
    client = client_for(authority)
    client.cookies.set(COOKIE, 'test-cookie')
    target = '/api/fleet/auth/authorize?' + query()
    api = client.get(target)
    assert api.status_code == 403 and api.json() == {'error': 'access_denied'}
    response = client.get(target, headers={'Accept': 'text/html'})
    assert response.status_code == 303
    location = urlsplit(response.headers['location'])
    assert location.path == '/console/login'
    assert parse_qs(location.query) == {'error': ['access_denied'], 'return': [target]}
    assert response.headers['cache-control'] == 'no-store'
    assert families[context['session_family']]['grants'] == []


def test_invalid_browser_request_does_not_preserve_untrusted_return(authority):
    client = client_for(authority)
    response = client.get('/api/fleet/auth/authorize?' + query(redirect_uri='https://evil.test'),
                          headers={'Accept': 'text/html'})
    assert response.status_code == 303
    location = urlsplit(response.headers['location'])
    assert location.path == '/console/login'
    assert parse_qs(location.query) == {'error': ['invalid_request'], 'return': ['/console']}
    assert 'evil.test' not in response.headers['location']


def test_browser_storage_outage_recovers_without_leaking_and_api_stays_503(authority, monkeypatch):
    client = client_for(authority)
    client.cookies.set(COOKIE, 'test-cookie')
    def fail(*args):
        raise sqlite3.OperationalError('private database secret')
    monkeypatch.setattr(authority[0], 'authorize', fail)
    target = '/api/fleet/auth/authorize?' + query()
    response = client.get(target, headers={'Accept': 'text/html'})
    assert response.status_code == 303
    assert parse_qs(urlsplit(response.headers['location']).query) == {
        'error': ['service_unavailable'], 'return': [target]}
    assert 'private' not in response.headers['location'] and 'secret' not in response.text
    assert client.get(target).status_code == 503
