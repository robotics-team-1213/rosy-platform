"""D-992: Account's narrow device route, and Fleet's link that never undoes the robot's hub link."""
import asyncio
import hashlib
import json
import os
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.account_link import AccountLink
from rosy_account.client_registry import ClientRegistry
from rosy_account.device_client_routes import install_device_client_routes
from test_account_client_registry import CALLBACK, Ledger, make_authority
from test_enrollment_hub_link import enrolled

TOKEN = 'registrar' + '-fixture-' + 'k' * 32
ISSUER = 'https://account.example.test'
ROBOT_BASE = 'https://rosy-09.local:8443'
DEVICE = {'callback': ROBOT_BASE + '/api/account/callback', 'home_url': ROBOT_BASE + '/dashboard', 'label': 'rosy_09'}
PATH = '/api/fleet/auth/device-clients/rosy_09'
AUTH = {'Authorization': 'Bearer ' + TOKEN}


@pytest.fixture
def account(tmp_path):
    authority = make_authority(tmp_path / 'accounts.sqlite3', {'app': {'redirect_uris': [CALLBACK], 'resources': ['robot:r1']}})
    app = FastAPI()
    install_device_client_routes(app, authority, clock=lambda: 1000,
                                 registrar_token_sha256=hashlib.sha256(TOKEN.encode()).hexdigest())
    return authority, TestClient(app, raise_server_exceptions=False)


def test_the_route_needs_the_registrar_key_and_is_closed_without_one(account, tmp_path):
    authority, client = account
    assert client.put(PATH, json=DEVICE).status_code == 403
    assert client.put(PATH, content=b'not json').status_code == 403, 'nothing is parsed before the key'
    assert client.put(PATH, json=DEVICE, headers={'Authorization': 'Bearer wrong'}).status_code == 403
    assert client.put(PATH, json=DEVICE, headers={'Authorization': 'Basic ' + TOKEN}).status_code == 403
    assert 'robot-rosy_09' not in authority.clients
    closed = FastAPI()
    install_device_client_routes(closed, authority, registrar_token_sha256=None, clock=lambda: 1000)
    assert TestClient(closed).put(PATH, json=DEVICE, headers=AUTH).status_code == 403
    assert TestClient(closed).put(PATH, json=DEVICE, headers={'Authorization': 'Bearer '}).status_code == 403


def test_it_writes_only_this_robots_row(account):
    authority, client = account
    made = client.put(PATH, json=DEVICE, headers=AUTH)
    assert made.status_code == 200
    assert made.json()['client_id'] == 'robot-rosy_09' and made.json()['resources'] == ['robot:rosy_09']
    assert authority.clients['robot-rosy_09']['redirect_uris'] == [DEVICE['callback']]
    assert client.put(PATH, json={**DEVICE, 'resources': ['site:all']}, headers=AUTH).status_code == 422
    assert client.put(PATH, json={**DEVICE, 'callback': ROBOT_BASE + '/steal'}, headers=AUTH).status_code == 422
    assert client.put(PATH, json={**DEVICE, 'callback': 'http://rosy-09.local/api/account/callback'}, headers=AUTH).status_code == 422
    assert client.put('/api/fleet/auth/device-clients/bad%20id', json=DEVICE, headers=AUTH).status_code == 422
    assert client.put(PATH, content=b'not json', headers=AUTH).status_code == 422
    assert client.put(PATH, content=b'{' + b' ' * 9000 + b'}', headers=AUTH).status_code == 422
    with authority.transaction() as db:
        rows = db.execute('SELECT * FROM account_client_audit').fetchall()
    assert [(r['actor_account_id'], r['client_id'], r['following_revision']) for r in rows] == [('device-registrar', 'robot-rosy_09', 1)]


def test_a_person_registered_row_with_that_name_is_refused(account):
    authority, client = account
    registry = ClientRegistry(Ledger(authority), lambda: 1000)
    registry.create('manager', client_id='robot-rosy_09', redirect_uris=[CALLBACK], resources=['robot:rosy_09'])
    assert client.put(PATH, json=DEVICE, headers=AUTH).status_code == 409, 'same resource, a person\'s own callback'
    assert authority.clients['robot-rosy_09']['redirect_uris'] == [CALLBACK]
    registry.update('manager', 'robot-rosy_09', revision=1, resources=['site:one'])
    assert client.put(PATH, json=DEVICE, headers=AUTH).status_code == 409


def test_repeating_is_a_no_op_and_an_administrators_stop_survives(account):
    authority, client = account
    registry = ClientRegistry(Ledger(authority), lambda: 1000)
    assert client.put(PATH, json=DEVICE, headers=AUTH).json()['revision'] == 1
    assert client.put(PATH, json=DEVICE, headers=AUTH).json()['revision'] == 1
    registry.update('manager', 'robot-rosy_09', revision=1, enabled=False)
    moved = client.put(PATH, json={**DEVICE, 'label': 'renamed'}, headers=AUTH).json()
    assert moved['enabled'] is False and moved['label'] == 'renamed' and moved['revision'] == 3
    assert 'robot-rosy_09' not in authority.clients


