"""D-689 self profile and ordinary password rotation, using the existing auth fixtures."""

import pytest
import sqlite3
import threading

from test_password_session import (
    CHANGE, COOKIE, ORIGIN, TOKEN, TYPED, _accounts, _app, _bootstrap, _client, _login,
)
from fleet.server.password_session import PasswordSessions
from fleet.server import password_session as session_module

PROFILE = "/api/fleet/auth/profile"
NEW_PASSWORD = "correct horse battery staple"


def test_profile_is_cookie_owned_durable_and_bound_to_principal(tmp_path):
    source = _accounts(principal_id="member@example.test")
    app, _ = _app(tmp_path, logins=source)
    client = _client(app)
    assert _login(client).status_code == 204
    assert client.get(PROFILE).json() == {
        "login": "alice", "principal_id": "member@example.test", "email": "member@example.test",
        "role": "operator", "display_name": "alice",
    }
    name = "<script>한글 이름</script>"
    assert client.patch(PROFILE, headers=ORIGIN, json={"display_name": "  " + name + "  "}).status_code == 200
    assert client.get(PROFILE).json()["display_name"] == name
    assert client.post(CHANGE, headers=ORIGIN, json={
        "current_password": TYPED, "password": NEW_PASSWORD,
    }).status_code == 204
    restarted = _client(_app(tmp_path, logins=source)[0])
    response = _login(restarted, password=NEW_PASSWORD)
    assert response.status_code == 204
    assert restarted.get(PROFILE).json()["display_name"] == name
    replaced = _client(_app(tmp_path, logins=_accounts(principal_id="replacement"))[0])
    assert _login(replaced).status_code == 204
    assert replaced.get(PROFILE).json()["display_name"] == "alice"
    assert replaced.get(PROFILE).json()["email"] is None


@pytest.mark.parametrize("body", [{}, {"display_name": " "}, {"display_name": "x" * 81},
    {"display_name": "a\nb"}, {"display_name": "a\x7fb"}, {"display_name": 12},
    {"display_name": "Name", "role": "policy-admin"},
    {"display_name": "Name", "login": "bob"}, {"display_name": "Name", "email": "other"}])
def test_profile_rejects_invalid_or_cross_account_fields(tmp_path, body):
    client = _client(_app(tmp_path)[0])
    _login(client)
    assert client.patch(PROFILE, headers=ORIGIN, json=body).status_code == 422
    assert client.get(PROFILE).json()["display_name"] == "alice"


def test_profile_requires_normal_cookie_and_same_origin(tmp_path):
    _, initial = _bootstrap(tmp_path)
    assert initial.get(PROFILE).status_code == 403
    normal = _client(_app(tmp_path / "normal")[0])
    _login(normal)
    assert normal.get(PROFILE, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 403
    assert normal.patch(PROFILE, json={"display_name": "Name"}).status_code == 403
    assert normal.patch(PROFILE, headers={"Origin": "https://other.test"},
                        json={"display_name": "Name"}).status_code == 403


@pytest.mark.parametrize("body", [r'{"display_name":"\ud800"}', r'{"display_name":"\udfff"}'])
def test_profile_rejects_unpaired_surrogates_as_invalid_input(tmp_path, body):
    client = _client(_app(tmp_path)[0])
    _login(client)
    response = client.patch(PROFILE, headers={**ORIGIN, "Content-Type": "application/json"}, content=body)
    assert response.status_code == 422
    assert client.get(PROFILE).json()["display_name"] == "alice"
    assert client.patch(PROFILE, headers=ORIGIN, json={"display_name": "한글 🙂"}).status_code == 200


def test_normal_password_change_checks_current_and_rotates_all_sessions(tmp_path):
    app, _ = _app(tmp_path)
    client = _client(app)
    _login(client)
    sessions = app.state.password_sessions
    old, other = client.cookies[COOKIE], sessions.issue("alice", remember=False)
    bad = client.post(CHANGE, headers=ORIGIN, json={"current_password": "wrong", "password": NEW_PASSWORD})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "CURRENT_PASSWORD_INCORRECT"
    assert sessions.principal(old) is not None
    assert client.post(CHANGE, headers=ORIGIN, json={"current_password": TYPED, "password": TYPED}).status_code == 422
    assert client.post(CHANGE, headers=ORIGIN, json={"current_password": TYPED, "password": NEW_PASSWORD}).status_code == 204
    assert sessions.principal(old) is sessions.principal(other) is None
    restarted = PasswordSessions(sessions.path, _accounts())
    assert restarted.check("restart", "alice", TYPED) is None
    assert restarted.check("restart", "alice", NEW_PASSWORD) is not None


@pytest.mark.parametrize("body", [{"password": NEW_PASSWORD},
    {"current_password": TYPED, "password": NEW_PASSWORD, "principal_id": "other"},
    {"current_password": 1, "password": NEW_PASSWORD}])
def test_normal_password_change_rejects_missing_or_foreign_fields(tmp_path, body):
    client = _client(_app(tmp_path)[0])
    _login(client)
    assert client.post(CHANGE, headers=ORIGIN, json=body).status_code == 422


def test_normal_concurrent_rotation_has_one_winner_and_invalidates_checked_password(tmp_path):
    original_password = TYPED
    sessions = PasswordSessions(tmp_path / "sessions.db", _accounts())
    cookie = sessions.issue("alice", remember=False)
    checked = sessions.check("racer", "alice", TYPED)
    barrier, results = threading.Barrier(2), []

    def rotate():
        barrier.wait()
        try:
            results.append(sessions.change_password(cookie, NEW_PASSWORD, current_password=original_password))
        except session_module.StalePasswordCheck:
            results.append(None)
    threads = [threading.Thread(target=rotate) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert len(results) == 2 and results.count(None) == 1
    with pytest.raises(session_module.StalePasswordCheck):
        sessions.issue("alice", remember=False, verified=checked)


def test_profile_and_normal_rotation_commit_failure_preserve_old_state(tmp_path, monkeypatch):
    app, _ = _app(tmp_path)
    client = _client(app)
    _login(client)
    sessions = app.state.password_sessions
    original = sessions._connect

    class CommitFailure(sqlite3.Connection):
        def __exit__(self, *_args):
            self.rollback()
            raise sqlite3.OperationalError("commit unavailable")

    def broken(**kwargs):
        db = sqlite3.connect(sessions.path, factory=CommitFailure)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr(sessions, "_connect", broken)
    assert client.patch(PROFILE, headers=ORIGIN, json={"display_name": "New name"}).status_code == 503
    assert client.post(CHANGE, headers=ORIGIN, json={
        "current_password": TYPED, "password": NEW_PASSWORD,
    }).status_code == 503
    monkeypatch.setattr(sessions, "_connect", original)
    assert client.get(PROFILE).json()["display_name"] == "alice"
    assert sessions.check("retry", "alice", TYPED) is not None


def test_profile_changes_do_not_touch_another_account(tmp_path):
    source = {**_accounts(), "second": {**_accounts()["alice"], "principal_id": "other"}}
    app, _ = _app(tmp_path, logins=source)
    client, second = _client(app), _client(app)
    _login(client)
    _login(second, login="second")
    assert client.patch(PROFILE, headers=ORIGIN, json={"display_name": "First"}).status_code == 200
    assert client.post(CHANGE, headers=ORIGIN, json={
        "current_password": TYPED, "password": NEW_PASSWORD,
    }).status_code == 204
    assert second.get(PROFILE).json()["display_name"] == "second"
