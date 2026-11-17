"""Read-only Fleet database maintenance status and its human admin boundary."""

import json
import sqlite3

from fleet.server.db_status import collect_db_status
from test_password_session import ORIGIN, TOKEN, _accounts, _app, _client, _login


class ReachableLog:
    def _connect_and(self, work):
        class Connection:
            def execute(self, statement):
                assert statement == "SELECT pg_database_size(current_database())"
                return self

            def fetchone(self):
                return (8192,)

        work(Connection())


class UnreachableLog:
    def _connect_and(self, work):
        raise OSError("private-host-name")


def test_collect_db_status_reads_wal_migrations_timestamps_and_backup_without_paths(tmp_path):
    db_path = tmp_path / "fleet.sqlite3"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "fleet-backup-20261112.sqlite3").write_bytes(b"backup")
    writer = sqlite3.connect(db_path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE fleet_component_migrations(component TEXT, version INTEGER)")
        writer.execute("INSERT INTO fleet_component_migrations VALUES ('tasks', 4)")
        writer.execute("CREATE TABLE events(created_at TEXT)")
        writer.executemany("INSERT INTO events VALUES (?)", [("2026-01-01",), ("2026-11-12",)])
        writer.commit()
        status = collect_db_status(db_path, context_log=ReachableLog(), backup_dir=backup_dir)
        assert status["fleet"]["journal_mode"] == "wal"
        assert status["fleet"]["wal_bytes"] > 0
        assert status["fleet"]["component_migrations"] == {"tasks": 4}
        assert status["fleet"]["newest_per_table"]["events"] == "2026-11-12"
        assert status["postgres"] == {"configured": True, "reachable": True, "database_size_bytes": 8192}
        assert status["backups"]["fleet"]["count"] == 1
        assert status["backups"]["fleet"]["newest_age_hours"] is not None
        assert str(tmp_path) not in json.dumps(status)
    finally:
        writer.close()


def test_collect_db_status_handles_missing_stores_and_unreachable_postgres(tmp_path):
    missing = collect_db_status(tmp_path / "missing.sqlite3", context_log=UnreachableLog())
    assert missing["fleet"]["configured"] is False
    assert missing["fleet"]["component_migrations"] == {}
    assert missing["postgres"] == {"configured": True, "reachable": False, "database_size_bytes": None}
    assert "private-host-name" not in json.dumps(missing)


def test_admin_db_status_requires_cookie_manage_grant_and_same_origin(tmp_path):
    app, _ = _app(tmp_path, logins={
        "alice": _accounts(role="policy-admin")["alice"],
        "operator": {**_accounts()["alice"], "principal_id": "operator"},
    })
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    client = _client(app)
    route = "/api/fleet/admin/db-status"
    for headers in ({}, {"Authorization": f"Bearer {TOKEN}"}):
        response = client.get(route, headers=headers)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ACCOUNT_ADMIN_REQUIRED"
    assert _login(client, login="operator").status_code == 204
    denied = client.get(route)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "ACCOUNT_ADMIN_REQUIRED"
    client.cookies.clear()
    assert _login(client).status_code == 204
    denied = client.get(route, headers={"Origin": "https://elsewhere.example"})
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "ACCOUNT_ADMIN_REQUIRED"
    response = client.get(route, headers=ORIGIN)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["fleet"]["journal_mode"] == "wal"
    assert "postgres" in response.json() and "backups" in response.json()
    assert str(tmp_path) not in response.text
