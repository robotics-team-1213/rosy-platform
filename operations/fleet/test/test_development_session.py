"""D-473 관제 콘솔 개발 연결 모드 — 세션 저장소, LAN 주소, Host/Origin, 상한, 만료."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.development_session import DevelopmentSessions, console_authority, lan_address
from fleet.server.site_auth import SitePrincipal, build_authorize, build_role_guards
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize("host", [
    "127.0.0.1", "10.1.2.3", "172.31.255.1", "192.168.0.9", "169.254.10.1",
    "::1", "fe80::1", "::ffff:192.168.1.5", "100.82.51.8", "100.64.0.1", "100.127.255.254",
])
def test_lan_address_accepts_loopback_rfc1918_and_link_local(host):
    assert lan_address(host)


@pytest.mark.parametrize("host", [
    "100.128.0.1", "172.32.0.1", "8.8.8.8", "2001:db8::1", "testclient", "", None,
])
def test_lan_address_refuses_everything_else(host):
    assert not lan_address(host)


@pytest.mark.parametrize(("host", "origin", "ok"), [
    ("192.168.1.10:8090", None, True),
    ("192.168.1.10:8090", "http://192.168.1.10:8090", True),
    ("rosy-site.local:8443", "https://rosy-site.local:8443", True),
    ("localhost:8090", "http://localhost:8090", True),
    ("[::1]:8090", "http://[::1]:8090", True),
    ("evil.example:8090", "http://evil.example:8090", False),  # DNS rebinding
    ("192.168.1.10:8090", "http://evil.example", False),
    ("192.168.1.10:8090", "http://192.168.1.10:9999", False),
    ("192.168.1.10:8090", "null", False),
    ("8.8.8.8", None, False),
    ("user@192.168.1.10:8090", None, False),
    (None, None, False),
])
def test_console_authority_requires_a_local_host_and_a_matching_origin(host, origin, ok):
    assert console_authority(host, origin) is ok


def test_session_is_a_named_operator_that_expires_after_one_hour():
    clock = Clock()
    sessions = DevelopmentSessions(clock=clock)
    token, principal, expires_at = sessions.issue()

    assert re.fullmatch(r"development-[0-9a-f]{8}", principal.principal_id)
    assert principal.role == "operator"
    assert expires_at == datetime.fromtimestamp(clock.now + 3600, timezone.utc).isoformat(timespec="seconds")
    assert sessions.principal(token) == principal
    clock.now += 3599
    assert sessions.principal(token) == principal
    clock.now += 1
    assert sessions.principal(token) is None
    assert sessions.principal("not-a-session") is None


def test_ninth_session_evicts_the_oldest():
    sessions = DevelopmentSessions(clock=Clock())
    tokens = [sessions.issue()[0] for _ in range(9)]

    assert sessions.principal(tokens[0]) is None
    assert all(sessions.principal(token) is not None for token in tokens[1:])


def test_a_session_in_use_outlives_newer_idle_ones():
    # Field check 2026-10-10: a console polling every second lost its token to eight newer
    # page loads; eviction follows last use, not issue time.
    sessions = DevelopmentSessions(clock=Clock())
    tokens = [sessions.issue()[0] for _ in range(8)]
    assert sessions.principal(tokens[0]) is not None
    newer = sessions.issue()[0]

    assert sessions.principal(tokens[0]) is not None
    assert sessions.principal(tokens[1]) is None
    assert sessions.principal(newer) is not None


def test_six_requests_per_address_per_minute():
    clock = Clock()
    sessions = DevelopmentSessions(clock=clock)

    assert all(sessions.admit("192.168.1.50") for _ in range(6))
    assert not sessions.admit("192.168.1.50")
    assert sessions.admit("192.168.1.51")
    clock.now += 60
    assert sessions.admit("192.168.1.50")


def test_revoked_session_no_longer_authenticates():
    sessions = DevelopmentSessions()
    token, _, _ = sessions.issue()
    sessions.revoke(token)

    assert sessions.principal(token) is None


def test_development_session_passes_the_named_operator_gate_without_site_users():
    sessions = DevelopmentSessions()
    token, principal, _ = sessions.issue()
    authorize = build_authorize("registry-secret", {}, None, development=sessions)
    _, _, named_operator, _ = build_role_guards(authorize, {})
    app = FastAPI()

    @app.post("/api/fleet/named")
    def named(caller: SitePrincipal = Depends(named_operator)) -> dict:
        return {"principal_id": caller.principal_id}

    client = TestClient(app)
    accepted = client.post("/api/fleet/named", headers={"Authorization": f"Bearer {token}"})
    assert accepted.json() == {"principal_id": principal.principal_id}
    shared = client.post("/api/fleet/named", headers={"Authorization": "Bearer registry-secret"})
    assert shared.status_code == 403
    assert shared.json()["detail"]["code"] == "OPERATOR_IDENTITY_REQUIRED"
    assert client.post("/api/fleet/named", headers={"Authorization": "Bearer wrong"}).status_code == 401


ROOT = Path(__file__).resolve().parents[3]
LAN = ("192.168.1.50", 50000)
BASE = "http://192.168.1.10:8090"
ORIGIN = {"Origin": BASE}
SESSION = "/api/fleet/auth/development-session"


def _app(tmp_path, *, sessions=None, lan_camera_proxy=False):
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8081", "t")], [FakeRobot("rosy_01")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)
    app = create_app(console, console_token="registry-secret", task_service=tasks,
                     development_sessions=sessions, lan_camera_proxy=lan_camera_proxy)
    return app, tasks


def _client(app, client=LAN, base_url=BASE):
    return TestClient(app, client=client, base_url=base_url)


def test_paired_console_reports_paired_and_refuses_sessions(tmp_path):
    app, _ = _app(tmp_path)
    client = _client(app)

    response = client.get("/api/fleet/auth/connection")
    assert response.status_code == 200
    assert response.json() == {"mode": "paired", "password_login": False}
    assert response.headers["cache-control"] == "no-store"
    refused = client.post(SESSION, headers=ORIGIN)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "FORBIDDEN"


def test_development_session_is_a_named_operator_and_is_audited(tmp_path):
    app, tasks = _app(tmp_path, sessions=DevelopmentSessions())
    client = _client(app)

    assert client.get("/api/fleet/auth/connection").json() == {"mode": "development", "password_login": False}
    issued = client.post(SESSION, headers=ORIGIN)
    assert issued.status_code == 201
    assert issued.headers["cache-control"] == "no-store"
    body = issued.json()
    assert set(body) == {"token", "principal_id", "role", "expires_at"}
    assert body["role"] == "operator"
    assert re.fullmatch(r"development-[0-9a-f]{8}", body["principal_id"])
    headers = {"Authorization": f"Bearer {body['token']}"}
    assert client.get("/api/fleet/session", headers=headers).json() == {
        "principal_id": body["principal_id"], "role": "operator"}
    assert client.get("/api/fleet/session").status_code == 401
    assert client.get("/api/fleet/session", headers={"Authorization": "Bearer registry-secret"}).json() == {
        "principal_id": "site-console", "role": "operator"}
    client.post("/api/fleet/estop", headers=headers)
    rows = tasks.store.api_audit(limit=20)
    intents = {(row["principal_id"], row["path"]) for row in rows if row["event_type"] == "INTENT"}
    assert {(body["principal_id"], SESSION), (body["principal_id"], "/api/fleet/estop")} <= intents
    assert any(row["event_type"] == "RESULT" and row["path"] == SESSION and row["status_code"] == 201
               for row in rows)


@pytest.mark.parametrize("peer", ["100.128.0.1", "8.8.8.8", "testclient"])
def test_session_is_refused_off_the_lan(tmp_path, peer):
    app, _ = _app(tmp_path, sessions=DevelopmentSessions())

    assert _client(app, client=(peer, 50000)).post(SESSION, headers=ORIGIN).status_code == 403


@pytest.mark.parametrize(("base_url", "origin", "status"), [
    ("http://evil.example:8090", "http://evil.example:8090", 403),
    (BASE, "http://evil.example", 403),
    (BASE, "http://192.168.1.10:9999", 403),
    ("https://rosy-site.local:8443", "https://rosy-site.local:8443", 201),
    (BASE, None, 201),
])
def test_session_requires_the_console_authority(tmp_path, base_url, origin, status):
    app, _ = _app(tmp_path, sessions=DevelopmentSessions())
    headers = {"Origin": origin} if origin is not None else {}

    assert _client(app, base_url=base_url).post(SESSION, headers=headers).status_code == status


@pytest.mark.parametrize(("trusted", "peer", "forwarded", "status"), [
    (True, "172.18.0.4", "8.8.8.8", 403),
    (True, "172.18.0.4", "192.168.1.50", 201),
    (False, "8.8.8.8", "192.168.1.50", 403),
])
def test_forwarded_address_counts_only_behind_the_site_proxy(tmp_path, trusted, peer, forwarded, status):
    app, _ = _app(tmp_path, sessions=DevelopmentSessions(), lan_camera_proxy=trusted)
    headers = {**ORIGIN, "X-Forwarded-For": forwarded}

    assert _client(app, client=(peer, 50000)).post(SESSION, headers=headers).status_code == status


def test_route_rate_limits_per_address(tmp_path):
    app, _ = _app(tmp_path, sessions=DevelopmentSessions())
    client = _client(app)

    for _ in range(6):
        assert client.post(SESSION, headers=ORIGIN).status_code == 201
    limited = client.post(SESSION, headers=ORIGIN)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.json()["detail"]["code"] == "RATE_LIMITED"
    assert _client(app, client=("192.168.1.51", 50000)).post(SESSION, headers=ORIGIN).status_code == 201


def test_expired_session_is_401(tmp_path):
    clock = Clock()
    app, _ = _app(tmp_path, sessions=DevelopmentSessions(clock=clock))
    client = _client(app)
    token = client.post(SESSION, headers=ORIGIN).json()["token"]

    clock.now += 3600
    assert client.get("/api/fleet/session", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_issue_fails_closed_when_the_audit_is_unavailable(tmp_path, monkeypatch):
    sessions = DevelopmentSessions()
    app, tasks = _app(tmp_path, sessions=sessions)

    def broken(**_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(tasks.store, "begin_api_audit", broken)
    response = _client(app).post(SESSION, headers=ORIGIN)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AUDIT_STORAGE_UNAVAILABLE"
    assert "token" not in response.json()
    assert sessions._sessions == {}


def test_development_mode_requires_the_durable_api_audit():
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8081", "t")], [FakeRobot("rosy_01")])

    with pytest.raises(ValueError, match="audit"):
        create_app(console, development_sessions=DevelopmentSessions())


def test_api_reference_documents_the_development_session_routes():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(encoding="utf-8")

    assert "**Version:** v1.195" in reference
    assert "| GET | `/api/fleet/auth/connection` |" in reference
    assert "| POST | `/api/fleet/auth/development-session` |" in reference
    assert "| v1.108 | 2026-10-06 | Additive (D-473)" in reference
