"""Schema, event helper, validation, and hold operations for MissionStore."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Any, Mapping

from core_common.protocol.schemas import (
    DeviceActionPhaseReceipt, MISSION_EVENT_DETAIL_MAX_BYTES,
)
from fleet.server.mission_store_queries import (
    MissionConflict,
    MissionStoreQueriesMixin,
    _confirm_phase_transition,
    _json,
    _json_utf8_size,
    _nonempty,
    _now,
    _phase_event_key,
    _prepare_phase_entry,
)

from .dispatch_admission import release as release_dispatch_claims


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
            ON fleet_mission_events(mission_id, action_id, attempt_id, event_id);
        CREATE TABLE IF NOT EXISTS fleet_mission_event_retention (
            mission_id TEXT PRIMARY KEY REFERENCES fleet_missions(mission_id),
            cursor_floor INTEGER NOT NULL DEFAULT 0 CHECK(cursor_floor >= 0)
        );
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(fleet_missions)").fetchall()}
    if "authority_epoch" not in columns:
        connection.execute("ALTER TABLE fleet_missions ADD COLUMN authority_epoch INTEGER")
    if "action_grant_json" not in columns:
        connection.execute("ALTER TABLE fleet_missions ADD COLUMN action_grant_json TEXT")
    if "reconciliation_pending" not in columns:
        connection.execute(
            "ALTER TABLE fleet_missions ADD COLUMN reconciliation_pending INTEGER NOT NULL DEFAULT 0"
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


def _check_step_start_claims(connection: sqlite3.Connection, mission_id: str,
                             expected_authority_epoch: int,
                             expected_generation: int
                             ) -> tuple[sqlite3.Row, sqlite3.Row, str | None, str | None]:
    row = connection.execute(
        "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
    ).fetchone()
    if row is None:
        raise KeyError(mission_id)
    control = connection.execute(
        "SELECT authority_epoch, generation, dispatch_enabled "
        "FROM fleet_dispatch_control WHERE control_id=1"
    ).fetchone()
    if row["status"] != "READY":
        raise MissionConflict("only a READY Mission step may start")
    rejected_reason = None
    if (not control["dispatch_enabled"] or control["authority_epoch"] != expected_authority_epoch
            or control["generation"] != expected_generation
            or row["authority_epoch"] != expected_authority_epoch
            or row["dispatch_generation"] != expected_generation):
        rejected_reason = "Fleet authority or stop generation changed before Mission step submission"
    else:
        resources = json.loads(row["resources_json"] or "[]")
        expected_keys = {f"{kind}:{resource}" for kind, resource in resources}
        claims = connection.execute(
            """SELECT resource_key FROM fleet_action_claims WHERE owner_kind='mission'
               AND owner_id=? AND generation=? AND phase='CLAIMED'""",
            (mission_id, expected_generation),
        ).fetchall()
        if {claim["resource_key"] for claim in claims} != expected_keys:
            rejected_reason = "Mission resource claim is no longer complete"
    reason_code = (None if not rejected_reason
                   else "FLEET_FENCE_CHANGED_BEFORE_SUBMISSION" if "generation" in rejected_reason
                   else "MISSION_RESOURCE_CLAIM_LOST")
    return row, control, rejected_reason, reason_code


def _check_action_result(connection: sqlite3.Connection, mission_id: str, *,
                         event_id: str, action_id: str, attempt_id: str,
                         outcome: str, result: Mapping[str, Any]
                         ) -> tuple[sqlite3.Row, bool, dict[str, Any], str, str | None, int]:
    if outcome not in {"SUCCEEDED", "FAILED", "UNKNOWN", "HOLD"}:
        raise ValueError("unsupported terminal Action outcome")
    if not isinstance(result, Mapping):
        raise ValueError("Action result must be a JSON object")
    detail = {"outcome": outcome, "result": dict(result)}
    detail_json = _json(detail)
    row = connection.execute(
        "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
    ).fetchone()
    if row is None:
        raise KeyError(mission_id)
    duplicate = connection.execute(
        "SELECT * FROM fleet_mission_events WHERE event_source='device_action' AND source_event_id=?",
        (event_id,),
    ).fetchone()
    if duplicate is not None:
        if (duplicate["mission_id"] != mission_id or duplicate["action_id"] != action_id
                or duplicate["attempt_id"] != attempt_id
                or duplicate["event_type"] != "ACTION_TERMINAL_RESULT"
                or duplicate["detail_json"] != detail_json):
            raise MissionConflict("device Action event ID was reused with different evidence")
        return row, True, detail, "", None, 0
    reconciling_hold = row["status"] == "HOLD" and row["reconciliation_pending"]
    if ((row["status"] != "RUNNING" and not reconciling_hold)
            or row["action_id"] != action_id or row["attempt_id"] != attempt_id):
        raise MissionConflict("Action result does not match the active Mission attempt")
    late_success = reconciling_hold and outcome == "SUCCEEDED"
    target_state = "HOLD" if late_success else "ACTION_SUCCEEDED" if outcome == "SUCCEEDED" else "HOLD"
    reason = ("LATE_SUCCESS_REQUIRES_INDEPENDENT_GOAL_EVIDENCE" if late_success
              else None if outcome == "SUCCEEDED" else f"ACTION_{outcome}")
    reconcile = 1 if outcome == "UNKNOWN" and result.get("reason") in {
        "LOCAL_ACTION_SUBMIT_OUTCOME_UNKNOWN", "LOCAL_ACTION_READBACK_UNKNOWN",
    } else 0
    return row, False, detail, target_state, reason, reconcile


def _load_phase_attempt(connection: sqlite3.Connection, mission_id: str, *,
                        action_id: str, attempt_id: str, authority_epoch: int,
                        dispatch_generation: int, phases: list[Mapping[str, Any]]
                        ) -> tuple[sqlite3.Row, dict[int, dict[str, Any]], list[dict[str, Any]]]:
    if type(authority_epoch) is not int or type(dispatch_generation) is not int:
        raise ValueError("phase receipt fence must be integer-valued")
    if not isinstance(phases, list) or len(phases) > 4:
        raise ValueError("phase summaries must be a bounded list")
    validated = [DeviceActionPhaseReceipt.model_validate(p).model_dump(mode="json") for p in phases]
    row = connection.execute(
        "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
    ).fetchone()
    if row is None:
        raise KeyError(mission_id)
    if (row["action_id"] != action_id or row["attempt_id"] != attempt_id
            or row["authority_epoch"] != authority_epoch
            or row["dispatch_generation"] != dispatch_generation
            or row["status"] not in {"RUNNING", "ACTION_SUCCEEDED", "HOLD", "GOAL_CONFIRMED"}):
        raise MissionConflict("phase receipt does not match the active Mission attempt")
    prior_rows = connection.execute(
        "SELECT * FROM fleet_mission_events WHERE mission_id=? AND action_id=? "
        "AND attempt_id=? AND event_source='device_action_phase' ORDER BY event_id",
        (mission_id, action_id, attempt_id),
    ).fetchall()
    latest: dict[int, dict[str, Any]] = {}
    for prior in prior_rows:
        detail = json.loads(prior["detail_json"])
        ordinal = detail["ordinal"]
        if (ordinal not in latest or detail["source_journal_event_id"]
                > latest[ordinal]["detail"]["source_journal_event_id"]):
            latest[ordinal] = {"detail": detail}
    return row, latest, validated


class MissionStoreHelpersMixin(MissionStoreQueriesMixin):
    """Event persistence, holds, and read queries for MissionStore."""

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
                "UPDATE fleet_missions SET status='HOLD', reason=?, updated_at=? WHERE mission_id=?",
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
            row = connection.execute(
                "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
            ).fetchone()
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
            updated = connection.execute(
                "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
            ).fetchone()
            connection.commit()
        return self._row(updated)

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
                "UPDATE fleet_missions SET reconciliation_pending=0, updated_at=? WHERE mission_id=?",
                (_now(), mission_id),
            )
            updated = connection.execute(
                "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
            ).fetchone()
            connection.commit()
        return self._row(updated)
