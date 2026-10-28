"""D-898: the decision encoder is canonical, and sign/verify bind the bytes, the key and the key id."""
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from rosy.contracts.learning.promotion_request import decision_encoded, encoded, sign, verify

RECORD = {'bundle_sha256': 'a' * 64, 'model_revision': 'seg-r7', 'files': [{'name': 'model.pt', 'sha256': 'b' * 64}],
          'proposed_by': '제안자', 'decided_by': 'admin-b', 'decided_ns': 7, 'state': 'APPROVED'}
KEY = Ed25519PrivateKey.generate()
PRIVATE = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
PUBLIC = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def test_the_encoding_is_canonical_whatever_the_key_order():
    raw = decision_encoded(RECORD)
    assert raw == decision_encoded(dict(reversed(RECORD.items())))
    assert raw == encoded(json.loads(raw)) and raw.endswith(b'\n') and '제안자'.encode() in raw
    assert json.loads(raw)['schema'] == 'rosy.fleet.perception-decision/1'


@pytest.mark.parametrize('change', [{'state': 'PENDING'}, {'extra': 1}, {'bundle_sha256': 'x'}, {'files': []}, {'decided_ns': -1}])
def test_a_malformed_record_cannot_be_encoded(change):
    with pytest.raises(ValueError):
        decision_encoded(dict(RECORD, **change))


def test_verify_returns_the_decision_and_refuses_everything_else():
    raw = decision_encoded(RECORD)
    signature = sign(raw, PRIVATE, 'k1')
    assert verify(raw, signature, PUBLIC, 'k1')['decided_by'] == 'admin-b'
    other = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    for args in ((raw + b' ', signature, PUBLIC, 'k1'), (raw, signature, PUBLIC, 'k2'), (raw, signature, other, 'k1'),
                 (raw, signature[:-4] + 'AAAA', PUBLIC, 'k1'), (raw, 'not base64!', PUBLIC, 'k1')):
        with pytest.raises(ValueError):
            verify(*args)


def test_a_validly_signed_non_canonical_encoding_is_refused():
    loose = json.dumps(json.loads(decision_encoded(RECORD)), indent=1).encode()
    with pytest.raises(ValueError, match='정본'):
        verify(loose, sign(loose, PRIVATE, 'k1'), PUBLIC, 'k1')
