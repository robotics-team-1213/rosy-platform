import hashlib
import json
from pathlib import Path
import pytest
from fleet.server.camera_peer_crypto import transcript, verify, ProofDenied


VECTORS = json.loads((Path(__file__).resolve().parents[3] / 'test/fixtures/protocol/camera-peer.v1.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('vector', VECTORS['vectors'])
def test_camera_transcript_matches_native_golden_ascii_and_hash(vector):
    raw = transcript(vector['context'], vector['fields'])
    assert raw.decode('ascii') == vector['ascii']
    assert hashlib.sha256(raw).hexdigest() == vector['sha256']


def test_public_signature_fixture_verifies_and_profile_context_tampering_rejects():
    row = VECTORS['python_signature']
    verify(row['public_key'],row['signature'],row['context'],row['fields'])
    for changed in [dict(row['fields'],source_id='ceiling_south'),
                    dict(row['fields'],profile='rosy.peer-proof/1'),
                    dict(row['fields'],source_role='operator')]:
        with pytest.raises(ProofDenied):
            verify(row['public_key'],row['signature'],row['context'],changed)
    with pytest.raises(ProofDenied):
        verify(row['public_key'],row['signature'],'receiver-challenge',row['fields'])
