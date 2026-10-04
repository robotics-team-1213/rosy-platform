"""Shared durable SQLite defaults for the Site Fleet journal database."""

from __future__ import annotations

import sqlite3


BUSY_TIMEOUT_MS = 5_000


def configure_connection(connection: sqlite3.Connection) -> sqlite3.Connection:
    """Apply shared locking, FK, and durability policy to each connection."""
    connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=FULL")
    return connection


def enable_wal(connection: sqlite3.Connection) -> None:
    """Enable persistent WAL and fail if the VFS rejects it."""
    mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    if str(mode).lower() != "wal":
        raise RuntimeError(f"SQLite WAL mode is required, got {mode!r}")


__all__ = ["BUSY_TIMEOUT_MS", "configure_connection", "enable_wal"]
