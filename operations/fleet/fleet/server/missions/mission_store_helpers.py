"""Schema, event helper, and query/hold operations for MissionStore."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Mapping

from core_common.protocol.schemas import MISSION_EVENT_DETAIL_MAX_BYTES

from .dispatch_admission import release as release_dispatch_claims


class MissionConflict(ValueError):
    """Mission request, admission, or event conflicts with durable state."""


def _phase_event_key(mission_id: str, action_id: str, attempt_id: str,
                     ordinal: int, local_event_id: int) -> str:
    identity = f"{mission_id}:{action_id}:{attempt_id}:{ordinal}:{local_event_id}"
    return "phase:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _nonempty(name: str, value: object, *, limit: int = 192) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > limit or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{name} must be a non-empty trimmed string of at most {limit} characters")
    return value


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Mission data must be finite JSON") from exc


def _json_utf8_size(value: object) -> int:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return len(encoded)


def _ensure_mission_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS fleet_missions (
            mission_id TEXT PRIMARY KEY,
            step_id TEXT NOT NULL UNIQUE,
            principal_id TEXT NOT NULL,
            request_key TEXT NOT NULL,
            request_digest TEXT NOT NULL,
            action_kind TEXT NOT NULL CHECK(action_kind='PICK_PLACE'),
            workcell_id TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            goal_predicate_json TEXT NOT NULL,
            resources_json TEXT,
            action_grant_json TEXT,
            reconciliation_pending INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL CHECK(status IN (
                'PROPOSED', 'READY', 'RUNNING', 'ACTION_SUCCEEDED',
                'GOAL_CONFIRMED', 'HOLD', 'CANCELED'
            )),
            dispatch_generation INTEGER,
            authority_epoch INTEGER,
            action_id TEXT,
            attempt_id TEXT,
            supersedes_mission_id TEXT,
            reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(principal_id, request_key)
        );
        CREATE INDEX IF NOT EXISTS fleet_missions_status
            ON fleet_missions(status, updated_at);
        CREATE TABLE IF NOT EXISTS fleet_mission_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_source TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            mission_id TEXT NOT NULL REFERENCES fleet_missions(mission_id),
            step_id TEXT NOT NULL,
            action_id TEXT,
            attempt_id TEXT,
            state TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(event_source, source_event_id)
        );
        CREATE INDEX IF NOT EXISTS fleet_mission_events_mission
            ON fleet_mission_events(mission_id, event_id);
        CREATE INDEX IF NOT EXISTS fleet_mission_events_attempt
            ON fleet_mission_events(
                mission_id, action_id, attempt_id, event_id
            );
        CREATE TABLE IF NOT EXISTS fleet_mission_event_retention (
            mission_id TEXT PRIMARY KEY REFERENCES fleet_missions(mission_id),
            cursor_floor INTEGER NOT NULL DEFAULT 0 CHECK(cursor_floor >= 0)
        );
        """
    )
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(fleet_missions)").fetchall()}
    if "authority_epoch" not in columns:
        connection.execute("ALTER TABLE fleet_missions ADD COLUMN authority_epoch INTEGER")
    if "action_grant_json" not in columns:
        connection.execute("ALTER TABLE fleet_missions ADD COLUMN action_grant_json TEXT")
    if "reconciliation_pending" not in columns:
        connection.execute(
            "ALTER TABLE fleet_missions ADD COLUMN reconciliation_pending "
            "INTEGER NOT NULL DEFAULT 0"
        )
    if "supersedes_mission_id" not in columns:
        connection.execute("ALTER TABLE fleet_missions ADD COLUMN supersedes_mission_id TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS fleet_missions_ready_queue "
        "ON fleet_missions(status, created_at, mission_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS fleet_missions_reconcile_queue "
        "ON fleet_missions(reconciliation_pending, updated_at, mission_id)"
    )


