"""D-962 Account SQLite connection policy — independent of fleet.*."""
from __future__ import annotations

import sqlite3

BUSY_TIMEOUT_MS = 5_000


def configure_connection(connection: sqlite3.Connection) -> sqlite3.Connection:
    connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=FULL")
    return connection


def enable_wal(connection: sqlite3.Connection) -> None:
    row = connection.execute("PRAGMA journal_mode=WAL").fetchone()
    mode = str(row[0]).lower() if row else ""
    if mode not in {"wal", "memory"}:
        raise RuntimeError(f"SQLite WAL mode is required, got {row!r}")
