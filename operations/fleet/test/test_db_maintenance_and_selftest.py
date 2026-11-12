"""Fleet DB admin actions, live SQLite checks, and archive-safe retention."""
import sqlite3
import threading
from contextlib import closing

from fleet.server.db_maintenance import (connect_sqlite, prune_expired_online,
    read_audit_archive_status, read_db_settings, run_db_maintenance_action, update_db_settings)
from fleet.server.sqlite_policy import set_wal_autocheckpoint
from fleet.server.task_store import FleetTaskStore
from test_audit_archive import FakePostgresArchive
from test_password_session import ORIGIN, _accounts, _app, _client, _login


def _admin(tmp_path):
    app, tasks = _app(tmp_path, logins={
        "alice": _accounts(role="policy-admin")["alice"],
        "operator": {**_accounts()["alice"], "principal_id": "operator"},
    })
    client = _client(app)
    assert _login(client).status_code == 204
    return client, tasks.store.path


def test_status_and_admin_boundary(tmp_path):
    client, path = _admin(tmp_path)
    status = client.get("/api/fleet/admin/db-status", headers=ORIGIN)
    assert status.status_code == 200
    assert status.json()["settings"]["history_retention_days"] == 30
    assert status.json()["audit_archive"]["pending_rows"] == 0
    for method, route, body in ((client.put, "db-settings", {"history_retention_days": 1}),
                                (client.post, "db-maintenance", {"action": "self-test"})):
        assert method("/api/fleet/admin/" + route, json=body).status_code == 200
    client.cookies.clear()
    assert _login(client, login="operator").status_code == 204
    for method, route, body in ((client.put, "db-settings", {"history_retention_days": 1}),
                                (client.post, "db-maintenance", {"action": "self-test"})):
        denied = method("/api/fleet/admin/" + route, json=body)
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "ACCOUNT_ADMIN_REQUIRED"


def test_settings_validation_persistence_and_new_connection_policy(tmp_path):
    client, path = _admin(tmp_path)
    route = "/api/fleet/admin/db-settings"
    for body in ({"unknown": 1}, {"history_retention_days": -1},
                 {"audit_retention_days": True}, {"wal_autocheckpoint_pages": 99}):
        response = client.put(route, json=body)
        assert response.status_code == 422
        assert response.json()["code"] == "INVALID_DB_SETTINGS"
    try:
        response = client.put(route, json={"wal_autocheckpoint_pages": 321, "history_retention_days": 1})
        assert response.status_code == 200
        with closing(connect_sqlite(path)) as db:
            assert db.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 321
            assert dict(db.execute("SELECT key, value_int FROM fleet_db_settings"))["history_retention_days"] == 1
    finally:
        set_wal_autocheckpoint(None)


def test_self_test_detects_foreign_key_violation_and_rejects_action(tmp_path):
    client, path = _admin(tmp_path)
    route = "/api/fleet/admin/db-maintenance"
    bad = client.post(route, json={"action": "unknown"})
    assert bad.status_code == 422 and bad.json()["code"] == "INVALID_DB_ACTION"
    good = client.post(route, json={"action": "self-test"}).json()
    assert good["ok"] is True
    assert set(good["checks"]) == {"policy", "integrity", "wal_and_fragmentation",
                                    "migrations_and_settings", "audit_archive"}
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("INSERT INTO fleet_task_history(task_id,status,source,actor_id,created_at) "
                   "VALUES ('missing','FAILED','console','test','2000-01-01')")
        db.commit()
    broken = client.post(route, json={"action": "self-test"}).json()
    assert broken["ok"] is False
    assert broken["checks"]["integrity"]["fk_violations"] > 0


def test_checkpoint_and_incremental_vacuum(tmp_path):
    client, _ = _admin(tmp_path)
    result = client.post("/api/fleet/admin/db-maintenance", json={"action": "checkpoint"}).json()
    assert result["busy"] == 0 and result["log_frames"] >= 0
    path = tmp_path / "vacuum.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        db.execute("VACUUM")
        db.execute("CREATE TABLE bulky (value TEXT)")
        db.executemany("INSERT INTO bulky VALUES (?)", [("x" * 2000,) for _ in range(100)])
        db.execute("DELETE FROM bulky")
        db.commit()
    result = run_db_maintenance_action(path, "incremental-vacuum")
    assert result["reclaimed_pages"] > 0
    assert result["freelist_after"] < result["freelist_before"]


def test_flush_and_archive_watermark_guard(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    first = store.begin_api_audit(principal_id="op", role="operator", method="POST", path="/tasks")
    store.finish_api_audit(first, status_code=200)
    path = store.path
    unconfigured = run_db_maintenance_action(path, "flush-audit")
    assert unconfigured["ok"] is False and unconfigured["error"] == "POSTGRES_UNCONFIGURED"
    archive = FakePostgresArchive()
    flushed = run_db_maintenance_action(path, "flush-audit", context_log=archive.context_log)
    assert flushed["ok"] is True and flushed["pending_rows"] == 0
    assert len(archive.rows) == 2
    with closing(sqlite3.connect(path)) as db:
        db.execute("UPDATE fleet_api_audit SET created_at='2000-01-01'")
        db.execute("UPDATE fleet_audit_flush SET last_rowid=1 WHERE kind='fleet_api_audit'")
        db.commit()
    deleted = prune_expired_online(path, read_db_settings(path))
    assert deleted["fleet_api_audit"] == 1
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT rowid FROM fleet_api_audit").fetchall() == [(2,)]


def test_updated_retention_and_zero_disable(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    request = dict(robot_id="rosy_01", task_type="delivery", source="console", actor_id="op",
                   request_key="old", request={"destination": "dock"}, evidence=None)
    store.create_task(task_id="old", **request)
    with closing(sqlite3.connect(store.path)) as db:
        db.execute("UPDATE fleet_tasks SET status='COMPLETED', updated_at='2000-01-01'")
        db.execute("UPDATE fleet_task_history SET created_at='2000-01-01'")
        db.commit()
    try:
        update_db_settings(store.path, {"history_retention_days": 0})
        assert run_db_maintenance_action(store.path, "prune-expired")["deleted"]["fleet_task_history"] == 0
        update_db_settings(store.path, {"history_retention_days": 1})
        assert run_db_maintenance_action(store.path, "prune-expired")["deleted"]["fleet_task_history"] > 0
    finally:
        set_wal_autocheckpoint(None)


def test_self_test_with_concurrent_wal_reader_and_writer(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    with closing(connect_sqlite(path)) as db:
        db.execute("CREATE TABLE sample(value INTEGER)")
        db.commit()
    ready = threading.Event()
    release = threading.Event()
    def reader():
        with closing(sqlite3.connect(path)) as db:
            db.execute("BEGIN")
            db.execute("SELECT * FROM sample").fetchall()
            ready.set()
            release.wait(5)
            db.commit()
    thread = threading.Thread(target=reader)
    thread.start()
    assert ready.wait(5)
    try:
        with closing(connect_sqlite(path)) as db:
            db.execute("INSERT INTO sample VALUES (1)")
            db.commit()
            assert db.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
        assert run_db_maintenance_action(path, "self-test")["ok"] is True
    finally:
        release.set()
        thread.join(5)
