"""v2 credentials have an intrinsic camera marker; legacy v1 IDs are unchanged."""
import re
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import ValidationError
import pytest
from core_common.protocol.camera_peer import SessionSnapshot
from test_camera_peer_service import receiver, approved, sign


def issued(service):
    key = ec.generate_private_key(ec.SECP256R1())
    created = approved(service, key)
    fields = service.challenge(created['request_id'], generation=0)['fields']
    return service.session({'fields':fields,'signature':sign(key,'session-request',fields)})


def test_actual_crypto_issue_has_intrinsic_camera_namespace(receiver):
    service, _ = receiver
    result = issued(service)
    assert re.fullmatch(r'cam-peer-[A-Za-z0-9_-]{24}',result['credential_id'])
    assert SessionSnapshot.model_validate(result).role == 'overhead-camera'


@pytest.mark.parametrize('bad_id', ['legacy-camera-id','cam-peer-short','cam-peer-'+'A'*25,'cam-peer-'+'!'*24])
def test_v2_session_rejects_legacy_or_malformed_credential_namespace(receiver,bad_id):
    service, _ = receiver
    result = issued(service)
    with pytest.raises(ValidationError):
        SessionSnapshot.model_validate(dict(result,credential_id=bad_id))
