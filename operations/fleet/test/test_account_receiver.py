"""Fleet PKCE receiver keeps the issuer's exact capabilities and uses a distinct cookie."""
from copy import deepcopy
import json
from urllib.parse import urlencode, urlsplit

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from core_common.protocol.account_client import AccountClient, AccountUnavailable
from fleet.server.account_authority import AccountAuthority
from fleet.server.account_receiver import COOKIE, FLOW_COOKIE, install_account_receiver
from fleet.server.site_auth import build_authorize, build_role_guards

ISSUER, BASE = 'https://account.test', 'https://fleet.test:8443'


@pytest.fixture
def receiver(tmp_path, monkeypatch):
    from fleet.server import account_receiver
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption())
    public = private.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
    context = {'account_id': 'account-1', 'principal_id': 'alice', 'login': 'alice',
               'display_name': 'Alice', 'role': 'operator', 'revision': 1, 'session_family': 'family-1',
               'grants': [{'resource': 'site:one', 'capabilities': ['fleet.read']}]}
    families = {'family-1': context}
    authority = AccountAuthority(tmp_path / 'authority.db', issuer=ISSUER, private_key=pem, key_id='one',
        clients={'fleet': {'redirect_uris': [BASE + '/api/fleet/auth/callback'], 'resources': ['site:one']}},
        resolve_family=lambda db, family: deepcopy(families.get(family)),
        revoke_family=lambda db, family: families.pop(family, None), clock=lambda: 1000)
    def post(endpoint, fields):
        if endpoint == 'token':
            _, body, status = authority.token(urlencode(fields))
            if status != 200:
                raise ValueError('exchange refused')
            return json.loads(body)
        return getattr(authority, endpoint)(fields['token'])
    account = AccountClient(tmp_path / 'receiver.db', issuer=ISSUER, client_id='fleet', resource='site:one',
        callback=BASE + '/api/fleet/auth/callback', public_keys={'one': public}, encryption_key=Fernet.generate_key(),
        post=post, clock=lambda: 1000, destinations=('/console',))
    monkeypatch.setattr(account_receiver, 'load_account_client', lambda *a, **k: account)
    app = FastAPI()
    sessions = install_account_receiver(app, config=tmp_path / 'public.json')
    authorize = build_authorize(None, {}, None, None, sessions)
    viewer, operator, _, _ = build_role_guards(authorize, {}, named_logins=True)
    @app.get('/read')
    def read(principal=Depends(viewer)):
        return {'id': principal.principal_id, 'grants': principal.grants}
    @app.post('/operate')
    def operate(principal=Depends(operator)):
        return {'ok': True}
    client = TestClient(app, base_url=BASE, follow_redirects=False)
    return client, account, authority, context, families


def login(receiver):
    client, _, authority, context, _ = receiver
    response = client.get('/console/login')
    assert response.status_code == 303 and FLOW_COOKIE in response.cookies
    url = response.headers['location']
    assert url.startswith(ISSUER + '/api/fleet/auth/authorize?')
    headers, _, status = authority.authorize(urlsplit(url).query, context)
    assert status == 302
    callback = client.get(headers['Location'])
    assert callback.status_code == 303 and callback.headers['location'] == '/console'
    assert COOKIE in callback.cookies and 'rosy_fleet_session' not in callback.cookies
    return client


def test_receiver_pkce_cookie_grants_csrf_and_online_revocation(receiver):
    client = login(receiver)
    response = client.get('/api/fleet/auth/session')
    assert response.json()['grants'] == [{'resource': 'site:one', 'capabilities': ['fleet.read']}]
    assert response.json()['role'] == 'viewer'  # Display role cannot invent fleet.operate.
    assert client.get('/read').json()['id'] == 'account-1'
    assert client.post('/operate').status_code == 403
    assert client.post('/operate', headers={'Origin': BASE}).status_code == 403
    assert client.get('/console/profile').headers['location'] == ISSUER + '/console/profile'
    assert client.get('/console/accounts').headers['location'] == ISSUER + '/console/accounts'
    receiver[4].clear()
    # AccountClient's strict online check happens after its bounded ten-second cache.
    receiver[1].clock = lambda: 1011
    assert client.get('/read').status_code == 401


def test_receiver_signed_bearer_preserves_capabilities_and_rejects_tampering(receiver):
    client = login(receiver)
    account = receiver[1]
    with account.transaction() as db:
        row = db.execute('SELECT tokens FROM app_account_sessions').fetchone()
    tokens = json.loads(account.cipher.decrypt(row['tokens']))
    access_value = tokens['access_token']
    client.cookies.clear()
    assert client.get('/read', headers={'Authorization': 'Bearer ' + access_value}).status_code == 200
    session = client.get('/api/fleet/auth/session', headers={'Authorization': 'Bearer ' + access_value})
    assert session.status_code == 200 and session.json()['via'] == 'bearer'
    assert client.post('/operate', headers={'Authorization': 'Bearer ' + access_value}).status_code == 403
    parts = access_value.split('.')
    parts[1] = parts[1][:-2] + 'xx'
    assert client.get('/read', headers={'Authorization': 'Bearer ' + '.'.join(parts)}).status_code == 401


