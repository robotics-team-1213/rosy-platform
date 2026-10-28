from contextlib import closing
import json

import pytest

from fleet.server.password_session import PasswordSessions
from test_account_ledger import activated, cookie
from test_password_session import _accounts


def test_legacy_identity_lookup_matches_existing_cookie_authority(tmp_path):
    sessions = PasswordSessions(tmp_path / "legacy.sqlite3", _accounts(policy_admin=True))
    expected, _ = sessions.principal(cookie(sessions))
    assert sessions.principal_by_id("alice") == expected
    assert sessions.principal_by_id("unknown") is None


def test_lookup_sees_account_activation_without_a_cookie_or_cached_site(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    stale = PasswordSessions(path, _accounts())
    current = PasswordSessions(path, _accounts(), accounts_bootstrap=("alice", "test-site"))
    context = current.account_context(cookie(current))
    principal = stale.principal_by_id("alice")
    assert principal.account_id == context["account_id"]
    assert principal.site_resource == "site:test-site"
    assert principal.role == "operator" and not principal.password_change_required
    assert principal.permits_site("fleet.operate", {"operator"})


@pytest.mark.parametrize("change", ["disable", "grant"])
def test_lookup_reads_uncommitted_authority_without_committing_or_closing(tmp_path, change):
    sessions = activated(tmp_path)
    assert sessions.principal_by_id("alice").permits_site("fleet.operate", {"operator"})
    with closing(sessions._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        if change == "disable":
            db.execute("UPDATE rosy_accounts SET enabled=0 WHERE principal_id=?", ("alice",))
        else:
            grants = [{"resource": "site:test-site", "capabilities": ["fleet.read", "accounts.manage"]}]
            db.execute("UPDATE rosy_accounts SET grants=? WHERE principal_id=?", (json.dumps(grants), "alice"))
        principal = sessions.principal_by_id("alice", db=db)
        if change == "disable":
            assert principal is None
        else:
            assert principal.account_id and not principal.permits_site("fleet.operate", {"operator"})
        assert sessions.migrated_principal("alice", db=db)
        assert db.in_transaction and db.execute("SELECT 1").fetchone()[0] == 1
        db.rollback()
    assert sessions.principal_by_id("alice").permits_site("fleet.operate", {"operator"})


def test_uncommitted_authority_probe_preserves_legacy_session_after_rollback(tmp_path):
    sessions = PasswordSessions(tmp_path / "legacy.sqlite3", _accounts())
    value = cookie(sessions)
    with closing(sessions._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO rosy_account_authority(singleton,site_id) VALUES(1,?)", ("transient-site",))
        assert sessions.principal_by_id("alice", db=db) is None
        assert db.in_transaction
        db.rollback()
    principal, _ = sessions.principal(value)
    assert principal.principal_id == "alice" and principal.account_id is None
