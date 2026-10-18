"""D-801: site-issued READ-only robot media grants — role, revocation, logout, audit, no relay."""

from __future__ import annotations

import base64
import json
import re
from hashlib import sha256

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from core_common.protocol.media_tokens import public_media_key, verify_media
from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.robot_media_routes import MediaGrantLedger
from fleet.server.site_auth import SitePrincipal
from fleet.server.site_users import hash_password
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from test_no_video_relay import FORBIDDEN_ROUTE

BASE = "https://rosy-site.local:8443"
ORIGIN = {"Origin": BASE}
TYPED = "correct horse"
VIEWER = "viewer-token-for-bearer"
OBSERVER = "observer-token-for-bearer"
GRANT = "/api/fleet/robots/rosy_01/media-grant"


@pytest.fixture
def site(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    (tmp_path / "media-site.pem").write_bytes(key)
    config = tmp_path / "fleet-media.json"
    config.write_text(json.dumps({"site_url": "https://media.site.example", "audience": "site:lab",
                                  "key_id": "site-1", "signing_key_file": str(tmp_path / "media-site.pem"),
                                  "audit_db": str(tmp_path / "fleet.sqlite3")}))
    monkeypatch.setenv("ROSY_FLEET_MEDIA_CONFIG", str(config))
    logins = {"alice": {"principal_id": "alice", "role": "operator", "password_scrypt": hash_password(TYPED)}}
    users = {sha256(VIEWER.encode()).hexdigest(): {"principal_id": "bob", "role": "viewer"},
             sha256(OBSERVER.encode()).hexdigest(): {"principal_id": "ai", "role": "ai_observer"}}

    def build(**options):
        console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8081", "t")], [FakeRobot("rosy_01")])
        tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)
        app = create_app(console, task_service=tasks, site_users=users, site_logins=logins, **options)
        return app, TestClient(app, base_url=BASE)

    return build, {"site-1": public_media_key(key)}, logins


def _validate(client, token):
    return client.post("/api/fleet/media/validate", headers={"Authorization": f"Bearer {token}"}).json()


def _login(client):
    response = client.post("/api/fleet/auth/login", headers=ORIGIN,
                           json={"login": "alice", "password": TYPED, "remember": False})
    assert response.status_code in (200, 204), response.text


def test_signed_in_viewer_gets_a_read_only_per_robot_grant(site):
    build, public, _ = site
    app, client = build()
    response = client.post(GRANT, headers={"Authorization": f"Bearer {VIEWER}"})
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    grant = response.json()
    claims = verify_media(grant["token"], public, robot_id="rosy_01", audience="site:lab")
    assert (claims.iss, claims.action, claims.sub, claims.path) == ("site:lab", "read", "bob", "robots/rosy_01/front")
    assert 0 < claims.exp - claims.iat <= 60
    assert grant["site_url"] == "https://media.site.example"
    assert _validate(client, grant["token"])["active"] is True
    [row] = app.state.robot_media.rows()
    assert (row["principal_id"], row["role"], row["robot_id"], row["ended_at"]) == ("bob", "viewer", "rosy_01", None)


def test_unauthenticated_machine_and_lan_proxy_principals_are_refused(site):
    build, _, _ = site
    _, client = build(lan_camera_proxy=True)
    assert client.post(GRANT).status_code == 401
    assert client.post(GRANT, headers={"Authorization": f"Bearer {OBSERVER}"}).status_code == 403
    assert client.post(GRANT, headers={"X-Rosy-Lan-Camera": "1"}).status_code == 403
    assert client.post("/api/fleet/robots/rosy_99/media-grant",
                       headers={"Authorization": f"Bearer {VIEWER}"}).status_code == 404


def test_logout_ends_the_grant_at_the_next_recheck_and_is_audited(site):
    build, _, _ = site
    app, client = build()
    _login(client)
    grant = client.post(GRANT, headers=ORIGIN).json()
    authority = TestClient(app, base_url=BASE)          # the media authority holds no cookie
    assert _validate(authority, grant["token"])["active"] is True
    assert client.post("/api/fleet/auth/logout", headers=ORIGIN).status_code in (200, 204)
    assert _validate(authority, grant["token"]) == {"active": False}
    [row] = app.state.robot_media.rows()
    assert row["principal_id"] == "alice" and row["end_reason"] == "credential_revoked" and row["ended_at"]


def test_renewal_keeps_the_grant_owner_and_close_is_audited(site):
    build, public, _ = site
    app, client = build()
    viewer = {"Authorization": f"Bearer {VIEWER}"}
    grant = client.post(GRANT, headers=viewer).json()
    renewed = client.post(f"{GRANT}/{grant['grant_id']}/renew", headers=viewer)
    assert renewed.status_code == 200 and renewed.json()["grant_id"] == grant["grant_id"]
    other = {"Authorization": "Bearer someone-else"}
    assert client.post(f"{GRANT}/{grant['grant_id']}/renew", headers=other).status_code == 401
    assert client.delete(f"{GRANT}/{grant['grant_id']}", headers=viewer).status_code == 204
    assert _validate(client, renewed.json()["token"]) == {"active": False}
    assert client.post(f"{GRANT}/{grant['grant_id']}/renew", headers=viewer).status_code == 403
    assert app.state.robot_media.rows()[0]["end_reason"] == "closed"


def test_forged_or_robot_signed_tokens_never_validate(site):
    build, _, _ = site
    _, client = build()
    grant = client.post(GRANT, headers={"Authorization": f"Bearer {VIEWER}"}).json()
    head, body, signature = grant["token"].split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    claims["robot_id"], claims["path"] = "rosy_02", "robots/rosy_02/front"
    forged = ".".join([head, base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("="), signature])
    assert _validate(client, forged) == {"active": False}
    assert _validate(client, "not-a-token") == {"active": False}


def test_idle_grants_end_as_expired(tmp_path):
    clock = [1000.0]
    ledger = MediaGrantLedger(str(tmp_path / "audit.sqlite3"), clock=lambda: clock[0])
    grant_id = ledger.start(SitePrincipal("bob", "viewer"), "rosy_01", [])
    clock[0] += 71
    ledger.sweep()
    assert ledger.get(grant_id) is None and ledger.rows()[0]["end_reason"] == "expired"


def test_routes_carry_no_video_words_and_console_csp_names_only_the_media_origin(site):
    build, _, _ = site
    app, client = build()
    paths = [route.path for route in app.routes if "media" in getattr(route, "path", "")]
    assert paths and not any(FORBIDDEN_ROUTE.search(path) for path in paths)
    policy = client.get("/console/login").headers.get("content-security-policy", "")
    assert re.search(r"connect-src 'self' https://media\.site\.example;", policy), policy


def test_media_grants_are_off_without_their_config(site, monkeypatch):
    build, _, _ = site
    monkeypatch.delenv("ROSY_FLEET_MEDIA_CONFIG")
    app, client = build()
    assert app.state.robot_media is None
    assert client.post(GRANT, headers={"Authorization": f"Bearer {VIEWER}"}).status_code == 404
