"""D-421 durable cancel-all record in the Fleet task journal database.

One row per cancel-all window (who, when, which robots, which queued tasks were
canceled, whose navigation cancel CORE answered) and one row per in-flight dispatch
attempt the window tagged. The CORE event projection (`task_results`) reads the tag:
a correlated `nav.canceled` is CORE evidence that a cancel was *issued* for that
attempt (not that the robot stands still, D-298). When it matches a tag the task
becomes `HOLD(FLEET_CANCEL_ALL)` and its robot claim is released. Without such an
event the task stays as it was — Fleet does not guess (D-170/D-293).

A match needs all of: the tag's `attempt_id` equals the event's correlation id; the
event source, when CORE gives one, is an API call (`api:*`); and either the window is
still open, or it closed at most `HOLD_GRACE_S` ago and that robot's navigation cancel
was answered (or the tag came from the dispatch fence's own re-cancel). A later
unrelated cancel of the same attempt (operator, stuck decision, safety) is not this
window's and stays `UNKNOWN`.

The tables are created by `FleetTaskStore` with the rest of the journal schema.
Future Mission cancels (D-420 §5.2) can reuse the record.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Iterable
from uuid import uuid4

from fleet.server.dispatch_admission import release as release_dispatch_claims

CANCEL_ALL_REASON = "FLEET_CANCEL_ALL"
DISPATCH_OVERLAP_REASON = "FLEET_CANCEL_ALL_DURING_DISPATCH"
#: A CORE nav.canceled for a tagged attempt counts for this long after the window closed.
#: CORE publishes it while serving navigation/cancel, so a healthy link delivers it within
#: seconds; 30 s covers a FleetAgent reconnect/replay without adopting much later cancels.
HOLD_GRACE_S = 30.0
#: Closed records (and their tags) older than this are pruned when a new window opens.
RETENTION_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS fleet_cancel_all (
    cancel_all_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    robot_ids_json TEXT NOT NULL,
    canceled_task_ids_json TEXT NOT NULL DEFAULT '[]',
    nav_answered_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS fleet_cancel_all_tasks (
    cancel_all_id TEXT NOT NULL REFERENCES fleet_cancel_all(cancel_all_id),
    task_id TEXT NOT NULL REFERENCES fleet_tasks(task_id),
    attempt_id TEXT NOT NULL,
    robot_id TEXT NOT NULL,
    origin TEXT NOT NULL CHECK(origin IN ('window', 'fence')),
    status_at_tag TEXT NOT NULL,
    tagged_at TEXT NOT NULL,
    PRIMARY KEY(cancel_all_id, task_id, attempt_id)
);
CREATE INDEX IF NOT EXISTS fleet_cancel_all_tasks_attempt
    ON fleet_cancel_all_tasks(task_id, attempt_id);
"""

_PRIOR_CANCEL = """EXISTS (SELECT 1 FROM fleet_task_core_events e
                    WHERE e.task_id=t.task_id AND e.attempt_id=t.attempt_id
                      AND e.event_type='nav.canceled')"""
