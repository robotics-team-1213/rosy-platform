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
from pathlib import Path

DEFAULT_DATABASE = Path("/var/lib/rosy/fleet.sqlite3")
DEFAULT_BACKUP_DIR = Path("/var/backups/rosy-site")
BACKUP_PREFIX = "fleet-backup-"


def _prune_backups(directory: Path, keep: int) -> list[str]:
    """Keep the newest ``keep`` timestamped backups, return what was removed."""
    backups = sorted(path for path in directory.glob(f"{BACKUP_PREFIX}*.sqlite3") if path.is_file())
    removed = [path.name for path in backups[:-keep]]
    for stale in backups[:-keep]:
        stale.unlink(missing_ok=True)
    return removed


def check_backups(directory: Path, *, max_age_hours: int) -> dict:
    """Newest backup must exist, be fresh, and pass integrity_check."""
    backups = sorted(path for path in directory.glob(f"{BACKUP_PREFIX}*.sqlite3") if path.is_file())
    if not backups:
        raise DatabaseError(f"no {BACKUP_PREFIX}*.sqlite3 backups in {directory}")
    if max_age_hours < 0:
        raise DatabaseError("max age hours must not be negative")
    newest = backups[-1]
    age_hours = (time.time() - newest.stat().st_mtime) / 3600.0
    if age_hours > max_age_hours:
        raise DatabaseError(f"newest backup {newest.name} is {age_hours:.1f} h old, over {max_age_hours} h")
    return {"newest": str(newest), "age_hours": round(age_hours, 3), "integrity": verify_database(newest)}


DEFAULT_HISTORY_RETENTION_DAYS = 30
DEFAULT_AUDIT_RETENTION_DAYS = 90
DEFAULT_API_AUDIT_RETENTION_DAYS = 90
DEFAULT_SIGHTING_RETENTION_DAYS = 90


