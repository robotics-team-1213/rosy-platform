"""Durable task state and append-only transition history for site Fleet."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path

from fleet.server.cancel_all_store import ensure_schema as ensure_cancel_all_schema
from fleet.server.control_stop_schema import ensure_schema as ensure_control_stop_schema
from fleet.server.dispatch_admission import release as release_dispatch_claims
from fleet.server.sqlite_policy import configure_connection, enable_wal
from fleet.server.task_payloads import safe_json as _safe_json
from fleet.server.task_schema import TaskSchemaMigrations

from . import task_store_queries as _queries
from .task_dispatch_control import TaskDispatchControl
from .task_dispatch_queue import TaskDispatchQueue
from .task_store_types import IdempotencyConflict, InvalidTaskTransition, _now

_TASK_TRANSITIONS = {
    "REQUESTED": {"QUEUED", "ACCEPTED", "FAILED", "UNKNOWN", "HOLD"},
    "QUEUED": {"ACCEPTED", "FAILED", "UNKNOWN", "HOLD", "CANCELED", "EXPIRED"},
    "ACCEPTED": {"RUNNING", "COMPLETED", "FAILED", "UNKNOWN", "HOLD"},
    "RUNNING": {"COMPLETED", "FAILED", "UNKNOWN", "HOLD"},
    "UNKNOWN": {"ACCEPTED", "RUNNING", "COMPLETED", "FAILED", "HOLD"},
    "FAILED": set(), "COMPLETED": set(), "HOLD": set(), "CANCELED": set(), "EXPIRED": set(),
}
_QUEUE_POSITION_QUERY = _queries._QUEUE_POSITION_QUERY


class FleetTaskStore(TaskSchemaMigrations, TaskDispatchControl, TaskDispatchQueue):
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
            ensure_control_stop_schema(connection)
        if os.name != "nt":
            self.path.chmod(0o600)

    begin_api_audit = _queries.begin_api_audit
    finish_api_audit = _queries.finish_api_audit
    api_audit = _queries.api_audit
    queued_task_ids = _queries.queued_task_ids
    unfinished_task_ids = _queries.unfinished_task_ids
    get_task = _queries.get_task
    history = _queries.history
    _task_dict = staticmethod(_queries._task_dict)

    def create_task(self, *, task_id: str, robot_id: str, task_type: str,
                    source: str, actor_id: str, request_key: str,
                    request: Mapping, evidence: Mapping | None, admission=None) -> dict:
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
                if admission is not None:
                    admission(connection, existing['task_id'])
                connection.commit()
                return {"created": False, "task": self._task_dict(existing)}

            if admission is not None:
                admission(connection, task_id)
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
                """SELECT task_id, dispatch_phase, lease_owner FROM fleet_tasks
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
                if row["lease_owner"] or row["dispatch_phase"] == "WAITING_TRAFFIC":
                    # The restart took a held lease (or an interrupted traffic wait) away;
                    # the ledger keeps the audit row. Untouched READY rows stay quiet.
                    self._append_history(connection, row["task_id"], "QUEUED", "system",
                                         "fleet-recovery", now, "LEASE_RECLAIMED")
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
            old_receipt = json.loads(current['receipt_json'] or '{}')
            if old_receipt.get('operation') or old_receipt.get('native_required'):
                new_receipt = _safe_json(json.loads(new_receipt or '{}') | old_receipt)
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
            if status in {"FAILED", "COMPLETED", "HOLD", "CANCELED", "EXPIRED"} and not (
                    new_receipt and (json.loads(new_receipt).get('operation') or json.loads(new_receipt).get('native_required'))):
                connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?",
                                   (task_id,))
                release_dispatch_claims(connection, owner_kind="task", owner_id=task_id)
            connection.commit()
        return self._task_dict(row)

    def project_core_event(self, *, robot_id: str, event_id: str, seq: int,
                           event_type: str, correlation_id: str, source: str | None = None,
                           run_id=None, boot_id=None, error_code=None) -> dict | None:
        from fleet.server.task_results import project_core_event

        return project_core_event(
            self, robot_id=robot_id, event_id=event_id, seq=seq,
            event_type=event_type, correlation_id=correlation_id, source=source,
            run_id=run_id, boot_id=boot_id, error_code=error_code,
        )

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
