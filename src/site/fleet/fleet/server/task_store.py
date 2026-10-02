"""Durable task state and append-only transition history for site Fleet."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fleet.server.cancel_all_store import ensure_schema as ensure_cancel_all_schema
from fleet.server.dispatch_admission import release as release_dispatch_claims
from fleet.server.dispatch_admission import reserve as reserve_dispatch_claims
from fleet.server.sqlite_policy import configure_connection, enable_wal

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
_QUEUE_POSITION_QUERY = """SELECT COUNT(*) FROM fleet_tasks
    INDEXED BY fleet_tasks_dispatch_queue_position
    WHERE status='QUEUED' AND lease_owner IS NULL
      AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')
      AND (priority_class, queued_at, task_id) < (?, ?, ?)"""


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
            enable_wal(connection)
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
                CREATE TABLE IF NOT EXISTS fleet_api_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status_code INTEGER,
                    created_at TEXT NOT NULL,
                    UNIQUE(request_id, event_type)
                );
                CREATE TABLE IF NOT EXISTS fleet_robot_reservations (
                    robot_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL UNIQUE REFERENCES fleet_tasks(task_id),
                    reserved_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_action_claims (
                    resource_key TEXT PRIMARY KEY,
                    resource_kind TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    owner_kind TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    lease_until TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(resource_key, owner_kind, owner_id, generation)
                );
                CREATE INDEX IF NOT EXISTS fleet_action_claims_owner
                    ON fleet_action_claims(owner_kind, owner_id, generation);
                CREATE TABLE IF NOT EXISTS fleet_dispatch_control (
                    control_id INTEGER PRIMARY KEY CHECK(control_id=1),
                    authority_epoch INTEGER NOT NULL DEFAULT 0,
                    generation INTEGER NOT NULL,
                    dispatch_enabled INTEGER NOT NULL CHECK(dispatch_enabled IN (0, 1)),
                    reason TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO fleet_dispatch_control
                    (control_id, generation, dispatch_enabled, reason, actor_id, updated_at)
                    VALUES (1, 0, 0, 'STARTUP_HOLD', 'system', CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS fleet_task_core_events (
                    robot_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    task_id TEXT NOT NULL REFERENCES fleet_tasks(task_id),
                    attempt_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    PRIMARY KEY(robot_id, event_id)
                );
                CREATE INDEX IF NOT EXISTS fleet_task_core_events_attempt
                    ON fleet_task_core_events(robot_id, attempt_id, seq);
                """
            )
            self._migrate_task_columns(connection)
            self._migrate_dispatch_control(connection)
            self._migrate_dispatch_claims(connection)
            ensure_cancel_all_schema(connection)  # D-421 cancel-all record and attempt tags
        if os.name != "nt":
            self.path.chmod(0o600)

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

    def reserve_resources(self, *, owner_kind: str, owner_id: str, generation: int,
                          resources: list[tuple[str, str]], phase: str = "CLAIMED") -> bool:
        """Atomically reserve canonical resources for a task, Mission, or direct Action."""
        if phase != "CLAIMED":
            raise ValueError("new resource reservations must use CLAIMED phase")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            control = connection.execute(
                "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if (not control["dispatch_enabled"] or control["generation"] != generation):
                connection.commit()
                return False
            claimed = reserve_dispatch_claims(
                connection, owner_kind=owner_kind, owner_id=owner_id,
                generation=generation, resources=resources, phase="CLAIMED",
            )
            connection.commit()
        return claimed

    def restore_unresolved_action_claim(self, *, owner_kind: str, owner_id: str,
                                        generation: int, resources: list[tuple[str, str]],
                                        phase: str) -> bool:
        """Restore persisted in-flight device ownership while dispatch is closed.

        Only an external, durable Action reconciliation path should call this;
        regular admission cannot manufacture DISPATCHING or UNKNOWN claims.
        """
        if owner_kind not in {"mission", "direct_action"}:
            raise ValueError("only Mission or direct Action claims may be restored here")
        if phase not in {"DISPATCHING", "UNKNOWN"}:
            raise ValueError("restored Action claim phase must be DISPATCHING or UNKNOWN")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            control = connection.execute(
                "SELECT dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if control["dispatch_enabled"]:
                connection.rollback()
                raise ValueError("unresolved Action claims may only be restored while dispatch is closed")
            claimed = reserve_dispatch_claims(
                connection, owner_kind=owner_kind, owner_id=owner_id,
                generation=generation, resources=resources, phase=phase,
            )
            connection.commit()
        return claimed

    def release_resources(self, *, owner_kind: str, owner_id: str,
                          generation: int | None = None) -> bool:
        """Release only the matching owner generation after outcome reconciliation."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            released = release_dispatch_claims(
                connection, owner_kind=owner_kind, owner_id=owner_id,
                generation=generation,
            )
            if owner_kind == "task":
                connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?",
                                   (owner_id,))
            connection.commit()
        return released > 0

    def resource_claims(self, *, resource_kind: str, resource_id: str) -> list[dict]:
        resource_key = f"{resource_kind}:{resource_id}"
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT resource_kind, resource_id, owner_kind, owner_id,
                          generation, phase
                   FROM fleet_action_claims WHERE resource_key=?""",
                (resource_key,),
            ).fetchall()
        return [dict(row) for row in rows]

    def dispatch_control(self) -> dict:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT authority_epoch, generation, dispatch_enabled, reason
                   FROM fleet_dispatch_control WHERE control_id=1"""
            ).fetchone()
            queued = connection.execute(
                """SELECT COUNT(*) FROM fleet_tasks WHERE status='QUEUED'
                   AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')"""
            ).fetchone()[0]
            unresolved = connection.execute(
                """SELECT COUNT(*) FROM fleet_action_claims
                   WHERE phase IN ('DISPATCHING', 'UNKNOWN')"""
            ).fetchone()[0]
        return {"authority_epoch": row["authority_epoch"],
                "generation": row["generation"],
                "dispatch_enabled": bool(row["dispatch_enabled"]),
                "reason": row["reason"], "queued_tasks": int(queued),
                "unresolved_actions": int(unresolved),
                "rearm_available": not bool(row["dispatch_enabled"]) and unresolved == 0}

    def close_dispatch_for_startup(self) -> dict:
        return self._advance_dispatch_control(enabled=False, actor_id="system",
                                              reason="PROCESS_RESTARTED",
                                              release_pre_dispatch=True,
                                              advance_authority_epoch=True)

    def trip_stop_latch(self, *, actor_id: str, reason: str = "SITE_STOP") -> dict:
        if not actor_id or len(actor_id) > 96 or not reason or len(reason) > 64:
            raise ValueError("invalid stop latch attribution")
        return self._advance_dispatch_control(enabled=False, actor_id=actor_id,
                                              reason=reason, release_pre_dispatch=True)

    def rearm_dispatch(self, *, expected_generation: int, actor_id: str) -> dict:
        if (isinstance(expected_generation, bool) or not isinstance(expected_generation, int)
                or expected_generation < 0 or not actor_id or len(actor_id) > 96):
            raise ValueError("invalid dispatch rearm request")
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if current["generation"] != expected_generation:
                raise InvalidTaskTransition("dispatch generation changed; refresh before rearm")
            if current["dispatch_enabled"]:
                raise InvalidTaskTransition("dispatch is already enabled")
            unresolved = connection.execute(
                "SELECT 1 FROM fleet_action_claims "
                "WHERE phase IN ('DISPATCHING', 'UNKNOWN') LIMIT 1"
            ).fetchone()
            if unresolved is not None:
                raise InvalidTaskTransition("unresolved Action claims must be reconciled before rearm")
            connection.execute(
                """UPDATE fleet_dispatch_control SET generation=generation+1,
                   dispatch_enabled=1, reason='OPERATOR_REARM', actor_id=?, updated_at=?
                   WHERE control_id=1 AND generation=? AND dispatch_enabled=0""",
                (actor_id, now, expected_generation),
            )
            connection.commit()
        return self.dispatch_control()

    def dispatch_generation_is_current(self, generation: int) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT 1 FROM fleet_dispatch_control
                   WHERE control_id=1 AND dispatch_enabled=1 AND generation=?""",
                (generation,),
            ).fetchone()
        return row is not None

    def abort_dispatch_before_send(self, task_id: str, *, attempt_id: str) -> dict:
        """Return an attempt to READY only when a stale permit prevented any send."""
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM fleet_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            control = connection.execute(
                "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if current is None:
                raise KeyError(task_id)
            if (current["dispatch_phase"] != "DISPATCHING"
                    or current["attempt_id"] != attempt_id
                    or (control["dispatch_enabled"]
                        and control["generation"] == current["dispatch_generation"])):
                raise InvalidTaskTransition("dispatch attempt is not fenced by a changed stop generation")
            reason = "STOP_GENERATION_CHANGED_BEFORE_SEND"
            connection.execute(
                """UPDATE fleet_tasks SET dispatch_phase='READY', attempt_id=NULL,
                   lease_owner=NULL, lease_until=NULL, reason=?, updated_at=?
                   WHERE task_id=?""",
                (reason, now, task_id),
            )
            connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?", (task_id,))
            release_dispatch_claims(connection, owner_kind="task", owner_id=task_id)
            self._append_history(connection, task_id, "QUEUED", "system", "fleet-dispatch",
                                 now, reason)
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                     (task_id,)).fetchone()
            connection.commit()
        return self._task_dict(row)

    def _advance_dispatch_control(self, *, enabled: bool, actor_id: str,
                                  reason: str, release_pre_dispatch: bool = False,
                                  advance_authority_epoch: bool = False) -> dict:
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE fleet_dispatch_control SET generation=generation+1,
                   authority_epoch=authority_epoch+?,
                   dispatch_enabled=?, reason=?, actor_id=?, updated_at=? WHERE control_id=1""",
                (int(advance_authority_epoch), int(enabled), reason, actor_id, now),
            )
            if release_pre_dispatch:
                rows = connection.execute(
                    """SELECT owner_kind, owner_id FROM fleet_action_claims
                       WHERE phase='CLAIMED'"""
                ).fetchall()
                for row in rows:
                    if row["owner_kind"] == "task":
                        connection.execute(
                            """UPDATE fleet_tasks SET lease_owner=NULL, lease_until=NULL,
                               updated_at=? WHERE task_id=? AND status='QUEUED'
                               AND dispatch_phase='READY'""",
                            (now, row["owner_id"]),
                        )
                        connection.execute(
                            "DELETE FROM fleet_robot_reservations WHERE task_id=?",
                            (row["owner_id"],),
                        )
                connection.execute("DELETE FROM fleet_action_claims WHERE phase='CLAIMED'")
            connection.commit()
        return self.dispatch_control()

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
            release_dispatch_claims(connection, owner_kind="task", owner_id=task_id)
            self._append_history(connection, task_id, "CANCELED", "operator", actor_id, now,
                                 "OPERATOR_CANCELED_BEFORE_DISPATCH")
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                     (task_id,)).fetchone()
            connection.commit()
        return self._task_dict(row)

    def cancel_queued_for_robot(self, robot_id: str, *, actor_id: str) -> list[str]:
        return self._cancel_queued_tasks(actor_id=actor_id, robot_id=robot_id)

    def cancel_all_queued(self, *, actor_id: str, reason: str | None = None) -> list[str]:
        return self._cancel_queued_tasks(actor_id=actor_id, reason=reason)  # D-421 reason

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
                release_dispatch_claims(connection, owner_kind="task",
                                         owner_id=row["task_id"])
            connection.commit()
        return recovered

    def transition(self, task_id: str, status: str, *, actor_id: str,
                   source: str, reason: str | None = None,
                   receipt: Mapping | None = None) -> dict:
        # D-170/D-293: this generic path has no correlated CORE final result.
        # D-177 activation must introduce a separate verified-result transition.
        if status in {"RUNNING", "COMPLETED"}:
            raise InvalidTaskTransition("verified CORE result is required for execution status")
        if status == "ACCEPTED" and (
            receipt is None or receipt.get("accepted") is not True
            or receipt.get("queued") is True
        ):
            raise InvalidTaskTransition("positive CORE receipt is required for acceptance")
        receipt_json = None if receipt is None else _safe_json(dict(receipt))
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM fleet_tasks WHERE task_id = ?",
                                         (task_id,)).fetchone()
            if current is None:
                raise KeyError(task_id)
            # A CORE event can race the REST receipt or its timeout. Never let a
            # late receipt/timeout downgrade an already correlated execution result.
            if (current["status"] in {"RUNNING", "COMPLETED", "FAILED", "HOLD"}  # D-421 HOLD
                    or (current["status"] == "UNKNOWN" and (
                        status == "ACCEPTED"
                        or current["reason"] == "CORE_CANCEL_RESULT_PENDING"
                    ))):
                connection.commit()
                return self._task_dict(current)
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
                release_dispatch_claims(connection, owner_kind="task", owner_id=task_id)
            connection.commit()
        return self._task_dict(row)

    def project_core_event(self, *, robot_id: str, event_id: str, seq: int,
                           event_type: str, correlation_id: str, source: str | None = None) -> dict | None:
        from fleet.server.task_results import project_core_event

        return project_core_event(
            self, robot_id=robot_id, event_id=event_id, seq=seq,
            event_type=event_type, correlation_id=correlation_id, source=source,
        )

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
            "dispatch_generation": row["dispatch_generation"],
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
        return configure_connection(connection)

    @staticmethod
    def _append_history(connection, task_id: str, status: str, source: str,
                        actor_id: str, now: str, reason: str | None = None) -> None:
        connection.execute(
            """INSERT INTO fleet_task_history
               (task_id, status, source, actor_id, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (task_id, status, source, actor_id, reason, now),
        )

    def _cancel_queued_tasks(self, *, actor_id: str, robot_id: str | None = None,
                             reason: str | None = None) -> list[str]:
        now, reason = _now(), reason or "OPERATOR_CANCELED_BEFORE_DISPATCH"
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT task_id FROM fleet_tasks WHERE status='QUEUED'
                   AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')
                   AND (? IS NULL OR robot_id=?)""", (robot_id, robot_id),
            ).fetchall()
            task_ids = [row["task_id"] for row in rows]
            for task_id in task_ids:
                connection.execute(
                    """UPDATE fleet_tasks SET status='CANCELED', dispatch_phase='CANCELED',
                       reason=?, blocked_by=NULL,
                       waiting_on_json='[]', lease_owner=NULL, lease_until=NULL, updated_at=?
                       WHERE task_id=?""",
                    (reason, now, task_id),
                )
                connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?",
                                   (task_id,))
                release_dispatch_claims(connection, owner_kind="task", owner_id=task_id)
                self._append_history(connection, task_id, "CANCELED", "operator", actor_id, now,
                                     reason)
            connection.commit()
        return task_ids

    @staticmethod
    def _migrate_dispatch_claims(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT OR IGNORE INTO fleet_action_claims
               (resource_key, resource_kind, resource_id, owner_kind, owner_id,
                generation, phase, lease_until, created_at)
               SELECT 'robot:' || r.robot_id, 'robot', r.robot_id, 'task', r.task_id,
                      COALESCE(t.dispatch_generation, 0),
                      CASE WHEN t.status='UNKNOWN' THEN 'UNKNOWN'
                           WHEN t.dispatch_phase='DISPATCHING' THEN 'DISPATCHING'
                           ELSE 'CLAIMED' END,
                      CASE WHEN t.dispatch_phase='READY' THEN t.lease_until ELSE NULL END,
                      r.reserved_at
               FROM fleet_robot_reservations r
               LEFT JOIN fleet_tasks t ON t.task_id=r.task_id"""
        )
        connection.commit()

    @staticmethod
    def _migrate_task_columns(connection: sqlite3.Connection) -> None:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(fleet_tasks)")}
        additions = {
            "priority_class": "INTEGER NOT NULL DEFAULT 0",
            "queued_at": "TEXT",
            "expires_at": "TEXT",
            "lease_owner": "TEXT",
            "lease_until": "TEXT",
            "dispatch_generation": "INTEGER NOT NULL DEFAULT 0",
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

    @staticmethod
    def _migrate_dispatch_control(connection: sqlite3.Connection) -> None:
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(fleet_dispatch_control)"
        )}
        if "authority_epoch" not in columns:
            connection.execute(
                "ALTER TABLE fleet_dispatch_control ADD COLUMN authority_epoch "
                "INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS fleet_tasks_queue_order "
            "ON fleet_tasks(status, priority_class, queued_at, task_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS fleet_tasks_dispatch_queue_position "
            "ON fleet_tasks(priority_class, queued_at, task_id) "
            "WHERE status='QUEUED' AND lease_owner IS NULL "
            "AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')"
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