def test_receiver_combined_operation_and_policy_grants_keep_operator_role(receiver):
    receiver[3]['grants'][0]['capabilities'] = ['fleet.read', 'fleet.operate', 'fleet.policy']
    client = login(receiver)
    session = client.get('/api/fleet/auth/session').json()
    assert session['role'] == 'operator'
    assert session['grants'] == [{'resource': 'site:one',
                                  'capabilities': ['fleet.operate', 'fleet.policy', 'fleet.read']}]
    assert client.post('/operate', headers={'Origin': BASE}).status_code == 200


def test_receiver_display_role_does_not_add_read_access(receiver):
    receiver[3]['grants'][0]['capabilities'] = ['accounts.manage']
    client = login(receiver)
    assert client.get('/api/fleet/auth/session').json()['role'] == 'viewer'
    assert client.get('/read').status_code == 403
    assert client.post('/operate', headers={'Origin': BASE}).status_code == 403


def test_receiver_proposer_lookup_uses_live_account_session_and_ignores_fleet_database(receiver):
    from fleet.server.account_receiver import FleetAccountSessions
    receiver[3]['grants'][0]['capabilities'] = ['fleet.read', 'fleet.operate']
    login(receiver)
    sessions = FleetAccountSessions(receiver[1])
    current = sessions.principal_by_id('account-1', db=object())
    assert current.role == 'operator' and current.permits_site('fleet.operate')
    assert sessions.principal_by_id('unknown', db=object()) is None
    assert sessions.migrated_principal('unknown', db=object()) is False
    receiver[4].clear()
    receiver[1].clock = lambda: 1001  # Inside normal receiver cache; recovery still requires a fresh check.
    assert sessions.principal_by_id('account-1', db=object()) is None


def test_receiver_proposer_lookup_fails_closed_without_retained_session_or_online_authority(receiver):
    from fleet.server.account_receiver import FleetAccountSessions
    sessions = FleetAccountSessions(receiver[1])
    assert sessions.principal_by_id('account-1') is None
    login(receiver)
    def unavailable(endpoint, fields):
        raise AccountUnavailable()
    receiver[1].post = unavailable
    with pytest.raises(ValueError, match='proposer state unavailable'):
        sessions.principal_by_id('account-1')


def test_receiver_logout_is_local_first_and_retried(receiver):
    client = login(receiver)
    account = receiver[1]
    original = account.post
    def unavailable(endpoint, fields):
        if endpoint == 'revoke':
            raise AccountUnavailable()
        return original(endpoint, fields)
    account.post = unavailable
    assert client.post('/api/fleet/auth/logout', headers={'Origin': BASE}).status_code == 503
    assert client.get('/read').status_code == 401
    with account.transaction() as db:
        assert db.execute('SELECT count(*) FROM app_account_revocations').fetchone()[0] == 1
    account.post = original
    account.retry_revocations()
    assert receiver[4] == {}


def test_receiver_rejects_callback_parameter_pollution_and_open_returns(receiver):
    client = receiver[0]
    assert client.get('/api/fleet/auth/login?return=https://evil.test').status_code == 401
    assert client.get('/api/fleet/auth/callback?code=x&code=y&state=z').status_code == 401


def test_receiver_sends_a_person_back_to_the_console_when_the_login_flow_expired(receiver):
    client = receiver[0]
    assert client.get('/api/fleet/auth/callback?code=x&state=z').status_code == 401
    page = client.get('/api/fleet/auth/callback?code=x&state=z', headers={'Accept': 'text/html'}, follow_redirects=False)
    assert page.status_code == 303 and page.headers['location'] == '/console'
    assert COOKIE not in page.cookies


@pytest.mark.parametrize('target', [
    '/console?view=work&show=new',
    '/console?view=records&show=log&inbox=1',
    '/console?view=work&arm_transfer=job:one&robot=r1',
    '/console/site-map?robot=r1#teach-heading',
    '/console/install#cameras',
])
def test_receiver_pkce_preserves_known_document_query_and_anchor(receiver, target):
    client, _, authority, context, _ = receiver
    response = client.get('/console/login', params={'return': target})
    assert response.status_code == 303
    headers, _, status = authority.authorize(urlsplit(response.headers['location']).query, context)
    assert status == 302
    result = client.get(headers['Location'])
    assert result.status_code == 303
    assert result.headers['location'] == target