def prune_ledger(source: Path | str, *, history_days: int = DEFAULT_HISTORY_RETENTION_DAYS,
                 audit_days: int = DEFAULT_AUDIT_RETENTION_DAYS,
                 api_audit_days: int = DEFAULT_API_AUDIT_RETENTION_DAYS,
                 sighting_days: int = DEFAULT_SIGHTING_RETENTION_DAYS) -> dict[str, int]:
    """Delete terminal-task history and audit rows past their retention windows on the live volume."""
    path = Path(source)
    if history_days < 0 or audit_days < 0 or api_audit_days < 0 or sighting_days < 0:
        raise DatabaseError("retention days must not be negative")
    if not path.is_file():
        raise DatabaseError("source database is missing")
    with closing(sqlite3.connect(path)) as settings_db:
        if settings_db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fleet_db_settings'").fetchone():
            settings = dict(settings_db.execute("SELECT key, value_int FROM fleet_db_settings"))
            if history_days == DEFAULT_HISTORY_RETENTION_DAYS:
                history_days = settings.get("history_retention_days", history_days)
            if audit_days == DEFAULT_AUDIT_RETENTION_DAYS:
                audit_days = settings.get("audit_retention_days", audit_days)
            if api_audit_days == DEFAULT_API_AUDIT_RETENTION_DAYS:
                api_audit_days = settings.get("api_audit_retention_days", api_audit_days)
            if sighting_days == DEFAULT_SIGHTING_RETENTION_DAYS:
                sighting_days = settings.get("sighting_retention_days", sighting_days)
    iso_cutoff = lambda d: (datetime.now(timezone.utc) - timedelta(days=d)).isoformat(timespec="milliseconds") if d > 0 else None
    history_cutoff = iso_cutoff(history_days)
    audit_cutoff = time.time() - audit_days * 86400.0 if audit_days > 0 else None
    audit_cutoff_iso = iso_cutoff(audit_days)
    api_audit_cutoff_iso = iso_cutoff(api_audit_days)
    sighting_cutoff = time.time() - sighting_days * 86400.0 if sighting_days > 0 else None
    removed = {"fleet_task_history": 0, "fleet_tasks": 0, "rosy_account_audit": 0,
               "device_pairing_audit": 0, "core_event_audit": 0, "fleet_api_audit": 0, "sighting_audit": 0}
    try:
        with closing(sqlite3.connect(path, timeout=30.0)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            db.execute("BEGIN IMMEDIATE")
            try:
                if history_cutoff is not None and {"fleet_task_history", "fleet_tasks"} <= tables:
                    removed["fleet_task_history"] = db.execute(
                        "DELETE FROM fleet_task_history WHERE task_id IN (SELECT task_id FROM fleet_tasks "
                        "WHERE status IN ('COMPLETED','FAILED','CANCELED','EXPIRED') AND updated_at < ?)",
                        (history_cutoff,)).rowcount
                if audit_cutoff is not None and "device_pairing_audit" in tables:
                    removed["device_pairing_audit"] = db.execute(
                        "DELETE FROM device_pairing_audit WHERE at < ?", (audit_cutoff,)).rowcount
                if audit_cutoff_iso is not None and "core_event_audit" in tables:
                    removed["core_event_audit"] = db.execute(
                        "DELETE FROM core_event_audit WHERE received_at < ?", (audit_cutoff_iso,)).rowcount
                if api_audit_cutoff_iso is not None and "fleet_api_audit" in tables:
                    watermark = db.execute("SELECT last_rowid FROM fleet_audit_flush WHERE kind='fleet_api_audit'").fetchone() \
                        if "fleet_audit_flush" in tables else None
                    removed["fleet_api_audit"] = db.execute(
                        "DELETE FROM fleet_api_audit WHERE created_at < ?" + (" AND rowid <= ?" if watermark else ""),
                        (api_audit_cutoff_iso, int(watermark[0])) if watermark else (api_audit_cutoff_iso,)).rowcount
                if sighting_cutoff is not None and "sighting_audit" in tables:
                    removed["sighting_audit"] = db.execute(
                        "DELETE FROM sighting_audit WHERE received_at < ?", (sighting_cutoff,)).rowcount
                db.commit()
            except sqlite3.Error:
                db.rollback()
                raise
    except sqlite3.Error as exc:
        raise DatabaseError("ledger retention prune failed") from exc
    return removed


def checkpoint_wal(source: Path | str) -> dict:
    """Best-effort ``wal_checkpoint(TRUNCATE)`` so pages freed by the prune return to the OS file."""
    path = Path(source)
    if not path.is_file():
        raise DatabaseError("source database is missing")
    try:
        with closing(sqlite3.connect(path, timeout=30.0)) as db:
            row = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        return {"wal_checkpoint": [int(value) for value in row]} if row else {"wal_checkpoint": None}
    except sqlite3.Error:
        return {"wal_checkpoint": None}


def vacuum_database(path: Path | str) -> dict:
    """Rewrite ``path`` in place with VACUUM so pages freed by the prune return to the OS."""
    target = Path(path)
    if not target.is_file():
        raise DatabaseError("database is missing")
    before = target.stat().st_size
    os.environ.setdefault("SQLITE_TMPDIR", str(target.parent))
    try:
        with closing(sqlite3.connect(target, timeout=30.0)) as db:
            db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            db.execute("VACUUM")
    except sqlite3.Error as exc:
        raise DatabaseError("vacuum failed") from exc
    return {"bytes_before": before, "bytes_after": target.stat().st_size}


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


def inspect_database(path: Path | str, *, quick_check: bool = True) -> dict:
    database = Path(path)
    if not database.is_file() or database.stat().st_size == 0:
        raise DatabaseError("database is missing or empty")
    try:
        with closing(sqlite3.connect(_database_uri(database), uri=True, timeout=5.0)) as conn:
            conn.execute("PRAGMA query_only=ON")
            if quick_check and conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise DatabaseError("database quick check failed")
            pragma = lambda name: conn.execute(f"PRAGMA {name}").fetchone()[0]
            tables = {}
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                        "AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                table = '"' + name.replace('"', '""') + '"'
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                stamp = next((column for column in ("updated_at", "created_at", "received_at",
                                                     "recorded_at", "at") if column in columns), None)
                newest = 'MAX("' + stamp + '")' if stamp else "NULL"
                count, latest = conn.execute(f"SELECT COUNT(*), {newest} FROM {table}").fetchone()
                tables[name] = {"rows": int(count), "newest_at": latest}
            wal = Path(f"{database}-wal")
            return {"path": str(database), "size_bytes": database.stat().st_size,
                    "wal_bytes": wal.stat().st_size if wal.is_file() else 0,
                    "journal_mode": str(pragma("journal_mode")).lower(),
                    "page_size": int(pragma("page_size")), "page_count": int(pragma("page_count")),
                    "freelist_count": int(pragma("freelist_count")),
                    "auto_vacuum": {0: "none", 1: "full", 2: "incremental"}.get(
                        int(pragma("auto_vacuum")), "unknown"),
                    "quick_check": "ok" if quick_check else None, "tables": tables,
                    "component_migrations": {row[0]: int(row[1]) for row in conn.execute(
                        "SELECT component, version FROM fleet_component_migrations ORDER BY component")}
                    if "fleet_component_migrations" in tables else {}}
    except sqlite3.Error as exc:
        raise DatabaseError("database inspection failed") from exc


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


def _guard_account_restore(source: Path, destination: Path) -> tuple[dict, bool]:
    """A stale whole-DB restore must not undo credential changes or token consumption."""
    def schema(db):
        return [row for row in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        ) if row[2].startswith(("rosy_account", "account_oauth_", "account_client", "fleet_console_"))]

    try:
        with closing(sqlite3.connect(_database_uri(source), uri=True, timeout=5.0)) as saved:
            saved.execute("BEGIN")
            saved_schema = schema(saved)
            if not destination.exists():
                if saved_schema:
                    raise DatabaseError("Account security state needs a readable current database")
                return {}, False
            with closing(sqlite3.connect(_database_uri(destination), uri=True, timeout=5.0)) as current:
                current.execute("BEGIN")
                if saved_schema != schema(current):
                    raise DatabaseError("Account security state schema differs; restore refused")
                audits, wipe_sessions = {}, False
                for kind, name, _, _ in saved_schema:
                    if kind != "table":
                        continue
                    table = '"' + name.replace('"', '""') + '"'
                    columns = len(saved.execute(f"SELECT * FROM {table} LIMIT 0").description)
                    query = f"SELECT * FROM {table} ORDER BY " + ",".join(
                        str(index) for index in range(1, columns + 1))
                    old, now = list(saved.execute(query)), list(current.execute(query))
                    if name in ("rosy_account_sessions", "fleet_console_sessions"):
                        if not {row[0] for row in old} <= {row[0] for row in now}:
                            raise DatabaseError("Account security state differs; restore refused")
                        wipe_sessions |= old != now
                        continue
                    if name in ("rosy_account_audit", "account_client_audit"):
                        old = list(saved.execute(f"SELECT rowid,* FROM {table} ORDER BY rowid"))
                        now = list(current.execute(f"SELECT rowid,* FROM {table} ORDER BY rowid"))
                        if now[:len(old)] != old:
                            raise DatabaseError("Account security state differs; restore refused")
                        audits[name] = now[len(old):]
                        continue
                    if name.startswith("account_oauth_"):
                        if not set(old) <= set(now):
                            raise DatabaseError("Account security state differs; restore refused")
                        continue
                    if old != now:
                        raise DatabaseError("Account security state differs; restore refused")
                return audits, wipe_sessions
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
        audits, wipe_sessions = _guard_account_restore(temporary, destination_path)
        if wipe_sessions or any(audits.values()):
            with closing(sqlite3.connect(temporary)) as restored, restored:
                if wipe_sessions:
                    for table in ("rosy_account_sessions", "fleet_console_sessions"):
                        if any(row[1] == table for row in restored.execute(
                                "SELECT type,name FROM sqlite_master WHERE type='table'")):
                            restored.execute(f"DELETE FROM {table}")
                for name, rows in audits.items():
                    if rows:
                        restored.executemany(f"INSERT INTO {name} (rowid," +
                                             ",".join('"' + column[1].replace('"', '""') + '"'
                                                      for column in restored.execute(f"PRAGMA table_info({name})")) +
                                             ") VALUES (" + ",".join("?" for _ in rows[0]) + ")", rows)
            verify_database(temporary)
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
    backup.add_argument("--destination", type=Path, help="explicit backup file (one-shot use)")
    backup.add_argument("--dest-dir", type=Path, help="timestamped backup directory (timer use); prunes old backups")
    backup.add_argument("--prune", type=int, default=14, help="backups to keep when --dest-dir is used (default 14)")
    for flag, default in (("--prune-history", DEFAULT_HISTORY_RETENTION_DAYS), ("--prune-audit", DEFAULT_AUDIT_RETENTION_DAYS),
                          ("--prune-api-audit", DEFAULT_API_AUDIT_RETENTION_DAYS), ("--prune-sightings", DEFAULT_SIGHTING_RETENTION_DAYS)):
        backup.add_argument(flag, type=int, default=default, metavar="DAYS")
    verify = commands.add_parser("verify", help="run SQLite integrity_check")
    verify.add_argument("--path", type=Path, required=True)
    inspect = commands.add_parser("inspect", help="read live SQLite database statistics")
    inspect.add_argument("--path", type=Path, default=DEFAULT_DATABASE)
    inspect.add_argument("--no-quick-check", action="store_true")
    inspect.add_argument("--json", action="store_true")
    compact = commands.add_parser("compact", help="VACUUM the database in place (quarterly, maintenance window)")
    compact.add_argument("--path", type=Path, default=DEFAULT_DATABASE)
    compact.add_argument("--assume-stopped", action="store_true")
    check = commands.add_parser("check", help="verify the newest dest-dir backup is fresh and passes integrity_check")
    check.add_argument("--dest-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    check.add_argument("--max-age-hours", type=int, default=48)
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
        pruned, pruned_ledger, checkpointed, vacuumed = [], None, None, None
        if args.command == "backup":
            if bool(args.destination) == bool(args.dest_dir):
                parser.error("pass exactly one of --destination or --dest-dir")
            if args.dest_dir is not None:
                if args.prune < 1:
                    parser.error("--prune must keep at least one backup")
                args.dest_dir.mkdir(parents=True, exist_ok=True)
                args.destination = args.dest_dir / f"{BACKUP_PREFIX}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.sqlite3"
            result = backup_database(args.source, args.destination)
            if args.dest_dir is not None:
                vacuumed, pruned = vacuum_database(args.destination), _prune_backups(args.dest_dir, args.prune)
            pruned_ledger = prune_ledger(args.source, history_days=args.prune_history, audit_days=args.prune_audit,
                                         api_audit_days=args.prune_api_audit, sighting_days=args.prune_sightings)
            checkpointed = checkpoint_wal(args.source)
        elif args.command == "verify":
            print(json.dumps({"path": str(args.path), "integrity": verify_database(args.path)}))
            return 0
        elif args.command == "inspect":
            print(json.dumps(inspect_database(args.path, quick_check=not args.no_quick_check)))
            return 0
        elif args.command == "compact":
            if not args.assume_stopped:
                parser.error("stop the site services first, then pass --assume-stopped")
            verify_database(args.path)
            report = vacuum_database(args.path)
            report.update({"path": str(args.path), "integrity": verify_database(args.path)})
            print(json.dumps(report))
            return 0
        elif args.command == "check":
            print(json.dumps(check_backups(args.dest_dir, max_age_hours=args.max_age_hours)))
            return 0
        else:
            result = restore_database(args.source, args.destination, replace=args.replace, assume_stopped=args.assume_stopped)
    except (DatabaseError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({"path": str(result.path), "integrity": result.integrity, "sha256": result.sha256,
                      "rollback_path": str(result.rollback_path) if result.rollback_path else None,
                      "pruned": pruned, "pruned_ledger": pruned_ledger, "checkpoint": checkpointed, "vacuum": vacuumed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
