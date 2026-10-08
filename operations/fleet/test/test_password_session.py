"""D-519 관제 콘솔 아이디·비밀번호 로그인 — 해시 형식, 계정 파일, 쿠키, 만료, 무효화, CSRF, 속도 제한."""

from __future__ import annotations

import io
import sqlite3
import sys
import threading
import time
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server import site_users as site_users_module
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server import password_session as password_session_module
from fleet.server.password_session import COOKIE, LoginRateLimited, PasswordSessions
from fleet.server.site_auth import SitePrincipal, build_authorize, build_role_guards
from fleet.server.site_users import hash_password, load_site_accounts, load_site_users, verify_password
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

BASE = "https://rosy-site.local:8443"
ORIGIN = {"Origin": BASE}
LOGIN = "/api/fleet/auth/login"
PASSWORD = "correct horse"
HASH = hash_password(PASSWORD)
TOKEN = "viewer-token-for-bearer"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def _accounts(**overrides):
    account = {"principal_id": "alice", "role": "operator", "password_scrypt": HASH}
    account.update(overrides)
    return {"alice": account}


def _write(tmp_path, body: str):
    path = tmp_path / "site-users.yaml"
    path.write_text("users:\n" + body, encoding="utf-8")
    return path


def _app(tmp_path, logins=None, users=None):
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8081", "t")], [FakeRobot("rosy_01")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)
    users = {sha256(TOKEN.encode()).hexdigest(): {"principal_id": "bob", "role": "viewer"}} if users is None else users
    app = create_app(console, task_service=tasks, site_users=users,
                     site_logins=_accounts() if logins is None else logins)
    return app, tasks


def _client(app):
    return TestClient(app, base_url=BASE)


def _login(client, password=PASSWORD, login="alice", remember=False):
    return client.post(LOGIN, headers=ORIGIN, json={"login": login, "password": password, "remember": remember})


# --- hash and site-users file ------------------------------------------------

def test_hash_format_round_trips_with_the_adr_parameters():
    parts = HASH.split("$")

    assert parts[:4] == ["scrypt", str(2 ** 15), "8", "1"]
    assert verify_password(PASSWORD, HASH)
    assert not verify_password("wrong", HASH)
    assert hash_password(PASSWORD) != HASH  # fresh salt


def test_hash_password_cli_reads_stdin(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("s3cret\n"))

    assert site_users_module.main(["hash-password"]) == 0
    assert verify_password("s3cret", capsys.readouterr().out.strip())


def test_loader_accepts_token_only_login_only_and_both(tmp_path):
    digest = sha256(b"t").hexdigest()
    path = _write(tmp_path,
                  f"  - {{principal_id: svc, role: service, token_sha256: {digest}}}\n"
                  f"  - {{principal_id: alice, role: operator, login: alice, password_scrypt: '{HASH}'}}\n"
                  f"  - {{principal_id: carol, role: viewer, login: carol.k, password_scrypt: '{HASH}',"
                  f" token_sha256: {sha256(b'c').hexdigest()}}}\n")

    users, logins = load_site_accounts(path)

    assert users == {digest: {"principal_id": "svc", "role": "service"},
                     sha256(b"c").hexdigest(): {"principal_id": "carol", "role": "viewer"}}
    assert logins == {"alice": {"principal_id": "alice", "role": "operator", "password_scrypt": HASH},
                      "carol.k": {"principal_id": "carol", "role": "viewer", "password_scrypt": HASH}}
    assert load_site_users(path) == users


@pytest.mark.parametrize("body", [
    "  - {principal_id: svc, role: service, login: svc, password_scrypt: '%s'}\n" % HASH,
    "  - {principal_id: a, role: viewer, login: x, password_scrypt: '%s'}\n"
    "  - {principal_id: b, role: viewer, login: x, password_scrypt: '%s'}\n" % (HASH, HASH),
    "  - {principal_id: a, role: viewer, login: x, password_scrypt: 'scrypt$1$8$1$AAAA$AAAA'}\n",
    "  - {principal_id: a, role: viewer, login: x, password_scrypt: 'plaintext'}\n",
    "  - {principal_id: a, role: viewer, login: Alice, password_scrypt: '%s'}\n" % HASH,
    "  - {principal_id: a, role: viewer, login: x}\n",
    "  - {principal_id: a, role: viewer}\n",
])
def test_loader_rejects_service_login_duplicate_login_bad_hash_and_missing_credential(tmp_path, body):
    with pytest.raises(ValueError):
        load_site_accounts(_write(tmp_path, body))


# --- login route -------------------------------------------------------------