class MissionStoreHelpersMixin:
    """Row decoding, event persistence, holds, and read queries for MissionStore."""

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for field in ("plan_json", "goal_predicate_json", "resources_json",
                      "action_grant_json"):
            if result[field] is not None:
                result[field.removesuffix("_json")] = json.loads(result[field])
                del result[field]
        return result

    def _event(self, connection: sqlite3.Connection, *, event_source: str,
               source_event_id: str, mission: sqlite3.Row, event_type: str,
               state: str, actor_id: str, detail: object,
               action_id: str | None = None, attempt_id: str | None = None) -> bool:
        source_event_id = _nonempty("source_event_id", source_event_id)
        event_source = _nonempty("event_source", event_source, limit=48)
        detail_json = _json(detail)
        if _json_utf8_size(detail) > MISSION_EVENT_DETAIL_MAX_BYTES:
            raise ValueError("Mission event detail exceeds the 16 KiB limit")
        prior = connection.execute(
            "SELECT * FROM fleet_mission_events WHERE event_source=? AND source_event_id=?",
            (event_source, source_event_id),
        ).fetchone()
        if prior is not None:
            if (prior["mission_id"] != mission["mission_id"]
                    or prior["step_id"] != mission["step_id"]
                    or prior["action_id"] != action_id
                    or prior["attempt_id"] != attempt_id
                    or prior["state"] != state
                    or prior["event_type"] != event_type
                    or prior["actor_id"] != actor_id
                    or prior["detail_json"] != detail_json):
                raise MissionConflict("event identity was reused with different Mission evidence")
            return False
        connection.execute(
            """INSERT INTO fleet_mission_events
               (event_source, source_event_id, mission_id, step_id, action_id, attempt_id,
                state, event_type, actor_id, detail_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_source, source_event_id, mission["mission_id"], mission["step_id"],
             action_id, attempt_id, state, event_type, actor_id, detail_json, _now()),
        )
        return True

    def hold_ready(self, mission_id: str, *, actor_id: str, reason: str) -> dict[str, Any]:
        actor_id = _nonempty("actor_id", actor_id, limit=96)
        reason = _nonempty("reason", reason, limit=96)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
            ).fetchone()
            if row is None:
                raise KeyError(mission_id)
            if row["status"] != "READY":
                raise MissionConflict("only a READY Mission may be held before dispatch")
            connection.execute(
                "UPDATE fleet_missions SET status='HOLD', reason=?, updated_at=? "
                "WHERE mission_id=?",
                (reason, _now(), mission_id),
            )
            self._event(
                connection, event_source="fleet_mission",
                source_event_id=f"pre-dispatch-hold:{mission_id}:{reason}",
                mission=row, event_type="MISSION_HELD_BEFORE_DISPATCH", state="HOLD",
                actor_id=actor_id, detail={"reason": reason},
            )
            release_dispatch_claims(
                connection, owner_kind="mission", owner_id=mission_id,
                generation=row["dispatch_generation"],
            )
            updated = connection.execute(
                "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
            ).fetchone()
            connection.commit()
        return self._row(updated)

    def hold_mission(self, mission_id: str, *, actor_id: str, event_id: str,
                     reason: str, evidence: Mapping[str, Any],
                     event_type: str = "GOAL_EVIDENCE_REJECTED") -> dict[str, Any]:
        reason = _nonempty("reason", reason, limit=96)
        if event_type not in {"GOAL_EVIDENCE_REJECTED", "GOAL_PREDICATE_UNSATISFIED"}:
            raise ValueError("invalid goal evidence hold event type")
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
            if row is None:
                raise KeyError(mission_id)
            if row["status"] not in {"ACTION_SUCCEEDED", "HOLD"}:
                raise MissionConflict("only an Action result or held Mission can be reconciled")
            connection.execute(
                "UPDATE fleet_missions SET status='HOLD', reason=?, updated_at=? WHERE mission_id=?",
                (reason, now, mission_id),
            )
            self._event(
                connection, event_source="goal_evidence", source_event_id=event_id,
                mission=row, event_type=event_type, state="HOLD",
                actor_id=actor_id, action_id=row["action_id"], attempt_id=row["attempt_id"],
                detail={"reason": reason, "evidence": dict(evidence)},
            )
            updated = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                         (mission_id,)).fetchone()
            connection.commit()
        return self._row(updated)

    @staticmethod
    def _terminal_action_succeeded(connection, mission_id: str, action_id: str,
                                   attempt_id: str) -> bool:
        terminal = connection.execute(
            """SELECT detail_json FROM fleet_mission_events
               WHERE mission_id=? AND action_id=? AND attempt_id=?
                 AND event_source='device_action' AND event_type='ACTION_TERMINAL_RESULT'
               ORDER BY event_id DESC LIMIT 1""",
            (mission_id, action_id, attempt_id),
        ).fetchone()
        return terminal is not None and json.loads(terminal["detail_json"]).get("outcome") == "SUCCEEDED"

    def terminal_action_succeeded(self, mission_id: str, *, action_id: str,
                                  attempt_id: str) -> bool:
        """Read durable terminal proof for exactly one Action attempt."""
        with closing(self._connect()) as connection:
            return self._terminal_action_succeeded(connection, mission_id, action_id, attempt_id)

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
        return self._row(row)

    def next_ready_mission(self) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM fleet_missions WHERE status='READY' "
                "ORDER BY created_at, mission_id LIMIT 1",
            ).fetchone()
        return self._row(row)

    def next_dispatch_mission(self, instances: Mapping[str, str], *, after_id: str) -> dict[str, Any] | None:
        """One bounded round-robin choice; unresolved attempts remain readable without configuration."""
        clauses = ["status='RUNNING'", "reconciliation_pending=1"]
        values = []
        for workcell_id, instance_id in instances.items():
            clauses.append("(status='READY' AND workcell_id=? AND instance_id=?)")
            values.extend((workcell_id, instance_id))
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM fleet_missions WHERE (" + " OR ".join(clauses) + ") "
                "ORDER BY CASE WHEN mission_id>? THEN 0 ELSE 1 END, mission_id LIMIT 1",
                [*values, after_id],
            ).fetchone()
        return self._row(row)

    def missions_awaiting_goal_evidence(self) -> list[dict[str, Any]]:
        """Return successful terminal Actions that have not confirmed their goal."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT m.*, e.created_at AS action_terminal_at
                   FROM fleet_missions AS m
                   JOIN fleet_mission_events AS e
                     ON e.mission_id=m.mission_id
                    AND e.action_id=m.action_id AND e.attempt_id=m.attempt_id
                    AND e.event_type='ACTION_TERMINAL_RESULT' AND e.state='ACTION_SUCCEEDED'
                   WHERE m.status='ACTION_SUCCEEDED'
                   ORDER BY e.event_id""",
            ).fetchall()
        return [self._row(row) | {"action_terminal_at": row["action_terminal_at"]}
                for row in rows]

    def finish_reconciliation(self, mission_id: str, *, action_id: str,
                              attempt_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
            ).fetchone()
            if row is None:
                raise KeyError(mission_id)
            if (row["action_id"] != action_id or row["attempt_id"] != attempt_id
                    or not row["reconciliation_pending"]):
                raise MissionConflict("reconciliation does not match a pending Action attempt")
            connection.execute(
                "UPDATE fleet_missions SET reconciliation_pending=0, updated_at=? "
                "WHERE mission_id=?", (_now(), mission_id),
            )
            updated = connection.execute(
                "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
            ).fetchone()
            connection.commit()
        return self._row(updated)

    def history(self, mission_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM fleet_mission_events WHERE mission_id=? ORDER BY event_id",
                (mission_id,),
            ).fetchall()
        result = [dict(row) for row in rows]
        for event in result:
            event["detail"] = json.loads(event.pop("detail_json"))
        return result

    def progress_snapshot_data(self, mission_id: str) -> dict[str, Any] | None:
        """Read Mission, history watermark, and Fleet stop fence in one SQLite snapshot."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            recent_events = connection.execute(
                "SELECT * FROM fleet_mission_events WHERE mission_id=? "
                "ORDER BY event_id DESC LIMIT 51",
                (mission_id,),
            ).fetchall()
            events = list(reversed(recent_events[:50]))
            active_action_events, active_goal_events, active_phase_events = [], [], []
            if row["action_id"] and row["attempt_id"]:
                active_action_events = connection.execute(
                    "SELECT * FROM fleet_mission_events WHERE mission_id=? "
                    "AND action_id=? AND attempt_id=? AND event_type IN "
                    "('STEP_SUBMITTED', 'ACTION_TERMINAL_RESULT') "
                    "ORDER BY event_id DESC LIMIT 1",
                    (mission_id, row["action_id"], row["attempt_id"]),
                ).fetchall()
                active_goal_events = connection.execute(
                    "SELECT * FROM fleet_mission_events WHERE mission_id=? "
                    "AND action_id=? AND attempt_id=? AND event_type IN "
                    "('GOAL_PREDICATE_CONFIRMED', 'GOAL_EVIDENCE_REJECTED', "
                    "'GOAL_PREDICATE_UNSATISFIED') "
                    "ORDER BY event_id DESC LIMIT 1",
                    (mission_id, row["action_id"], row["attempt_id"]),
                ).fetchall()
                active_phase_events = connection.execute(
                    "SELECT * FROM fleet_mission_events WHERE mission_id=? AND action_id=? "
                    "AND attempt_id=? AND event_source='device_action_phase' "
                    "ORDER BY event_id",
                    (mission_id, row["action_id"], row["attempt_id"]),
                ).fetchall()
            control = connection.execute(
                "SELECT authority_epoch, generation, dispatch_enabled, reason, updated_at "
                "FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            retention = connection.execute(
                "SELECT cursor_floor FROM fleet_mission_event_retention WHERE mission_id=?",
                (mission_id,),
            ).fetchone()
            connection.commit()
        history = [dict(event) for event in events]
        progress_events = [dict(event) for event in (
            *active_action_events, *active_goal_events, *active_phase_events,
        )]
        for event in [*history, *progress_events]:
            event["detail"] = json.loads(event.pop("detail_json"))
        return {
            "mission": self._row(row),
            "history": history,
            "history_truncated": len(recent_events) > 50 or bool(
                retention and int(retention["cursor_floor"]) > 0
            ),
            "progress_events": progress_events,
            "snapshot_event_id": max(
                int(recent_events[0]["event_id"]) if recent_events else 0,
                int(retention["cursor_floor"]) if retention else 0,
            ),
            "cursor_floor": int(retention["cursor_floor"]) if retention else 0,
            "stop_control": dict(control) if control else None,
        }

    def mission_events_after(self, mission_id: str, *, after_event_id: int,
                             limit: int) -> dict[str, Any] | None:
        """Read one bounded journal page and its cursor bounds atomically."""
        if (isinstance(after_event_id, bool) or not isinstance(after_event_id, int)
                or after_event_id < 0):
            raise ValueError("after_event_id must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            mission = connection.execute(
                "SELECT 1 FROM fleet_missions WHERE mission_id=?", (mission_id,),
            ).fetchone()
            if mission is None:
                connection.rollback()
                return None
            watermark = connection.execute(
                "SELECT COALESCE(MAX(event_id), 0) FROM fleet_mission_events "
                "WHERE mission_id=?", (mission_id,),
            ).fetchone()[0]
            retention = connection.execute(
                "SELECT cursor_floor FROM fleet_mission_event_retention WHERE mission_id=?",
                (mission_id,),
            ).fetchone()
            floor = int(retention["cursor_floor"]) if retention else 0
            watermark = max(int(watermark), floor)
            if after_event_id < floor or after_event_id > watermark:
                connection.commit()
                return {
                    "snapshot_event_id": int(watermark),
                    "cursor_floor": floor,
                    "cursor_state": "EXPIRED" if after_event_id < floor else "AHEAD",
                    "events": [],
                    "next_after_event_id": after_event_id,
                    "has_more": False,
                }
            rows = connection.execute(
                "SELECT * FROM fleet_mission_events WHERE mission_id=? AND event_id>? "
                "ORDER BY event_id LIMIT ?",
                (mission_id, after_event_id, limit + 1),
            ).fetchall()
            connection.commit()
        has_more = len(rows) > limit
        events = [dict(row) for row in rows[:limit]]
        for event in events:
            event["detail"] = json.loads(event.pop("detail_json"))
        next_cursor = events[-1]["event_id"] if events else after_event_id
        return {
            "snapshot_event_id": int(watermark),
            "cursor_floor": floor,
            "cursor_state": "OK",
            "events": events,
            "next_after_event_id": int(next_cursor),
            "has_more": has_more,
        }

    def feedback_events_after(self, *, after_event_id: int,
                              limit: int = 100) -> list[dict[str, Any]]:
        """Read a bounded global journal page for the feedback outbox scanner."""
        if type(after_event_id) is not int or after_event_id < 0:
            raise ValueError("after_event_id must be a non-negative integer")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("feedback event page limit must be from 1 to 500")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT event_id, mission_id, action_id, attempt_id, event_type
                   FROM fleet_mission_events WHERE event_id>? ORDER BY event_id LIMIT ?""",
                (after_event_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]
