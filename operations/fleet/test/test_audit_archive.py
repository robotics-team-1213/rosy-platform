"""AuditArchiver: idempotent watermark copy of the SQLite API audit into Postgres.

The Postgres side is a recording fake (a ContextLog over a fake pool); SQLite is
the real `FleetTaskStore` ledger, so the watermark, the read-only source query
and the crash replay run against the actual files.
"""
import sqlite3
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from fleet.server.audit_archive import AuditArchiver, ensure_month_partitions
from fleet.server.context_log import ContextLog
from fleet.server.task_store import FleetTaskStore

_ARCHIVE_COLUMNS = ("request_id", "event_type", "recorded_at", "principal_id", "role",
                    "method", "path", "status_code", "detail")


class ArchiveConnection:
    """Accepts the archive DDL; applies the insert's ON CONFLICT DO NOTHING."""

    def __init__(self, archive):
        self.archive = archive
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, params=None):
        self.archive.statements.append(statement)
        if statement.startswith("INSERT INTO fleet_api_audit_archive"):
            key = (params[0], params[1], params[2])  # the archive primary key
            if key not in self.archive.keys:
                self.archive.keys.add(key)
                self.archive.rows.append(dict(zip(_ARCHIVE_COLUMNS, params)))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class ArchivePool:
    def __init__(self, archive):
        self.archive = archive
        self.acquires = 0

    def connection(self):
        self.acquires += 1
        return nullcontext(ArchiveConnection(self.archive))

    def close(self):
        pass


class FakePostgresArchive:
    """The Postgres side as the archiver sees it: a ContextLog over a recording pool."""

    def __init__(self):
        self.rows = []
        self.keys = set()
        self.statements = []
        self.pool = ArchivePool(self)
        self.context_log = ContextLog("postgres", "rosy_context", "rosy",
                                      pool_factory=lambda dsn: self.pool)


def _store_with_one_request(tmp_path):
    store = FleetTaskStore(Path(tmp_path) / "fleet.sqlite3")
    request_id = store.begin_api_audit(principal_id="op-1", role="operator",
                                       method="POST", path="/api/fleet/tasks")
    store.finish_api_audit(request_id, status_code=200)
    return store.path


def test_flush_copies_committed_rows_and_advances_the_watermark(tmp_path):
    db_path = _store_with_one_request(tmp_path)
    archive = FakePostgresArchive()
    archiver = AuditArchiver(db_path, archive.context_log, batch_size=1)

    assert archiver.flush_once() == {"copied": 1, "cursor": 1, "error": None}
    assert archiver.flush_once() == {"copied": 1, "cursor": 2, "error": None}
    assert archiver.flush_once() == {"copied": 0, "cursor": 2, "error": None}  # nothing new

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT kind, last_rowid FROM fleet_audit_flush").fetchall() == [("fleet_api_audit", 2)]
    assert [row["event_type"] for row in archive.rows] == ["INTENT", "RESULT"]
    assert archive.rows[0]["status_code"] is None and archive.rows[0]["detail"] == "{}"
    assert archive.rows[1]["status_code"] == 200
    assert any("PARTITION BY RANGE (recorded_at)" in s for s in archive.statements)
    assert any("fleet_api_audit_default" in s for s in archive.statements)
    assert any("fleet_api_audit_y" in s for s in archive.statements)


def test_flush_of_a_missing_store_reports_an_empty_cursor(tmp_path):
    archiver = AuditArchiver(tmp_path / "nowhere" / "fleet.sqlite3",
                             FakePostgresArchive().context_log)
    assert archiver.flush_once() == {"copied": 0, "cursor": 0, "error": None}


def test_flush_without_the_audit_table_keeps_the_cursor(tmp_path):
    db_path = tmp_path / "bare.sqlite3"
    sqlite3.connect(db_path).close()  # the file exists but has no audit table
    archive = FakePostgresArchive()
    archiver = AuditArchiver(db_path, archive.context_log)
    assert archiver.flush_once() == {"copied": 0, "cursor": 0, "error": None}
    assert archive.pool.acquires == 0  # Postgres is never touched
    assert archive.rows == []


def test_flush_after_a_crash_between_commit_and_watermark_replays_without_duplicates(
        tmp_path, monkeypatch):
    db_path = _store_with_one_request(tmp_path)
    archive = FakePostgresArchive()
    archiver = AuditArchiver(db_path, archive.context_log)
    original = AuditArchiver._advance_watermark

    def crash_once(self, rowid):
        monkeypatch.setattr(AuditArchiver, "_advance_watermark", original)
        raise RuntimeError("crash before the watermark update")

    monkeypatch.setattr(AuditArchiver, "_advance_watermark", crash_once)
    first = archiver.flush_once()
    assert first["copied"] == 0 and first["cursor"] == 0 and first["error"] is not None
    assert len(archive.rows) == 2  # Postgres committed before the crash

    second = archiver.flush_once()  # replays rowid > 0; conflicts are ignored
    assert second == {"copied": 2, "cursor": 2, "error": None}
    assert len(archive.rows) == 2  # ON CONFLICT DO NOTHING kept the replay duplicate-free
    assert archiver.flush_once() == {"copied": 0, "cursor": 2, "error": None}


def test_postgres_outage_reports_an_error_and_leaves_the_cursor(tmp_path):
    db_path = _store_with_one_request(tmp_path)

    def unreachable(dsn):
        raise RuntimeError("connection refused")

    archiver = AuditArchiver(db_path, ContextLog("postgres", "rosy_context", "rosy",
                                                 pool_factory=unreachable))
    result = archiver.flush_once()
    assert result["copied"] == 0 and result["cursor"] == 0
    assert "connection refused" in result["error"]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_audit_flush").fetchone()[0] == 0


def test_ensure_month_partitions_spans_the_year_boundary():
    archive = FakePostgresArchive()
    ensured = ensure_month_partitions(ArchiveConnection(archive),
                                      datetime(2026, 11, 12, tzinfo=timezone.utc))
    assert ensured == ["fleet_api_audit_y2026m11", "fleet_api_audit_y2026m12",
                       "fleet_api_audit_y2027m01"]
    assert "CREATE TABLE IF NOT EXISTS fleet_api_audit_y2026m12 PARTITION OF" in archive.statements[1]
    assert "FROM ('2026-12-01T00:00:00Z') TO ('2027-01-01T00:00:00Z')" in archive.statements[1]
    assert "CREATE TABLE IF NOT EXISTS fleet_api_audit_y2027m01 PARTITION OF" in archive.statements[2]
