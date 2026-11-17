"""Durable, transcript-free outbox for bounded ER 2 reasoning turns."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from core_common.protocol.schemas import MissionFeedbackTurnScope

from .mission_model_turn_claims import MissionModelTurnClaimMixin, _now, _reason, _stamp
from .sqlite_policy import configure_connection, enable_wal


class MissionModelTurnStore(MissionModelTurnClaimMixin):
    """SQLite outbox with one client submission attempt per logical turn.

    Provider steps, signatures, prompts, images and tool payloads are never
    accepted by this API. After ``SUBMITTING`` a lost response is UNKNOWN and
    cannot be reclaimed for another provider POST.
    """

    def __init__(self, path: Path | str, *, claim_lease_seconds: int = 60,
                 max_rows: int = 10_000) -> None:
        if type(claim_lease_seconds) is not int or not 1 <= claim_lease_seconds <= 3600:
            raise ValueError("claim lease must be an integer from 1 to 3600 seconds")
        if type(max_rows) is not int or not 1 <= max_rows <= 1_000_000:
            raise ValueError("max_rows must be an integer from 1 to 1000000")
        self.path = Path(path)
        self.claim_lease_seconds = claim_lease_seconds
        self.max_rows = max_rows
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            enable_wal(connection)
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS fleet_mission_model_turns (
                    turn_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    workcell_id TEXT NOT NULL,
                    mission_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    dispatch_generation INTEGER NOT NULL,
                    event_watermark INTEGER NOT NULL,
                    model_policy_revision TEXT NOT NULL,
                    outcome_policy TEXT NOT NULL CHECK(outcome_policy IN ('STATUS_ONLY','STATUS_AND_REPLAN')),
                    trigger_event_id INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN (
                        'PENDING','CLAIMED','SUBMITTING','RESPONDED','REJECTED',
                        'UNKNOWN','SUPPRESSED')),
                    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count BETWEEN 0 AND 1),
                    claimed_by TEXT,
                    lease_until TEXT,
                    reason_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(mission_id, trigger_event_id, dispatch_generation, model_policy_revision)
                );
                CREATE INDEX IF NOT EXISTS fleet_model_turns_queue
                    ON fleet_mission_model_turns(state, created_at, turn_id);
                CREATE TABLE IF NOT EXISTS fleet_mission_model_turn_cursors (
                    cursor_name TEXT PRIMARY KEY,
                    event_id INTEGER NOT NULL CHECK(event_id >= 0),
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO fleet_mission_model_turn_cursors
                    (cursor_name, event_id, updated_at) VALUES ('feedback-v1', 0, '');
                CREATE TABLE IF NOT EXISTS fleet_mission_model_turn_capacity (
                    capacity_id INTEGER PRIMARY KEY CHECK(capacity_id=1),
                    dropped_count INTEGER NOT NULL DEFAULT 0 CHECK(dropped_count >= 0),
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO fleet_mission_model_turn_capacity
                    (capacity_id, dropped_count, updated_at) VALUES (1, 0, '');
            """)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def enqueue(self, *, scope: MissionFeedbackTurnScope | Mapping[str, Any],
                trigger_event_id: int) -> dict[str, Any]:
        parsed = (scope if isinstance(scope, MissionFeedbackTurnScope)
                  else MissionFeedbackTurnScope.model_validate(scope))
        if type(trigger_event_id) is not int or trigger_event_id < 0:
            raise ValueError("trigger_event_id must be a non-negative integer")
        if parsed.event_watermark < trigger_event_id:
            raise ValueError("captured event watermark cannot precede the trigger event")
        stamp = _stamp(_now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                """SELECT * FROM fleet_mission_model_turns WHERE mission_id=?
                   AND trigger_event_id=? AND dispatch_generation=?
                   AND model_policy_revision=?""",
                (parsed.mission_id, trigger_event_id, parsed.dispatch_generation,
                 parsed.model_policy_revision),
            ).fetchone()
            if prior is not None:
                prior_scope = {
                    key: prior[key] for key in (
                        "principal_id", "workcell_id", "mission_id", "action_id",
                        "attempt_id", "dispatch_generation", "event_watermark",
                        "model_policy_revision", "outcome_policy",
                    )
                }
                if prior_scope != parsed.model_dump():
                    connection.rollback()
                    raise ValueError("duplicate feedback trigger has conflicting trusted scope")
                connection.commit()
                return {"turn": self._row(prior), "created": False}
            row_count = connection.execute(
                "SELECT COUNT(*) FROM fleet_mission_model_turns",
            ).fetchone()[0]
            if row_count >= self.max_rows:
                connection.execute(
                    "UPDATE fleet_mission_model_turn_capacity SET dropped_count="
                    "dropped_count+1, updated_at=? WHERE capacity_id=1", (stamp,),
                )
                connection.commit()
                return {"turn": None, "created": False,
                        "reason_code": "OUTBOX_CAPACITY"}
            turn_id = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO fleet_mission_model_turns
                   (turn_id, principal_id, workcell_id, mission_id, action_id, attempt_id,
                    dispatch_generation, event_watermark, model_policy_revision,
                    outcome_policy, trigger_event_id, state, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)""",
                (turn_id, parsed.principal_id, parsed.workcell_id, parsed.mission_id,
                 parsed.action_id, parsed.attempt_id, parsed.dispatch_generation,
                 parsed.event_watermark, parsed.model_policy_revision,
                 parsed.outcome_policy, trigger_event_id, stamp, stamp),
            )
            row = connection.execute(
                "SELECT * FROM fleet_mission_model_turns WHERE turn_id=?", (turn_id,),
            ).fetchone()
            connection.commit()
        return {"turn": self._row(row), "created": True}

    def capacity_dropped_count(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT dropped_count FROM fleet_mission_model_turn_capacity WHERE capacity_id=1",
            ).fetchone()
        return int(row["dropped_count"]) if row is not None else 0

    def get(self, turn_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            return self._row(connection.execute(
                "SELECT * FROM fleet_mission_model_turns WHERE turn_id=?", (turn_id,),
            ).fetchone())

    def get_event_cursor(self, *, cursor_name: str = "feedback-v1") -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT event_id FROM fleet_mission_model_turn_cursors WHERE cursor_name=?",
                (cursor_name,),
            ).fetchone()
        if row is None:
            raise RuntimeError("feedback event cursor is missing")
        return int(row["event_id"])

    def advance_event_cursor(self, event_id: int, *,
                             cursor_name: str = "feedback-v1") -> int:
        if type(event_id) is not int or event_id < 0:
            raise ValueError("event cursor must be a non-negative integer")
        now = _stamp(_now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE fleet_mission_model_turn_cursors SET event_id=MAX(event_id, ?), "
                "updated_at=? WHERE cursor_name=?",
                (event_id, now, cursor_name),
            )
            row = connection.execute(
                "SELECT event_id FROM fleet_mission_model_turn_cursors WHERE cursor_name=?",
                (cursor_name,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise RuntimeError("feedback event cursor is missing")
            connection.commit()
        return int(row["event_id"])


__all__ = ["MissionModelTurnStore", "_now", "_reason", "_stamp"]
