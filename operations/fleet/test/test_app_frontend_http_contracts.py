"""Exercise frontend-facing reads and writes absent from the initial HTTP evidence."""
from hashlib import sha256

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from fleet.server.app import create_app
from fleet.server.camera_peer_crypto import public_key
from test_camera_peer_routes import client as peer_client
from test_camera_peer_service import receiver, sign


def test_hub_link_create_and_delete_use_enrollment_owner(tmp_path):
    from fastapi import FastAPI
    from fleet.server.enrollment_routes import install_enrollment_routes
    from fleet.server.site_auth import SitePrincipal
    from test_enrollment_hub_link import enrolled
    service, _, _, store = enrolled(tmp_path)
    app = FastAPI()
    principal = lambda: SitePrincipal('alice', 'operator')
    install_enrollment_routes(app, service, require_viewer=principal, require_operator=principal, named_identity=True)
    client = TestClient(app)
    path = '/api/fleet/robots/rosy_09/hub-link'
    assert client.post(path).status_code == 200
    assert store.get('rosy_09')['hub_digest']
    assert client.delete(path).status_code == 200
    assert store.get('rosy_09')['hub_digest'] is None


def test_channel_deliberation_read_is_owned_and_does_not_call_model(tmp_path):
    from fastapi import FastAPI
    from types import SimpleNamespace
    from fleet.server.channel.conversation.runtime import install_conversation_routes
    from fleet.server.channel.model_runtime import BrokerConfig
    from fleet.server.site_auth import SitePrincipal
    from test_channel_model_jobs import model_jobs
    _, journal, _, receipt, snapshot, problem, _ = model_jobs(tmp_path)
    app = FastAPI()
    app.state.channel_requests = journal
    app.state.fleet_gather = SimpleNamespace()
    cfg = BrokerConfig(host='ai.example', key_file='/run/rosy-deliberation/broker.key',
        known_hosts_file='/run/rosy-deliberation/known_hosts', profile_revision='d720-v1', source_commit='a' * 40,
        valid_until=9999999999.0, primary_admitted=True, reviewer_admitted=False)
    install_conversation_routes(app, None, cfg, None, None, lambda: SitePrincipal('op', 'operator'), [])
    app.state.channel_model_jobs.stage(receipt, problem, snapshot)
    client = TestClient(app)
    response = client.get('/api/fleet/channel-requests/' + receipt['request_id'] + '/deliberation')
    assert response.status_code == 200 and response.json()['action_admissible'] is False


def test_cell_document_reads_keep_saved_identity_and_digest(tmp_path):
    from test_cell_job_api import _setup
    from test_cell_app_api import _refs
    client, _, _ = _setup(tmp_path)
    refs = _refs(client)
    headers = {'Authorization':'Bearer operator-secret'}
    listing = client.get('/api/fleet/cell-app/documents', headers=headers)
    assert listing.status_code == 200 and len(listing.json()['documents']) == 2
    for kind in ('recipe', 'cell'):
        response = client.get(f'/api/fleet/cell-app/documents/{kind}/demo', headers=headers)
        assert response.status_code == 200 and response.json()['digest'] == refs[kind + '_digest']


def test_managed_account_reset_and_revoke_are_http_transactions(tmp_path):
    from test_password_session import _app, _client, _login, ORIGIN, TYPED
    from fleet.server.password_session import COOKIE
    app, _ = _app(tmp_path)
    app.state.password_sessions.bootstrap_accounts('alice', 'test-site')
    client = _client(app)
    assert _login(client).status_code == 204
    value = client.cookies.get(COOKIE)
    row = app.state.password_sessions.create_account(value, login='bob', principal_id='bob', role='viewer',
        password=TYPED, grants=[{'resource':'site:test-site','capabilities':['fleet.read']}])
    base = '/api/fleet/auth/accounts/' + row['account_id']
    response = client.post(base + '/reset-password', headers=ORIGIN,
                           json={'revision':row['revision'], 'password':'another password'})
    assert response.status_code == 200
    row = response.json()
    response = client.post(base + '/revoke-sessions', headers=ORIGIN, json={'revision':row['revision']})
    assert response.status_code == 200


def test_peer_request_pending_identity_and_revoke_http_lifecycle(peer_client):
    http, service, _ = peer_client
    base = '/api/fleet/pairing/v2'
    owner = {'Authorization':'Bearer owner-secret'}
    identity = http.get(base + '/identity')
    assert identity.status_code == 200 and identity.json()['tls_ca_sha256']
    key = ec.generate_private_key(ec.SECP256R1())
    fields = dict(service.PROFILE, receiver_id=service.receiver_id, receiver_key_sha256=service.identity.fingerprint,
                  client_id='camera-one', client_public_key=public_key(key.public_key()), label='sample camera', nonce='0' * 64)
    response = http.post(base + '/requests', json={'fields':fields, 'signature':sign(key, 'request', fields)})
    assert response.status_code == 201
    created = response.json()
    pending = http.get(base + '/pending', headers=owner)
    assert pending.status_code == 200 and pending.json()[0]['request_id'] == created['request_id']
    response = http.post(base + '/requests/' + created['request_id'] + '/decision', headers=owner,
                         json={'action':'approve', 'revision':0, 'source_id':'ceiling_north', 'persist_requested':True})
    assert response.status_code == 200
    rows = http.get(base + '/relationships', headers=owner)
    assert rows.status_code == 200 and rows.json()[0]['relationship_id'] == created['request_id']
    response = http.post(base + '/relationships/' + created['request_id'] + '/revoke', headers=owner)
    assert response.status_code == 200 and response.json()['state'] == 'revoked'


def test_named_operator_formation_http_lifecycle_uses_existing_owner(tmp_path):
    from test_server_formation import _console, _fleet
    console = _console(*_fleet(2))
    users = {sha256(b'owner-token').hexdigest(): {'principal_id':'owner', 'role':'operator'}}
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    tasks = FleetTaskService(FleetTaskStore(tmp_path / 'fleet.sqlite3'), robot_ids=console.robot_ids)
    app = create_app(console, site_users=users, task_service=tasks, start_task_dispatcher=False)
    with TestClient(app) as client:
        headers = {'Authorization':'Bearer owner-token'}
        assert client.get('/api/fleet/formation', headers=headers).json()['active'] is False
        response = client.post('/api/fleet/formation/start', headers=headers,
                               json={'leader':'rosy_01', 'formation':'COLUMN', 'spacing':.6})
        assert response.status_code == 200 and response.json()['state'] == 'RUNNING'
        response = client.post('/api/fleet/formation/reform', headers=headers, json={'formation':'COLUMN', 'spacing':.7})
        assert response.status_code == 200
        response = client.post('/api/fleet/formation/resume', headers=headers)
        assert response.status_code == 200 and response.json()['state'] == 'RUNNING'
        assert client.post('/api/fleet/formation/stop', headers=headers).json()['active'] is False
