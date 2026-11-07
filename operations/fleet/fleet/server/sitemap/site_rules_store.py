"""D-982 site rules storage: one editable draft and immutable activated versions.

Same shape as ``SiteMapStore``: the active document is the highest activated version, a draft
is saved by a named operator against a revision, activation copies the draft and is refused
while a route runs. It shares the site map database and its ``site_map_events`` audit rows.
With no activated document ``active_rules()`` is None and callers keep their old constants.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Callable, Optional

from fleet.server.site_map_store import SiteMapError
from fleet.site_rules import SiteRules


class SiteRulesStore:
    def __init__(self, db, lock, clock: Callable[[], float], event: Callable[..., None],
                 places: Callable[[], Optional[set]]) -> None:
        """``event`` writes a ``site_map_events`` row inside the caller's transaction; ``places`` are the active map's ids."""
        self._db, self._lock, self._clock, self._event, self._places = db, lock, clock, event, places
        with self._lock, self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS site_rules_versions (
                    version INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL,
                    sha256 TEXT NOT NULL, activated_by TEXT NOT NULL, activated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS site_rules_draft (
                    slot INTEGER PRIMARY KEY CHECK (slot = 1), body TEXT NOT NULL,
                    revision TEXT NOT NULL, saved_by TEXT NOT NULL, saved_at REAL NOT NULL);
            """)
        self._cached: Optional[SiteRules] = None
        self._publish()

    def _row(self):
        return self._db.execute("SELECT version, body, sha256, activated_by, activated_at FROM site_rules_versions "
                                "ORDER BY version DESC LIMIT 1").fetchone()

    def _publish(self) -> None:
        with self._lock:
            row = self._row()
            self._cached = SiteRules.model_validate(json.loads(row[1])) if row else None

    def active_rules(self) -> Optional[SiteRules]:
        """The active document, or None when the site has none (callers then keep their constants)."""
        return self._cached

    def active_view(self) -> Optional[dict]:
        with self._lock:
            row = self._row()
        if row is None:
            return None
        return {"version": row[0], "sha256": row[2], "activated_by": row[3], "activated_at": row[4],
                "rules": json.loads(row[1])}

    def draft_view(self) -> dict:
        with self._lock:
            row = self._db.execute("SELECT body, revision, saved_by, saved_at FROM site_rules_draft").fetchone()
        if row is None:
            return {"rules": None, "revision": None}
        return {"rules": json.loads(row[0]), "revision": row[1], "saved_by": row[2], "saved_at": row[3]}

    def _check_places(self, rules: SiteRules) -> None:
        known = self._places()
        unknown = sorted(rules.place_ids() - known) if known is not None else []
        if unknown:
            raise SiteMapError(422, "SITE_RULES_UNKNOWN_PLACE", f"places not on the active map: {', '.join(unknown)}")

    def save_draft(self, rules: SiteRules, *, expected_revision: Optional[str], principal_id: str) -> dict:
        self._check_places(rules)
        revision = uuid.uuid4().hex
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            current = self._db.execute("SELECT revision FROM site_rules_draft").fetchone()
            if (current[0] if current else None) != expected_revision:
                raise SiteMapError(409, "SITE_RULES_DRAFT_CHANGED", "another operator changed the draft; reload first")
            self._db.execute("INSERT OR REPLACE INTO site_rules_draft VALUES (1, ?, ?, ?, ?)",
                             (json.dumps(rules.body(), ensure_ascii=False), revision, principal_id, self._clock()))
            self._event("rules_draft_saved", principal_id, {"revision": revision})
        return self.draft_view()

    def activate(self, *, expected_revision: str, principal_id: str, route_active: bool) -> dict:
        if route_active:
            raise SiteMapError(409, "SITE_RULES_ROUTE_ACTIVE",
                               "a trip, formation or map recording is active; activate after it ends")
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute("SELECT body, revision FROM site_rules_draft").fetchone()
            if row is None:
                raise SiteMapError(409, "SITE_RULES_NO_DRAFT", "save a draft before activating")
            if row[1] != expected_revision:
                raise SiteMapError(409, "SITE_RULES_DRAFT_CHANGED", "the draft changed; review it again")
            rules = SiteRules.model_validate(json.loads(row[0]))
            self._check_places(rules)
            text = json.dumps(rules.body(), sort_keys=True, ensure_ascii=False)
            version = self._db.execute(
                "INSERT INTO site_rules_versions (body, sha256, activated_by, activated_at) VALUES (?, ?, ?, ?)",
                (text, hashlib.sha256(text.encode("utf-8")).hexdigest(), principal_id, self._clock())).lastrowid
            self._event("rules_activated", principal_id, {"revision": expected_revision, "version": int(version)})
            self._db.execute("DELETE FROM site_rules_draft")
        self._publish()
        return self.active_view()
