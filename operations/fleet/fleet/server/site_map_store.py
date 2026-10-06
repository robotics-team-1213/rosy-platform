"""D-484 site map storage: one editable draft and immutable activated versions.

The active map is the highest activated version. Activation copies the draft, is done by a
named operator (routes) and is refused while a lane route is running. Every activation and
every trip plan (D-486 8) is a row here beside the HTTP audit of the request.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from fleet.meet.place import Painted, painted_from, use_painted
from fleet.routing.graph import Graph, build_graph
from fleet.server.sqlite_policy import configure_connection, enable_wal
from fleet.site_map import SiteMap


class SiteMapError(ValueError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class SiteMapStore:
    def __init__(self, path: Optional[Path] = None, *, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path) if path is not None else None
        self.clock = clock
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path) if self.path else ":memory:", check_same_thread=False)
        configure_connection(self._db)
        if self.path is not None:
            enable_wal(self._db)
        with self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS site_map_versions (
                    version INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL,
                    sha256 TEXT NOT NULL, activated_by TEXT NOT NULL, activated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS site_map_draft (
                    slot INTEGER PRIMARY KEY CHECK (slot = 1), body TEXT NOT NULL,
                    revision TEXT NOT NULL, saved_by TEXT NOT NULL, saved_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS site_trip_plans (
                    plan_id TEXT PRIMARY KEY, robot_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                    map_version INTEGER, request TEXT NOT NULL, result TEXT NOT NULL,
                    created_at REAL NOT NULL);
            """)
        self._cached: Optional[tuple[int, SiteMap, Graph, Painted]] = None
        self._publish()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---- active ---------------------------------------------------------------------

    def _active_row(self):
        return self._db.execute(
            "SELECT version, body, sha256, activated_by, activated_at FROM site_map_versions "
            "ORDER BY version DESC LIMIT 1").fetchone()

    def _publish(self) -> None:
        """Rebuild the cached map/graph and the meet ``Painted`` for the newest version."""
        with self._lock:
            row = self._active_row()
            if row is None:  # nothing to publish; the meet geometry keeps what it has
                return
            site_map = SiteMap.model_validate(json.loads(row[1]))
            painted = painted_from(site_map)
            self._cached = (row[0], site_map, build_graph(site_map, version=row[0]), painted)
            use_painted(painted)

    def active(self) -> Optional[tuple[int, SiteMap, Graph, Painted]]:
        """``(version, map, graph, painted)`` or None. Built once per version (D-486 6)."""
        return self._cached

    def active_view(self) -> Optional[dict]:
        with self._lock:
            row = self._active_row()
        if row is None:
            return None
        return {"version": row[0], "sha256": row[2], "activated_by": row[3],
                "activated_at": row[4], "map": json.loads(row[1])}

    def _insert_version(self, site_map: SiteMap, principal_id: str) -> int:
        text = json.dumps(site_map.body(), sort_keys=True, ensure_ascii=False)
        cursor = self._db.execute(
            "INSERT INTO site_map_versions (body, sha256, activated_by, activated_at) VALUES (?, ?, ?, ?)",
            (text, hashlib.sha256(text.encode("utf-8")).hexdigest(), principal_id, self.clock()))
        return int(cursor.lastrowid)

    def import_if_empty(self, site_map: SiteMap, *, source: str) -> Optional[int]:
        """The configured import source becomes version 1 only when the site has no map."""
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            if self._active_row() is not None:
                return None
            version = self._insert_version(site_map, f"import:{source}"[:96])
        self._publish()
        return version

    # ---- draft ----------------------------------------------------------------------

    def draft_view(self) -> dict:
        with self._lock:
            row = self._db.execute("SELECT body, revision, saved_by, saved_at FROM site_map_draft").fetchone()
        if row is None:
            return {"map": None, "revision": None}
        return {"map": json.loads(row[0]), "revision": row[1], "saved_by": row[2], "saved_at": row[3]}

    def save_draft(self, site_map: SiteMap, *, expected_revision: Optional[str], principal_id: str) -> dict:
        revision = uuid.uuid4().hex
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            current = self._db.execute("SELECT revision FROM site_map_draft").fetchone()
            if (current[0] if current else None) != expected_revision:
                raise SiteMapError(409, "SITE_MAP_DRAFT_CHANGED", "another operator changed the draft; reload first")
            self._db.execute("INSERT OR REPLACE INTO site_map_draft VALUES (1, ?, ?, ?, ?)",
                             (json.dumps(site_map.body(), ensure_ascii=False), revision, principal_id, self.clock()))
        return self.draft_view()

    def activate(self, *, expected_revision: str, principal_id: str, route_active: bool) -> dict:
        if route_active:
            raise SiteMapError(409, "SITE_MAP_ROUTE_ACTIVE",
                               "a lane route is running; activate after it ends")
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute("SELECT body, revision FROM site_map_draft").fetchone()
            if row is None:
                raise SiteMapError(409, "SITE_MAP_NO_DRAFT", "save a draft before activating")
            if row[1] != expected_revision:
                raise SiteMapError(409, "SITE_MAP_DRAFT_CHANGED", "the draft changed; review it again")
            self._insert_version(SiteMap.model_validate(json.loads(row[0])), principal_id)
            self._db.execute("DELETE FROM site_map_draft")
        self._publish()
        return self.active_view()

    # ---- trip plan audit (D-486 8) --------------------------------------------------

    def record_plan(self, *, plan_id: str, robot_id: str, principal_id: str,
                    map_version: Optional[int], request: dict, result: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO site_trip_plans VALUES (?, ?, ?, ?, ?, ?, ?)",
                (plan_id, robot_id, principal_id, map_version, json.dumps(request, sort_keys=True),
                 json.dumps(result, sort_keys=True), self.clock()))

    def plans(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT plan_id, robot_id, principal_id, map_version, request, result, created_at "
                "FROM site_trip_plans ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [{"plan_id": r[0], "robot_id": r[1], "principal_id": r[2], "map_version": r[3],
                 "request": json.loads(r[4]), "result": json.loads(r[5]), "created_at": r[6]} for r in rows]
