"""Durable task state and append-only transition history for site Fleet."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

_SENSITIVE_FIELD = re.compile(
    r"(?:passwo?rd|passwd|psk|passphrase|secret|token|credential|authorization|"
    r"api[_-]?key|private[_-]?key|bearer)",
    re.IGNORECASE,
)
_TASK_TRANSITIONS = {
    "REQUESTED": {"ACCEPTED", "FAILED", "UNKNOWN", "HOLD"},
    "ACCEPTED": {"RUNNING", "COMPLETED", "FAILED", "UNKNOWN", "HOLD"},
    "RUNNING": {"COMPLETED", "FAILED", "UNKNOWN", "HOLD"},
    "UNKNOWN": {"ACCEPTED", "RUNNING", "COMPLETED", "FAILED", "HOLD"},
    "FAILED": set(), "COMPLETED": set(), "HOLD": set(),
}


class IdempotencyConflict(ValueError):
    """The same actor reused an idempotency key for a different task request."""


class InvalidTaskTransition(ValueError):
    """A task status transition is outside the declared state machine."""


def _safe_json(value: object) -> str:
    def inspect(child: object) -> None:
        if isinstance(child, Mapping):
            for key, nested in child.items():
                if _SENSITIVE_FIELD.search(str(key)):
                    raise ValueError("task records cannot contain credential fields")
                inspect(nested)
        elif isinstance(child, (list, tuple)):
            for nested in child:
                inspect(nested)

    inspect(value)
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                           allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("task data must be finite JSON") from exc
    if len(text.encode("utf-8")) > 64 * 1024:
        raise ValueError("task data exceeds the 64 KiB limit")
    return text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class FleetTaskStore:
    """Current task projection plus a transactional, append-only status journal."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS fleet_tasks (
                    task_id TEXT PRIMARY KEY,
                    robot_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    request_json TEXT NOT NULL,
                    evidence_json TEXT,
                    receipt_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source, actor_id, request_key)
                );
                CREATE INDEX IF NOT EXISTS fleet_tasks_robot_updated
                    ON fleet_tasks(robot_id, updated_at);
                CREATE INDEX IF NOT EXISTS fleet_tasks_status
                    ON fleet_tasks(status);
                CREATE TABLE IF NOT EXISTS fleet_task_history (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES fleet_tasks(task_id),
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS fleet_task_history_task
                    ON fleet_task_history(task_id, audit_id);
                """
            )
        if os.name != "nt":
            self.path.chmod(0o600)

    def create_task(self, *, task_id: str, robot_id: str, task_type: str,
                    source: str, actor_id: str, request_key: str,
                    request: Mapping, evidence: Mapping | None) -> dict:
        request_json = _safe_json(dict(request))
        evidence_json = None if evidence is None else _safe_json(dict(evidence))
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """SELECT * FROM fleet_tasks
                   WHERE source = ? AND actor_id = ? AND request_key = ?""",
                (source, actor_id, request_key),
            ).fetchone()
            if existing is not None:
                if (existing["robot_id"] != robot_id or existing["task_type"] != task_type
                        or existing["request_json"] != request_json
                        or existing["evidence_json"] != evidence_json):
                    raise IdempotencyConflict("idempotency key already belongs to another request")
                connection.commit()
                return {"created": False, "task": self._task_dict(existing)}

            connection.execute(
                """INSERT INTO fleet_tasks
                   (task_id, robot_id, task_type, source, actor_id, request_key,
                    status, request_json, evidence_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'REQUESTED', ?, ?, ?, ?)""",
                (task_id, robot_id, task_type, source, actor_id, request_key,
                 request_json, evidence_json, now, now),
            )
            connection.execute(
                """INSERT INTO fleet_task_history
                   (task_id, status, source, actor_id, created_at)
                   VALUES (?, 'REQUESTED', ?, ?, ?)""",
                (task_id, source, actor_id, now),
            )
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id = ?",
                                     (task_id,)).fetchone()
            connection.commit()
        return {"created": True, "task": self._task_dict(row)}

    def transition(self, task_id: str, status: str, *, actor_id: str,
                   source: str, reason: str | None = None,
                   receipt: Mapping | None = None) -> dict:
        receipt_json = None if receipt is None else _safe_json(dict(receipt))
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM fleet_tasks WHERE task_id = ?",
                                         (task_id,)).fetchone()
            if current is None:
                raise KeyError(task_id)
            if status not in _TASK_TRANSITIONS.get(current["status"], set()):
                raise InvalidTaskTransition(f"{current['status']} cannot transition to {status}")
            new_receipt = receipt_json if receipt_json is not None else current["receipt_json"]
            connection.execute(
                """UPDATE fleet_tasks SET status = ?, reason = ?, receipt_json = ?, updated_at = ?
                   WHERE task_id = ?""",
                (status, reason, new_receipt, now, task_id),
            )
            connection.execute(
                """INSERT INTO fleet_task_history
                   (task_id, status, source, actor_id, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (task_id, status, source, actor_id, reason, now),
            )
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id = ?",
                                     (task_id,)).fetchone()
            connection.commit()
        return self._task_dict(row)

    def get_task(self, task_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id = ?",
                                     (task_id,)).fetchone()
        return self._task_dict(row) if row is not None else None

    def history(self, task_id: str) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT audit_id, status, source, actor_id, reason, created_at
                   FROM fleet_task_history WHERE task_id = ? ORDER BY audit_id""",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def recover_interrupted_requests(self) -> int:
        """Fail closed after process restart; never infer that an unsent request is safe to retry."""
        now = _now()
        reason = "PROCESS_RESTARTED_WITH_REQUESTED_TASK"
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT task_id FROM fleet_tasks WHERE status = 'REQUESTED'"
            ).fetchall()
            recovered = 0
            for row in rows:
                task_id = row["task_id"]
                connection.execute(
                    "UPDATE fleet_tasks SET status = 'UNKNOWN', reason = ?, updated_at = ? "
                    "WHERE task_id = ? AND status = 'REQUESTED'",
                    (reason, now, task_id),
                )
                if connection.execute("SELECT changes()").fetchone()[0] != 1:
                    continue
                connection.execute(
                    """INSERT INTO fleet_task_history
                       (task_id, status, source, actor_id, reason, created_at)
                       VALUES (?, 'UNKNOWN', 'system', 'fleet-recovery', ?, ?)""",
                    (task_id, reason, now),
                )
                recovered += 1
            connection.commit()
        return recovered

    @staticmethod
    def _task_dict(row) -> dict:
        return {
            "task_id": row["task_id"],
            "robot_id": row["robot_id"],
            "task_type": row["task_type"],
            "source": row["source"],
            "actor_id": row["actor_id"],
            "status": row["status"],
            "reason": row["reason"],
            "request": json.loads(row["request_json"]),
            "evidence": json.loads(row["evidence_json"]) if row["evidence_json"] else None,
            "receipt": json.loads(row["receipt_json"]) if row["receipt_json"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
