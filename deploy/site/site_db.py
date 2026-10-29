"""SQLite online backup and guarded restore for the site Fleet data volume."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import zip_longest
from pathlib import Path

DEFAULT_DATABASE = Path("/var/lib/rosy/fleet.sqlite3")
BACKUP_PREFIX = "fleet-backup-"


def _prune_backups(directory: Path, keep: int) -> list[str]:
    """Keep the newest ``keep`` timestamped backups, return what was removed."""
    backups = sorted(path for path in directory.glob(f"{BACKUP_PREFIX}*.sqlite3")
                     if path.is_file())
    removed = [path.name for path in backups[:-keep]]
    for stale in backups[:-keep]:
        stale.unlink(missing_ok=True)
    return removed


#: 2026-10-28 자원 경계: 무한히 쌓이던 원장 행의 보존 기간(일).
DEFAULT_HISTORY_RETENTION_DAYS = 30   # 종료 작업의 fleet_task_history 행
DEFAULT_AUDIT_RETENTION_DAYS = 90     # device_pairing_audit / core_event_audit


def prune_ledger(source: Path | str, *, history_days: int = DEFAULT_HISTORY_RETENTION_DAYS,
                 audit_days: int = DEFAULT_AUDIT_RETENTION_DAYS) -> dict[str, int]:
    """Delete terminal-task history older than
    ``history_days`` and pairing/CORE audit rows older than ``audit_days``. Runs on the live
    volume after a fresh backup; tables missing from an older schema are skipped."""
    path = Path(source)
    if history_days < 0 or audit_days < 0:
        raise DatabaseError("retention days must not be negative")
    if not path.is_file():
        raise DatabaseError("source database is missing")
    # fleet_tasks.updated_at / fleet_task_history.created_at are `_now()` ISO strings
    # (task_store_types._now); core_event_audit.received_at uses the same shape. The
    # same format keeps the string comparison exact. A retention of 0 days skips that
    # group entirely (the CLI's "disable" value).
    history_cutoff = (datetime.now(timezone.utc)
                      - timedelta(days=history_days)).isoformat(timespec="milliseconds") \
        if history_days > 0 else None
    audit_cutoff = time.time() - audit_days * 86400.0 if audit_days > 0 else None
    audit_cutoff_iso = (datetime.now(timezone.utc)
                        - timedelta(days=audit_days)).isoformat(timespec="milliseconds") \
        if audit_days > 0 else None
    removed = {"fleet_task_history": 0, "fleet_tasks": 0, "rosy_account_audit": 0,
               "device_pairing_audit": 0, "core_event_audit": 0}
    try:
        with closing(sqlite3.connect(path, timeout=30.0)) as db:
            tables = {row[0] for row in
                      db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            db.execute("BEGIN IMMEDIATE")
            try:
                if history_cutoff is not None and {"fleet_task_history", "fleet_tasks"} <= tables:
                    removed["fleet_task_history"] = db.execute(
                        "DELETE FROM fleet_task_history WHERE task_id IN ("
                        " SELECT task_id FROM fleet_tasks WHERE status IN"
                        " ('COMPLETED','FAILED','CANCELED','EXPIRED')"
                        " AND updated_at < ?)", (history_cutoff,)).rowcount
                    # Task rows retain request-key identity and the original replay response.
                # Account audit is part of the exact security-state restore guard.
                if audit_cutoff is not None and "device_pairing_audit" in tables:
                    removed["device_pairing_audit"] = db.execute(
                        "DELETE FROM device_pairing_audit WHERE at < ?",
                        (audit_cutoff,)).rowcount
                # Durable CORE event audit (observe/events.py). Dedup survives restarts
                # on the remaining window; a replay older than the retention re-inserts
                # as new, which is far beyond any agent replay horizon.
                if audit_cutoff_iso is not None and "core_event_audit" in tables:
                    removed["core_event_audit"] = db.execute(
                        "DELETE FROM core_event_audit WHERE received_at < ?",
                        (audit_cutoff_iso,)).rowcount
                db.commit()
            except sqlite3.Error:
                db.rollback()
                raise
    except sqlite3.Error as exc:
        raise DatabaseError("ledger retention prune failed") from exc
    return removed


def checkpoint_wal(source: Path | str) -> dict:
    """Best-effort ``wal_checkpoint(TRUNCATE)`` so pages freed by the prune return to
    the OS file. Never raises: a busy live writer leaves the WAL in place and the
    result row reports it as (busy=1, log, checkpointed)."""
    path = Path(source)
    if not path.is_file():
        raise DatabaseError("source database is missing")
    try:
        with closing(sqlite3.connect(path, timeout=30.0)) as db:
            row = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        return {"wal_checkpoint": [int(value) for value in row]} if row else {"wal_checkpoint": None}
    except sqlite3.Error:
        return {"wal_checkpoint": None}


class DatabaseError(RuntimeError):
    """A backup or restore could not be completed safely."""


@dataclass(frozen=True)
class DatabaseResult:
    path: Path
    integrity: str
    sha256: str
    rollback_path: Path | None = None


def _database_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


def verify_database(path: Path | str) -> str:
    database = Path(path)
    if not database.is_file() or database.stat().st_size == 0:
        raise DatabaseError("database is missing or empty")
    try:
        with closing(sqlite3.connect(_database_uri(database), uri=True, timeout=5.0)) as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError("database integrity check could not read the file") from exc
    if rows != [("ok",)]:
        raise DatabaseError("database integrity check failed")
    return "ok"


def _copy_database(source: Path, destination: Path) -> None:
    try:
        with (closing(sqlite3.connect(source, timeout=10.0)) as source_db,
              closing(sqlite3.connect(destination, timeout=10.0)) as destination_db):
            source_db.backup(destination_db, pages=256, sleep=0.05)
            journal_mode = destination_db.execute("PRAGMA journal_mode=DELETE").fetchone()
            if journal_mode is None or journal_mode[0].lower() != "delete":
                raise sqlite3.DatabaseError("backup could not be made self-contained")
    except sqlite3.Error as exc:
        raise DatabaseError("SQLite online backup failed") from exc


def _temporary_path(parent: Path, name: str) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=parent)
    os.close(descriptor)
    path = Path(raw_path)
    path.unlink()
    return path


def _private_mode(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_database(source: Path | str, destination: Path | str) -> DatabaseResult:
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if source_path == destination_path:
        raise DatabaseError("backup source and destination must differ")
    if not source_path.is_file():
        raise DatabaseError("source database is missing")
    verify_database(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        raise DatabaseError("backup destination already exists")

    temporary = _temporary_path(destination_path.parent, destination_path.name)
    try:
        _copy_database(source_path, temporary)
        integrity = verify_database(temporary)
        _private_mode(temporary)
        try:
            # A same-directory hard link gives an atomic no-overwrite publish.
            os.link(temporary, destination_path)
        except FileExistsError as exc:
            raise DatabaseError("backup destination already exists") from exc
        temporary.unlink()
        return DatabaseResult(destination_path, integrity, _sha256(destination_path))
    finally:
        temporary.unlink(missing_ok=True)


def _rollback_name(target: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return target.with_name(f"{target.name}.pre-restore-{stamp}.sqlite3")


def _guard_account_restore(source: Path, destination: Path) -> None:
    """A stale whole-DB restore must not undo credential changes or token consumption."""
    def schema(db):
        return [row for row in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        ) if row[2].startswith(("rosy_account", "account_oauth_", "fleet_console_"))]

    try:
        with closing(sqlite3.connect(_database_uri(source), uri=True, timeout=5.0)) as saved:
            saved.execute("BEGIN")
            saved_schema = schema(saved)
            if not destination.exists():
                if saved_schema:
                    raise DatabaseError("Account security state needs a readable current database")
                return
            with closing(sqlite3.connect(_database_uri(destination), uri=True, timeout=5.0)) as current:
                current.execute("BEGIN")
                if saved_schema != schema(current):
                    raise DatabaseError("Account security state schema differs; restore refused")
                for kind, name, _, _ in saved_schema:
                    if kind != "table":
                        continue
                    table = '"' + name.replace('"', '""') + '"'
                    columns = len(saved.execute(f"SELECT * FROM {table} LIMIT 0").description)
                    query = f"SELECT * FROM {table} ORDER BY " + ",".join(
                        str(index) for index in range(1, columns + 1))
                    if any(left != right for left, right in zip_longest(
                            saved.execute(query), current.execute(query))):
                        raise DatabaseError("Account security state differs; restore refused")
    except sqlite3.Error as exc:
        raise DatabaseError("Account security state could not be verified") from exc


def restore_database(
    source: Path | str,
    destination: Path | str = DEFAULT_DATABASE,
    *,
    replace: bool = False,
    assume_stopped: bool = False,
) -> DatabaseResult:
    if not assume_stopped:
        raise DatabaseError("restore requires an explicit stopped-service assertion")
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if source_path == destination_path:
        raise DatabaseError("restore source and destination must differ")
    verify_database(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists() and not replace:
        raise DatabaseError("restore destination exists; pass replace after preserving it")
    sidecars = [Path(str(destination_path) + suffix) for suffix in ("-wal", "-shm")]
    if not destination_path.exists() and any(path.exists() for path in sidecars):
        raise DatabaseError("restore destination has SQLite sidecars without a database")

    temporary = _temporary_path(destination_path.parent, destination_path.name)
    rollback: Path | None = None
    archived_sidecars: list[tuple[Path, Path]] = []
    old_database_removed = False
    try:
        _copy_database(source_path, temporary)
        verify_database(temporary)
        _private_mode(temporary)
        _guard_account_restore(temporary, destination_path)
        if destination_path.exists():
            rollback = _rollback_name(destination_path)
            backup_database(destination_path, rollback)
            for sidecar in sidecars:
                if sidecar.exists():
                    archived = Path(str(rollback) + sidecar.name[len(destination_path.name):])
                    os.replace(sidecar, archived)
                    archived_sidecars.append((sidecar, archived))
            destination_path.unlink()
            old_database_removed = True
        os.replace(temporary, destination_path)
        _private_mode(destination_path)
        integrity = verify_database(destination_path)
        return DatabaseResult(destination_path, integrity, _sha256(destination_path), rollback)
    except (DatabaseError, OSError):
        if rollback is not None and rollback.is_file() and old_database_removed:
            if destination_path.exists():
                destination_path.unlink()
            recovery = _temporary_path(destination_path.parent, destination_path.name)
            try:
                _copy_database(rollback, recovery)
                os.replace(recovery, destination_path)
            finally:
                recovery.unlink(missing_ok=True)
        for original, archived in archived_sidecars:
            if archived.exists():
                os.replace(archived, original)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def _rekey(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """D-361 4: reseal every enrolled robot token in one transaction, Fleet stopped."""
    if not args.assume_stopped:
        parser.error("stop the Fleet service first, then pass --assume-stopped")
    from fleet.server.enrollment_store import CredentialKeyError, SealError, load_key_file, rekey

    if not Path(args.path).is_file():
        parser.error(f"database {args.path} does not exist")
    try:
        old_key, new_key = load_key_file(args.old_key_file), load_key_file(args.new_key_file)
        if old_key == new_key:
            parser.error("the new key must differ from the old key")
        count = rekey(args.path, old_key, new_key)
    except (CredentialKeyError, SealError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps({"path": str(args.path), "resealed": count}))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="create a consistent SQLite online backup")
    backup.add_argument("--source", type=Path, default=DEFAULT_DATABASE)
    backup.add_argument("--destination", type=Path,
                        help="explicit backup file (one-shot use)")
    backup.add_argument("--dest-dir", type=Path,
                        help="timestamped backup directory (timer use); prunes old backups")
    backup.add_argument("--prune", type=int, default=14,
                        help="backups to keep when --dest-dir is used (default 14)")
    backup.add_argument("--prune-history", type=int, default=DEFAULT_HISTORY_RETENTION_DAYS,
                        metavar="DAYS",
                        help="delete terminal-task history rows older than DAYS after the "
                             "backup (default 30; 0 disables)")
    backup.add_argument("--prune-audit", type=int, default=DEFAULT_AUDIT_RETENTION_DAYS,
                        metavar="DAYS",
                        help="delete pairing/CORE event audit rows older than DAYS after the "
                             "backup (default 90; 0 disables)")
    verify = commands.add_parser("verify", help="run SQLite integrity_check")
    verify.add_argument("--path", type=Path, required=True)
    restore = commands.add_parser("restore", help="restore after stopping the site services")
    restore.add_argument("--source", type=Path, required=True)
    restore.add_argument("--destination", type=Path, default=DEFAULT_DATABASE)
    restore.add_argument("--replace", action="store_true")
    restore.add_argument("--assume-stopped", action="store_true")
    rekey = commands.add_parser("rekey", help="reseal enrolled robot credentials (Fleet stopped)")
    rekey.add_argument("--path", type=Path, default=DEFAULT_DATABASE)
    rekey.add_argument("--old-key-file", type=Path, required=True)
    rekey.add_argument("--new-key-file", type=Path, required=True)
    rekey.add_argument("--assume-stopped", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "rekey":
        return _rekey(parser, args)
    try:
        pruned = []
        pruned_ledger = None
        checkpointed = None
        if args.command == "backup":
            if bool(args.destination) == bool(args.dest_dir):
                parser.error("pass exactly one of --destination or --dest-dir")
            if args.dest_dir is not None:
                if args.prune < 1:
                    parser.error("--prune must keep at least one backup")
                args.dest_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                args.destination = args.dest_dir / f"{BACKUP_PREFIX}{timestamp}.sqlite3"
            result = backup_database(args.source, args.destination)
            if args.dest_dir is not None:
                pruned = _prune_backups(args.dest_dir, args.prune)
            # Retention runs only after the backup file exists (2026-10-28 resource bounds).
            pruned_ledger = prune_ledger(args.source, history_days=args.prune_history,
                                         audit_days=args.prune_audit)
            checkpointed = checkpoint_wal(args.source)
        elif args.command == "verify":
            print(json.dumps({"path": str(args.path), "integrity": verify_database(args.path)}))
            return 0
        else:
            result = restore_database(args.source, args.destination,
                                      replace=args.replace, assume_stopped=args.assume_stopped)
    except (DatabaseError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "path": str(result.path),
        "integrity": result.integrity,
        "sha256": result.sha256,
        "rollback_path": str(result.rollback_path) if result.rollback_path else None,
        "pruned": pruned,
        "pruned_ledger": pruned_ledger,
        "checkpoint": checkpointed,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
