"""Configured Account service and OAuth transactions use the real account SQLite ledger."""
import json
import sqlite3
from urllib.parse import urlencode

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from fleet.server.account_authority import AccountAuthority
from fleet.server.app import create_app
from test_account_ledger import activated, cookie
from test_account_authority import ISSUER, CALLBACK, get_code, exchange
from test_password_session import _app, _accounts, _client, _login
from fleet.server.password_session import COOKIE


def config(tmp_path):
    key = tmp_path / "signing.pem"
    key.write_bytes(Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key.chmod(0o600)
    data = {"issuer": ISSUER, "site_id": "test-site", "key_id": "key-1", "private_key_file": str(key),
            "bootstrap_admin_login": "alice",
            "clients": {"robot-app": {"redirect_uris": [CALLBACK], "resources": ["robot:r1"]}}}
    path = tmp_path / "account.json"
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return path, data, key.read_bytes()


def service(tmp_path):
    path, data, pem = config(tmp_path)
    sessions = activated(tmp_path)
    value = cookie(sessions)
    context = sessions.account_context(value)
    sessions.update_account(value, context["account_id"], revision=context["revision"], grants=[
        {"resource": "site:test-site", "capabilities": ["accounts.manage"]},
        {"resource": "robot:r1", "capabilities": ["robot.read"]}])
    value = cookie(sessions)
    authority = AccountAuthority(sessions.path, issuer=ISSUER, private_key=pem, key_id="key-1",
                                 clients=data["clients"],
                                 resolve_family=lambda db, family: sessions.context_by_family(family, db=db),
                                 revoke_family=lambda db, family: sessions.revoke_family(family, db=db))
    return authority, sessions, value


def test_explicit_configuration_wires_authority_and_survives_yaml_removal(tmp_path):
    path, _, _ = config(tmp_path)
    base, tasks = _app(tmp_path)
    app = create_app(base.state.console, task_service=tasks, site_logins=_accounts(), account_config=path)
    client = _client(app)
    assert _login(client).status_code == 204
    assert client.get("/api/fleet/auth/keys").status_code == 200
    restarted = create_app(base.state.console, task_service=tasks, site_logins={}, account_config=path)
    assert _login(_client(restarted)).status_code == 204


def test_authority_configuration_accepts_public_rotation_overlap(tmp_path):
    from fleet.server.account_config import load_account_config
    path, data, private = config(tmp_path)
    public = tmp_path/'old-public.pem'
    public.write_bytes(serialization.load_pem_private_key(private, None).public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    public.chmod(0o600)
    data['public_key_files'] = {'old-key':str(public)}
    path.write_text(json.dumps(data))
    loaded = load_account_config(path)
    assert loaded['trusted_public_keys']['old-key'] == public.read_bytes()
    base, tasks = _app(tmp_path)
    app = create_app(base.state.console, task_service=tasks, site_logins=_accounts(), account_config=path)
    assert {key['kid'] for key in _client(app).get('/api/fleet/auth/keys').json()['keys']} == {'old-key','key-1'}


def test_account_management_rejects_previous_browser_family_marker(tmp_path):
    app, _ = _app(tmp_path)
    sessions = app.state.password_sessions
    sessions.bootstrap_accounts('alice', 'test-site')
    client = _client(app)
    assert _login(client).status_code == 204
    marker = client.get('/api/fleet/auth/session').json()['session_family']
    assert _login(client).status_code == 204
    response = client.get('/api/fleet/auth/accounts', headers={'Origin':'https://fleet.test', 'X-Rosy-Session':marker})
    assert response.status_code == 403


def test_managed_session_exports_capabilities_and_serves_admin_document(tmp_path):
    app, _ = _app(tmp_path)
    app.state.password_sessions.bootstrap_accounts("alice", "test-site")
    client = _client(app)
    assert _login(client).status_code == 204
    identity = client.get("/api/fleet/auth/session").json()
    assert identity["site_resource"] == "site:test-site"
    assert "accounts.manage" in identity["grants"][0]["capabilities"]
    assert client.get("/console/accounts").status_code == 200
    assert client.get("/console/assets/account-page.js").status_code == 200


def test_private_config_rejects_unknown_fields_and_unprotected_key(tmp_path):
    from fleet.server.account_config import load_account_config
    path, data, _ = config(tmp_path)
    path.write_text(json.dumps({**data, "allow_all": True}))
    with pytest.raises(ValueError):
        load_account_config(path)
    path.write_text(json.dumps(data))
    from pathlib import Path
    Path(data["private_key_file"]).chmod(0o644)
    with pytest.raises(ValueError, match="protected"):
        load_account_config(path)


def test_authority_configuration_rejects_public_key_before_activation(tmp_path):
    from fleet.server.account_config import load_account_config
    from pathlib import Path
    path, data, _ = config(tmp_path)
    public = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    Path(data["private_key_file"]).write_bytes(public)
    with pytest.raises(ValueError, match="private"):
        load_account_config(path)


def test_real_sql_refresh_replay_revocation_survives_reopen(tmp_path):
    authority, sessions, value = service(tmp_path)
    token = json.loads(exchange(authority, get_code(authority, sessions.account_context(value)))[1])
    form = urlencode({"grant_type": "refresh_token", "client_id": "robot-app", "refresh_token": token["refresh_token"]})
    assert authority.token(form)[2] == 200
    assert authority.token(form)[2] == 400
    from fleet.server.password_session import PasswordSessions
    reopened = PasswordSessions(sessions.path, {})
    assert reopened.principal(value) is None
    assert authority.introspect(token["access_token"]) == {"active": False}


def test_real_sql_code_consumption_and_issuance_rollback_together(tmp_path):
    authority, sessions, value = service(tmp_path)
    code = get_code(authority, sessions.account_context(value))
    with sqlite3.connect(sessions.path) as db:
        db.execute("CREATE TRIGGER fail_access BEFORE INSERT ON account_oauth_access "
                   "BEGIN SELECT RAISE(ABORT, 'storage failure'); END")
    with pytest.raises(sqlite3.Error):
        exchange(authority, code)
    with sqlite3.connect(sessions.path) as db:
        assert db.execute("SELECT count(*) FROM account_oauth_access").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM account_oauth_refresh").fetchone()[0] == 0
        db.execute("DROP TRIGGER fail_access")
    assert exchange(authority, code)[2] == 200


@pytest.mark.parametrize("action", ["logout", "reset"])
def test_real_sql_logout_reset_block_pending_code_and_refresh(tmp_path, action):
    authority, sessions, value = service(tmp_path)
    context = sessions.account_context(value)
    token = json.loads(exchange(authority, get_code(authority, context))[1])
    pending = get_code(authority, context)
    if action == "logout":
        sessions.revoke(value)
    else:
        sessions.reset_account_password(value, context["account_id"], revision=context["revision"],
                                        password="SuperSecretSitePsk99")
    assert exchange(authority, pending)[2] == 400
    assert authority.token(urlencode({"grant_type": "refresh_token", "client_id": "robot-app",
                                     "refresh_token": token["refresh_token"]}))[2] == 400


@pytest.mark.parametrize("same_account", [False, True])
def test_successful_browser_account_switch_revokes_old_app_family(tmp_path, same_account):
    path, _, _ = config(tmp_path)
    base, tasks = _app(tmp_path)
    app = create_app(base.state.console, task_service=tasks, site_logins=_accounts(), account_config=path)
    client, sessions, authority = _client(app), app.state.password_sessions, app.state.account_authority
    assert _login(client).status_code == 204
    value = client.cookies[COOKIE]
    context = sessions.account_context(value)
    sessions.create_account(value, login="bob", principal_id="bob", role="viewer",
                            password="fixture-pass-9384", grants=[])
    sessions.update_account(value, context["account_id"], revision=context["revision"], grants=[
        {"resource": "site:test-site", "capabilities": ["accounts.manage"]},
        {"resource": "robot:r1", "capabilities": ["robot.read"]}])
    assert _login(client).status_code == 204
    old = client.cookies[COOKIE]
    tokens = json.loads(exchange(authority, get_code(authority, sessions.account_context(old)))[1])
    assert _login(client, login="bob", password="wrong").status_code == 401
    assert authority.introspect(tokens["access_token"])["active"] is True
    replacement = _login(client) if same_account else _login(client, login="bob", password="fixture-pass-9384")
    assert replacement.status_code == 204
    assert authority.introspect(tokens["access_token"]) == {"active": False}
    assert sessions.principal(old) is None
    assert sessions.principal(client.cookies[COOKIE])[0].principal_id == ("alice" if same_account else "bob")
