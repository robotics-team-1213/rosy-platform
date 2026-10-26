"""Queue admission, claims, and traffic waits for the existing task ledger."""

from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fleet.server.dispatch_admission import release as release_dispatch_claims
from fleet.server.dispatch_admission import reserve as reserve_dispatch_claims
from fleet.server.task_payloads import safe_json as _safe_json

from .task_store_types import InvalidTaskTransition, _now

_PRIORITY_CLASSES = {0, 1, 2}


class TaskDispatchQueue:
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
                   first_queued_at=?,
                   expires_at=?, reason=NULL, updated_at=? WHERE task_id=?""",
                (priority_class, now, now, expires_at, now, task_id),
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
                release_dispatch_claims(connection, owner_kind="task",
                                        owner_id=row["task_id"])
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
                release_dispatch_claims(connection, owner_kind="task",
                                        owner_id=row["task_id"])
            selected = None
            control = connection.execute(
                "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if not control["dispatch_enabled"]:
                connection.commit()
                return None
            if robot_ids:
                placeholders = ",".join("?" for _ in robot_ids)
                selected = connection.execute(
                    f"""SELECT t.task_id, t.robot_id FROM fleet_tasks AS t
                        WHERE t.status='QUEUED' AND t.dispatch_phase='READY'
                          AND t.robot_id IN ({placeholders})
                          AND (t.lease_until IS NULL OR t.lease_until <= ?)
                          AND NOT EXISTS (SELECT 1 FROM fleet_action_claims c
                                          WHERE c.resource_key='robot:' || t.robot_id)
                        ORDER BY t.priority_class ASC, t.queued_at ASC, t.task_id ASC LIMIT 1""",
                    (*robot_ids, now),
                ).fetchone()
            if selected is None:
                connection.commit()
                return None
            connection.execute(
                """UPDATE fleet_tasks SET lease_owner=?, lease_until=?, dispatch_generation=?,
                   updated_at=? WHERE task_id=?""",
                (worker_id, lease_until, control["generation"], now, selected["task_id"]),
            )
            claimed = reserve_dispatch_claims(
                connection, owner_kind="task", owner_id=selected["task_id"],
                generation=control["generation"], resources=[("robot", selected["robot_id"])],
                phase="CLAIMED", lease_until=lease_until,
            )
            if not claimed:
                connection.rollback()
                return None
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
            control = connection.execute(
                "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if (not control["dispatch_enabled"]
                    or control["generation"] != current["dispatch_generation"]):
                raise InvalidTaskTransition("task claim belongs to an obsolete stop generation")
            attempt_id = str(uuid4())
            connection.execute(
                """UPDATE fleet_tasks SET dispatch_phase='DISPATCHING', attempt_id=?,
                   attempt_seq=attempt_seq+1, updated_at=? WHERE task_id=?""",
                (attempt_id, now, task_id),
            )
            claim = connection.execute(
                """UPDATE fleet_action_claims SET phase='DISPATCHING', lease_until=NULL
                   WHERE resource_key='robot:' || ? AND owner_kind='task'
                     AND owner_id=? AND generation=? AND phase='CLAIMED'""",
                (current["robot_id"], task_id, current["dispatch_generation"]),
            )
            if claim.rowcount != 1:
                raise InvalidTaskTransition("task no longer owns its robot dispatch claim")
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
            if json.loads(current['receipt_json'] or '{}').get('operation'):
                raise InvalidTaskTransition('native traffic cancellation requires exact outcome reconciliation')
            connection.execute(
                """UPDATE fleet_tasks SET dispatch_phase='WAITING_TRAFFIC', reason=?,
                   blocked_by=?, waiting_on_json=?, lease_owner=NULL, lease_until=NULL,
                   updated_at=? WHERE task_id=?""",
                (reason, blocked_by, waiting_json, now, task_id),
            )
            connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?", (task_id,))
            release_dispatch_claims(connection, owner_kind="task", owner_id=task_id)
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


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("expires_at must include a timezone")
    return parsed.astimezone(timezone.utc)
