"""D-757 durable human accounts and live revocation, without robot commands."""
import sqlite3
import json
from hashlib import sha256

import pytest

from fleet.server.password_session import PasswordSessions, SessionStorageUnavailable, StalePasswordCheck
from fleet.server.site_users import hash_password
from test_password_session import _accounts, _app, _client, _login, TYPED, ORIGIN


def activated(tmp_path):
    sessions = PasswordSessions(tmp_path / "accounts.sqlite3", _accounts())
    sessions.bootstrap_accounts("alice", "test-site")
    return sessions


def cookie(sessions, login="alice", typed=TYPED):
    verified = sessions.check("local", login, typed)
    assert verified is not None
    return sessions.issue(login, remember=False, verified=verified)


def test_activation_preserves_effective_password_profile_and_identity(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    original = PasswordSessions(path, _accounts())
    value = cookie(original)
    original.profile(value, "Alice Example")
    value, _ = original.change_password(value, "correct horse battery staple", current_password=TYPED)
    # Activate before stale YAML can reconcile away the effective password.
    active = PasswordSessions(path, _accounts(role="viewer"), accounts_bootstrap=("alice", "test-site"))
    assert active.check("a", "alice", TYPED) is None
    value = cookie(active, typed="correct horse battery staple")
    context = active.account_context(value)
    assert context["account_id"] and context["session_family"] != value
    assert context["grants"] == [{"resource": "site:test-site", "capabilities": ["fleet.read", "accounts.manage"]}]
    assert active.profile(value)["display_name"] == "Alice Example"
    restarted = PasswordSessions(path, {})
    assert restarted.account_context(value)["account_id"] == context["account_id"]


def test_activation_requires_change_for_id_bang_password_and_keeps_new_password(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    sessions = PasswordSessions(path, _accounts(password_scrypt=hash_password("alice!")))
    sessions.bootstrap_accounts("alice", "test-site")
    value = cookie(sessions, typed="alice!")
    assert sessions.principal(value)[0].password_change_required
    value, _ = sessions.change_password(value, TYPED)
    assert not sessions.principal(value)[0].password_change_required
    reopened = PasswordSessions(path, {})
    assert reopened.check("local", "alice", "alice!") is None
    assert reopened.check("local", "alice", TYPED) is not None


@pytest.mark.parametrize("active", [False, True])
def test_profile_cannot_restore_id_bang_as_permanent_password(tmp_path, active):
    login = "longername"
    sessions = PasswordSessions(tmp_path / "accounts.sqlite3", {login: _accounts()["alice"]})
    if active:
        sessions.bootstrap_accounts(login, "test-site")
    value = cookie(sessions, login=login)
    with pytest.raises(ValueError, match="invalid new password"):
        sessions.change_password(
            value, login + "!", current_password=TYPED,
        )
    assert sessions.principal(value) is not None


def test_bootstrap_requires_explicit_existing_login_and_is_one_time(tmp_path):
    sessions = PasswordSessions(tmp_path / "accounts.sqlite3", _accounts())
    with pytest.raises(ValueError):
        sessions.bootstrap_accounts("missing", "test-site")
    sessions.bootstrap_accounts("alice", "test-site")
    with pytest.raises(ValueError):
        sessions.bootstrap_accounts("alice", "other-site")


@pytest.mark.parametrize('role', ['viewer', 'operator', 'policy-admin'])
def test_bootstrap_does_not_add_vault_grants(tmp_path, role):
    sessions = PasswordSessions(tmp_path / 'accounts.sqlite3', _accounts(role=role))
    sessions.bootstrap_accounts('alice', 'test-site')
    context = sessions.account_context(cookie(sessions))
    capabilities = context['grants'][0]['capabilities']
    assert not any(capability.startswith('vault.') for capability in capabilities)


@pytest.mark.parametrize("INITIAL_PASSWORD", ["fixture-pass-9384", "bob!"])
def test_account_mutations_are_cas_audited_and_revoke_across_processes(tmp_path, INITIAL_PASSWORD):
    sessions = activated(tmp_path)
    manager = cookie(sessions)
    new = sessions.create_account(
        manager, login="bob", principal_id="bob", role="operator",
        password=INITIAL_PASSWORD,
        grants=[],
    )
    second = PasswordSessions(sessions.path, {})
    bob = cookie(second, "bob", INITIAL_PASSWORD)
    assert second.principal(bob)[0].password_change_required
    bob, _ = second.change_password(bob, "a permanent secret")
    current = sessions.list_accounts(manager)
    new = next(row for row in current if row["account_id"] == new["account_id"])
    verified = second.check("b", "bob", "a permanent secret")
    changed = sessions.update_account(manager, new["account_id"], revision=new["revision"], enabled=False)
    assert changed["revision"] == new["revision"] + 1
    assert second.principal(bob) is None
    with pytest.raises(StalePasswordCheck):
        second.issue("bob", remember=False, verified=verified)
    with pytest.raises(ValueError, match="revision"):
        sessions.update_account(manager, new["account_id"], revision=new["revision"], enabled=True)
    with sqlite3.connect(sessions.path) as db:
        event = db.execute("SELECT actor_account_id, target_account_id, previous_revision, next_revision "
                           "FROM rosy_account_audit ORDER BY rowid DESC LIMIT 1").fetchone()
    assert event == (sessions.account_context(manager)["account_id"], new["account_id"],
                     new["revision"], changed["revision"])


def test_last_manager_and_operator_cannot_manage_accounts(tmp_path):
    sessions = activated(tmp_path)
    manager = cookie(sessions)
    me = sessions.account_context(manager)
    for changes in ({"enabled": False}, {"grants": []}):
        with pytest.raises(ValueError, match="last"):
            sessions.update_account(manager, me["account_id"], revision=me["revision"], **changes)
    other = sessions.create_account(manager, login="bob", principal_id="bob", role="operator",
                                    password="fixture-pass-9384", grants=[])
    bob, _ = sessions.change_password(cookie(sessions, "bob", "fixture-pass-9384"), "Tr0ub4dor3xyz")
    with pytest.raises(PermissionError):
        sessions.list_accounts(bob)
    assert "password_scrypt" not in other


@pytest.mark.parametrize("INITIAL_PASSWORD", ["SuperSecretSitePsk99", "bob!"])
def test_admin_reset_and_revoke_sessions(tmp_path, INITIAL_PASSWORD):
    sessions = activated(tmp_path)
    manager = cookie(sessions)
    row = sessions.create_account(manager, login="bob", principal_id="bob", role="viewer",
                                  password="fixture-pass-9384", grants=[])
    bob = cookie(sessions, "bob", "fixture-pass-9384")
    updated = sessions.reset_account_password(
        manager, row["account_id"], revision=row["revision"],
        password=INITIAL_PASSWORD,
    )
    assert sessions.principal(bob) is None
    bob = cookie(sessions, "bob", INITIAL_PASSWORD)
    assert sessions.principal(bob)[0].password_change_required
    sessions.revoke_account_sessions(manager, row["account_id"], revision=updated["revision"])
    assert sessions.principal(bob) is None


@pytest.mark.parametrize("password", ["other!", "bob", ""])
def test_account_creation_rejects_other_short_passwords(tmp_path, password):
    sessions = activated(tmp_path)
    with pytest.raises(ValueError, match="invalid password"):
        sessions.create_account(cookie(sessions), login="bob", principal_id="bob", role="viewer",
                                password=password, grants=[])


def test_account_api_cookie_origin_capability_and_strict_bodies(tmp_path):
    app, _ = _app(tmp_path)
    app.state.password_sessions.bootstrap_accounts("alice", "test-site")
    client = _client(app)
    assert _login(client).status_code == 204
    path = "/api/fleet/auth/accounts"
    assert client.get(path, headers=ORIGIN).status_code == 200
    assert client.get(path).status_code == 403
    assert client.get(path, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    body = {"login": "bob", "principal_id": "bob", "role": "viewer",
            "password": "fixture-pass-9384", "grants": []}
    assert client.post(path, headers=ORIGIN, json={**body, "admin": True}).status_code == 422
    created = client.post(path, headers=ORIGIN, json=body)
    assert created.status_code == 201
    row = created.json()
    response = client.patch(path + "/" + row["account_id"], headers=ORIGIN,
                            json={"revision": row["revision"], "enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_family_context_and_logout_share_authority_transaction(tmp_path):
    sessions = activated(tmp_path)
    value = cookie(sessions)
    family = sessions.account_context(value)["session_family"]
    assert sessions.context_by_family(family)["login"] == "alice"
    with sessions._ledger.db(write=True) as db:
        assert sessions.context_by_family(family, db=db)["login"] == "alice"
        sessions.revoke_family(family, db=db)
    assert sessions.principal(value) is None
    assert sessions.context_by_family(family) is None


@pytest.mark.parametrize("grants", [
    [{"resource": "robot:r1", "capabilities": ["accounts.manage"]}],
    [{"resource": "site:s1", "capabilities": ["robot.operate"]}],
    [{"resource": "project:p1", "capabilities": []}],
    [{"resource": "project:*", "capabilities": ["learning.view"]}],
])
def test_grants_reject_capability_resource_mismatch(tmp_path, grants):
    sessions = activated(tmp_path)
    with pytest.raises(ValueError):
        sessions.create_account(cookie(sessions), login="bob", principal_id="bob", role="viewer",
                                password="fixture-pass-9384", grants=grants)


def test_active_ledger_app_restarts_without_yaml(tmp_path):
    app, _ = _app(tmp_path)
    app.state.password_sessions.bootstrap_accounts("alice", "test-site")
    restarted, _ = _app(tmp_path, logins={})
    client = _client(restarted)
    assert _login(client).status_code == 204
    assert client.get("/api/fleet/auth/accounts", headers=ORIGIN).status_code == 200


def test_account_api_rejects_non_string_role(tmp_path):
    app, _ = _app(tmp_path)
    app.state.password_sessions.bootstrap_accounts("alice", "test-site")
    client = _client(app)
    assert _login(client).status_code == 204
    assert client.post("/api/fleet/auth/accounts", headers=ORIGIN,
                       json={"login": "bob", "principal_id": "bob", "role": [],
                             "password": "fixture-pass-9384", "grants": []}).status_code == 422


def test_revision_change_fences_previously_verified_password(tmp_path):
    sessions = activated(tmp_path)
    manager = cookie(sessions)
    row = sessions.create_account(manager, login="bob", principal_id="bob", role="viewer",
                                  password="fixture-pass-9384", grants=[])
    old = sessions.check("b", "bob", "fixture-pass-9384")
    sessions.revoke_account_sessions(manager, row["account_id"], revision=row["revision"])
    with pytest.raises(StalePasswordCheck):
        sessions.issue("bob", remember=False, verified=old)


def test_account_db_failure_only_allows_cached_estop(tmp_path, monkeypatch):
    sessions = activated(tmp_path)
    value = cookie(sessions)
    assert sessions.principal(value)

    def unavailable(**kwargs):
        raise sqlite3.OperationalError("locked")
    monkeypatch.setattr(sessions, "_connect", unavailable)
    with pytest.raises(SessionStorageUnavailable):
        sessions.principal(value)
    assert sessions.principal(value, allow_stale=True)


def test_revoked_family_cannot_fallback_to_own_cached_estop(tmp_path, monkeypatch):
    sessions = activated(tmp_path)
    value = cookie(sessions)
    family = sessions.account_context(value)["session_family"]
    assert sessions.principal(value)
    sessions.revoke_family(family)

    def unavailable(**kwargs):
        raise sqlite3.OperationalError("locked")
    monkeypatch.setattr(sessions, "_connect", unavailable)
    with pytest.raises(SessionStorageUnavailable):
        sessions.principal(value, allow_stale=True)


def test_disabled_sessions_cannot_change_profile_or_password_across_instances(tmp_path):
    sessions = activated(tmp_path)
    manager = cookie(sessions)
    row = sessions.create_account(manager, login="bob", principal_id="bob", role="viewer",
                                  password="fixture-pass-9384", grants=[])
    other = PasswordSessions(sessions.path, {})
    value, _ = other.change_password(cookie(other, "bob", "fixture-pass-9384"), "Tr0ub4dor3xyz")
    row = next(r for r in sessions.list_accounts(manager) if r["account_id"] == row["account_id"])
    sessions.update_account(manager, row["account_id"], revision=row["revision"], enabled=False)
    with pytest.raises(StalePasswordCheck):
        other.profile(value, "stale edit")
    with pytest.raises(StalePasswordCheck):
        other.change_password(value, "MyEXAMPLEpass99", current_password="Tr0ub4dor3xyz")


def test_managed_operator_requires_exact_site_grant_for_robot_command(tmp_path):
    app, _ = _app(tmp_path)
    sessions = app.state.password_sessions
    sessions.bootstrap_accounts("alice", "test-site")
    manager = cookie(sessions)
    row = sessions.create_account(manager, login="bob", principal_id="bob", role="operator",
                                  password="fixture-pass-9384", grants=[])
    client = _client(app)
    assert _login(client, login="bob", password="fixture-pass-9384").status_code == 204
    assert client.post("/api/fleet/auth/change-password", headers=ORIGIN,
                       json={"password": "Tr0ub4dor3xyz"}).status_code == 204
    robot = app.state.console.clients()["rosy_01"]
    before = list(robot.calls)
    assert client.get("/api/fleet/state").status_code == 403
    assert client.post("/api/fleet/estop", headers=ORIGIN).status_code == 403
    assert robot.calls == before
    row = next(r for r in sessions.list_accounts(manager) if r["login"] == "bob")
    row = sessions.update_account(manager, row["account_id"], revision=row["revision"], grants=[
        {"resource": "site:test-site", "capabilities": ["fleet.read", "fleet.operate"]}])
    assert _login(client, login="bob", password="Tr0ub4dor3xyz").status_code == 204
    assert client.post("/api/fleet/estop", headers=ORIGIN).status_code == 200
    assert len(robot.calls) > len(before)
    before = list(robot.calls)
    sessions.update_account(manager, row["account_id"], revision=row["revision"], grants=[
        {"resource": "site:other-site", "capabilities": ["fleet.read", "fleet.operate"]}])
    assert _login(client, login="bob", password="Tr0ub4dor3xyz").status_code == 204
    assert client.post("/api/fleet/estop", headers=ORIGIN).status_code == 403
    assert robot.calls == before


def test_account_audit_preserves_historical_before_after_grants(tmp_path):
    sessions = activated(tmp_path)
    manager = cookie(sessions)
    row = sessions.create_account(manager, login="bob", principal_id="bob", role="operator",
                                  password="fixture-pass-9384", grants=[])
    first = [{"resource": "site:test-site", "capabilities": ["fleet.read"]}]
    updated = sessions.update_account(manager, row["account_id"], revision=row["revision"], grants=first)
    sessions.update_account(manager, row["account_id"], revision=updated["revision"], grants=[])
    history = [r for r in sessions.list_account_audit(manager) if r["target_account_id"] == row["account_id"]]
    assert history[-2]["before"]["grants"] == []
    assert history[-2]["after"]["grants"] == first
    assert history[-1]["before"]["grants"] == first
    assert history[-1]["after"]["grants"] == []
    assert history[-1]["outcome"] == "success"
    assert "password_scrypt" not in json.dumps(history)


def test_preactivation_worker_observes_activation_and_disable(tmp_path):
    sessions = PasswordSessions(tmp_path / "accounts.sqlite3", _accounts())
    old = PasswordSessions(sessions.path, _accounts())
    old_cookie = cookie(old)
    sessions.bootstrap_accounts("alice", "test-site")
    manager = cookie(sessions)
    row = sessions.create_account(manager, login="bob", principal_id="bob", role="operator",
                                  password="fixture-pass-9384", grants=[])
    assert old.principal(old_cookie) is None
    assert old.check("b", "bob", "fixture-pass-9384") is not None
    sessions.update_account(manager, row["account_id"], revision=row["revision"], enabled=False)
    assert old.check("c", "bob", "fixture-pass-9384") is None


def test_migration_rejects_reused_login_with_different_principal(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    sessions = PasswordSessions(path, _accounts())
    sessions.change_password(cookie(sessions), "correcthorsebattery", current_password=TYPED)
    with pytest.raises(ValueError, match="identity"):
        PasswordSessions(path, _accounts(principal_id="different-owner"),
                         accounts_bootstrap=("alice", "test-site"))


def test_managed_cookie_supports_top_level_sso_without_cross_site_mutation(tmp_path):
    app, _ = _app(tmp_path)
    app.state.password_sessions.bootstrap_accounts("alice", "test-site")
    client = _client(app)
    response = _login(client)
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    assert client.post("/api/fleet/estop", headers={"Origin": "https://other.example"}).status_code == 403


def test_managed_policy_role_does_not_inflate_policy_permission(tmp_path):
    app, _ = _app(tmp_path)
    sessions = app.state.password_sessions
    sessions.bootstrap_accounts("alice", "test-site")
    manager = cookie(sessions)
    sessions.create_account(manager, login="bob", principal_id="bob", role="policy-admin",
                            password="fixture-pass-9384", grants=[])
    client = _client(app)
    assert _login(client, login="bob", password="fixture-pass-9384").status_code == 204
    assert client.post("/api/fleet/auth/change-password", headers=ORIGIN,
                       json={"password": "Tr0ub4dor3xyz"}).status_code == 204
    response = client.delete("/api/fleet/ai/human-classes/missing?reason=test", headers=ORIGIN)
    assert response.status_code == 403


def test_migrated_human_bearer_cannot_bypass_grants_or_disable(tmp_path):
    users = {sha256(b"old-human-key").hexdigest(): {"principal_id": "alice", "role": "operator"},
             sha256(b"machine-key").hexdigest(): {"principal_id": "site-health", "role": "viewer"}}
    app, _ = _app(tmp_path, users=users)
    client = _client(app)
    human = {"Authorization": "Bearer old-human-key"}
    machine = {"Authorization": "Bearer machine-key"}
    assert client.get("/api/fleet/state", headers=human).status_code == 200
    sessions = app.state.password_sessions
    sessions.bootstrap_accounts("alice", "test-site")
    manager = cookie(sessions)
    alice = sessions.account_context(manager)
    sessions.update_account(manager, alice["account_id"], revision=alice["revision"], grants=[
        {"resource": "site:test-site", "capabilities": ["accounts.manage"]}])
    assert client.get("/api/fleet/state", headers=human).status_code == 401
    assert client.get("/api/fleet/state", headers=machine).status_code == 200
    manager = cookie(sessions)
    sessions.create_account(manager, login="bob", principal_id="bob", role="viewer",
                            password="fixture-pass-9384", grants=[
                                {"resource": "site:test-site", "capabilities": ["accounts.manage"]}])
    bob, _ = sessions.change_password(cookie(sessions, "bob", "fixture-pass-9384"), "Tr0ub4dor3xyz")
    alice = sessions.account_context(manager)
    sessions.update_account(bob, alice["account_id"], revision=alice["revision"], enabled=False)
    assert client.get("/api/fleet/state", headers=human).status_code == 401
    assert client.get("/api/fleet/state", headers=machine).status_code == 200


def test_managed_own_profile_exposes_exact_grants(tmp_path):
    sessions = activated(tmp_path)
    value = cookie(sessions)
    assert sessions.profile(value)['grants'] == sessions.account_context(value)['grants']
