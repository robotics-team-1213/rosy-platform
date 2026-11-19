"""Watermark-cursor Postgres archive of the Fleet site API audit.

The Fleet control ledger stays SQLite (D-750). This module copies committed
`fleet_api_audit` rows into a monthly range-partitioned Postgres table through
`ContextLog` (the D-796 sidecar). Postgres being slow or down only delays the
cursor: rows are read with `rowid > last_rowid`, inserts are idempotent
(`ON CONFLICT DO NOTHING`), and the SQLite watermark (`fleet_audit_flush`)
advances only after the Postgres commit, so a crash between the two replays
without duplicating rows. `flush_once` never raises.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fleet.server.context_log import ContextLog
from fleet.server.sqlite_policy import configure_connection

_LOG = logging.getLogger(__name__)

#: SQLite watermark: the last `fleet_api_audit` rowid copied per source kind.
_WATERMARK_DDL = """CREATE TABLE IF NOT EXISTS fleet_audit_flush (
    kind TEXT PRIMARY KEY,
    last_rowid INTEGER NOT NULL,
    flushed_at TEXT NOT NULL
)"""
_WATERMARK_READ = "SELECT last_rowid FROM fleet_audit_flush WHERE kind = 'fleet_api_audit'"
_WATERMARK_WRITE = """INSERT INTO fleet_audit_flush (kind, last_rowid, flushed_at)
    VALUES ('fleet_api_audit', ?, ?)
    ON CONFLICT(kind) DO UPDATE SET
        last_rowid = excluded.last_rowid,
        flushed_at = excluded.flushed_at"""

#: Postgres archive: monthly range partitions plus a DEFAULT catch-all.
_ARCHIVE_DDL = (
    """CREATE TABLE IF NOT EXISTS fleet_api_audit_archive (
        request_id text NOT NULL,
        event_type text NOT NULL,
        recorded_at timestamptz NOT NULL,
        principal_id text NOT NULL,
        role text NOT NULL,
        method text NOT NULL,
        path text NOT NULL,
        status_code integer,
        detail jsonb NOT NULL DEFAULT '{}'::jsonb,
        PRIMARY KEY (request_id, event_type, recorded_at)
    ) PARTITION BY RANGE (recorded_at)""",
    """CREATE TABLE IF NOT EXISTS fleet_api_audit_default
        PARTITION OF fleet_api_audit_archive DEFAULT""",
)
_ARCHIVE_INSERT = """INSERT INTO fleet_api_audit_archive
        (request_id, event_type, recorded_at, principal_id, role, method, path, status_code, detail)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
    ON CONFLICT (request_id, event_type, recorded_at) DO NOTHING"""

#: SQLite source rows in rowid order; `created_at` becomes the archive `recorded_at`.
_AUDIT_SELECT = """SELECT rowid, request_id, event_type, principal_id, role, method, path, status_code, created_at
    FROM fleet_api_audit
    WHERE rowid > ?
    ORDER BY rowid ASC
    LIMIT ?"""


def _month_start(now: datetime, offset: int) -> datetime:
    total = now.year * 12 + (now.month - 1) + offset
    return datetime(total // 12, total % 12 + 1, 1, tzinfo=timezone.utc)


def ensure_month_partitions(conn: Any, now: Optional[datetime] = None, *,
                            months_ahead: int = 2) -> list[str]:
    """Ensure partitions for the current month and the next ``months_ahead`` months."""
    current = now if now is not None else datetime.now(timezone.utc)
    ensured: list[str] = []
    for offset in range(months_ahead + 1):
        start, end = _month_start(current, offset), _month_start(current, offset + 1)
        name = f"fleet_api_audit_y{start.year:04d}m{start.month:02d}"
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF fleet_api_audit_archive "
            f"FOR VALUES FROM ('{start:%Y-%m-%dT%H:%M:%SZ}') TO ('{end:%Y-%m-%dT%H:%M:%SZ}')")
        ensured.append(name)
    return ensured


class AuditArchiver:
    """Asynchronous, idempotent SQLite→Postgres copy of the Fleet API audit."""

    def __init__(self, store_path: Path | str, context_log: ContextLog, *,
                 batch_size: int = 500) -> None:
        self.store_path = Path(store_path)
        self.context_log = context_log
        self.batch_size = batch_size

    def flush_once(self, *, now: Optional[datetime] = None) -> dict:
        """Copy at most ``batch_size`` committed rows; never raises, returns ``error``."""
        if not self.store_path.exists():
            return {"copied": 0, "cursor": 0, "error": None}
        last_rowid = 0
        try:
            last_rowid = self._read_watermark()
            rows = self._read_batch(last_rowid)
            if not rows:
                return {"copied": 0, "cursor": last_rowid, "error": None}
            self.context_log._connect_and(self._archive_work(rows, now))
            self._advance_watermark(rows[-1][0])
            return {"copied": len(rows), "cursor": rows[-1][0], "error": None}
        except Exception as exc:  # a down Postgres must never block Fleet (D-796)
            _LOG.warning("audit archive flush skipped: %s", exc)
            return {"copied": 0, "cursor": last_rowid, "error": str(exc)}

    def _archive_work(self, rows: list[tuple], now: Optional[datetime]) -> Callable[[Any], None]:
        def work(conn: Any) -> None:
            for statement in _ARCHIVE_DDL:
                conn.execute(statement)
            ensure_month_partitions(conn, now)
            for row in rows:
                conn.execute(_ARCHIVE_INSERT, (
                    row[1], row[2], row[8], row[3], row[4], row[5], row[6], row[7], "{}"))

        return work

    def _read_watermark(self) -> int:
        with closing(configure_connection(sqlite3.connect(self.store_path))) as connection:
            connection.execute(_WATERMARK_DDL)
            connection.commit()
            row = connection.execute(_WATERMARK_READ).fetchone()
        return int(row[0]) if row else 0

    def _read_batch(self, last_rowid: int) -> Optional[list[tuple]]:
        # Read-only URI + query_only so the live WAL ledger is never written or checkpointed.
        uri = f"{self.store_path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON")
            present = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'fleet_api_audit'"
            ).fetchone()
            if present is None:
                return None
            return connection.execute(_AUDIT_SELECT, (last_rowid, self.batch_size)).fetchall()

    def _advance_watermark(self, rowid: int) -> None:
        flushed_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with closing(configure_connection(sqlite3.connect(self.store_path))) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(_WATERMARK_WRITE, (rowid, flushed_at))
            connection.commit()
