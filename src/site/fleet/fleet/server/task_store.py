"""Durable task state and append-only transition history for site Fleet."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping
from uuid import uuid4

_SENSITIVE_FIELD = re.compile(
    r"(?:passwo?rd|passwd|psk|passphrase|secret|token|credential|authorization|"
    r"api[_-]?key|private[_-]?key|bearer)",
    re.IGNORECASE,
)
_TASK_TRANSITIONS = {
    "REQUESTED": {"QUEUED", "ACCEPTED", "FAILED", "UNKNOWN", "HOLD"},
    "QUEUED": {"ACCEPTED", "FAILED", "UNKNOWN", "HOLD", "CANCELED", "EXPIRED"},
    "ACCEPTED": {"RUNNING", "COMPLETED", "FAILED", "UNKNOWN", "HOLD"},
    "RUNNING": {"COMPLETED", "FAILED", "UNKNOWN", "HOLD"},
    "UNKNOWN": {"ACCEPTED", "RUNNING", "COMPLETED", "FAILED", "HOLD"},
    "FAILED": set(), "COMPLETED": set(), "HOLD": set(), "CANCELED": set(), "EXPIRED": set(),
}
_PRIORITY_CLASSES = {0, 1, 2}


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
        text = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False, sort_keys=True
        )
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
                CREATE TABLE IF NOT EXISTS fleet_robot_reservations (
                    robot_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL UNIQUE REFERENCES fleet_tasks(task_id),
                    reserved_at TEXT NOT NULL
                );
                """
            )
            self._migrate_task_columns(connection)
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

    def enqueue(self, task_id: str, *, priority_class: int, expires_at: str | None = None,
                actor_id: str = "site-scheduler", source: str = "scheduler") -> dict:
        """Durably move a validated request into the dispatchable queue."""
        if priority_class not in _PRIORITY_CLASSES:
            raise ValueError("priority_class must be operator=0, accepted-policy=1, background=2")
        if expires_at is not None:
            expires_at = _parse_time(expires_at).isoformat(timespec="milliseconds")
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM fleet_tasks WHERE task_id = ?",
                                         (task_id,)).fetchone()
            if current is None:
                raise KeyError(task_id)
            if current["status"] != "REQUESTED":
                raise InvalidTaskTransition(f"{current['status']} cannot transition to QUEUED")
            connection.execute(
                """UPDATE fleet_tasks SET status='QUEUED', priority_class=?, queued_at=?,
                   expires_at=?, reason=NULL, updated_at=? WHERE task_id=?""",
                (priority_class, now, expires_at, now, task_id),
            )
            self._append_history(connection, task_id, "QUEUED", source, actor_id, now)
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id = ?",
                                     (task_id,)).fetchone()
            connection.commit()
        return self._task_dict(row)

    def claim_next(self, *, worker_id: str, available_robot_ids: set[str],
                   lease_seconds: float = 30.0) -> dict | None:
        """Atomically claim the highest-priority eligible task and reserve its robot."""
        if not worker_id or len(worker_id) > 96:
            raise ValueError("invalid worker_id")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        robot_ids = sorted(set(available_robot_ids))
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat(timespec="milliseconds")
        lease_until = (now_dt + timedelta(seconds=lease_seconds)).isoformat(
            timespec="milliseconds")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            expired = connection.execute(
                """SELECT task_id, source, actor_id FROM fleet_tasks
                   WHERE status='QUEUED' AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')
                     AND expires_at IS NOT NULL AND expires_at <= ?""",
                (now,),
            ).fetchall()
            for row in expired:
                connection.execute(
                    """UPDATE fleet_tasks SET status='EXPIRED', dispatch_phase='EXPIRED',
                       reason='TASK_EXPIRED', blocked_by=NULL, waiting_on_json='[]', updated_at=? """
                    "WHERE task_id=? AND status='QUEUED'", (now, row["task_id"]),
                )
                connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?",
                                   (row["task_id"],))
                self._append_history(connection, row["task_id"], "EXPIRED", "scheduler",
                                     "site-scheduler", now, "TASK_EXPIRED")
            stale_claims = connection.execute(
                """SELECT task_id FROM fleet_tasks WHERE status='QUEUED'
                   AND dispatch_phase='READY' AND lease_until IS NOT NULL AND lease_until <= ?""",
                (now,),
            ).fetchall()
            for row in stale_claims:
                connection.execute(
                    "UPDATE fleet_tasks SET lease_owner=NULL, lease_until=NULL "
                    "WHERE task_id=?", (row["task_id"],),
                )
                connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?",
                                   (row["task_id"],))
            selected = None
            if robot_ids:
                placeholders = ",".join("?" for _ in robot_ids)
                selected = connection.execute(
                    f"""SELECT t.task_id, t.robot_id FROM fleet_tasks AS t
                        WHERE t.status='QUEUED' AND t.dispatch_phase='READY'
                          AND t.robot_id IN ({placeholders})
                          AND (t.lease_until IS NULL OR t.lease_until <= ?)
                          AND NOT EXISTS (SELECT 1 FROM fleet_robot_reservations r
                                          WHERE r.robot_id=t.robot_id)
                        ORDER BY t.priority_class ASC, t.queued_at ASC, t.task_id ASC LIMIT 1""",
                    (*robot_ids, now),
                ).fetchone()
            if selected is None:
                connection.commit()
                return None
            connection.execute(
                "UPDATE fleet_tasks SET lease_owner=?, lease_until=?, updated_at=? WHERE task_id=?",
                (worker_id, lease_until, now, selected["task_id"]),
            )
            connection.execute(
                "INSERT INTO fleet_robot_reservations(robot_id, task_id, reserved_at) VALUES (?, ?, ?)",
                (selected["robot_id"], selected["task_id"], now),
            )
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                     (selected["task_id"],)).fetchone()
            connection.commit()
        return self._task_dict(row)

    def mark_dispatching(self, task_id: str, *, worker_id: str) -> dict:
        """Persist an attempt ID before a CORE call; its presence forbids blind replay."""
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                         (task_id,)).fetchone()
            if current is None:
                raise KeyError(task_id)
            if (current["status"] != "QUEUED" or current["lease_owner"] != worker_id
                    or current["dispatch_phase"] != "READY"
                    or current["lease_until"] is None or current["lease_until"] <= now):
                raise InvalidTaskTransition("task is not held by this active dispatch lease")
            attempt_id = str(uuid4())
            connection.execute(
                """UPDATE fleet_tasks SET dispatch_phase='DISPATCHING', attempt_id=?,
                   attempt_seq=attempt_seq+1, updated_at=? WHERE task_id=?""",
                (attempt_id, now, task_id),
            )
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                     (task_id,)).fetchone()
            connection.commit()
        return self._task_dict(row)

    def wait_for_traffic(self, task_id: str, *, worker_id: str, reason: str,
                         blocked_by: str | None, waiting_on: list[str],
                         dispatch_attempted: bool, cancel_confirmed: bool) -> dict:
        """Persist a queued traffic wait only when no goal remains active on the robot."""
        if dispatch_attempted and not cancel_confirmed:
            raise ValueError("traffic wait requires confirmed cancellation")
        if not reason or len(reason) > 64 or len(waiting_on) > 32:
            raise ValueError("invalid traffic wait details")
        waiting_json = _safe_json(list(waiting_on))
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                         (task_id,)).fetchone()
            if current is None:
                raise KeyError(task_id)
            if (current["status"] != "QUEUED" or current["dispatch_phase"] != "DISPATCHING"
                    or current["lease_owner"] != worker_id):
                raise InvalidTaskTransition("task is not held by this dispatch attempt")
            connection.execute(
                """UPDATE fleet_tasks SET dispatch_phase='WAITING_TRAFFIC', reason=?,
                   blocked_by=?, waiting_on_json=?, lease_owner=NULL, lease_until=NULL,
                   updated_at=? WHERE task_id=?""",
                (reason, blocked_by, waiting_json, now, task_id),
            )
            connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?", (task_id,))
            self._append_history(connection, task_id, "QUEUED", current["source"],
                                 current["actor_id"], now, reason)
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                     (task_id,)).fetchone()
            connection.commit()
        return self._task_dict(row)

    def release_traffic_wait(self, task_id: str) -> dict:
        """Make a confirmed-canceled traffic wait eligible for a fresh attempt."""
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                         (task_id,)).fetchone()
            if current is None:
                raise KeyError(task_id)
            if current["status"] != "QUEUED" or current["dispatch_phase"] != "WAITING_TRAFFIC":
                raise InvalidTaskTransition("task is not waiting for traffic release")
            connection.execute(
                """UPDATE fleet_tasks SET dispatch_phase='READY', reason=NULL, blocked_by=NULL,
                   waiting_on_json='[]', queued_at=?, updated_at=? WHERE task_id=?""",
                (now, now, task_id),
            )
            self._append_history(connection, task_id, "QUEUED", "scheduler",
                                 "site-scheduler", now, "TRAFFIC_QUEUE_RELEASED")
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                     (task_id,)).fetchone()
            connection.commit()
        return self._task_dict(row)

    def cancel_queued(self, task_id: str, *, actor_id: str) -> dict:
        """Cancel only a task that has not entered its CORE dispatch attempt."""
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                         (task_id,)).fetchone()
            if current is None:
                raise KeyError(task_id)
            if current["status"] == "CANCELED":
                connection.commit()
                return self._task_dict(current)
            if (current["status"] != "QUEUED"
                    or current["dispatch_phase"] not in {"READY", "WAITING_TRAFFIC"}):
                raise InvalidTaskTransition("only a task not yet dispatched can be canceled here")
            connection.execute(
                """UPDATE fleet_tasks SET status='CANCELED', dispatch_phase='CANCELED',
                   reason='OPERATOR_CANCELED_BEFORE_DISPATCH', blocked_by=NULL,
                   waiting_on_json='[]', lease_owner=NULL, lease_until=NULL, updated_at=?
                   WHERE task_id=?""",
                (now, task_id),
            )
            connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?", (task_id,))
            self._append_history(connection, task_id, "CANCELED", "operator", actor_id, now,
                                 "OPERATOR_CANCELED_BEFORE_DISPATCH")
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                     (task_id,)).fetchone()
            connection.commit()
        return self._task_dict(row)

    def cancel_queued_for_robot(self, robot_id: str, *, actor_id: str) -> list[str]:
        return self._cancel_queued_tasks(actor_id=actor_id, robot_id=robot_id)

    def cancel_all_queued(self, *, actor_id: str) -> list[str]:
        return self._cancel_queued_tasks(actor_id=actor_id)

    def queued_task_ids(self) -> set[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT task_id FROM fleet_tasks WHERE status='QUEUED'
                   AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')"""
            ).fetchall()
        return {row["task_id"] for row in rows}

    def recover_interrupted_work(self) -> int:
        """Requeue only work proven not sent; ambiguous CORE calls become UNKNOWN."""
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT task_id, source, actor_id, status, dispatch_phase FROM fleet_tasks
                   WHERE status='REQUESTED' OR (status='QUEUED' AND dispatch_phase='DISPATCHING')"""
            ).fetchall()
            recovered = 0
            for row in rows:
                if row["status"] == "REQUESTED":
                    status, reason = "UNKNOWN", "PROCESS_RESTARTED_WITH_REQUESTED_TASK"
                else:
                    status, reason = "UNKNOWN", "PROCESS_RESTARTED_DURING_DISPATCH"
                connection.execute(
                    "UPDATE fleet_tasks SET status=?, reason=?, updated_at=? WHERE task_id=?",
                    (status, reason, now, row["task_id"]),
                )
                self._append_history(connection, row["task_id"], status, "system",
                                     "fleet-recovery", now, reason)
                recovered += 1
            safe = connection.execute(
                """SELECT task_id FROM fleet_tasks
                   WHERE status='QUEUED' AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')"""
            ).fetchall()
            for row in safe:
                connection.execute(
                    """UPDATE fleet_tasks SET dispatch_phase='READY', reason=NULL, blocked_by=NULL,
                       waiting_on_json='[]', lease_owner=NULL, lease_until=NULL, updated_at=? """
                    "WHERE task_id=?", (now, row["task_id"]),
                )
                connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?",
                                   (row["task_id"],))
            connection.commit()
        return recovered

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
            if status in {"FAILED", "COMPLETED", "HOLD", "CANCELED", "EXPIRED"}:
                connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?",
                                   (task_id,))
            connection.commit()
        return self._task_dict(row)

    def get_task(self, task_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id = ?",
                                     (task_id,)).fetchone()
            if row is None:
                return None
            task = self._task_dict(row)
            if (task["status"] == "QUEUED"
                    and task["lease_owner"] is None
                    and task["dispatch_phase"] in {"READY", "WAITING_TRAFFIC"}):
                ahead = connection.execute(
                    """SELECT COUNT(*) FROM fleet_tasks
                       WHERE status='QUEUED' AND lease_owner IS NULL
                         AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')
                       AND (priority_class < ? OR
                            (priority_class = ? AND queued_at < ?) OR
                            (priority_class = ? AND queued_at = ? AND task_id < ?))""",
                    (task["priority_class"], task["priority_class"], task["queued_at"],
                     task["priority_class"], task["queued_at"], task_id),
                ).fetchone()[0]
                task["queue_position"] = int(ahead) + 1
        return task

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
            "priority_class": row["priority_class"],
            "queued_at": row["queued_at"],
            "expires_at": row["expires_at"],
            "lease_owner": row["lease_owner"],
            "lease_until": row["lease_until"],
            "dispatch_phase": row["dispatch_phase"],
            "attempt_id": row["attempt_id"],
            "attempt_seq": row["attempt_seq"],
            "blocked_by": row["blocked_by"],
            "waiting_on": json.loads(row["waiting_on_json"]),
            "queue_position": None,
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _append_history(connection, task_id: str, status: str, source: str,
                        actor_id: str, now: str, reason: str | None = None) -> None:
        connection.execute(
            """INSERT INTO fleet_task_history
               (task_id, status, source, actor_id, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (task_id, status, source, actor_id, reason, now),
        )

    def _cancel_queued_tasks(self, *, actor_id: str, robot_id: str | None = None) -> list[str]:
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if robot_id is None:
                rows = connection.execute(
                    """SELECT task_id FROM fleet_tasks WHERE status='QUEUED'
                       AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')"""
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT task_id FROM fleet_tasks WHERE status='QUEUED'
                       AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC') AND robot_id=?""",
                    (robot_id,),
                ).fetchall()
            task_ids = [row["task_id"] for row in rows]
            for task_id in task_ids:
                connection.execute(
                    """UPDATE fleet_tasks SET status='CANCELED', dispatch_phase='CANCELED',
                       reason='OPERATOR_CANCELED_BEFORE_DISPATCH', blocked_by=NULL,
                       waiting_on_json='[]', lease_owner=NULL, lease_until=NULL, updated_at=?
                       WHERE task_id=?""",
                    (now, task_id),
                )
                connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?",
                                   (task_id,))
                self._append_history(connection, task_id, "CANCELED", "operator", actor_id, now,
                                     "OPERATOR_CANCELED_BEFORE_DISPATCH")
            connection.commit()
        return task_ids

    @staticmethod
    def _migrate_task_columns(connection: sqlite3.Connection) -> None:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(fleet_tasks)")}
        additions = {
            "priority_class": "INTEGER NOT NULL DEFAULT 0",
            "queued_at": "TEXT",
            "expires_at": "TEXT",
            "lease_owner": "TEXT",
            "lease_until": "TEXT",
            "dispatch_phase": "TEXT NOT NULL DEFAULT 'READY'",
            "attempt_id": "TEXT",
            "attempt_seq": "INTEGER NOT NULL DEFAULT 0",
            "blocked_by": "TEXT",
            "waiting_on_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        connection.execute("BEGIN IMMEDIATE")
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE fleet_tasks ADD COLUMN {name} {definition}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS fleet_tasks_queue_order "
            "ON fleet_tasks(status, priority_class, queued_at, task_id)"
        )
        connection.commit()


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("expires_at must include a timezone")
    return parsed.astimezone(timezone.utc)
