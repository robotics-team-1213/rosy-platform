"""Read-only queries, row decoders, and JSON/validation primitives for MissionStore."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Mapping


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


_PHASE_ALLOWED_NEXT = {
    "SUBMITTING": {"ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "SUCCEEDED", "FAILED", "CANCELED"},
    "ACCEPTED": {"RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "SUCCEEDED", "FAILED", "CANCELED"},
    "RUNNING": {"CANCEL_REQUESTED", "UNKNOWN", "SUCCEEDED", "FAILED", "CANCELED"},
    "CANCEL_REQUESTED": {"UNKNOWN", "SUCCEEDED", "FAILED", "CANCELED"},
}


def _prepare_phase_entry(mission_id: str, action_id: str, attempt_id: str,
                         phase: Mapping[str, Any]) -> tuple[int, int, str, dict[str, Any]]:
    if not isinstance(phase, Mapping):
        raise ValueError("phase snapshot must be an object")
    ordinal, source_event_id = phase.get("ordinal"), phase.get("journal_event_id")
    if (type(ordinal) is not int or not 0 <= ordinal < 4
            or type(source_event_id) is not int or source_event_id < 1):
        raise ValueError("phase snapshot identity is invalid")
    detail = {
        "phase_id": phase["phase_id"], "ordinal": ordinal, "state": phase["state"],
        "observed_at": phase["observed_at"], "source_journal_event_id": source_event_id,
    }
    return ordinal, source_event_id, _phase_event_key(mission_id, action_id, attempt_id, ordinal, source_event_id), detail


def _confirm_phase_transition(latest: dict[int, dict[str, Any]], ordinal: int,
                              source_event_id: int, state: str,
                              detail: dict[str, Any]) -> None:
    previous = latest.get(ordinal)
    if previous is not None:
        if source_event_id <= previous["detail"]["source_journal_event_id"]:
            return
        prior_state = previous["detail"]["state"]
        if (prior_state not in _PHASE_ALLOWED_NEXT
                or state not in _PHASE_ALLOWED_NEXT[prior_state] and state != prior_state):
            raise MissionConflict("phase receipt regresses or changes a terminal phase")
    if ordinal > 0:
        previous_phase = latest.get(ordinal - 1)
        if previous_phase is None or previous_phase["detail"]["state"] != "SUCCEEDED":
            raise MissionConflict("phase receipt skips an unconfirmed prior phase")
    latest[ordinal] = {"detail": detail}


class MissionStoreQueriesMixin:
    """Row decoding and read-only SQLite queries for MissionStore."""

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for field in ("plan_json", "goal_predicate_json", "resources_json", "action_grant_json"):
            if result[field] is not None:
                result[field.removesuffix("_json")] = json.loads(result[field])
                del result[field]
        return result

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
                "SELECT * FROM fleet_mission_events WHERE mission_id=? ORDER BY event_id DESC LIMIT 51",
                (mission_id,),
            ).fetchall()
            events = list(reversed(recent_events[:50]))
            active_action_events, active_goal_events, active_phase_events = [], [], []
            if row["action_id"] and row["attempt_id"]:
                active_action_events = connection.execute(
                    "SELECT * FROM fleet_mission_events WHERE mission_id=? "
                    "AND action_id=? AND attempt_id=? AND event_type IN "
                    "('STEP_SUBMITTED', 'ACTION_TERMINAL_RESULT') ORDER BY event_id DESC LIMIT 1",
                    (mission_id, row["action_id"], row["attempt_id"]),
                ).fetchall()
                active_goal_events = connection.execute(
                    "SELECT * FROM fleet_mission_events WHERE mission_id=? "
                    "AND action_id=? AND attempt_id=? AND event_type IN "
                    "('GOAL_PREDICATE_CONFIRMED', 'GOAL_EVIDENCE_REJECTED', "
                    "'GOAL_PREDICATE_UNSATISFIED') ORDER BY event_id DESC LIMIT 1",
                    (mission_id, row["action_id"], row["attempt_id"]),
                ).fetchall()
                active_phase_events = connection.execute(
                    "SELECT * FROM fleet_mission_events WHERE mission_id=? AND action_id=? "
                    "AND attempt_id=? AND event_source='device_action_phase' ORDER BY event_id",
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
        floor = int(retention["cursor_floor"]) if retention else 0
        return {
            "mission": self._row(row),
            "history": history,
            "history_truncated": len(recent_events) > 50 or floor > 0,
            "progress_events": progress_events,
            "snapshot_event_id": max(int(recent_events[0]["event_id"]) if recent_events else 0, floor),
            "cursor_floor": floor,
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
                "SELECT COALESCE(MAX(event_id), 0) FROM fleet_mission_events WHERE mission_id=?",
                (mission_id,),
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
                    "snapshot_event_id": int(watermark), "cursor_floor": floor,
                    "cursor_state": "EXPIRED" if after_event_id < floor else "AHEAD",
                    "events": [], "next_after_event_id": after_event_id, "has_more": False,
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
            "snapshot_event_id": int(watermark), "cursor_floor": floor, "cursor_state": "OK",
            "events": events, "next_after_event_id": int(next_cursor), "has_more": has_more,
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
