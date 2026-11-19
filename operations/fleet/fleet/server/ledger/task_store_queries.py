"""Read-only queries, row mapping, and site API audit helpers for ``FleetTaskStore``."""

from __future__ import annotations

import json
from contextlib import closing
from uuid import uuid4

from .task_store_types import _now

_QUEUE_POSITION_QUERY = """SELECT COUNT(*) FROM fleet_tasks
    INDEXED BY fleet_tasks_dispatch_queue_position
    WHERE status='QUEUED' AND lease_owner IS NULL
      AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')
      AND (priority_class, queued_at, task_id) < (?, ?, ?)"""


def begin_api_audit(self, *, principal_id: str, role: str,
                    method: str, path: str) -> str:
    if (not principal_id or len(principal_id) > 96 or any(ord(char) < 32 for char in principal_id)
            or role not in {"viewer", "operator", "policy-admin", "service"}
            or method != "POST" or not path.startswith("/api/fleet/")
            or path == "/api/fleet/sightings"):
        raise ValueError("invalid site API audit entry")
    request_id = uuid4().hex
    with closing(self._connect()) as connection:
        connection.execute(
            """INSERT INTO fleet_api_audit
               (request_id, event_type, principal_id, role, method, path, created_at)
               VALUES (?, 'INTENT', ?, ?, ?, ?, ?)""",
            (request_id, principal_id, role, method, path, _now()),
        )
        connection.commit()
        return request_id


def finish_api_audit(self, request_id: str, *, status_code: int) -> None:
    with closing(self._connect()) as connection:
        intent = connection.execute(
            """SELECT principal_id, role, method, path FROM fleet_api_audit
               WHERE request_id = ? AND event_type = 'INTENT'""",
            (request_id,),
        ).fetchone()
        if intent is None:
            raise KeyError("site API audit intent was not found")
        connection.execute(
            """INSERT INTO fleet_api_audit
               (request_id, event_type, principal_id, role, method, path, status_code, created_at)
               VALUES (?, 'RESULT', ?, ?, ?, ?, ?, ?)""",
            (request_id, intent["principal_id"], intent["role"], intent["method"],
             intent["path"], int(status_code), _now()),
        )
        connection.commit()


def api_audit(self, *, limit: int = 100) -> list[dict]:
    if not 1 <= limit <= 1000:
        raise ValueError("audit limit must be between 1 and 1000")
    with closing(self._connect()) as connection:
        rows = connection.execute(
            """SELECT audit_id, request_id, event_type, principal_id, role,
                      method, path, status_code, created_at
               FROM fleet_api_audit ORDER BY audit_id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def queued_task_ids(self) -> set[str]:
    with closing(self._connect()) as connection:
        rows = connection.execute(
            """SELECT task_id FROM fleet_tasks WHERE status='QUEUED'
               AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')"""
        ).fetchall()
    return {row["task_id"] for row in rows}


def unfinished_task_ids(self, robot_id: str) -> list[str]:
    """Waiting, assigned or running work that blocks unenrolling a robot (D-361 5)."""
    with closing(self._connect()) as connection:
        rows = connection.execute(
            """SELECT task_id FROM fleet_tasks WHERE robot_id=?
               AND status IN ('REQUESTED', 'QUEUED', 'ACCEPTED', 'RUNNING', 'UNKNOWN')
               ORDER BY created_at, task_id""", (robot_id,)
        ).fetchall()
    return [row["task_id"] for row in rows]


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
            if task["queued_at"] is None:
                # Preserve legacy NULL ordering until old queue rows leave.
                ahead = connection.execute(
                    """SELECT COUNT(*) FROM fleet_tasks
                       WHERE status='QUEUED' AND lease_owner IS NULL
                         AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')
                       AND (priority_class < ? OR
                            (priority_class = ? AND queued_at < ?) OR
                            (priority_class = ? AND queued_at = ?
                             AND task_id < ?))""",
                    (task["priority_class"], task["priority_class"],
                     task["queued_at"], task["priority_class"],
                     task["queued_at"], task_id),
                ).fetchone()[0]
            else:
                ahead = connection.execute(
                    _QUEUE_POSITION_QUERY,
                    (task["priority_class"], task["queued_at"], task_id),
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
        "first_queued_at": row["first_queued_at"],
        "expires_at": row["expires_at"],
        "lease_owner": row["lease_owner"],
        "lease_until": row["lease_until"],
        "dispatch_generation": row["dispatch_generation"],
        "dispatch_phase": row["dispatch_phase"],
        "attempt_id": row["attempt_id"],
        "attempt_seq": row["attempt_seq"],
        "blocked_by": row["blocked_by"],
        "waiting_on": json.loads(row["waiting_on_json"]),
        "queue_position": None,
    }
