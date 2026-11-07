"""D-992: Fleet gives CORE public Account settings over TLS; they apply at once and the secret stays here."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from test_fleet_link import TLS, _token

ROUTE = "/api/v1/account/receiver"
CALLBACK = "https://robot.local/api/account/callback"
ISSUER = "https://account.example.test"


def _public_pem() -> str:
    return Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


def _body(**changes) -> dict:
    return {"issuer": ISSUER, "client_id": "robot-x", "callback": CALLBACK,
            "public_keys": {"key-1": _public_pem()}, **changes}


@pytest.fixture
def robot(core_client, tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_FLEET_LINK", str(tmp_path / "link" / "fleet-link.yaml"))
    overlay = tmp_path / "rosy.yaml"
    overlay.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("ROSY_CONFIG", str(overlay))
    tc, svc = core_client(config_overrides=TLS)
    https = TestClient(tc.app, base_url="https://robot.local")
    seats = {"site": _token(svc, "site", "operator", "pair-physical", "site:rosy-site"),
             "screen": _token(svc, "screen", "operator", "pair-physical", "robot screen login"),
             "admin": _token(svc, "admin", "administrator", "manual", "card")}
    return https, svc, seats, tmp_path / "link"


def pin(svc, body):
    svc.config["auth"]["account_trust"] = {"issuer": body["issuer"], "public_key_sha256": [
        hashlib.sha256(pem.encode("ascii")).hexdigest() for pem in body["public_keys"].values()]}
    return body


def test_delivery_applies_without_a_restart_and_forces_this_robot(robot):
    https, svc, seats, folder = robot
    assert https.get(ROUTE, headers=seats["site"]).json()["configured"] is False
    assert https.app.state.account_client is None
    answer = https.put(ROUTE, json=pin(svc, _body()), headers=seats["site"])
    assert answer.status_code == 200
    body = answer.json()
    assert body["configured"] is True and body["client_id"] == "robot-x"
    assert body["resource"] == "robot:" + svc.identity.robot_id
    assert https.app.state.account_client.resource == body["resource"]
    assert https.get("/api/account/session").json()["enabled"] is True  # the shared routes read it live


def test_the_secret_is_made_here_private_kept_and_never_returned(robot):
    https, _, seats, folder = robot
    first = https.put(ROUTE, json=_body(), headers=seats["admin"]).text
    secret = folder / "account-session.key"
    value = secret.read_bytes()
    assert value.decode("ascii") not in first
    if os.name == "posix":
        assert stat.S_IMODE(secret.stat().st_mode) == 0o600
        assert stat.S_IMODE((folder / "account-receiver.json").stat().st_mode) == 0o600
    https.put(ROUTE, json=_body(client_id="robot-y"), headers=seats["admin"])
    assert secret.read_bytes() == value, "replacing the key would sign out everyone on this robot"
    assert json.loads((folder / "account-receiver.json").read_text(encoding="utf-8"))["client_id"] == "robot-y"


def test_a_site_label_alone_cannot_choose_who_signs_admin_here(robot):
    """The label is chosen by whoever pairs, so an issuer it picked would make that caller robot.admin."""
    https, svc, seats, folder = robot
    attacker = _body(issuer="https://attacker.example.test")
    refused = https.put(ROUTE, json=attacker, headers=seats["site"])
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "ACCOUNT_TRUST_UNPINNED"
    assert https.app.state.account_client is None and not (folder / "account-receiver.json").exists()
    real = pin(svc, _body())
    assert https.put(ROUTE, json=attacker, headers=seats["site"]).status_code == 403, "issuer not pinned"
    assert https.put(ROUTE, json=_body(), headers=seats["site"]).status_code == 403, "right issuer, unpinned key"
    two = {**real, "public_keys": {**real["public_keys"], "extra": _public_pem()}}
    assert https.put(ROUTE, json=two, headers=seats["site"]).status_code == 403, "one extra key is enough to sign"
    assert https.put(ROUTE, json=real, headers=seats["site"]).status_code == 200
    moved = https.put(ROUTE, json=attacker, headers=seats["site"])
    assert moved.status_code == 403 and https.app.state.account_client.issuer == ISSUER


def test_changing_issuer_drops_stored_sessions_and_only_then(robot):
    https, _, seats, folder = robot
    assert https.put(ROUTE, json=_body(), headers=seats["admin"]).status_code == 200
    sessions = folder / "account-sessions.sqlite3"
    assert sessions.exists()
    with sqlite3.connect(sessions) as db:
        db.execute("CREATE TABLE marker (x)")
    assert https.put(ROUTE, json=_body(), headers=seats["admin"]).status_code == 200
    with sqlite3.connect(sessions) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='marker'").fetchone()[0] == 1
    assert https.put(ROUTE, json=_body(issuer="https://other.example.test"), headers=seats["admin"]).status_code == 200
    with sqlite3.connect(sessions) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='marker'").fetchone()[0] == 0, \
            "refresh tokens of the old issuer must never reach the new one"


def test_administrator_can_clear_and_a_site_token_cannot(robot):
    https, _, seats, folder = robot
    assert https.put(ROUTE, json=_body(), headers=seats["admin"]).status_code == 200
    assert https.delete(ROUTE, headers=seats["site"]).status_code == 403
    assert https.app.state.account_client is not None
    cleared = https.delete(ROUTE, headers=seats["admin"])
    assert cleared.status_code == 200 and cleared.json()["configured"] is False
    assert https.app.state.account_client is None and not (folder / "account-receiver.json").exists()


def test_the_seat_needs_tls(robot):
    https, svc, seats, folder = robot
    plain = TestClient(https.app, base_url="http://robot.local")
    refused = plain.put(ROUTE, json=pin(svc, _body()), headers=seats["site"])
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "TLS_REQUIRED"
    assert https.put(ROUTE, json=_body(), headers=seats["screen"]).status_code == 403
    assert https.put(ROUTE, json=_body()).status_code == 401
    assert not (folder / "account-receiver.json").exists()
    assert https.put(ROUTE, json=_body(), headers=seats["admin"]).status_code == 200


@pytest.mark.parametrize("changes", [
    {"callback": "https://robot.local/elsewhere"}, {"callback": "http://robot.local/api/account/callback"},
    {"callback": "https://attacker.example.test/api/account/callback"},
    {"issuer": "http://account.example.test"}, {"client_id": "has space"},
    {"public_keys": {}}, {"public_keys": {"key-1": "not a pem"}}, {"resource": "robot:other"},
])
def test_invalid_settings_are_refused_and_keep_the_working_ones(robot, changes):
    https, _, seats, folder = robot
    assert https.put(ROUTE, json=_body(), headers=seats["admin"]).status_code == 200
    working = https.app.state.account_client
    before = (folder / "account-receiver.json").read_bytes()
    assert https.put(ROUTE, json=_body(**changes), headers=seats["admin"]).status_code == 400
    assert https.app.state.account_client is working
    assert (folder / "account-receiver.json").read_bytes() == before


def test_an_operator_file_wins(robot):
    https, svc, seats, folder = robot
    svc.config["auth"]["account_client_file"] = "/etc/rosy/account/robot.json"
    answer = https.put(ROUTE, json=_body(), headers=seats["admin"])
    assert answer.status_code == 409 and answer.json()["error"]["code"] == "ACCOUNT_RECEIVER_MANAGED"
    assert not (folder / "account-receiver.json").exists()


def test_a_damaged_delivery_does_not_stop_core(robot):
    from core_api_web.api.v1.account_receiver import load_provisioned
    https, svc, seats, folder = robot
    assert load_provisioned(svc.identity.robot_id) is None  # nothing delivered yet
    assert https.put(ROUTE, json=_body(), headers=seats["admin"]).status_code == 200
    robot_id = svc.identity.robot_id
    assert load_provisioned(robot_id).resource == "robot:" + robot_id
    assert load_provisioned("another-robot") is None, "a file for another identity is not this robot's"
    (folder / "account-receiver.json").write_text("{broken", encoding="utf-8")
    assert load_provisioned(robot_id) is None


def test_capabilities_announce_it(robot):
    https, _, seats, _ = robot
    caps = https.get("/api/v1/system/capabilities", headers=seats["site"]).json()
    assert caps["account_receiver_provisioning"] is True