#: In flight = may hold a CORE goal. An UNKNOWN attempt already canceled before the
#: window is an older cancel, not this window's.
_IN_FLIGHT = f"""t.attempt_id IS NOT NULL AND (t.status IN ('ACCEPTED', 'RUNNING')
                 OR (t.status='QUEUED' AND t.dispatch_phase='DISPATCHING')
                 OR (t.status='UNKNOWN' AND (t.updated_at >= ? OR NOT {_PRIOR_CANCEL})))"""


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def open_record(store, *, principal_id: str, robot_ids: Iterable[str]) -> dict:
    """Open the window record and tag every in-flight attempt of the robots in it."""
    record = {"cancel_all_id": str(uuid4()), "opened_at": _now()}
    robots = sorted(set(robot_ids))
    with closing(store._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        _prune(connection)
        connection.execute(
            """INSERT INTO fleet_cancel_all
               (cancel_all_id, principal_id, opened_at, robot_ids_json) VALUES (?, ?, ?, ?)""",
            (record["cancel_all_id"], principal_id, record["opened_at"], json.dumps(robots)),
        )
        _tag_in_flight(connection, record["cancel_all_id"], robots, record["opened_at"])
        connection.commit()
    return record


def _prune(connection) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat(
        timespec="milliseconds")
    connection.execute(
        """DELETE FROM fleet_cancel_all_tasks WHERE cancel_all_id IN (SELECT cancel_all_id
           FROM fleet_cancel_all WHERE closed_at IS NOT NULL AND closed_at < ?)""", (cutoff,))
    connection.execute("DELETE FROM fleet_cancel_all WHERE closed_at IS NOT NULL AND closed_at < ?",
                       (cutoff,))


def _tag_in_flight(connection, cancel_all_id: str, robots: list[str], opened_at: str) -> None:
    if not robots:
        return
    marks = ",".join("?" for _ in robots)
    connection.execute(
        f"""INSERT OR IGNORE INTO fleet_cancel_all_tasks
            (cancel_all_id, task_id, attempt_id, robot_id, origin, status_at_tag, tagged_at)
            SELECT ?, t.task_id, t.attempt_id, t.robot_id, 'window', t.status, ?
            FROM fleet_tasks AS t WHERE t.robot_id IN ({marks}) AND {_IN_FLIGHT}""",
        (cancel_all_id, _now(), *robots, opened_at),
    )


def _settle_already_canceled(connection, cancel_all_id: str, opened_at: str,
                             task_id: str | None = None) -> None:
    """CORE's nav.canceled may beat the tag (the window's own cancel hit a dispatch that
    was mid-flight). Such a task was projected UNKNOWN/CORE_CANCEL_RESULT_PENDING during
    this window: settle it as the projection would have, in this transaction."""
    rows = connection.execute(
        f"""SELECT t.task_id, t.robot_id FROM fleet_tasks AS t
            JOIN fleet_cancel_all_tasks AS g
              ON g.task_id=t.task_id AND g.attempt_id=t.attempt_id AND g.cancel_all_id=?
            WHERE t.status='UNKNOWN' AND t.reason='CORE_CANCEL_RESULT_PENDING'
              AND t.updated_at >= ? AND {_PRIOR_CANCEL} AND (? IS NULL OR t.task_id=?)""",
        (cancel_all_id, opened_at, task_id, task_id),
    ).fetchall()
    now = _now()
    for row in rows:
        hold(connection, row["task_id"], row["robot_id"], now)


def hold(connection, task_id: str, robot_id: str, now: str) -> None:
    """HOLD(FLEET_CANCEL_ALL): terminal, so the reservation and robot claim go."""
    connection.execute("UPDATE fleet_tasks SET status='HOLD', reason=?, updated_at=? "
                       "WHERE task_id=?", (CANCEL_ALL_REASON, now, task_id))
    connection.execute(
        """INSERT INTO fleet_task_history (task_id, status, source, actor_id, reason, created_at)
           VALUES (?, 'HOLD', 'core-event', ?, ?, ?)""", (task_id, robot_id, CANCEL_ALL_REASON, now))
    connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?", (task_id,))
    release_dispatch_claims(connection, owner_kind="task", owner_id=task_id)


def tag_task(store, cancel_all_id: str, task_id: str) -> None:
    """Tag the current attempt of one task the dispatch fence saw overlap the window."""
    with closing(store._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        opened = connection.execute("SELECT opened_at FROM fleet_cancel_all WHERE cancel_all_id=?",
                                    (cancel_all_id,)).fetchone()
        if opened is not None:
            connection.execute(
                """INSERT INTO fleet_cancel_all_tasks
                   (cancel_all_id, task_id, attempt_id, robot_id, origin, status_at_tag, tagged_at)
                   SELECT ?, task_id, attempt_id, robot_id, 'fence', status, ? FROM fleet_tasks
                   WHERE task_id=? AND attempt_id IS NOT NULL
                   ON CONFLICT(cancel_all_id, task_id, attempt_id) DO UPDATE SET origin='fence'""",
                (cancel_all_id, _now(), task_id),
            )
            _settle_already_canceled(connection, cancel_all_id, opened["opened_at"], task_id)
        connection.commit()


def close_record(store, cancel_all_id: str, *, canceled_task_ids: Iterable[str],
                 nav_answered: Iterable[str]) -> dict:
    """Close the window; tag in-flight work that appeared during it; read what still waits.

    Returns robot_id -> task ids still waiting for a CORE result: ACCEPTED/RUNNING, plus
    UNKNOWN changed at or after the window opened (an older UNKNOWN is not this window's).
    """
    with closing(store._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT opened_at, robot_ids_json FROM fleet_cancel_all WHERE cancel_all_id=?",
            (cancel_all_id,),
        ).fetchone()
        robots = json.loads(row["robot_ids_json"])
        _tag_in_flight(connection, cancel_all_id, robots, row["opened_at"])
        _settle_already_canceled(connection, cancel_all_id, row["opened_at"])
        connection.execute(
            """UPDATE fleet_cancel_all SET closed_at=?, canceled_task_ids_json=?,
               nav_answered_json=? WHERE cancel_all_id=?""",
            (_now(), json.dumps(sorted(canceled_task_ids)), json.dumps(sorted(nav_answered)),
             cancel_all_id),
        )
        awaiting: dict[str, list[str]] = {robot: [] for robot in robots}
        if robots:
            marks = ",".join("?" for _ in robots)
            for task in connection.execute(
                    f"""SELECT task_id, robot_id FROM fleet_tasks WHERE robot_id IN ({marks})
                        AND (status IN ('ACCEPTED', 'RUNNING')
                             OR (status='UNKNOWN' AND updated_at >= ?))
                        ORDER BY created_at, task_id""", (*robots, row["opened_at"])):
                awaiting[task["robot_id"]].append(task["task_id"])
        connection.commit()
    return awaiting


def matching_tag(connection: sqlite3.Connection, *, task_id: str, robot_id: str,
                 attempt_id: str, source: str | None, now: str) -> bool:
    """True when this nav.canceled is the cancel a cancel-all window issued (see module doc)."""
    if source is not None and not str(source).startswith("api:"):
        return False
    tags = connection.execute(
        """SELECT g.origin, r.closed_at, r.nav_answered_json FROM fleet_cancel_all_tasks AS g
           JOIN fleet_cancel_all AS r ON r.cancel_all_id=g.cancel_all_id
           WHERE g.task_id=? AND g.attempt_id=?""", (task_id, attempt_id)).fetchall()
    for tag in tags:
        if tag["closed_at"] is None:
            return True
        cutoff = (datetime.fromisoformat(tag["closed_at"])
                  + timedelta(seconds=HOLD_GRACE_S)).isoformat(timespec="milliseconds")
        answered = tag["origin"] == "fence" or robot_id in json.loads(tag["nav_answered_json"])
        if answered and now <= cutoff:
            return True
    return False


def record(store, cancel_all_id: str) -> dict | None:
    with closing(store._connect()) as connection:
        row = connection.execute("SELECT * FROM fleet_cancel_all WHERE cancel_all_id=?",
                                 (cancel_all_id,)).fetchone()
        if row is None:
            return None
        tasks = connection.execute(
            """SELECT task_id, attempt_id, robot_id, origin, status_at_tag
               FROM fleet_cancel_all_tasks WHERE cancel_all_id=? ORDER BY task_id""",
            (cancel_all_id,)).fetchall()
    out = dict(row)
    out["robot_ids"] = json.loads(out.pop("robot_ids_json"))
    out["canceled_task_ids"] = json.loads(out.pop("canceled_task_ids_json"))
    out["nav_answered"] = json.loads(out.pop("nav_answered_json"))
    out["tagged_tasks"] = [dict(task) for task in tasks]
    return out
