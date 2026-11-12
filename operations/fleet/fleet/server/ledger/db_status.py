"""Read-only, path-free Fleet database maintenance status."""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

from core_common.protocol.account_access import same_origin
from fleet.server.context_log import active


NO_STORE = {"Cache-Control": "no-store"}
_TIMESTAMPS = ("updated_at", "created_at", "received_at", "recorded_at", "at")


def collect_db_status(store_path: Path | str | None, *, context_log=None,
                      backup_dir: Path | str | None = None) -> dict:
    fleet = {
        "configured": False, "journal_mode": None, "size_bytes": 0, "wal_bytes": 0,
        "page_size": 0, "page_count": 0, "freelist_count": 0,
        "fragmentation_pct": 0.0, "component_migrations": {}, "newest_per_table": {},
    }
    if store_path is not None and (path := Path(store_path)).exists():
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5.0)) as conn:
            conn.execute("PRAGMA query_only=ON")
            fleet["configured"] = True
            fleet["size_bytes"] = path.stat().st_size
            wal_file = Path(f"{path}-wal")
            fleet["wal_bytes"] = wal_file.stat().st_size if wal_file.exists() else 0
            for name in ("journal_mode", "page_size", "page_count", "freelist_count"):
                fleet[name] = conn.execute(f"PRAGMA {name}").fetchone()[0]
            fleet["fragmentation_pct"] = (
                round(fleet["freelist_count"] / fleet["page_count"] * 100.0, 2)
                if fleet["page_count"] > 0 else 0.0
            )
            tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )]
            if "fleet_component_migrations" in tables:
                fleet["component_migrations"] = dict(conn.execute(
                    "SELECT component, version FROM fleet_component_migrations ORDER BY component"
                ))
            for table in tables:
                quoted_table = '"' + table.replace('"', '""') + '"'
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({quoted_table})")}
                column = next((name for name in _TIMESTAMPS if name in columns), None)
                if column is not None:
                    fleet["newest_per_table"][table] = conn.execute(
                        f'SELECT MAX("{column}") FROM {quoted_table}'
                    ).fetchone()[0]

    sink = context_log if context_log is not None else active()
    postgres = {"configured": sink is not None, "reachable": False, "database_size_bytes": None}
    if sink is not None:
        def read_size(conn):
            postgres["database_size_bytes"] = int(conn.execute(
                "SELECT pg_database_size(current_database())"
            ).fetchone()[0])

        try:
            sink._connect_and(read_size)
            postgres["reachable"] = True
        except Exception:
            postgres["database_size_bytes"] = None

    env_dir = os.environ.get("ROSY_SITE_BACKUP_DIR")
    bdir = Path(backup_dir) if backup_dir is not None else (Path(env_dir) if env_dir else None)
    files = list(bdir.glob("fleet-backup-*.sqlite3")) if bdir is not None and bdir.is_dir() else []
    newest = max((path.stat().st_mtime for path in files), default=None)
    backups = {"fleet": {
        "configured": bdir is not None, "count": len(files),
        "newest_age_hours": round((time.time() - newest) / 3600.0, 2) if newest is not None else None,
    }}
    return {"fleet": fleet, "postgres": postgres, "backups": backups}


def install_db_status_routes(app, *, store_path: Path | str | None = None, authorize,
                             context_log=None, backup_dir: Path | str | None = None) -> None:
    @app.get("/api/fleet/admin/db-status", tags=["fleet-auth"])
    def db_status(request: Request, authorization: str | None = Header(default=None)):
        forbidden = HTTPException(403, detail={"code": "ACCOUNT_ADMIN_REQUIRED"}, headers=NO_STORE)
        try:
            principal = authorize(request, authorization=authorization)
        except HTTPException:
            raise forbidden from None
        if (getattr(request.state, "site_auth_via", None) != "cookie"
                or getattr(principal, "password_change_required", False)
                or not principal.permits_site("accounts.manage", {"policy-admin"})
                or (request.headers.get("origin") is not None and not same_origin(request))):
            raise forbidden
        return JSONResponse(
            collect_db_status(store_path, context_log=context_log, backup_dir=backup_dir), headers=NO_STORE
        )
