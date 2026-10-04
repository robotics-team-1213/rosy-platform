from hashlib import sha256
import os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from core_common.protocol.pairing import der_sha256
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.pairing import PairingService
from fleet.server.pairing_store import PairingStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.camera_peer_routes import BASE
from test_camera_peer_routes import certificates
from test_camera_peer_service import request, sign


def test_actual_app_mount_and_existing_vision_sync_enforce_persistent_binding(tmp_path):
    ca, chain = certificates()
    users = {sha256(b'owner-secret').hexdigest(): {'principal_id':'owner','role':'operator'}}
    pairing = PairingService(PairingStore(tmp_path/'fleet.sqlite3'),
                            leaf_cert_sha256=der_sha256(chain), site_ca_pem=ca,
                            tls_host='site.local', site_name='Site', sources={'ceiling_north':'paired'},
                            served_leaf_pem=chain)
    app = create_app(FleetConsole([],[]),site_users=users,pairing=pairing,
                     pairing_sync_token='vision-sync-secret',start_task_dispatcher=False,
                     task_service=FleetTaskService(FleetTaskStore(tmp_path/'fleet.sqlite3'),robot_ids=[]),
                     web_common=Path(os.environ.get('ROSY_TEST_BASE',Path(__file__).resolve().parents[3]))/'shared/web')
    http = TestClient(app,base_url='https://site.local:8443')
    service = app.state.camera_peer
    key = ec.generate_private_key(ec.SECP256R1())
    created = request(service,key)
    accepted = http.post(BASE+'/requests/'+created['request_id']+'/decision',
                         headers={'Authorization':'Bearer owner-secret'},
                         json={'action':'approve','revision':0,'source_id':'ceiling_north','persist_requested':True})
    assert accepted.status_code == 200
    fields = http.post(BASE+'/challenge',json={'relationship_id':created['request_id'],'generation':0}).json()['fields']
    result = http.post(BASE+'/session',json={'fields':fields,'signature':sign(key,'session-request',fields)})
    assert result.status_code == 200
    path = '/api/fleet/pairing/v1/credentials?role=overhead-camera'
    headers = {'Authorization':'Bearer vision-sync-secret'}
    listed = http.get(path,headers=headers)
    assert listed.status_code == 200
    rows = listed.json()['credentials']
    assert len(rows) == 1
    assert rows[0]['token_sha256'] == sha256(result.json()['token'].encode()).hexdigest()
    assert set(rows[0]) == {'credential_id','source_id','token_sha256','expires_at'}
    assert pairing._source_has_credential('ceiling_north')
    # Current issuer withdrawal: no reapproval/fallback, and next successful sync is empty.
    users.clear()
    assert http.get(path,headers=headers).json()['credentials'] == []
    assert pairing._source_has_credential('ceiling_north')  # Requires explicit source release.


def test_marked_credential_never_syncs_if_v2_adapter_is_unavailable(tmp_path):
    ca, chain = certificates()
    pairing = PairingService(PairingStore(tmp_path/'fleet.sqlite3'),leaf_cert_sha256=der_sha256(chain),
                            site_ca_pem=ca,tls_host='site.local',site_name='Site',sources={'ceiling_north':'paired'})
    pairing.store.insert_pending(credential_id='cam-peer-orphan',source_id='ceiling_north',
                                  token_sha256='b'*64,device_label='Cam',principal_id='owner',expires_at=9999999999.)
    pairing.store.activate('cam-peer-orphan')
    assert pairing.sync_listing() == []
