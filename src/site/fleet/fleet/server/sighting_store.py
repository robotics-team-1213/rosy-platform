"""SQLite persistence for derived site sightings and their acceptance audit."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Mapping


class SightingStore:
    """Persist pose rows and source lineage without ever storing credentials or media."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS latest_sightings (
                    robot_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    captured_at REAL NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sighting_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    robot_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    captured_at REAL NOT NULL,
                    received_at REAL NOT NULL
                );
                PRAGMA user_version=1;
                """
            )
        if os.name != "nt":
            self.path.chmod(0o600)

    def save_sighting(self, row: Mapping) -> None:
        payload = json.dumps(dict(row), separators=(",", ":"), allow_nan=False)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """INSERT INTO latest_sightings(robot_id, source_id, captured_at, payload_json)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(robot_id) DO UPDATE SET source_id=excluded.source_id,
                         captured_at=excluded.captured_at, payload_json=excluded.payload_json""",
                    (row["robot_id"], row["source_id"], row["captured_at"], payload),
                )
                connection.execute(
                    """INSERT INTO sighting_audit
                       (event, robot_id, source_id, seq, captured_at, received_at)
                       VALUES ('sighting.accepted', ?, ?, ?, ?, ?)""",
                    (row["robot_id"], row["source_id"], row["seq"],
                     row["captured_at"], row["received_at"]),
                )

    def load_latest(self) -> dict[str, dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT robot_id, payload_json FROM latest_sightings ORDER BY robot_id"
            ).fetchall()
        return {row["robot_id"]: json.loads(row["payload_json"]) for row in rows}

    def audit_events(self) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT event, robot_id, source_id, seq, captured_at, received_at
                   FROM sighting_audit ORDER BY audit_id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def backup(self, destination: Path | str) -> None:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as source, closing(sqlite3.connect(target)) as backup:
            source.backup(backup)
        if os.name != "nt":
            target.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection
