"""D-992: Fleet gives CORE public Account settings over TLS; they apply at once and the secret stays here."""

from __future__ import annotations

import json
import os
import stat

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from test_fleet_link import TLS, _token

ROUTE = "/api/v1/account/receiver"
CALLBACK = "https://robot.local:8443/api/account/callback"


def _public_pem() -> str:
    return Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


def _body(**changes) -> dict:
    return {"issuer": "https://account.example.test", "client_id": "robot-x", "callback": CALLBACK,
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


def test_delivery_applies_without_a_restart_and_forces_this_robot(robot):
    https, svc, seats, folder = robot
    assert https.get(ROUTE, headers=seats["site"]).json()["configured"] is False
    assert https.app.state.account_client is None
    answer = https.put(ROUTE, json=_body(), headers=seats["site"])
    assert answer.status_code == 200
    body = answer.json()
    assert body["configured"] is True and body["client_id"] == "robot-x"
    assert body["resource"] == "robot:" + svc.identity.robot_id
    assert https.app.state.account_client.resource == body["resource"]
    assert https.get("/api/account/session").json()["enabled"] is True  # the shared routes read it live


def test_the_secret_is_made_here_private_kept_and_never_returned(robot):
    https, _, seats, folder = robot
    first = https.put(ROUTE, json=_body(), headers=seats["site"]).text
    secret = folder / "account-session.key"
    value = secret.read_bytes()
    assert value.decode("ascii") not in first
    if os.name == "posix":
        assert stat.S_IMODE(secret.stat().st_mode) == 0o600
        assert stat.S_IMODE((folder / "account-receiver.json").stat().st_mode) == 0o600
    https.put(ROUTE, json=_body(client_id="robot-y"), headers=seats["site"])
    assert secret.read_bytes() == value, "replacing the key would sign out everyone on this robot"
    assert json.loads((folder / "account-receiver.json").read_text(encoding="utf-8"))["client_id"] == "robot-y"


def test_the_seat_is_the_hub_links_seat(robot):
    https, _, seats, folder = robot
    plain = TestClient(https.app, base_url="http://robot.local")
    refused = plain.put(ROUTE, json=_body(), headers=seats["site"])
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "TLS_REQUIRED"
    assert https.put(ROUTE, json=_body(), headers=seats["screen"]).status_code == 403
    assert https.put(ROUTE, json=_body()).status_code == 401
    assert not (folder / "account-receiver.json").exists()
    assert https.put(ROUTE, json=_body(), headers=seats["admin"]).status_code == 200


@pytest.mark.parametrize("changes", [
    {"callback": "https://robot.local:8443/elsewhere"}, {"callback": "http://robot.local/api/account/callback"},
    {"issuer": "http://account.example.test"}, {"client_id": "has space"},
    {"public_keys": {}}, {"public_keys": {"key-1": "not a pem"}}, {"resource": "robot:other"},
])
def test_invalid_settings_are_refused_and_keep_the_working_ones(robot, changes):
    https, _, seats, folder = robot
    assert https.put(ROUTE, json=_body(), headers=seats["site"]).status_code == 200
    working = https.app.state.account_client
    before = (folder / "account-receiver.json").read_bytes()
    assert https.put(ROUTE, json=_body(**changes), headers=seats["site"]).status_code == 400
    assert https.app.state.account_client is working
    assert (folder / "account-receiver.json").read_bytes() == before


def test_an_operator_file_wins(robot):
    https, svc, seats, folder = robot
    svc.config["auth"]["account_client_file"] = "/etc/rosy/account/robot.json"
    answer = https.put(ROUTE, json=_body(), headers=seats["site"])
    assert answer.status_code == 409 and answer.json()["error"]["code"] == "ACCOUNT_RECEIVER_MANAGED"
    assert not (folder / "account-receiver.json").exists()


def test_a_damaged_delivery_does_not_stop_core(robot):
    from core_api_web.api.v1.account_receiver import load_provisioned
    https, svc, seats, folder = robot
    assert load_provisioned(svc.identity.robot_id) is None  # nothing delivered yet
    assert https.put(ROUTE, json=_body(), headers=seats["site"]).status_code == 200
    robot_id = svc.identity.robot_id
    assert load_provisioned(robot_id).resource == "robot:" + robot_id
    assert load_provisioned("another-robot") is None, "a file for another identity is not this robot's"
    (folder / "account-receiver.json").write_text("{broken", encoding="utf-8")
    assert load_provisioned(robot_id) is None


def test_capabilities_announce_it(robot):
    https, _, seats, _ = robot
    caps = https.get("/api/v1/system/capabilities", headers=seats["site"]).json()
    assert caps["account_receiver_provisioning"] is True
