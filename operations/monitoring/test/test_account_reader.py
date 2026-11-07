"""D-990: Account sessions read their own site; reader keys keep working when Account is down."""

import time

from fastapi.testclient import TestClient

from core_common.protocol.account_access import AccountAccess
from core_common.protocol.account_client import AccountUnavailable
from rosy.monitoring.account_routes import COOKIE, COOKIE_PATH, FLOW_COOKIE, HOME
from rosy.monitoring.config import load_credentials
from rosy.monitoring.service import Collector, create_app
from rosy.monitoring.store import MonitoringStore
from test_cache import runtime, observed_node

KEY = 'reader-secret-for-tests-only-00000000'
SNAPSHOT = '/api/monitoring/v1/snapshot'
RESOURCE = 'site:site-a'


def claims(*capabilities, resource=RESOURCE):
    now = int(time.time())
    return AccountAccess.model_validate({
        'iss': 'https://account.example.test', 'aud': resource, 'sub': 'person', 'sid': 'session', 'jti': 'j' * 16,
        'rev': 1, 'iat': now, 'exp': now + 60, 'grants': [{'resource': resource, 'capabilities': list(capabilities)}]})


class Receiver:
    """The AccountClient calls Monitoring makes; the real client has its own foundation tests."""
    resource, callback, profile_url = RESOURCE, 'https://site.example.test/api/monitoring/v1/account/callback', None

    def __init__(self):
        self.value, self.down, self.logged_out = None, False, []

    def resolve(self, cookie):
        if self.down:
            raise AccountUnavailable()
        return self.value if cookie == 'good' else None

    def profile(self, _cookie):
        return None

    def start(self, target):
        return 'flow', f'https://account.example.test/authorize?target={target}'

    def finish(self, flow, state, code):
        if flow != 'flow' or state != 's' or code != 'c':
            raise ValueError('refused')
        return 'good', HOME

    def logout(self, cookie):
        if self.down:
            raise AccountUnavailable()
        self.logged_out.append(cookie)

    def retry_revocations(self):
        pass


def app(runtime, tmp_path, account):
    cache, _clock = runtime
    collector = Collector(cache.config, load_credentials(cache.config, {'READ': KEY}),
                          MonitoringStore(tmp_path / 'monitoring.sqlite3', cache.config.collector_id))
    collector.cache.update_local('pc-a', nodes=(observed_node(),))
    return TestClient(create_app(collector, account=account), base_url='https://site.example.test')


def test_without_account_config_only_keys_read(runtime, tmp_path):
    client = app(runtime, tmp_path, None)
    assert client.get('/api/monitoring/v1/account/session').json() == {
        'enabled': False, 'authenticated': False, 'can_read': False}
    assert client.get(SNAPSHOT, cookies={COOKIE: 'good'}).status_code == 401
    assert client.get('/api/monitoring/v1/account/login', follow_redirects=False).status_code == 404


def test_capability_decides_what_an_account_reads(runtime, tmp_path):
    receiver = Receiver()
    client = app(runtime, tmp_path, receiver)
    receiver.value = claims('monitoring.read')
    reply = client.get(SNAPSHOT, cookies={COOKIE: 'good'})
    assert reply.status_code == 200 and reply.json()['scope_sites'] == ['site-a']
    assert client.get(SNAPSHOT + '?site_id=secret-site', cookies={COOKIE: 'good'}).status_code == 403
    assert client.get('/api/monitoring/v1/sites/site-a/events', cookies={COOKIE: 'good'}).status_code == 200
    assert client.get('/api/monitoring/v1/account/session', cookies={COOKIE: 'good'}).json()['can_read'] is True

    receiver.value = claims('fleet.read')
    assert client.get(SNAPSHOT, cookies={COOKIE: 'good'}).status_code == 403
    assert client.get('/api/monitoring/v1/sites/site-a/events', cookies={COOKIE: 'good'}).status_code == 403
    assert client.get('/api/monitoring/v1/account/session', cookies={COOKIE: 'good'}).json()['can_read'] is False

    client.cookies.clear()
    assert client.get(SNAPSHOT, cookies={COOKIE: 'expired'}).status_code == 401


def test_account_outage_refuses_sessions_but_not_keys(runtime, tmp_path):
    receiver = Receiver()
    client = app(runtime, tmp_path, receiver)
    receiver.down = True
    down = client.get(SNAPSHOT, cookies={COOKIE: 'good'})
    assert down.status_code == 503 and down.json()['error']['code'] == 'MONITORING_ACCOUNT'
    assert down.headers['cache-control'] == 'no-store'
    client.cookies.clear()
    assert client.get(SNAPSHOT, headers={'Authorization': f'Bearer {KEY}'}).status_code == 200


def test_a_wrong_header_never_falls_back_to_the_cookie(runtime, tmp_path):
    receiver = Receiver()
    receiver.value = claims('monitoring.read')
    client = app(runtime, tmp_path, receiver)
    assert client.get(SNAPSHOT, cookies={COOKIE: 'good'}, headers={'Authorization': 'Bearer wrong'}).status_code == 401


def test_login_flow_and_logout_cookies(runtime, tmp_path):
    receiver = Receiver()
    client = app(runtime, tmp_path, receiver)
    start = client.get('/api/monitoring/v1/account/login', follow_redirects=False)
    assert start.status_code == 303 and start.headers['location'].startswith('https://account.example.test/')
    flow = start.headers['set-cookie']
    assert f'{FLOW_COOKIE}=flow' in flow and f'Path={COOKIE_PATH}' in flow and 'HttpOnly' in flow and 'Secure' in flow

    refused = client.get('/api/monitoring/v1/account/callback?state=s&code=wrong', follow_redirects=False)
    assert refused.status_code == 401
    assert client.get('/api/monitoring/v1/account/callback?state=s', follow_redirects=False).status_code == 401
    done = client.get('/api/monitoring/v1/account/callback?state=s&code=c', follow_redirects=False)
    assert done.status_code == 303 and done.headers['location'] == HOME
    assert any(f'{COOKIE}=good' in value and f'Path={COOKIE_PATH}' in value and 'HttpOnly' in value and 'Secure' in value
               for value in done.headers.get_list('set-cookie'))

    assert client.post('/api/monitoring/v1/account/logout', cookies={COOKIE: 'good'}).status_code == 403
    assert client.post('/api/monitoring/v1/account/logout', cookies={COOKIE: 'good'},
                       headers={'Origin': 'https://evil.example.test'}).status_code == 403
    assert receiver.logged_out == []
    origin = {'Origin': 'https://site.example.test'}
    assert client.post('/api/monitoring/v1/account/logout', cookies={COOKIE: 'good'}, headers=origin).status_code == 200
    assert receiver.logged_out == ['good']
    receiver.down = True
    pending = client.post('/api/monitoring/v1/account/logout', cookies={COOKIE: 'good'}, headers=origin)
    assert pending.status_code == 503 and pending.json()['revocation_pending'] is True