def link(handler):
    return AccountLink(issuer=ISSUER, registrar_token=TOKEN, public_keys={'key-1': 'PEM'},
                       transport=httpx.MockTransport(handler))


class Robot:
    def __init__(self, *, supported=True, error=None, capability_error=None):
        self._ep = SimpleNamespace(base_url=ROBOT_BASE + '/')
        self.supported, self.error, self.capability_error, self.received = supported, error, capability_error, []

    async def capabilities(self):
        if self.capability_error:
            raise self.capability_error
        return {'account_receiver_provisioning': self.supported}

    async def account_receiver_put(self, body):
        self.received.append(body)
        if self.error:
            raise self.error
        return {'configured': True}


def accepted(request):
    assert request.headers['authorization'] == 'Bearer ' + TOKEN
    assert json.loads(request.content) == DEVICE
    return httpx.Response(200, json={'client_id': 'robot-rosy_09'})


def test_success_sends_public_values_in_order():
    robot, seen = Robot(), []
    def handler(request):
        seen.append(request.url.path)
        assert robot.received == [], 'the registry row comes before the robot'
        return accepted(request)
    account = link(handler)
    assert asyncio.run(account.provision('rosy_09', robot)) == 'linked'
    assert seen == [PATH] and account.states == {'rosy_09': 'linked'}
    assert robot.received == [{'issuer': ISSUER, 'client_id': 'robot-rosy_09', 'callback': DEVICE['callback'],
                               'public_keys': {'key-1': 'PEM'}}]
    assert TOKEN not in json.dumps(robot.received), 'the registrar key never reaches a robot'


@pytest.mark.parametrize('robot,handler,state', [
    (lambda: Robot(supported=False), accepted, 'robot_unsupported'),
    (lambda: Robot(capability_error=OSError('down')), accepted, 'robot_unreachable'),
    (lambda: Robot(error=OSError('refused')), accepted, 'robot_refused'),
    (Robot, lambda request: httpx.Response(403, json={}), 'account_unreachable'),
    (Robot, lambda request: httpx.Response(200, json={}), 'account_unreachable'),
    (Robot, lambda request: (_ for _ in ()).throw(httpx.ConnectError('down')), 'account_unreachable'),
])
def test_failures_name_the_step_and_never_raise(robot, handler, state):
    assert asyncio.run(link(handler).provision('rosy_09', robot())) == state


def test_a_failed_account_link_keeps_the_hub_link_and_is_visible(tmp_path):
    service, _, console, store = enrolled(tmp_path)
    robot = console._clients['rosy_09']
    service._account_link = link(lambda request: httpx.Response(503, json={}))
    row = asyncio.run(service.link_hub('rosy_09', principal_id='alice'))
    assert row['hub_linked'] is True and len(robot.puts) == 1, 'people\'s login never undoes the robot link'
    assert store.get('rosy_09')['hub_digest']
    assert row['account_link'] in {'robot_unsupported', 'account_unreachable'}


def test_a_hung_account_never_holds_the_hub_lock(tmp_path):
    service, _, console, _ = enrolled(tmp_path)
    seen = {}
    class Probe:
        states = {}
        async def provision(self, robot_id, client):
            seen['locked'] = service._hub_lock(robot_id).locked()
            return 'linked'
    service._account_link = Probe()
    asyncio.run(service.link_hub('rosy_09', principal_id='alice'))
    assert seen == {'locked': False}


def test_a_robot_unlinked_after_the_lock_is_not_provisioned(tmp_path):
    service, _, console, _ = enrolled(tmp_path)
    calls = []
    class Probe:
        states = {}
        async def provision(self, robot_id, client):
            calls.append(robot_id)
            return 'linked'
    service._account_link = Probe()
    service._tls_client = lambda robot_id: None
    row = asyncio.run(service.link_hub('rosy_09', principal_id='alice'))
    assert calls == [] and row['account_link'] == 'robot_unreachable' and row['hub_linked'] is True


def test_load_reads_a_private_token_file(tmp_path):
    token = tmp_path / 'registrar'
    token.write_text(TOKEN + '\n', encoding='utf-8')
    if os.name == 'posix':
        token.chmod(0o600)
    (tmp_path / 'key.pem').write_text('PEM', encoding='ascii')
    config = tmp_path / 'link.json'
    config.write_text(json.dumps({'issuer': ISSUER, 'registrar_token_file': 'registrar',
                                  'public_key_files': {'key-1': 'key.pem'}}), encoding='utf-8')
    loaded = AccountLink.load(config)
    assert loaded.issuer == ISSUER and loaded.public_keys == {'key-1': 'PEM'}
    if os.name == 'posix':
        token.chmod(0o644)
        with pytest.raises(ValueError):
            AccountLink.load(config)
    config.write_text(json.dumps({'issuer': ISSUER}), encoding='utf-8')
    with pytest.raises(ValueError):
        AccountLink.load(config)