@pytest.mark.parametrize('target', [
    'https://evil.test/console?view=work', '//evil.test/console', '/console\\evil', '/console\n?view=work',
    '/console?unknown=value', '/console?view=work&view=records', '/console?view=other',
    '/console?show=new', '/console?view=work&show=other', '/console?inbox=0',
    '/console?view=records&arm_transfer=job:one', '/console?view=work&arm_transfer=bad/one',
    '/console?robot=' + 'x' * 129, '/console?robot=../../x', '/console/site-map#other', '/console/install#other',
    '/console/install?view=work', '/api/fleet/auth/authorize?client_id=evil',
    '/console?view=work&arm_transfer=' + 'x' * 193, '/console?' + 'x' * 4096,
])
def test_receiver_rejects_unsafe_or_unknown_document_returns(receiver, target):
    response = receiver[0].get('/console/login', params={'return': target})
    assert response.status_code == 401
    assert FLOW_COOKIE not in response.cookies


def test_fleet_receiver_does_not_create_authority_tables(receiver, tmp_path):
    import sqlite3
    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.swarm.robots import RobotEndpoint
    console = FleetConsole([RobotEndpoint('r1', 'http://127.0.0.1:8081', 't')], [FakeRobot('r1')])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / 'fleet.db'), robot_ids=console.robot_ids)
    app = create_app(console, task_service=tasks, account_client_config=tmp_path / 'public.json')
    assert app.state.account_authority is None
    assert app.state.password_sessions.client is receiver[1]
    with sqlite3.connect(tasks.store.path) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'rosy_accounts' not in tables and 'fleet_console_passwords' not in tables
    with pytest.raises(ValueError, match='cannot own'):
        create_app(console, task_service=tasks, account_client_config=tmp_path / 'public.json',
                   account_config=tmp_path / 'private.json')


def _machine_receiver_app(tmp_path, users, logins=None):
    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.swarm.robots import RobotEndpoint
    console = FleetConsole([RobotEndpoint('r1', 'http://127.0.0.1:8081', 'robot-key')], [FakeRobot('r1')])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / 'fleet.db'), robot_ids=console.robot_ids)
    return create_app(console, task_service=tasks, site_users=users, site_logins=logins,
                      account_client_config=tmp_path / 'public.json',
                      vision_lease_secret='v' * 32, vision_sources=('camera-1',))


def test_receiver_explicit_machine_viewer_reads_health_without_command_or_proposal_authority(receiver, tmp_path):
    from hashlib import sha256
    credential = 'health-check-credential'
    users = {sha256(credential.encode()).hexdigest(): {
        'principal_id': 'health-check', 'role': 'viewer', 'machine': True},
        sha256(b'human-legacy-credential').hexdigest(): {'principal_id': 'alice', 'role': 'viewer'}}
    app = _machine_receiver_app(tmp_path, users)
    client = TestClient(app, base_url=BASE)
    headers = {'Authorization': 'Bearer ' + credential}
    assert client.get('/api/fleet/state', headers=headers).status_code == 200
    assert client.get('/api/fleet/dispatch-control', headers=headers).status_code == 200
    sources = client.get('/api/fleet/vision/sources', headers=headers)
    assert sources.status_code == 200 and sources.json() == {'sources': ['camera-1']}
    assert client.post('/api/fleet/estop', headers=headers, json={}).status_code == 403
    assert client.post('/api/fleet/trip-proposals', headers=headers, json={
        'candidate_robot_ids': ['r1'], 'request_key': 'health/check',
        'steps': [{'to': 'B', 'via': []}]}).status_code == 403
    for path in ('/api/fleet/state', '/api/fleet/vision/sources'):
        assert client.get(path, headers={'Authorization': 'Bearer human-legacy-credential'}).status_code == 401


@pytest.mark.parametrize('changes', [
    {'machine': False}, {'machine': 'true'}, {'machine': 1}, {'machine': None},
    {'role': 'operator'}, {'role': 'policy-admin'}, {'role': 'service'}, {'role': 'ai_observer'},
    {'login': 'health'}, {'password_scrypt': 'unused'}, {'policy_admin': False}, {'policy_admin': True},
    {'login': 'health', 'password_scrypt': 'unused'},
])
def test_receiver_rejects_invalid_programmatic_machine_entries_at_startup(receiver, tmp_path, changes):
    from hashlib import sha256
    users = {sha256(b'health-check-credential').hexdigest(): {
        'principal_id': 'health-check', 'role': 'viewer', 'machine': True, **changes}}
    with pytest.raises(ValueError):
        _machine_receiver_app(tmp_path, users)


def test_receiver_rejects_machine_principal_shared_with_human_login(receiver, tmp_path):
    from hashlib import sha256
    users = {sha256(b'health-check-credential').hexdigest(): {
        'principal_id': 'health-check', 'role': 'viewer', 'machine': True}}
    logins = {'alice': {'principal_id': 'health-check', 'role': 'viewer', 'password_scrypt': 'unused'}}
    with pytest.raises(ValueError):
        _machine_receiver_app(tmp_path, users, logins)
