"""Operator camera evidence storage is authenticated and retrievable."""

import json

from core_api_web.api.v1 import vision_evidence


OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


def packet(metadata, image):
    encoded = json.dumps(metadata).encode()
    return len(encoded).to_bytes(4, "little") + encoded + image


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
