from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from deploy.site import site_db
from deploy.site.site_db import (
    DatabaseError,
    backup_database,
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