def test_login_sets_a_strict_http_only_cookie_and_session_reports_it(tmp_path):
    app, tasks = _app(tmp_path)
    client = _client(app)

    response = _login(client)
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert flag.lower() in cookie.lower()
    assert "max-age" not in cookie.lower()
    session = client.get("/api/fleet/auth/session").json()
    assert session["principal_id"] == "alice" and session["role"] == "operator"
    assert client.get("/api/fleet/auth/connection").json() == {"mode": "paired", "password_login": True}
    assert session["via"] == "cookie" and session["expires_at"]
    rows = tasks.store.api_audit(limit=10)
    assert any(r["principal_id"] == "alice" and r["path"] == LOGIN and r["event_type"] == "INTENT" for r in rows)


def test_remember_sets_thirty_day_max_age(tmp_path):
    response = _login(_client(_app(tmp_path)[0]), remember=True)

    assert f"max-age={30 * 86400}" in response.headers["set-cookie"].lower()


def test_wrong_password_and_unknown_login_give_the_same_401(tmp_path):
    app, tasks = _app(tmp_path)
    client = _client(app)

    wrong = _login(client, password="nope")
    unknown = _login(client, login="mallory")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": {"code": "LOGIN_FAILED",
                                                         "message": "login or password is incorrect"}}
    assert COOKIE not in client.cookies
    intents = {r["principal_id"] for r in tasks.store.api_audit(limit=10) if r["event_type"] == "INTENT"}
    assert {"login:alice", "login:mallory"} <= intents


def test_five_failures_per_address_rate_limit(tmp_path):
    client = _client(_app(tmp_path)[0])

    for _ in range(5):
        assert _login(client, password="nope").status_code == 401
    limited = _login(client)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.json()["detail"]["code"] == "RATE_LIMITED"


def test_ten_failures_per_login_rate_limit_and_window_expiry():
    clock = Clock()
    sessions = PasswordSessions(":memory:", _accounts(), clock=clock)

    for index in range(10):
        assert sessions.check(f"10.0.0.{index}", "alice", "nope") is None
    with pytest.raises(LoginRateLimited):
        sessions.check("10.0.0.99", "alice", PASSWORD)
    assert sessions.check("10.0.0.99", "bob", "nope") is None
    clock.now += 60
    assert sessions.check("10.0.0.99", "alice", PASSWORD) == SitePrincipal("alice", "operator")


