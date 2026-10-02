"""Correlate CORE navigation events with one durable Fleet dispatch attempt."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Protocol

from fleet.server.cancel_all_store import CANCEL_ALL_REASON
from fleet.server.cancel_all_store import matching_tag as cancel_all_tag_matches
from fleet.server.dispatch_admission import release as release_dispatch_claims

_LOG = logging.getLogger(__name__)


class _TaskStore(Protocol):
    def _connect(self) -> sqlite3.Connection: ...

    @staticmethod
    def _append_history(connection, task_id: str, status: str, source: str,
                        actor_id: str, now: str, reason: str | None = None) -> None: ...

    @staticmethod
    def _task_dict(row) -> dict: ...


def project_core_event(store: _TaskStore, *, robot_id: str, event_id: str, seq: int,
                       event_type: str, correlation_id: str,
                       source: str | None = None) -> dict | None:
    """Apply a correlated navigation event once to its exact dispatch attempt.

    `source` is CORE's `data.source` when the event carries one (D-421 match rule)."""
    statuses = {
        "nav.started": ("RUNNING", None),
        "nav.completed": ("COMPLETED", None),
        "nav.failed": ("FAILED", "CORE_NAV_FAILED"),
        # NavigationManager emits nav.canceled after issuing a cancel request;
        # the action result and standstill are separate evidence.
        "nav.canceled": ("UNKNOWN", "CORE_CANCEL_RESULT_PENDING"),
    }
    mapped = statuses.get(event_type)
    if (mapped is None or not robot_id or not event_id or not correlation_id
            or isinstance(seq, bool) or not isinstance(seq, int) or seq < 1):
        return None

    status, reason = mapped
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    with closing(store._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        task = connection.execute(
            """SELECT * FROM fleet_tasks WHERE robot_id=? AND task_type='navigate'
               AND attempt_id=?""",
            (robot_id, correlation_id),
        ).fetchone()
        if task is None:
            connection.commit()
            return None

        prior = connection.execute(
            """SELECT seq FROM fleet_task_core_events
               WHERE robot_id=? AND attempt_id=? ORDER BY seq DESC LIMIT 1""",
            (robot_id, correlation_id),
        ).fetchone()
        duplicate = connection.execute(
            """SELECT event_id, task_id, attempt_id, seq, event_type
               FROM fleet_task_core_events WHERE robot_id=? AND event_id=?""",
            (robot_id, event_id),
        ).fetchone()
        if duplicate is not None:
            if (duplicate["task_id"] != task["task_id"]
                    or duplicate["attempt_id"] != correlation_id
                    or duplicate["seq"] != seq
                    or duplicate["event_type"] != event_type):
                raise ValueError("CORE event identity was reused with different content")
            connection.commit()
            return store._task_dict(task)
        if prior is not None and seq <= prior["seq"]:
            connection.commit()
            return store._task_dict(task)

        connection.execute(
            """INSERT INTO fleet_task_core_events
               (robot_id, event_id, task_id, attempt_id, seq, event_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (robot_id, event_id, task["task_id"], correlation_id, seq, event_type),
        )
        current_status = task["status"]
        dispatching = (current_status == "QUEUED"
                       and task["dispatch_phase"] == "DISPATCHING")
        if current_status == "HOLD" and task["reason"] == CANCEL_ALL_REASON:
            # D-421: settled by a cancel-all; a later correlated event is recorded, not applied.
            _LOG.warning("CORE %s for task %s after HOLD(FLEET_CANCEL_ALL) recorded, not applied",
                         event_type, task["task_id"])
        if event_type == "nav.canceled" and cancel_all_tag_matches(
                connection, task_id=task["task_id"], robot_id=robot_id,
                attempt_id=correlation_id, source=source, now=now):
            # D-421: CORE confirmed the cancel a cancel-all window asked for. HOLD is terminal,
            # so the robot claim is released and the robot can take new work.
            status, reason = "HOLD", CANCEL_ALL_REASON
        if ((current_status in {"RUNNING", "ACCEPTED", "UNKNOWN"} or dispatching)
                and status != current_status):
            terminal = status in {"COMPLETED", "FAILED", "HOLD"}
            connection.execute(
                "UPDATE fleet_tasks SET status=?, reason=?, updated_at=? WHERE task_id=?",
                (status, reason, now, task["task_id"]),
            )
            store._append_history(connection, task["task_id"], status,
                                  "core-event", robot_id, now, reason)
            if terminal:
                connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?",
                                   (task["task_id"],))
                release_dispatch_claims(connection, owner_kind="task",
                                         owner_id=task["task_id"])
            task = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                      (task["task_id"],)).fetchone()
        connection.commit()
    return store._task_dict(task)
