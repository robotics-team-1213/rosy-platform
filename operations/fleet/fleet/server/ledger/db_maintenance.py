"""Online Fleet SQLite settings, maintenance, and read-only health checks."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fleet.server.audit_archive import AuditArchiver
from fleet.server.sqlite_policy import configure_connection, enable_wal, set_wal_autocheckpoint

DEFAULT_DB_SETTINGS = {
    "history_retention_days": 30, "audit_retention_days": 90,
    "api_audit_retention_days": 90, "sighting_retention_days": 90,
    "wal_autocheckpoint_pages": 1000, "incremental_vacuum_pages": 256,
}
SETTING_BOUNDS = {key: ((100, 100000) if key == "wal_autocheckpoint_pages" else
                        (0, 10000) if key == "incremental_vacuum_pages" else (0, 3650))
                  for key in DEFAULT_DB_SETTINGS}
VALID_ACTIONS = frozenset({"self-test", "checkpoint", "incremental-vacuum", "flush-audit", "prune-expired"})
_SETTINGS_DDL = """CREATE TABLE IF NOT EXISTS fleet_db_settings (
    key TEXT PRIMARY KEY, value_int INTEGER NOT NULL, updated_at TEXT NOT NULL)"""


def connect_sqlite(path: Path | str) -> sqlite3.Connection:
    conn = configure_connection(sqlite3.connect(path, timeout=5.0))
    enable_wal(conn)
    return conn


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2.0)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def read_db_settings(store_path: Path | str | None) -> dict[str, Any]:
    settings = dict(DEFAULT_DB_SETTINGS)
    if store_path is not None and (path := Path(store_path)).is_file():
        with closing(_read_only(path)) as conn:
            try:
                settings.update((key, value) for key, value in conn.execute(
                    "SELECT key, value_int FROM fleet_db_settings") if key in settings)
            except sqlite3.OperationalError:  # pre-settings ledger
                pass
    return {**settings, "applied_mode": "next_prune_and_new_connections"}


def update_db_settings(store_path: Path | str | None, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or not payload:
        raise ValueError("Settings payload must be a non-empty object")
    for key, value in payload.items():
        bounds = SETTING_BOUNDS.get(key)
        if bounds is None or not isinstance(value, int) or isinstance(value, bool) or not bounds[0] <= value <= bounds[1]:
            raise ValueError(f"Invalid setting {key}={value!r}")
    if store_path is None:
        raise ValueError("Database path is not configured")
    path = Path(store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_sqlite(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(_SETTINGS_DDL)
            stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            conn.executemany("""INSERT INTO fleet_db_settings(key, value_int, updated_at)
                VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET
                value_int=excluded.value_int, updated_at=excluded.updated_at""",
                [(key, value, stamp) for key, value in payload.items()])
            pages = dict(conn.execute("SELECT key, value_int FROM fleet_db_settings")).get(
                "wal_autocheckpoint_pages", DEFAULT_DB_SETTINGS["wal_autocheckpoint_pages"])
            conn.execute(f"PRAGMA wal_autocheckpoint={pages}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    set_wal_autocheckpoint(pages)
    return read_db_settings(path)


def read_audit_archive_status(store_path: Path | str | None, *, context_log: Any = None) -> dict[str, Any]:
    configured = bool(context_log and getattr(context_log, "_dsn", None))
    last_rowid, flushed_at, max_rowid = 0, None, 0
    if store_path is not None and (path := Path(store_path)).is_file():
        with closing(_read_only(path)) as conn:
            tables = _tables(conn)
            if "fleet_audit_flush" in tables:
                row = conn.execute("SELECT last_rowid, flushed_at FROM fleet_audit_flush "
                                   "WHERE kind='fleet_api_audit'").fetchone()
                if row:
                    last_rowid, flushed_at = int(row[0]), row[1]
            if "fleet_api_audit" in tables:
                max_rowid = conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM fleet_api_audit").fetchone()[0]
    return {"configured": configured, "last_rowid": last_rowid, "flushed_at": flushed_at,
            "pending_rows": max(0, max_rowid - last_rowid)}


def run_db_self_test(store_path: Path | str | None, *, context_log: Any = None,
                     backup_dir: Path | str | None = None) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    if store_path is None or not Path(store_path).is_file():
        return {"action": "self-test", "ok": False,
                "checks": {"policy": {"ok": False, "error": "DATABASE_MISSING"}}}
    path = Path(store_path)
    with closing(connect_sqlite(path)) as conn:
        policy = {name: conn.execute(f"PRAGMA {name}").fetchone()[0] for name in
                  ("journal_mode", "synchronous", "foreign_keys", "busy_timeout", "wal_autocheckpoint")}
        checks["policy"] = {"ok": (policy["journal_mode"] == "wal" and policy["synchronous"] in (1, 2)
                                   and policy["foreign_keys"] == 1 and policy["busy_timeout"] >= 5000
                                   and policy["wal_autocheckpoint"] >= 100), **policy}
        quick = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
        violations = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        checks["integrity"] = {"ok": quick == "ok" and violations == 0,
                               "quick_check": quick, "fk_violations": violations}
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        free = conn.execute("PRAGMA freelist_count").fetchone()[0]
        av = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        wal = Path(f"{path}-wal")
        wal_bytes = wal.stat().st_size if wal.exists() else 0
        ratio = free / pages if pages else 0.0
        checks["wal_and_fragmentation"] = {
            "ok": True, "page_count": pages, "freelist_count": free, "free_ratio": ratio,
            "wal_bytes": wal_bytes, "auto_vacuum": {0: "none", 1: "full", 2: "incremental"}.get(av, "none"),
            "warning": wal_bytes > 67108864 or ratio > 0.25}
        tables = _tables(conn)
        migration_table = "fleet_schema_migrations" if "fleet_schema_migrations" in tables else "fleet_component_migrations"
        applied = conn.execute(f"SELECT COUNT(*) FROM {migration_table}").fetchone()[0] if migration_table in tables else 0
        settings = read_db_settings(path)
        valid = all(isinstance(settings[key], int) and not isinstance(settings[key], bool)
                    and SETTING_BOUNDS[key][0] <= settings[key] <= SETTING_BOUNDS[key][1] for key in SETTING_BOUNDS)
        checks["migrations_and_settings"] = {"ok": valid, "applied_count": applied}
    archive = read_audit_archive_status(path, context_log=context_log)
    pg_status = context_log.status() if archive["configured"] and hasattr(context_log, "status") else {}
    checks["audit_archive"] = {**archive, "ok": not archive["configured"] or bool(pg_status.get("ok"))}
    return {"action": "self-test", "ok": all(check["ok"] for check in checks.values()), "checks": checks}


def prune_expired_online(store_path: Path | str, settings: Mapping[str, Any], *,
                         context_log: Any = None) -> dict[str, int]:
    deleted = {key: 0 for key in ("fleet_task_history", "device_pairing_audit", "core_event_audit",
                                  "fleet_api_audit", "sighting_audit")}
    now = datetime.now(timezone.utc)
    with closing(connect_sqlite(store_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            tables = _tables(conn)
            def cutoff(key: str) -> str | None:
                days = int(settings[key])
                return (now - timedelta(days=days)).isoformat(timespec="milliseconds") if days > 0 else None

            history = cutoff("history_retention_days")
            if history and {"fleet_task_history", "fleet_tasks"} <= tables:
                deleted["fleet_task_history"] = conn.execute(
                    "DELETE FROM fleet_task_history WHERE task_id IN (SELECT task_id FROM fleet_tasks "
                    "WHERE status IN ('COMPLETED','FAILED','CANCELED','EXPIRED') AND updated_at < ?)",
                    (history,)).rowcount
            audit = cutoff("audit_retention_days")
            if audit and "device_pairing_audit" in tables:
                deleted["device_pairing_audit"] = conn.execute("DELETE FROM device_pairing_audit WHERE at < ?",
                    ((now - timedelta(days=int(settings["audit_retention_days"]))).timestamp(),)).rowcount
            if audit and "core_event_audit" in tables:
                deleted["core_event_audit"] = conn.execute("DELETE FROM core_event_audit WHERE received_at < ?", (audit,)).rowcount
            sighting = cutoff("sighting_retention_days")
            if sighting and "sighting_audit" in tables:
                deleted["sighting_audit"] = conn.execute("DELETE FROM sighting_audit WHERE received_at < ?",
                    ((now - timedelta(days=int(settings["sighting_retention_days"]))).timestamp(),)).rowcount
            api = cutoff("api_audit_retention_days")
            if api and "fleet_api_audit" in tables:
                row = conn.execute("SELECT last_rowid FROM fleet_audit_flush WHERE kind='fleet_api_audit'").fetchone() if "fleet_audit_flush" in tables else None
                guarded = bool(context_log and getattr(context_log, "_dsn", None)) or row is not None
                sql = "DELETE FROM fleet_api_audit WHERE created_at < ?" + (" AND rowid <= ?" if guarded else "")
                deleted["fleet_api_audit"] = conn.execute(sql, (api, int(row[0]) if row else 0) if guarded else (api,)).rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return deleted


def run_db_maintenance_action(store_path: Path | str | None, action: str, *,
                              context_log: Any = None, backup_dir: Path | str | None = None) -> dict[str, Any]:
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unknown maintenance action: {action!r}")
    if action == "self-test":
        return run_db_self_test(store_path, context_log=context_log, backup_dir=backup_dir)
    if store_path is None:
        raise ValueError("Database path is not configured")
    path = Path(store_path)
    if action == "flush-audit":
        if not (context_log and getattr(context_log, "_dsn", None)):
            return {"action": action, "ok": False, "copied": 0, "cursor": 0,
                    "pending_rows": read_audit_archive_status(path)["pending_rows"], "error": "POSTGRES_UNCONFIGURED"}
        result = AuditArchiver(path, context_log).flush_once()
        after = read_audit_archive_status(path, context_log=context_log)
        return {"action": action, "ok": result.get("error") is None, "copied": result["copied"],
                "cursor": result["cursor"], "pending_rows": after["pending_rows"], "error": result.get("error")}
    if action == "prune-expired":
        return {"action": action, "ok": True,
                "deleted": prune_expired_online(path, read_db_settings(path), context_log=context_log)}
    with closing(connect_sqlite(path)) as conn:
        if action == "checkpoint":
            wal = Path(f"{path}-wal")
            before = wal.stat().st_size if wal.exists() else 0
            busy, frames, copied = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            after = wal.stat().st_size if wal.exists() else 0
            return {"action": action, "ok": busy == 0, "busy": int(busy), "log_frames": int(frames),
                    "checkpointed_frames": int(copied), "wal_bytes_before": before, "wal_bytes_after": after}
        pages = int(read_db_settings(path)["incremental_vacuum_pages"])
        av = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        before = conn.execute("PRAGMA freelist_count").fetchone()[0]
        if av == 2 and pages > 0:
            conn.execute(f"PRAGMA incremental_vacuum({pages})")
        after = conn.execute("PRAGMA freelist_count").fetchone()[0]
        return {"action": action, "ok": True, "auto_vacuum": {0: "none", 1: "full", 2: "incremental"}.get(av, "none"),
                "freelist_before": int(before), "freelist_after": int(after), "reclaimed_pages": max(0, int(before) - int(after))}