def test_concurrent_failures_from_one_address_run_at_most_five_password_checks(monkeypatch):
    sessions = PasswordSessions(":memory:", _accounts())
    calls = []

    def slow_verify(password, encoded):
        calls.append(password)
        time.sleep(0.05)
        return False

    monkeypatch.setattr(password_session_module, "verify_password", slow_verify)
    start = threading.Barrier(12)
    outcomes = []

    def attempt():
        start.wait()
        try:
            outcomes.append(sessions.check("10.0.0.7", "alice", "nope"))
        except LoginRateLimited:
            outcomes.append("limited")

    workers = [threading.Thread(target=attempt) for _ in range(12)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert len(calls) <= 5
    assert outcomes.count("limited") >= 7


def test_success_refunds_its_reserved_slot():
    sessions = PasswordSessions(":memory:", _accounts())

    for _ in range(10):
        assert sessions.check("10.0.0.8", "alice", PASSWORD) is not None
    for _ in range(5):
        assert sessions.check("10.0.0.8", "alice", "nope") is None
    with pytest.raises(LoginRateLimited):
        sessions.check("10.0.0.8", "alice", PASSWORD)


@pytest.mark.parametrize("login", ["a" * 33, "Alice", "bad login", ""])
def test_malformed_login_gets_the_same_401_and_is_no_rate_key(tmp_path, login):
    app, tasks = _app(tmp_path)
    client = _client(app)

    response = _login(client, login=login)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "LOGIN_FAILED"
    sessions_failures = [key for key in app.state.password_sessions._failures if key[0] == "login"]
    assert sessions_failures == []
    assert any(r["principal_id"] == "login:?" for r in tasks.store.api_audit(limit=10))


def test_rate_limited_logins_are_audited_once_per_address_window(tmp_path):
    app, tasks = _app(tmp_path)
    client = _client(app)

    for _ in range(5):
        _login(client, password="nope")
    for _ in range(4):
        assert _login(client).status_code == 429
    rows = [r for r in tasks.store.api_audit(limit=50) if r["event_type"] == "RESULT" and r["status_code"] == 429]
    assert len(rows) == 1


def test_login_routes_are_absent_without_login_accounts(tmp_path):
    client = _client(_app(tmp_path, logins={})[0])

    assert _login(client).status_code == 404
    assert client.get("/api/fleet/auth/connection").json()["password_login"] is False
    assert client.post("/api/fleet/auth/logout", headers=ORIGIN).status_code == 404
    assert client.get("/api/fleet/auth/session").status_code == 401
    bearer = client.get("/api/fleet/auth/session", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert bearer == {"principal_id": "bob", "role": "viewer", "via": "bearer", "expires_at": None}


# --- expiry and invalidation ---------------------------------------------------

def test_idle_window_slides_and_ends_after_twelve_hours(tmp_path):
    clock = Clock()
    sessions = PasswordSessions(tmp_path / "s.sqlite3", _accounts(), clock=clock)
    value = sessions.issue("alice", remember=False)

    clock.now += 11 * 3600
    assert sessions.principal(value)[0] == SitePrincipal("alice", "operator")
    clock.now += 11 * 3600  # 22 h after login, 11 h after the last use
    assert sessions.principal(value) is not None
    clock.now += 12 * 3600
    assert sessions.principal(value) is None


def test_remember_lasts_thirty_days_and_absolute_cap_ends_any_session(tmp_path):
    clock = Clock()
    sessions = PasswordSessions(tmp_path / "s.sqlite3", _accounts(), clock=clock)
    remembered = sessions.issue("alice", remember=True)
    busy = sessions.issue("alice", remember=False)

    for _ in range(59):  # touched every 12 h minus a bit, so the idle window never lapses
        clock.now += 12 * 3600 - 1
        assert sessions.principal(busy) is not None
    clock.now = 1_000_000.0 + 30 * 86400
    assert sessions.principal(busy) is None
    assert sessions.principal(remembered) is None


def test_remember_survives_a_long_idle_gap(tmp_path):
    clock = Clock()
    sessions = PasswordSessions(tmp_path / "s.sqlite3", _accounts(), clock=clock)
    value = sessions.issue("alice", remember=True)

    clock.now += 20 * 86400
    assert sessions.principal(value) is not None


@pytest.mark.parametrize("changed", [
    {"password_scrypt": hash_password("new password")},
    {"role": "viewer"},
    {"principal_id": "alice-2"},
    None,
])
def test_password_role_principal_change_or_removed_account_voids_the_session(tmp_path, changed):
    path = tmp_path / "s.sqlite3"
    value = PasswordSessions(path, _accounts()).issue("alice", remember=True)

    reloaded = PasswordSessions(path, {} if changed is None else _accounts(**changed))
    assert reloaded.principal(value) is None
    assert PasswordSessions(path, _accounts()).principal(value) is None  # deleted, not just hidden


def test_session_survives_a_new_app_on_the_same_database(tmp_path):
    first = _client(_app(tmp_path)[0])
    _login(first)
    cookie = first.cookies[COOKIE]

    second = _client(_app(tmp_path)[0])
    second.cookies.set(COOKIE, cookie)
    assert second.get("/api/fleet/auth/session").json()["principal_id"] == "alice"


# --- authorization order and CSRF ---------------------------------------------

@pytest.mark.parametrize(("origin", "status"), [(None, 403), ("https://evil.example", 403), (BASE, 202)])
def test_cookie_post_requires_this_console_origin(tmp_path, origin, status):
    client = _client(_app(tmp_path)[0])
    _login(client)

    response = client.post("/api/fleet/estop", headers={"Origin": origin} if origin else {})
    if status == 403:
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "CSRF_REJECTED"
    else:
        assert response.status_code not in {401, 403}


def test_bearer_wins_over_the_cookie(tmp_path):
    client = _client(_app(tmp_path)[0])
    _login(client)

    session = client.get("/api/fleet/auth/session", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert (session["principal_id"], session["via"]) == ("bob", "bearer")
    assert client.get("/api/fleet/auth/session", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_logout_ends_the_session(tmp_path):
    client = _client(_app(tmp_path)[0])
    _login(client)
    cookie = client.cookies[COOKIE]

    response = client.post("/api/fleet/auth/logout", headers=ORIGIN)
    assert response.status_code == 204
    assert f"{COOKIE}=" in response.headers["set-cookie"]
    client.cookies.set(COOKIE, cookie)
    assert client.get("/api/fleet/auth/session").status_code == 401


def test_login_only_site_users_still_need_a_credential_and_cookie_is_a_named_operator(tmp_path):
    client = _client(_app(tmp_path, users={})[0])

    assert client.get("/api/fleet/auth/session").status_code == 401
    _login(client)
    assert client.get("/api/fleet/auth/session").json()["principal_id"] == "alice"


def test_cookie_principal_passes_the_named_operator_gate(tmp_path):
    sessions = PasswordSessions(tmp_path / "s.sqlite3", _accounts())
    value = sessions.issue("alice", remember=False)
    authorize = build_authorize(None, {}, None, password_sessions=sessions)
    _, _, named_operator, _ = build_role_guards(authorize, {}, named_logins=True)
    app = FastAPI()

    @app.post("/api/fleet/named")
    def named(caller: SitePrincipal = Depends(named_operator)) -> dict:
        return {"principal_id": caller.principal_id}

    client = TestClient(app, base_url=BASE)
    client.cookies.set(COOKIE, value)
    assert client.post("/api/fleet/named", headers=ORIGIN).json() == {"principal_id": "alice"}
    client.cookies.clear()
    assert client.post("/api/fleet/named", headers=ORIGIN).status_code == 401


def test_logout_during_an_in_flight_lookup_is_not_undone(tmp_path):
    clock = Clock()
    sessions = PasswordSessions(tmp_path / "s.sqlite3", _accounts(), clock=clock)
    value = sessions.issue("alice", remember=False)
    clock.now += 61  # stale cache -> DB path, like the review probe
    original, fired = sessions._expiry, []

    def racing(row, now):
        if not fired:
            fired.append(True)
            sessions.revoke(value)  # logout lands between the snapshot and _remember
        return original(row, now)

    sessions._expiry = racing
    assert sessions.principal(value) is None
    sessions._expiry = original
    assert fired
    assert sessions.principal(value) is None
    clock.now += 30
    assert sessions.principal(value) is None
    assert sessions.principal(value, allow_stale=True) is None


def _locked_writer(path):
    """Hold a write transaction on the tasks DB from another connection (WAL: reads still work)."""
    holder = sqlite3.connect(path, timeout=0)
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("UPDATE fleet_console_sessions SET last_used_at = last_used_at")
    return holder


def test_cookie_estop_succeeds_while_the_sessions_table_is_locked(tmp_path):
    app, _ = _app(tmp_path)
    client = _client(app)
    _login(client)
    assert client.get("/api/fleet/auth/session").status_code == 200  # one prior successful use

    holder = _locked_writer(tmp_path / "fleet.sqlite3")
    try:
        stop = client.post("/api/fleet/estop", headers=ORIGIN)
    finally:
        holder.rollback()
        holder.close()
    assert stop.status_code not in {401, 403, 500, 503}


def test_unreadable_session_storage_is_503_except_a_cached_estop(tmp_path, monkeypatch):
    clock = Clock()
    sessions = PasswordSessions(tmp_path / "s.sqlite3", _accounts(), clock=clock)
    known = sessions.issue("alice", remember=False)
    unknown = sessions.issue("alice", remember=False)
    sessions._forget(password_session_module._digest(unknown))

    def broken(**_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(sessions, "_connect", broken)
    assert sessions.principal(known)[0] == SitePrincipal("alice", "operator")  # cache, no DB
    clock.now += 61 * 60  # past the cache window and the touch interval
    with pytest.raises(password_session_module.SessionStorageUnavailable):
        sessions.principal(known)
    assert sessions.principal(known, allow_stale=True)[0] == SitePrincipal("alice", "operator")
    with pytest.raises(password_session_module.SessionStorageUnavailable):
        sessions.principal(unknown, allow_stale=True)

    authorize = build_authorize(None, {}, None, password_sessions=sessions)
    probe = FastAPI()

    @probe.get("/api/fleet/probe")
    def probe_route(caller: SitePrincipal = Depends(authorize)) -> dict:
        return {"principal_id": caller.principal_id}

    probe_client = TestClient(probe, base_url=BASE)
    probe_client.cookies.set(COOKIE, known)
    unavailable = probe_client.get("/api/fleet/probe")
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "SESSION_STORAGE_UNAVAILABLE"


def test_cookie_operator_presence_names_the_actor(tmp_path):
    from fake_signals import FakeSignal
    from fleet.server.signals import SignalConsole, SignalEndpoint

    signals = SignalConsole([SignalEndpoint("signal_1", "http://127.0.0.1:9081", "t1")],
                            [FakeSignal("signal_1")])
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8081", "t")], [FakeRobot("rosy_01")],
                           signal_console=signals)
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)
    client = _client(create_app(console, task_service=tasks, site_users={}, site_logins=_accounts()))
    _login(client)

    response = client.post("/api/fleet/signals/presence", headers=ORIGIN)
    assert response.status_code == 200
    assert "alice" in signals._presence


def test_api_reference_documents_the_login_routes():
    root = Path(__file__).resolve().parents[3]
    reference = (root / "docs/reference/ROSY API & Protocol Reference.md").read_text(encoding="utf-8")

    for row in ("| POST | `/api/fleet/auth/login` |", "| POST | `/api/fleet/auth/logout` |",
                "| GET | `/api/fleet/auth/session` |", "| v1.137 | 2026-10-08 | Additive (D-519)"):
        assert row in reference
