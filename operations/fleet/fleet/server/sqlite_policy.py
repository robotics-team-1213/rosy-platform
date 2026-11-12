"""Shared durable SQLite defaults for the Site Fleet journal database."""

from __future__ import annotations

import sqlite3


BUSY_TIMEOUT_MS = 5_000
_WAL_AUTOCHECKPOINT_PAGES: int | None = None


def set_wal_autocheckpoint(pages: int | None) -> None:
    global _WAL_AUTOCHECKPOINT_PAGES
    _WAL_AUTOCHECKPOINT_PAGES = pages


def get_wal_autocheckpoint() -> int | None:
    return _WAL_AUTOCHECKPOINT_PAGES


def configure_connection(connection: sqlite3.Connection) -> sqlite3.Connection:
    """Apply shared locking, FK, and durability policy to each connection."""
    connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=FULL")
    if _WAL_AUTOCHECKPOINT_PAGES is not None:
        connection.execute(f"PRAGMA wal_autocheckpoint={int(_WAL_AUTOCHECKPOINT_PAGES)}")
    return connection


def enable_wal(connection: sqlite3.Connection) -> None:
    """Enable persistent WAL and fail if the VFS rejects it."""
    mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    if str(mode).lower() != "wal":
        raise RuntimeError(f"SQLite WAL mode is required, got {mode!r}")


__all__ = ["BUSY_TIMEOUT_MS", "configure_connection", "enable_wal",
           "set_wal_autocheckpoint", "get_wal_autocheckpoint"]
