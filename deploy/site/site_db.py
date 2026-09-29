"""SQLite online backup and guarded restore for the site Fleet data volume."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DATABASE = Path("/var/lib/rosy/fleet.sqlite3")


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
    """D-352 4: reseal every enrolled robot token in one transaction, Fleet stopped."""
    if not args.assume_stopped:
        parser.error("stop the Fleet service first, then pass --assume-stopped")
    from fleet.server.enrollment_store import CredentialKeyError, SealError, load_key_file, rekey

    try:
        count = rekey(args.path, load_key_file(args.old_key_file), load_key_file(args.new_key_file))
    except (CredentialKeyError, SealError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps({"path": str(args.path), "resealed": count}))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="create a consistent SQLite online backup")
    backup.add_argument("--source", type=Path, default=DEFAULT_DATABASE)
    backup.add_argument("--destination", type=Path, required=True)
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
        if args.command == "backup":
            result = backup_database(args.source, args.destination)
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
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
