"""D-555: Fleet delivers the hub credential to CORE over TLS; the token never comes back out."""

from __future__ import annotations

import logging
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from fastapi.testclient import TestClient

TOKEN = "hub" + "-credential-" + "x" * 40  # assembled: no literal secret is tracked
SITE_HOST = "rosy-site.local"
TLS = {"network": {"tls": {"cert_file": "/c", "key_file": "/k"}}}


def _ca_pem() -> str:
    pytest.importorskip("cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Site CA")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _token(svc, name: str, role: str, source: str, label: str) -> dict:
    from core_api_web.api.deps import new_token_record, stored_token_entries

    plain = name + "-" + "t" * 24
    svc.config["auth"]["tokens"].extend(stored_token_entries(
        [new_token_record(plain, role, label, source=source)]))
    return {"Authorization": "Bearer " + plain}


@pytest.fixture
def robot(core_client, tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_FLEET_LINK", str(tmp_path / "link" / "fleet-link.yaml"))
    tc, svc = core_client(config_overrides=TLS)
    relinked = []

    def relink(fleet_cfg):  # the real restart is checked in test_relink_restarts_only_the_agent
        relinked.append(fleet_cfg)
        svc.config["fleet"] = fleet_cfg

    monkeypatch.setattr(svc.fleet_agent, "relink", relink)
    https = TestClient(tc.app, base_url="https://robot.local")
    seats = {
        "site": _token(svc, "site", "operator", "pair-physical", "site:rosy-site"),
        "screen": _token(svc, "screen", "operator", "pair-physical", "robot screen login"),
        "admin": _token(svc, "admin", "administrator", "manual", "card"),
        "dev": {"Authorization": "Bearer rosy-dev-admin"},
    }
    return https, svc, seats, relinked, tmp_path / "link"


def _body() -> dict:
    return {"pairing_token": TOKEN, "expected_hostname": SITE_HOST, "ca_pem": _ca_pem()}


def test_plain_http_is_refused_and_writes_nothing(robot):
    https, _, seats, relinked, folder = robot
    plain = TestClient(https.app, base_url="http://robot.local")
    response = plain.put("/api/v1/fleet/link", json=_body(), headers=seats["site"])
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TLS_REQUIRED"
    assert not folder.exists() and relinked == []


@pytest.mark.parametrize("seat,status", [("screen", 403), ("dev", 403), ("site", 200), ("admin", 200)])
def test_only_the_site_enrollment_token_or_an_administrator(robot, seat, status):
    https, _, seats, relinked, _ = robot
    response = https.put("/api/v1/fleet/link", json=_body(), headers=seats[seat])
    assert response.status_code == status, response.text
    assert bool(relinked) is (status == 200)


def test_put_writes_a_private_file_restarts_the_agent_and_hides_the_token(robot, caplog):
    https, svc, seats, relinked, folder = robot
    published = []
    svc.events.subscribe(published.append)
    with caplog.at_level(logging.DEBUG):
        put = https.put("/api/v1/fleet/link", json=_body(), headers=seats["site"])
        got = https.get("/api/v1/fleet/link", headers=seats["screen"])
    assert put.status_code == 200 and got.status_code == 200
    assert got.json()["configured"] is True and got.json()["provisioned"] is True
    assert got.json()["expected_hostname"] == SITE_HOST
    link = folder / "fleet-link.yaml"
    stored = yaml.safe_load(link.read_text(encoding="utf-8"))["fleet"]
    assert stored["pairing_token"] == TOKEN
    assert stored["discovery"]["ca_file"] == str(folder / "fleet-link-ca.pem")
    if os.name == "posix":
        assert stat.S_IMODE(link.stat().st_mode) == 0o600
    # Exactly one agent restart, with the new link in the fleet block.
    assert len(relinked) == 1 and relinked[0]["pairing_token"] == TOKEN
    assert relinked[0]["discovery"]["expected_hostname"] == SITE_HOST
    for text in (put.text, got.text, caplog.text, repr(published)):
        assert TOKEN not in text


def test_a_bad_body_never_echoes_the_token(robot):
    https, _, seats, relinked, folder = robot
    response = https.put("/api/v1/fleet/link", headers=seats["site"],
                         json={**_body(), "expected_hostname": "not-local.example"})
    assert response.status_code == 400 and TOKEN not in response.text
    response = https.put("/api/v1/fleet/link", headers=seats["site"],
                         json={**_body(), "pairing_token": TOKEN + "!"})
    assert response.status_code == 400 and TOKEN not in response.text
    assert relinked == [] and not (folder / "fleet-link.yaml").exists()


def test_delete_removes_the_link_and_restarts_the_agent_without_it(robot):
    https, _, seats, relinked, folder = robot
    assert https.put("/api/v1/fleet/link", json=_body(), headers=seats["site"]).status_code == 200
    response = https.delete("/api/v1/fleet/link", headers=seats["site"])
    assert response.status_code == 200 and response.json()["removed"] is True
    assert response.json()["configured"] is False
    assert not (folder / "fleet-link.yaml").exists() and not (folder / "fleet-link-ca.pem").exists()
    assert "pairing_token" not in relinked[-1] and "discovery" not in relinked[-1]


def test_capability_announces_provisioning(robot):
    https, _, seats, _, _ = robot
    caps = https.get("/api/v1/system/capabilities", headers=seats["screen"]).json()
    assert caps["fleet_link_provisioning"] is True


def test_load_config_merges_the_link_last(tmp_path, monkeypatch):
    from core_common.config import load_config, write_fleet_link

    overlay = tmp_path / "rosy.yaml"
    overlay.write_text(yaml.safe_dump({"fleet": {"hub_url": "ws://old/ws/robots",
                                                 "pairing_token": "old" + "-tok"}}), encoding="utf-8")
    monkeypatch.setenv("ROSY_CONFIG", str(overlay))
    monkeypatch.setenv("ROSY_FLEET_LINK", str(tmp_path / "fleet-link.yaml"))
    write_fleet_link(TOKEN, SITE_HOST, "pem")
    fleet = load_config()["fleet"]
    assert fleet["pairing_token"] == TOKEN and "hub_url" not in fleet
    assert fleet["discovery"]["expected_hostname"] == SITE_HOST
    assert fleet["heartbeat_reply_timeout_s"] == 2.0  # other fleet keys stay


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX")
def test_a_link_file_others_can_read_is_ignored(tmp_path, monkeypatch):
    from core_common.config import fleet_link_layer, fleet_link_path, write_fleet_link

    monkeypatch.setenv("ROSY_FLEET_LINK", str(tmp_path / "fleet-link.yaml"))
    write_fleet_link(TOKEN, SITE_HOST, "pem")
    assert fleet_link_layer() is not None
    fleet_link_path().chmod(0o644)
    assert fleet_link_layer() is None


def test_relink_restarts_only_the_agent_and_saf003_follows(tmp_path):
    from types import SimpleNamespace

    from core_features.fleet_agent.agent import FleetAgent
    from core.fleet_loss_wiring import build_fleet_loss

    config = {"fleet": {}, "safety": {}}
    agent = FleetAgent(SimpleNamespace(), SimpleNamespace(subscribe=lambda _cb: lambda: None),
                       config, SimpleNamespace(robot_id="rosy_09"))
    nav = SimpleNamespace(fleet_goal=lambda: None, cancel=lambda **_: True, home=lambda **_: None)
    monitor = build_fleet_loss(config, events=None, fleet_agent=agent, nav=nav,
                               safety=SimpleNamespace(fleet_loss_policy="STOP"), localization=None)
    assert monitor.status()["configured"] is False
    agent.relink({"pairing_token": TOKEN, "discovery": {"expected_hostname": SITE_HOST,
                                                          "ca_file": str(tmp_path / "ca.pem")}})
    # No running loop: start() defers to the API loop with the new link pending.
    assert agent.enabled is True and agent._pending == ("", TOKEN)
    assert monitor.status()["configured"] is True
    agent.relink({})
    assert agent.enabled is False and monitor.status()["configured"] is False
