import base64
from pathlib import Path
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
import pytest

from fleet.server.camera_peer_crypto import public_key, transcript, ProofDenied
from fleet.server.camera_peer_service import CameraPeerService, CameraPeerDenied
from fleet.server.camera_peer_store import CameraPeerStore
from fleet.server.pairing_store import PairingStore
from test_camera_peer_store import ISSUER


def sign(key, context, fields):
    return base64.b64encode(key.sign(transcript(context, fields), ec.ECDSA(hashes.SHA256()))).decode('ascii')


@pytest.fixture
def receiver(tmp_path):
    clock = [1000.]
    store = CameraPeerStore(PairingStore(tmp_path / 'fleet.sqlite3', clock=lambda: clock[0]),
                            current_issuers=lambda: [ISSUER], paired_sources=lambda: {'ceiling_north'},
                            clock=lambda: clock[0])
    service = CameraPeerService(store, identity_path=tmp_path / 'receiver.pem',
                                wall=lambda: clock[0], monotonic=lambda: clock[0])
    return service, clock


def request(service, key, nonce='0'*64):
    fields = dict(service.PROFILE, receiver_id=service.receiver_id,
                  receiver_key_sha256=service.identity.fingerprint, client_id='camera-one',
                  client_public_key=public_key(key.public_key()), label='천장 📷', nonce=nonce)
    return service.request({'fields': fields, 'signature': sign(key, 'request', fields)})


def approved(service, key):
    created = request(service, key)
    service.decide(created['request_id'], {'action': 'approve', 'revision': 0,
                   'source_id': 'ceiling_north', 'persist_requested': True}, issuer=ISSUER)
    return created


def test_real_p256_proof_after_receiver_approval_issues_only_bound_camera_credential(receiver):
    service, _ = receiver
    key = ec.generate_private_key(ec.SECP256R1())
    created = approved(service, key)
    state = service.status(created['request_id'], created['request_secret'])
    assert state['credential_issued'] is False
    assert state['authorization_available'] is True
    challenge = service.challenge(created['request_id'], generation=0)
    fields = challenge['fields']
    result = service.session({'fields': fields, 'signature': sign(key, 'session-request', fields)})
    assert result['role'] == 'overhead-camera'
    assert result['source_id'] == 'ceiling_north'
    assert 'operator' not in result.values()
    assert len(service.sync_rows()) == 1
    with pytest.raises(CameraPeerDenied):
        service.session({'fields': fields, 'signature': sign(key, 'session-request', fields)})


@pytest.mark.parametrize('field,value', [('profile','rosy.peer-proof/1'), ('source_role','operator'),
                                        ('audience','core-login')])
def test_cross_profile_requests_are_rejected_even_with_valid_client_signature(receiver, field, value):
    service, _ = receiver
    key = ec.generate_private_key(ec.SECP256R1())
    fields = dict(service.PROFILE, receiver_id=service.receiver_id,
                  receiver_key_sha256=service.identity.fingerprint, client_id='camera-one',
                  client_public_key=public_key(key.public_key()), label='Cam', nonce='0'*64)
    fields[field] = value
    with pytest.raises((CameraPeerDenied, ValueError)):
        service.request({'fields':fields, 'signature':sign(key,'request',fields)})


def test_invalid_signature_is_rate_admitted_before_crypto(receiver):
    service, _ = receiver
    key = ec.generate_private_key(ec.SECP256R1())
    fields = dict(service.PROFILE, receiver_id=service.receiver_id,
                  receiver_key_sha256=service.identity.fingerprint, client_id='camera-one',
                  client_public_key=public_key(key.public_key()), label='Cam', nonce='0'*64)
    for _ in range(30):
        with pytest.raises(ProofDenied):
            service.request({'fields':fields, 'signature':'AAAA'})
    with pytest.raises(CameraPeerDenied, match='rate'):
        service.request({'fields':fields, 'signature':sign(key,'request',fields)})


def test_missing_receiver_key_with_relationship_does_not_regenerate(receiver):
    service, _ = receiver
    approved(service, ec.generate_private_key(ec.SECP256R1()))
    Path(service.identity_path).unlink()
    with pytest.raises(ProofDenied):
        CameraPeerService(service.store, identity_path=service.identity_path)


def test_changed_challenge_source_and_signature_cannot_retarget_credential(receiver):
    service, _ = receiver
    key = ec.generate_private_key(ec.SECP256R1())
    created = approved(service, key)
    fields = service.challenge(created['request_id'], generation=0)['fields']
    changed = dict(fields, source_id='ceiling_south')
    with pytest.raises(CameraPeerDenied):
        service.session({'fields':changed, 'signature':sign(key,'session-request',changed)})
    assert service.sync_rows() == []


def test_approved_status_recovers_after_restart_without_issuing_a_credential(receiver):
    service, clock = receiver
    created = approved(service,ec.generate_private_key(ec.SECP256R1()))
    restarted = CameraPeerService(service.store, identity_path=service.identity_path,
                                   wall=lambda:clock[0],monotonic=lambda:clock[0])
    state = restarted.status(created['request_id'],created['request_secret'])
    assert state['relationship_id'] == created['request_id']
    assert state['authorization_available'] is True
    assert state['credential_issued'] is False
    assert restarted.sync_rows() == []
    with pytest.raises(CameraPeerDenied):
        restarted.status(created['request_id'],'wrong')


def test_poll_is_bounded_but_cancel_does_not_wait_for_next_poll(receiver):
    service, clock = receiver
    created = request(service,ec.generate_private_key(ec.SECP256R1()))
    assert service.status(created['request_id'],created['request_secret'])['state']=='pending'
    with pytest.raises(CameraPeerDenied,match='rate'):
        service.status(created['request_id'],created['request_secret'])
    assert service.cancel(created['request_id'],created['request_secret'])['state']=='cancelled'


def test_four_character_collision_is_bounded_and_never_lists_ambiguous_request(receiver,monkeypatch):
    service,_=receiver
    key=ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr('fleet.server.camera_peer_service.secrets.choice',lambda _: '2')
    first=request(service,key)
    assert first['display_code']=='2222'
    with pytest.raises(CameraPeerDenied,match='correlation'):
        request(service,key,nonce='1'*64)
    assert len(service.pending())==1
