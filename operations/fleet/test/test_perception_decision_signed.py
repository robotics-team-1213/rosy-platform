"""D-898: Fleet signs a decided perception promotion with its own role key; no key, no decision."""

import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from rosy.contracts.learning.promotion_request import encoded, verify

from test_perception_promotion import URL, auth, bundle, code, made, upload  # noqa: F401  made is a fixture

KEY_ID = "perception-decision-v1"


@pytest.fixture
def public_key(tmp_path, monkeypatch):
    """The role key lives in a protected file outside the repo, named by ROSY_PERCEPTION_DECISION_KEY."""
    private = Ed25519PrivateKey.generate()
    pem, config = tmp_path / "decision.pem", tmp_path / "decision-key.json"
    pem.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    config.write_text(json.dumps({"key_id": KEY_ID, "private_key_file": "decision.pem"}), encoding="utf-8")
    for path in (pem, config):
        os.chmod(path, 0o600)
    monkeypatch.setenv("ROSY_PERCEPTION_DECISION_KEY", str(config))
    return private.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo)


def proposed(client):
    return upload(client, encoded(bundle())).json()["bundle_sha256"]


def decide(client, digest, decision="APPROVED"):
    response = client.post(f"{URL}/{digest}/decision", headers=auth("admin-b"),
                           json={"operator_confirmed": True, "decision": decision})
    assert response.status_code == 200, response.text


def test_a_viewer_gets_the_decision_signed_with_the_role_key(made, public_key):
    client, _ = made
    digest = proposed(client)
    decide(client, digest)
    assert client.get(f"{URL}/{digest}/decision.signed").status_code == 401  # viewer at least
    response = client.get(f"{URL}/{digest}/decision.signed", headers=auth("viewer-a"))
    assert response.status_code == 200, response.text
    signed = response.json()
    assert set(signed) == {"key_id", "decision", "signature"} and signed["key_id"] == KEY_ID
    doc = verify(signed["decision"].encode(), signed["signature"], public_key, KEY_ID)
    assert doc == {"schema": "rosy.fleet.perception-decision/1", "bundle_sha256": digest, "model_revision": "seg-r7",
                   "files": [{"name": "model.pt", "sha256": "b" * 64}], "proposed_by": "admin-a",
                   "decided_by": "admin-b", "decided_ns": doc["decided_ns"], "state": "APPROVED"}
    with pytest.raises(ValueError):
        verify(signed["decision"].encode(), signed["signature"], public_key, "other-key")


def test_an_undecided_proposal_has_no_signed_decision(made, public_key):
    client, _ = made
    response = client.get(f"{URL}/{proposed(client)}/decision.signed", headers=auth("viewer-a"))
    assert (response.status_code, code(response)) == (409, "PROPOSAL_NOT_DECIDED")
    missing = client.get(f"{URL}/{'0' * 64}/decision.signed", headers=auth("viewer-a"))
    assert (missing.status_code, code(missing)) == (404, "PROPOSAL_NOT_FOUND")


def test_without_a_configured_key_nothing_unsigned_is_served(made, monkeypatch):
    monkeypatch.delenv("ROSY_PERCEPTION_DECISION_KEY", raising=False)
    client, _ = made
    digest = proposed(client)
    decide(client, digest)
    response = client.get(f"{URL}/{digest}/decision.signed", headers=auth("viewer-a"))
    assert (response.status_code, code(response)) == (503, "DECISION_KEY_NOT_CONFIGURED")
    assert "signature" not in response.text and "decided_by" not in response.text
