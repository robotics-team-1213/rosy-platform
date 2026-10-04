"""Operator camera evidence storage is authenticated and retrievable."""

import json
import pytest

from core_api_web.api.v1 import vision_evidence


OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


def packet(metadata, image):
    encoded = json.dumps(metadata).encode()
    return len(encoded).to_bytes(4, "little") + encoded + image


def _video(mode, group='a'*32):
    return dict(schema_version=1, kind='video', mime_type='video/webm',
                started_at='2026-10-04T00:00:00Z', stopped_at='2026-10-04T00:00:01Z',
                frame_count=2, operations=[], preview_mode=mode, pair_group_id=group)


def test_paired_annotation_requires_preserved_raw_and_readback_keeps_provenance(core_client, monkeypatch, tmp_path):
    monkeypatch.setattr(vision_evidence, 'evidence_root', lambda: tmp_path)
    client, _ = core_client()
    path = '/api/v1/vision/front/evidence'
    (tmp_path / 'malformed.json').write_text('[]')
    media = b'\x1a\x45\xdf\xa3video'
    assert client.post(path, content=packet(_video('annotated'), media), headers=OPERATOR).status_code == 400
    raw = client.post(path, content=packet(_video('raw'), media), headers=OPERATOR)
    assert raw.status_code == 201 and raw.json()['preview_mode'] == 'raw'
    annotation = client.post(path, content=packet(_video('annotated'), media), headers=OPERATOR)
    assert annotation.status_code == 201
    assert annotation.json()['annotation_origin'] == 'model_unreviewed'
    listed = client.get(path, headers=OPERATOR).json()['records']
    assert len(listed) == 2 and {row['preview_mode'] for row in listed} == {'raw','annotated'}
    assert {row['pair_group_id'] for row in listed} == {'a'*32}


@pytest.mark.parametrize('group', ['../wrong', 'A'*32, 'a'*31])
def test_paired_video_group_is_a_closed_identifier(group):
    with pytest.raises(vision_evidence.EvidenceError):
        vision_evidence._validate(_video('raw', group))


def test_screenshot_storage_requires_operator_and_returns_a_saved_file(core_client, monkeypatch, tmp_path):
    monkeypatch.setattr(vision_evidence, "evidence_root", lambda: tmp_path)
    client, _ = core_client()
    metadata = {"schema_version": 1, "kind": "screenshot", "mime_type": "image/jpeg",
                "saved_at": "2026-09-26T00:00:00Z", "sequence": 1, "source": "PINKY"}
    body = packet(metadata, b"\xff\xd8camera\xff\xd9")
    path = "/api/v1/vision/front/evidence"
    assert client.post(path, content=body).status_code == 401
    assert client.post(path, content=body, headers=VIEWER).status_code == 403
    stored = client.post(path, content=body, headers=OPERATOR)
    assert stored.status_code == 201
    record = stored.json()
    assert record["kind"] == "screenshot"
    assert (tmp_path / record["file_name"]).read_bytes() == b"\xff\xd8camera\xff\xd9"
    listed = client.get(path, headers=OPERATOR)
    assert listed.status_code == 200
    assert listed.json()["records"][0]["id"] == record["id"]
    fetched = client.get(f"{path}/{record['id']}", headers=OPERATOR)
    assert fetched.status_code == 200
    assert fetched.content == b"\xff\xd8camera\xff\xd9"
