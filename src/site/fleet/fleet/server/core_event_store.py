"""Durable, credential-free audit history for authenticated CORE Agent events."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

MAX_EVENT_BYTES = 64 * 1024
_SENSITIVE_FIELD = re.compile(
    r"(?:passwo?rd|passwd|psk|passphrase|secret|token|credential|authorization|"
    r"api[_-]?key|private[_-]?key|bearer)",
    re.IGNORECASE,
)
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")


class EventRejected(ValueError):
    """Event data is unsafe or outside the bounded audit contract."""


def _contains_sensitive_field(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            _SENSITIVE_FIELD.search(str(key)) or _contains_sensitive_field(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_field(child) for child in value)
    if isinstance(value, str):
        return bool(_PRIVATE_KEY.search(value))
    return False


class CoreEventStore:
    """Append accepted CORE events once and provide stable audit cursors."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS core_event_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    robot_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(robot_id, event_id)
                );
                CREATE INDEX IF NOT EXISTS core_event_audit_robot_cursor
                    ON core_event_audit(robot_id, audit_id);
                """
            )
        if os.name != "nt":
            self.path.chmod(0o600)

    def append_event(self, event: Mapping[str, object]) -> bool:
        if _contains_sensitive_field(event):
            raise EventRejected("event contains a forbidden credential field")
        try:
            payload = json.dumps(dict(event), ensure_ascii=False, separators=(",", ":"),
                                 allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise EventRejected("event is not valid finite JSON") from exc
        if len(payload.encode("utf-8")) > MAX_EVENT_BYTES:
            raise EventRejected("event exceeds the 64 KiB audit limit")
        event_id = event.get("event_id")
        robot_id = event.get("robot_id")
        seq = event.get("seq")
        event_type = event.get("type")
        if not all(isinstance(value, str) and value for value in (event_id, robot_id, event_type)):
            raise EventRejected("event identity fields are required")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
            raise EventRejected("event sequence must be a positive integer")
        received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO core_event_audit
                   (robot_id, event_id, seq, event_type, received_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (robot_id, event_id, seq, event_type, received_at, payload),
            )
            if cursor.rowcount == 1:
                return True
            existing = connection.execute(
                "SELECT payload_json FROM core_event_audit WHERE robot_id = ? AND event_id = ?",
                (robot_id, event_id),
            ).fetchone()
            if existing is None or existing["payload_json"] != payload:
                raise EventRejected("event identity was reused with different content")
            return False

    def read_events(self, *, after_id: int = 0, limit: int = 100,
                    robot_id: str | None = None) -> list[dict]:
        if after_id < 0 or not 1 <= limit <= 200:
            raise ValueError("cursor must be nonnegative and limit must be 1..200")
        query = (
            "SELECT audit_id, robot_id, event_id, seq, event_type, received_at, payload_json "
            "FROM core_event_audit WHERE audit_id > ?"
        )
        params: list[object] = [after_id]
        if robot_id is not None:
            query += " AND robot_id = ?"
            params.append(robot_id)
        query += " ORDER BY audit_id ASC LIMIT ?"
        params.append(limit + 1)
        with closing(self._connect()) as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            {
                "audit_id": row["audit_id"],
                "robot_id": row["robot_id"],
                "event_id": row["event_id"],
                "seq": row["seq"],
                "type": row["event_type"],
                "received_at": row["received_at"],
                "event": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection
