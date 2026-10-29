from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from deploy.site import site_db
from deploy.site.site_db import (
    DatabaseError,
    backup_database,
    prune_ledger,
    restore_database,
    verify_database,
)


def _database(path: Path, value: str) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE records (value TEXT NOT NULL)")
        connection.execute("INSERT INTO records VALUES (?)", (value,))


def _value(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT value FROM records").fetchone()[0]


def test_backup_captures_committed_wal_data_and_is_integrity_checked(tmp_path):
    source = tmp_path / "fleet.sqlite3"
    backup = tmp_path / "backups" / "fleet.sqlite3"
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE records (value TEXT NOT NULL)")
    connection.execute("INSERT INTO records VALUES ('committed-in-wal')")
    connection.commit()
    try:
        assert Path(str(source) + "-wal").exists()
        result = backup_database(source, backup)
    finally:
        connection.close()

    assert result.integrity == "ok"
    assert result.sha256
    assert verify_database(backup) == "ok"
    with closing(sqlite3.connect(backup)) as backup_connection:
        assert backup_connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
    assert not Path(str(backup) + "-wal").exists()
    assert not Path(str(backup) + "-shm").exists()
    assert _value(backup) == "committed-in-wal"
    if os.name != "nt":
        assert backup.stat().st_mode & 0o077 == 0


def test_backup_refuses_to_overwrite_an_existing_operator_backup(tmp_path):
    source = tmp_path / "fleet.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    _database(source, "source")
    backup.write_bytes(b"keep-existing-backup")

    with pytest.raises(DatabaseError, match="already exists"):
        backup_database(source, backup)

    assert backup.read_bytes() == b"keep-existing-backup"


def test_prune_keeps_the_newest_timestamped_backups_only(tmp_path):
    for name in ("fleet-backup-20260101-000000.sqlite3", "fleet-backup-20260102-000000.sqlite3",
                 "fleet-backup-20260103-000000.sqlite3", "unrelated.sqlite3"):
        (tmp_path / name).write_bytes(b"x")

    removed = site_db._prune_backups(tmp_path, keep=2)

    assert removed == ["fleet-backup-20260101-000000.sqlite3"]
    assert not (tmp_path / "fleet-backup-20260101-000000.sqlite3").exists()
    assert (tmp_path / "fleet-backup-20260103-000000.sqlite3").exists()
    assert (tmp_path / "unrelated.sqlite3").exists()  # 이 도구가 만든 것만 치운다


def test_cli_backup_with_dest_dir_timestamps_and_prunes(tmp_path, capsys):
    source = tmp_path / "fleet.sqlite3"
    _database(source, "timer")
    dest_dir = tmp_path / "nightly"
    stale, newer = (dest_dir / "fleet-backup-20260101-000000.sqlite3",
                    dest_dir / "fleet-backup-20260102-000000.sqlite3")
    dest_dir.mkdir(parents=True)
    stale.write_bytes(b"old")
    newer.write_bytes(b"recent")

    code = site_db.main(["backup", "--source", str(source), "--dest-dir", str(dest_dir),
                         "--prune", "2"])

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    created = Path(report["path"])
    assert created.parent == dest_dir and created.is_file()
    assert created.name.startswith("fleet-backup-") and created.name.endswith(".sqlite3")
    assert report["pruned"] == ["fleet-backup-20260101-000000.sqlite3"]
    assert not stale.exists()  # 가장 오래된 것만 정리
    assert newer.exists() and _value(created) == "timer"


def test_cli_backup_rejects_ambiguous_or_empty_targets(tmp_path):
    source = tmp_path / "fleet.sqlite3"
    _database(source, "x")

    with pytest.raises(SystemExit):
        site_db.main(["backup", "--source", str(source)])
    with pytest.raises(SystemExit):
        site_db.main(["backup", "--source", str(source), "--destination", str(tmp_path / "a"),
                      "--dest-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        site_db.main(["backup", "--source", str(source), "--dest-dir", str(tmp_path),
                      "--prune", "0"])


def test_restore_requires_stopped_assertion_and_keeps_pre_restore_snapshot(tmp_path):
    source = tmp_path / "restore.sqlite3"
    target = tmp_path / "fleet.sqlite3"
    _database(source, "restored")
    _database(target, "before-restore")

    with pytest.raises(DatabaseError, match="stopped"):
        restore_database(source, target, replace=True)
    assert _value(target) == "before-restore"

    result = restore_database(source, target, replace=True, assume_stopped=True)

    assert result.integrity == "ok"
    assert result.rollback_path is not None and result.rollback_path.is_file()
    assert _value(target) == "restored"
    assert _value(result.rollback_path) == "before-restore"


def test_restore_validates_source_before_touching_current_database(tmp_path):
    source = tmp_path / "corrupt.sqlite3"
    target = tmp_path / "fleet.sqlite3"
    source.write_bytes(b"not a sqlite database")
    _database(target, "keep-current")

    with pytest.raises(DatabaseError, match="integrity"):
        restore_database(source, target, replace=True, assume_stopped=True)

    assert _value(target) == "keep-current"
    assert not list(tmp_path.glob("*.pre-restore-*.sqlite3"))


@pytest.mark.parametrize("table", [
    "rosy_account_authority", "rosy_accounts", "rosy_account_sessions", "rosy_account_audit",
    "fleet_console_sessions", "fleet_console_passwords", "fleet_console_profiles",
    "account_oauth_codes", "account_oauth_refresh", "account_oauth_access",
])
def test_restore_refuses_changed_account_security_state(tmp_path, table):
    source, target = tmp_path / "backup.sqlite3", tmp_path / "fleet.sqlite3"
    _database(target, "keep-current")
    with closing(sqlite3.connect(target)) as db, db:
        db.execute(f'CREATE TABLE "{table}" (state TEXT)')
        db.execute(f'INSERT INTO "{table}" VALUES (?)', ("before-revocation",))
    backup_database(target, source)
    with closing(sqlite3.connect(target)) as db, db:
        db.execute(f'UPDATE "{table}" SET state=?', ("after-revocation",))
    before = target.read_bytes()

    with pytest.raises(DatabaseError, match="Account security state"):
        restore_database(source, target, replace=True, assume_stopped=True)

    assert target.read_bytes() == before
    assert _value(target) == "keep-current"
    assert not list(tmp_path.glob("*.pre-restore-*.sqlite3"))


@pytest.mark.parametrize("state", ["missing", "corrupt", "legacy", "schema", "trigger", "duplicates"])
def test_account_restore_requires_matching_readable_current_state(tmp_path, state):
    source, target = tmp_path / "backup.sqlite3", tmp_path / "fleet.sqlite3"
    _database(source, "older-operational-data")
    with closing(sqlite3.connect(source)) as db, db:
        db.execute("CREATE TABLE rosy_accounts (state TEXT)")
        db.executemany("INSERT INTO rosy_accounts VALUES (?)", [("a",), ("a",), ("b",)])
    if state == "corrupt":
        target.write_bytes(b"unreadable-current-state")
    elif state == "legacy":
        _database(target, "keep-current")
    elif state != "missing":
        backup_database(source, target)
        with closing(sqlite3.connect(target)) as db, db:
            if state == "schema":
                db.execute("ALTER TABLE rosy_accounts ADD COLUMN revision INTEGER")
            elif state == "trigger":
                db.execute("CREATE TRIGGER keep_auth AFTER DELETE ON rosy_accounts BEGIN SELECT 1; END")
            else:
                db.execute("DELETE FROM rosy_accounts")
                db.executemany("INSERT INTO rosy_accounts VALUES (?)", [("a",), ("b",), ("b",)])
    before = target.read_bytes() if target.exists() else None

    with pytest.raises(DatabaseError, match="Account security state"):
        restore_database(source, target, replace=True, assume_stopped=True)

    assert (target.read_bytes() if target.exists() else None) == before
    assert not list(tmp_path.glob("*.pre-restore-*.sqlite3"))


def test_restore_refuses_legacy_backup_over_current_account_state(tmp_path):
    source, target = tmp_path / "backup.sqlite3", tmp_path / "fleet.sqlite3"
    _database(source, "legacy")
    backup_database(source, target)
    with closing(sqlite3.connect(target)) as db, db:
        db.execute("CREATE TABLE rosy_account_authority (site_id TEXT)")
        db.execute("INSERT INTO rosy_account_authority VALUES ('test-site')")
    with pytest.raises(DatabaseError, match="Account security state"):
        restore_database(source, target, replace=True, assume_stopped=True)
    assert _value(target) == "legacy"


def test_restore_allows_operational_recovery_with_identical_account_state(tmp_path):
    source, target = tmp_path / "backup.sqlite3", tmp_path / "fleet.sqlite3"
    _database(source, "restored-operational-data")
    with closing(sqlite3.connect(source)) as db, db:
        db.execute("CREATE TABLE rosy_accounts (state TEXT)")
        db.executemany("INSERT INTO rosy_accounts VALUES (?)", [("b",), ("a",)])
    backup_database(source, target)
    with closing(sqlite3.connect(target)) as db, db:
        db.execute("UPDATE records SET value='current-operational-data'")
        db.execute("DELETE FROM rosy_accounts")
        db.executemany("INSERT INTO rosy_accounts VALUES (?)", [("a",), ("b",)])

    result = restore_database(source, target, replace=True, assume_stopped=True)

    assert _value(target) == "restored-operational-data"
    assert _value(result.rollback_path) == "current-operational-data"
    with closing(sqlite3.connect(target)) as db:
        assert db.execute("SELECT state FROM rosy_accounts ORDER BY state").fetchall() == [("a",), ("b",)]


def test_account_restore_observes_committed_wal_changes(tmp_path):
    source, target = tmp_path / "backup.sqlite3", tmp_path / "fleet.sqlite3"
    _database(target, "keep-current")
    with closing(sqlite3.connect(target)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE account_oauth_refresh (spent INTEGER)")
        db.execute("INSERT INTO account_oauth_refresh VALUES (0)")
        db.commit()
        backup_database(target, source)
        db.execute("UPDATE account_oauth_refresh SET spent=1")
        db.commit()
        assert Path(str(target) + "-wal").exists()
        with pytest.raises(DatabaseError, match="Account security state"):
            restore_database(source, target, replace=True, assume_stopped=True)
        assert db.execute("SELECT spent FROM account_oauth_refresh").fetchone() == (1,)


def test_restore_does_not_leave_old_wal_sidecars_on_restored_target(tmp_path):
    source = tmp_path / "restore.sqlite3"
    target = tmp_path / "fleet.sqlite3"
    _database(source, "restored")
    _database(target, "before-restore")
    (tmp_path / "fleet.sqlite3-wal").write_bytes(b"stale-wal-sidecar")
    (tmp_path / "fleet.sqlite3-shm").write_bytes(b"stale-shm-sidecar")

    result = restore_database(source, target, replace=True, assume_stopped=True)

    assert _value(target) == "restored"
    assert result.rollback_path is not None
    assert not Path(str(target) + "-wal").exists()
    assert not Path(str(target) + "-shm").exists()


def test_restore_rolls_back_if_atomic_install_fails(tmp_path, monkeypatch):
    source = tmp_path / "restore.sqlite3"
    target = tmp_path / "fleet.sqlite3"
    _database(source, "restored")
    _database(target, "before-restore")
    real_replace = site_db.os.replace
    failed_once = False

    def fail_new_database_install(source_path, destination_path):
        nonlocal failed_once
        if Path(destination_path) == target and str(source_path).endswith(".tmp") and not failed_once:
            failed_once = True
            raise OSError("simulated atomic install failure")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(site_db.os, "replace", fail_new_database_install)
    with pytest.raises(OSError, match="simulated atomic install failure"):
        restore_database(source, target, replace=True, assume_stopped=True)

    assert failed_once
    assert _value(target) == "before-restore"


def test_rekey_reseals_enrolled_robot_credentials_offline(tmp_path):
    """D-361 4: key rotation is an offline command over the stopped Fleet database."""
    import base64

    from fleet.server.enrollment_store import EnrollmentStore, seal, unseal

    old_key, new_key = bytes(range(32)), bytes(range(1, 33))
    old_file, new_file = tmp_path / "old.key", tmp_path / "new.key"
    old_file.write_bytes(base64.b64encode(old_key) + b"\n")
    new_file.write_bytes(base64.b64encode(new_key) + b"\n")
    database = tmp_path / "fleet.sqlite3"
    store = EnrollmentStore(database)
    secret = "tok-" + "rekey-1"
    store.insert({"robot_id": "rosy_09", "hostname": "h", "address": "192.168.1.2:8080",
                  "token_id": "t1", "role": "operator", "source": "pair-physical",
                  "principal_id": "alice", "state": "active"},
                 seal(old_key, secret, slot="rest", robot_id="rosy_09", token_id="t1"))

    with pytest.raises(SystemExit):
        site_db.main(["rekey", "--path", str(database), "--old-key-file", str(old_file),
                      "--new-key-file", str(new_file)])
    assert site_db.main(["rekey", "--path", str(database), "--old-key-file", str(old_file),
                         "--new-key-file", str(new_file), "--assume-stopped"]) == 0
    assert unseal(new_key, store.ciphertext("rosy_09"), slot="rest", robot_id="rosy_09",
                  token_id="t1") == secret


def test_rekey_refuses_a_missing_database_and_an_unchanged_key(tmp_path):
    import base64

    key_file = tmp_path / "same.key"
    key_file.write_bytes(base64.b64encode(bytes(range(32))) + b"\n")
    missing = tmp_path / "absent.sqlite3"
    with pytest.raises(SystemExit):
        site_db.main(["rekey", "--path", str(missing), "--old-key-file", str(key_file),
                      "--new-key-file", str(key_file), "--assume-stopped"])
    assert not missing.exists()
    from fleet.server.enrollment_store import EnrollmentStore

    database = tmp_path / "fleet.sqlite3"
    EnrollmentStore(database)
    with pytest.raises(SystemExit):
        site_db.main(["rekey", "--path", str(database), "--old-key-file", str(key_file),
                      "--new-key-file", str(key_file), "--assume-stopped"])


def _retention_database(path: Path) -> None:
    """task 원장과 감사 표를 과거·최근 행과 함께 만든다(2026-10-28 자원 경계 시험)."""
    from datetime import datetime, timedelta, timezone

    def iso(days_ago: float) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(
            timespec="milliseconds")

    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE fleet_tasks (
            task_id TEXT PRIMARY KEY, robot_id TEXT NOT NULL, task_type TEXT NOT NULL,
            source TEXT NOT NULL, actor_id TEXT NOT NULL, request_key TEXT NOT NULL,
            status TEXT NOT NULL, reason TEXT, request_json TEXT NOT NULL,
            evidence_json TEXT, receipt_json TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE fleet_task_history (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
            status TEXT NOT NULL, source TEXT NOT NULL, actor_id TEXT NOT NULL,
            reason TEXT, created_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE rosy_account_audit (
            actor_account_id TEXT NOT NULL, target_account_id TEXT NOT NULL,
            operation TEXT NOT NULL, previous_revision INTEGER NOT NULL,
            next_revision INTEGER NOT NULL, created_at REAL NOT NULL)""")
        db.execute("""CREATE TABLE device_pairing_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
            device_kind TEXT NOT NULL, action TEXT NOT NULL, outcome TEXT NOT NULL,
            principal_id TEXT)""")
        db.execute("""CREATE TABLE core_event_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT, robot_id TEXT NOT NULL,
            event_id TEXT NOT NULL, seq INTEGER NOT NULL, event_type TEXT NOT NULL,
            received_at TEXT NOT NULL, payload_json TEXT NOT NULL,
            UNIQUE(robot_id, event_id))""")
        rows = [  # (task_id, status, days_ago)
            ("old-done", "COMPLETED", 40.0), ("old-failed", "FAILED", 60.0),
            ("old-hold", "HOLD", 40.0),            # HOLD는 종료 상태가 아니다 — 남는다
            ("new-done", "COMPLETED", 2.0),
            ("old-running", "RUNNING", 40.0),      # 종료 상태가 아니다 — 남는다
        ]
        for task_id, status, days_ago in rows:
            stamp = iso(days_ago)
            db.execute("INSERT INTO fleet_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (task_id, "rosy_01", "delivery", "console", "op", task_id,
                        status, None, "{}", None, None, stamp, stamp))
            db.execute("INSERT INTO fleet_task_history (task_id,status,source,actor_id,reason,"
                       "created_at) VALUES (?,?,?,?,?,?)",
                       (task_id, status, "console", "op", None, stamp))
        db.execute("INSERT INTO rosy_account_audit VALUES ('a','a','create',0,1,?)", (0.0,))
        db.execute("INSERT INTO rosy_account_audit VALUES ('a','a','rotate',1,2,?)",
                   (datetime.now(timezone.utc).timestamp() - 3 * 86400.0,))
        db.execute("INSERT INTO device_pairing_audit (at,device_kind,action,outcome,principal_id)"
                   " VALUES (?,?,?,?,?)", (0.0, "overhead-camera", "pair", "ok", "op"))
        for event_id, days_ago in (("event-old-1", 100.0), ("event-old-2", 95.0),
                                   ("event-new", 1.0)):   # observe/events.py received_at 모양
            db.execute("INSERT INTO core_event_audit (robot_id,event_id,seq,event_type,"
                       "received_at,payload_json) VALUES (?,?,?,?,?,?)",
                       ("rosy_01", event_id, 1, "nav.completed", iso(days_ago), "{}"))


def test_prune_ledger_deletes_only_terminal_task_history_and_expired_audit(tmp_path):
    database = tmp_path / "fleet.sqlite3"
    _retention_database(database)

    removed = prune_ledger(database)

    with closing(sqlite3.connect(database)) as db:
        kept_tasks = {row[0] for row in db.execute("SELECT task_id FROM fleet_task_history")}
        kept_rows = {row[0] for row in db.execute("SELECT task_id FROM fleet_tasks")}
        kept_audit = db.execute("SELECT COUNT(*) FROM rosy_account_audit").fetchone()[0]
        kept_pairing = db.execute("SELECT COUNT(*) FROM device_pairing_audit").fetchone()[0]
        kept_events = db.execute("SELECT COUNT(*) FROM core_event_audit").fetchone()[0]
    assert removed == {"fleet_task_history": 2, "fleet_tasks": 0, "rosy_account_audit": 0,
                       "device_pairing_audit": 1, "core_event_audit": 2}
    assert kept_tasks == {"old-hold", "new-done", "old-running"}
    assert kept_rows == {"old-done", "old-failed", "old-hold", "new-done", "old-running"}
    assert kept_audit == 2 and kept_pairing == 0
    assert kept_events == 1                                        # 최근 감사 사건은 남는다


def test_prune_ledger_zero_retention_disables_and_missing_tables_are_skipped(tmp_path):
    database = tmp_path / "fleet.sqlite3"
    _retention_database(database)

    disabled = prune_ledger(database, history_days=0, audit_days=0)
    assert disabled == {"fleet_task_history": 0, "fleet_tasks": 0, "rosy_account_audit": 0,
                        "device_pairing_audit": 0, "core_event_audit": 0}
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT COUNT(*) FROM fleet_task_history").fetchone()[0] == 5
        assert db.execute("SELECT COUNT(*) FROM fleet_tasks").fetchone()[0] == 5

    empty = tmp_path / "empty.sqlite3"
    with closing(sqlite3.connect(empty)) as db:   # 표가 하나도 없는 오래된 스키마
        db.execute("CREATE TABLE marker (v INT)")
    assert prune_ledger(empty) == {"fleet_task_history": 0, "fleet_tasks": 0,
                                   "rosy_account_audit": 0, "device_pairing_audit": 0,
                                   "core_event_audit": 0}


def test_prune_ledger_preserves_task_identity_after_an_earlier_history_prune(tmp_path):
    """History expiry must not remove the task identity used for replay admission."""
    database = tmp_path / "fleet.sqlite3"
    _retention_database(database)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("DELETE FROM fleet_task_history")            # 과거 prune이 지운 상태 재현

    removed = prune_ledger(database)

    with closing(sqlite3.connect(database)) as db:
        kept_rows = {row[0] for row in db.execute("SELECT task_id FROM fleet_tasks")}
    assert removed["fleet_tasks"] == 0
    assert kept_rows == {"old-done", "old-failed", "old-hold", "new-done", "old-running"}


def test_backup_command_prunes_the_live_ledger_after_writing_the_backup(tmp_path, capsys):
    database = tmp_path / "fleet.sqlite3"
    _retention_database(database)

    code = site_db.main(["backup", "--source", str(database),
                         "--destination", str(tmp_path / "b.sqlite3"),
                         "--prune-history", "30", "--prune-audit", "90"])

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["pruned_ledger"] == {"fleet_task_history": 2, "fleet_tasks": 0,
                                       "rosy_account_audit": 0, "device_pairing_audit": 1,
                                       "core_event_audit": 2}
    assert "checkpoint" in report and report["checkpoint"]["wal_checkpoint"] is not None
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT COUNT(*) FROM fleet_task_history").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM fleet_tasks").fetchone()[0] == 5


def test_retention_preserves_same_principal_request_replay(tmp_path):
    from fleet.server.task_store import FleetTaskStore

    database = tmp_path / "fleet.sqlite3"
    store = FleetTaskStore(database)
    request = dict(robot_id="rosy_01", task_type="delivery", source="console",
                   actor_id="op", request_key="retry-key", request={"destination": "dock"},
                   evidence=None)
    original = store.create_task(task_id="original", **request)
    assert original["created"] is True
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE fleet_tasks SET status='COMPLETED', updated_at='2000-01-01T00:00:00.000+00:00'")

    prune_ledger(database)

    replay = store.create_task(task_id="must-not-be-created", **request)
    assert replay["created"] is False
    assert replay["task"]["task_id"] == "original"
    assert replay["task"]["status"] == "COMPLETED"
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT COUNT(*) FROM fleet_tasks").fetchone()[0] == 1


def test_fresh_backup_remains_restorable_after_account_audit_retention(tmp_path, capsys):
    database, backup = tmp_path / "fleet.sqlite3", tmp_path / "backup.sqlite3"
    _retention_database(database)
    assert site_db.main(["backup", "--source", str(database),
                         "--destination", str(backup)]) == 0
    capsys.readouterr()

    restored = restore_database(backup, database, replace=True, assume_stopped=True)

    assert restored.integrity == "ok"
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT COUNT(*) FROM rosy_account_audit").fetchone()[0] == 2
