"""A random identity created once with the owner's SQLite journal (C4b 1d item 3).

Fleet records it at submit. A later GetAction 404 means "never journaled" only if the owner still
reports the same journal identity; a fresh journal (an owner restarted on a new file) cannot
prove that an earlier attempt never ran.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def journal_identity(path: Path | str) -> str:
    with closing(sqlite3.connect(path, timeout=5.0, isolation_level=None)) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS omx_journal_identity (singleton INTEGER PRIMARY KEY "
            "CHECK(singleton=1), journal_id TEXT NOT NULL, created_at TEXT NOT NULL)")
        connection.execute("INSERT OR IGNORE INTO omx_journal_identity VALUES (1, ?, ?)",
                           (str(uuid.uuid4()), datetime.now(timezone.utc).isoformat()))
        return connection.execute("SELECT journal_id FROM omx_journal_identity").fetchone()[0]


__all__ = ["journal_identity"]
