"""Durable, non-executable operator/model candidate records for Fleet Missions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .proposal_store_helpers import (  # noqa: F401
    ModelToolCall,
    ModelToolResult,
    ProposalConflict,
    ProposalRejected,
    _ALLOWED_FIELDS,
    _MAX_CANDIDATE_BYTES,
    _MAX_CELL_JOB_CANDIDATE_BYTES,
    _MAX_POST_ACTION_OBSERVATION_AGE,
    _SELECTOR_FIELDS,
    _SOURCE_FIELDS,
    _TRANSFORM_FIELDS,
    _check_candidate,
    _complete_model_tool_call_in_transaction,
    _json,
    _now,
    _text,
    _tool_call_digest,
    begin_model_tool_call,
    complete_model_tool_call,
    create_feedback_candidate_fenced,
    mark_model_tool_call_unknown,
)
from .sqlite_policy import configure_connection, enable_wal


class ProposalStore:
    """SQLite proposal metadata store; it never stores source image bytes."""

    def __init__(self, path: Path | str, *, retention_days: int = 30) -> None:
        if type(retention_days) is not int or not 1 <= retention_days <= 365:
            raise ValueError("retention_days must be an integer from 1 to 365")
        self.path = Path(path)
        self.retention_days = retention_days
        with closing(self._connect()) as connection:
            enable_wal(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS fleet_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    workcell_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    candidate_digest TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('PROPOSED', 'RESOLVING', 'UNRESOLVED', 'RESOLVED', 'REJECTED')),
                    mission_id TEXT,
                    resolved_json TEXT,
                    reason TEXT,
                    source_mission_id TEXT,
                    source_action_id TEXT,
                    source_attempt_id TEXT,
                    source_dispatch_generation INTEGER,
                    source_event_watermark INTEGER,
                    source_observation_id TEXT,
                    source_observed_at TEXT,
                    supersedes_mission_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    UNIQUE(principal_id, request_key)
                );
                CREATE INDEX IF NOT EXISTS fleet_proposals_expiry
                    ON fleet_proposals(expires_at);
                CREATE TABLE IF NOT EXISTS fleet_model_tool_call_results (
                    turn_id TEXT NOT NULL,
                    provider_call_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                    content_digest TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('IN_PROGRESS','COMPLETED','UNKNOWN')),
                    result_json TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(turn_id, provider_call_id),
                    CHECK((state = 'COMPLETED' AND result_json IS NOT NULL)
                       OR (state IN ('IN_PROGRESS','UNKNOWN') AND result_json IS NULL))
                );
                """
            )
            # A prior process may have exited after claiming the call but before
            # durably storing its effect result. Such calls are ambiguous and
            # must not be replayed automatically after restart.
            connection.execute(
                "UPDATE fleet_model_tool_call_results SET state='UNKNOWN', updated_at=? "
                "WHERE state='IN_PROGRESS'", (_now(),),
            )
            columns = {row[1] for row in connection.execute(
                "PRAGMA table_info(fleet_proposals)").fetchall()}
            for name, sql_type in (
                ("source_mission_id", "TEXT"), ("source_action_id", "TEXT"),
                ("source_attempt_id", "TEXT"),
                ("source_dispatch_generation", "INTEGER"),
                ("source_event_watermark", "INTEGER"),
                ("source_observation_id", "TEXT"), ("source_observed_at", "TEXT"),
                ("supersedes_mission_id", "TEXT"),
            ):
                if name not in columns:
                    connection.execute(f"ALTER TABLE fleet_proposals ADD COLUMN {name} {sql_type}")
        self.purge_expired()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["candidate"] = json.loads(result.pop("candidate_json"))
        if result["resolved_json"] is not None:
            result["resolution"] = json.loads(result.pop("resolved_json"))
        else:
            del result["resolved_json"]
        return result

    _tool_call_digest = staticmethod(_tool_call_digest)
    begin_model_tool_call = begin_model_tool_call
    complete_model_tool_call = complete_model_tool_call
    mark_model_tool_call_unknown = mark_model_tool_call_unknown
    _complete_model_tool_call_in_transaction = staticmethod(_complete_model_tool_call_in_transaction)
    create_feedback_candidate_fenced = create_feedback_candidate_fenced

    def create(self, *, principal_id: str, request_key: str,
               workcell_id: str, instance_id: str,
               candidate: Mapping[str, Any]) -> dict[str, Any]:
        principal_id = _text("principal_id", principal_id, limit=96)
        request_key = _text("request_key", request_key, limit=160)
        workcell_id = _text("workcell_id", workcell_id, limit=96)
        instance_id = _text("instance_id", instance_id, limit=96)
        candidate_json = _json(_check_candidate(candidate))
        request_json = _json({"candidate": json.loads(candidate_json),
                              "workcell_id": workcell_id, "instance_id": instance_id})
        digest = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        self.purge_expired()
        now = datetime.now(timezone.utc)
        expires = now.replace(microsecond=0) + timedelta(days=self.retention_days)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT * FROM fleet_proposals WHERE principal_id=? AND request_key=?",
                (principal_id, request_key),
            ).fetchone()
            if prior is not None:
                if prior["candidate_digest"] != digest:
                    raise ProposalConflict("request_key is already bound to a different candidate")
                connection.commit()
                return {"proposal": self._row(prior), "created": False}
            proposal_id = str(uuid.uuid4())
            stamp = now.isoformat(timespec="microseconds")
            connection.execute(
                """INSERT INTO fleet_proposals
                   (proposal_id, principal_id, request_key, workcell_id, instance_id,
                    candidate_digest, candidate_json,
                    state, created_at, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?, ?)""",
                (proposal_id, principal_id, request_key, workcell_id, instance_id,
                 digest, candidate_json,
                 stamp, stamp, expires.isoformat()),
            )
            row = connection.execute("SELECT * FROM fleet_proposals WHERE proposal_id=?",
                                     (proposal_id,)).fetchone()
            connection.commit()
        return {"proposal": self._row(row), "created": True}

    def finalize_resolution(self, mission_store: Any, *, proposal_id: str,
                            principal_id: str, resolution: Mapping[str, Any],
                            mission_request: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bool]:
        """Atomically insert a Mission draft and mark its source proposal resolved."""
        proposal_id = _text("proposal_id", proposal_id)
        principal_id = _text("principal_id", principal_id, limit=96)
        resolution_json = _json(dict(resolution))
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fleet_proposals WHERE proposal_id=? AND principal_id=?",
                (proposal_id, principal_id),
            ).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            if row["state"] == "RESOLVED":
                mission = mission_store.get_mission(proposal_id)
                if mission is None:
                    raise ProposalConflict("resolved proposal has no durable Mission")
                connection.commit()
                return self._row(row), mission, False
            if row["state"] != "PROPOSED":
                raise ProposalConflict("proposal is not available for resolution")
            if row["source_mission_id"] is not None:
                control = connection.execute(
                    "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1",
                ).fetchone()
                source = connection.execute(
                    "SELECT principal_id, workcell_id, action_id, attempt_id, "
                    "dispatch_generation, status, reason FROM fleet_missions WHERE mission_id=?",
                    (row["source_mission_id"],),
                ).fetchone()
                latest_event_id = connection.execute(
                    "SELECT COALESCE(MAX(event_id), 0) FROM fleet_mission_events "
                    "WHERE mission_id=?", (row["source_mission_id"],),
                ).fetchone()[0]
                if control is None or not control["dispatch_enabled"]:
                    connection.execute(
                        "UPDATE fleet_proposals SET state='REJECTED', reason=?, updated_at=? "
                        "WHERE proposal_id=?",
                        ("STOP_FENCE_CLOSED", _now(), proposal_id),
                    )
                    connection.commit()
                    raise ProposalRejected("STOP_FENCE_CLOSED")
                if (control["generation"] != row["source_dispatch_generation"]
                        or source is None
                        or source["principal_id"] != row["principal_id"]
                        or source["workcell_id"] != row["workcell_id"]
                        or source["action_id"] != row["source_action_id"]
                        or source["attempt_id"] != row["source_attempt_id"]
                        or source["dispatch_generation"] != row["source_dispatch_generation"]
                        or source["status"] != "HOLD"
                        or source["reason"] != "GOAL_NOT_SATISFIED"
                        or latest_event_id != row["source_event_watermark"]):
                    connection.execute(
                        "UPDATE fleet_proposals SET state='REJECTED', reason=?, updated_at=? "
                        "WHERE proposal_id=?",
                        ("FEEDBACK_CANDIDATE_STALE", _now(), proposal_id),
                    )
                    connection.commit()
                    raise ProposalRejected("FEEDBACK_CANDIDATE_STALE")
            mission_result = mission_store.create_proposal(
                mission_id=proposal_id, principal_id=principal_id,
                request_key=row["request_key"], action_kind="PICK_PLACE",
                workcell_id=row["workcell_id"], instance_id=row["instance_id"],
                plan=mission_request["plan"], goal_predicate=mission_request["goal_predicate"],
                supersedes_mission_id=row["supersedes_mission_id"],
                connection=connection,
            )
            connection.execute(
                """UPDATE fleet_proposals SET state='RESOLVED', resolved_json=?, mission_id=?,
                   reason=NULL, updated_at=? WHERE proposal_id=? AND principal_id=?""",
                (resolution_json, proposal_id, _now(), proposal_id, principal_id),
            )
            updated = connection.execute("SELECT * FROM fleet_proposals WHERE proposal_id=?",
                                         (proposal_id,)).fetchone()
            mission = mission_result["mission"]
            connection.commit()
        if mission is None:
            raise ProposalConflict("Mission draft was not persisted")
        return self._row(updated), mission, True

    def finalize_cell_job(self, cell_job_store: Any, *, proposal_id: str,
                          principal_id: str, submission: Mapping[str, Any]) -> tuple[dict, dict, bool]:
        """Atomically persist a recompiled ordered Cell Job and resolve its proposal."""
        proposal_id = _text("proposal_id", proposal_id)
        principal_id = _text("principal_id", principal_id, limit=96)
        resolution_json = _json(dict(submission))
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fleet_proposals WHERE proposal_id=? AND principal_id=?",
                (proposal_id, principal_id),
            ).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            candidate = json.loads(row["candidate_json"])
            if candidate.get("kind") != "cell_job":
                raise ProposalConflict("only a cell_job proposal can create an ordered Cell Job")
            if row["state"] == "RESOLVED":
                existing = cell_job_store._get(connection, proposal_id)
                if existing is None:
                    raise ProposalConflict("resolved Cell Job proposal has no durable ordered steps")
                connection.commit()
                return self._row(row), existing, False
            if row["state"] != "PROPOSED":
                raise ProposalConflict("proposal is not available for resolution")
            cell_job = cell_job_store.create_in_transaction(
                connection, mission_id=proposal_id, proposal_principal_id=principal_id,
                request_key=row["request_key"], request_digest=row["candidate_digest"],
                submission=submission,
            )
            connection.execute(
                """UPDATE fleet_proposals SET state='RESOLVED', resolved_json=?, mission_id=?,
                   reason=NULL, updated_at=? WHERE proposal_id=? AND principal_id=?""",
                (resolution_json, proposal_id, _now(), proposal_id, principal_id),
            )
            updated = connection.execute(
                "SELECT * FROM fleet_proposals WHERE proposal_id=?", (proposal_id,),
            ).fetchone()
            connection.commit()
        return self._row(updated), cell_job, True

    def get(self, proposal_id: str, *, principal_id: str | None = None) -> dict[str, Any] | None:
        proposal_id = _text("proposal_id", proposal_id)
        self.purge_expired()
        with closing(self._connect()) as connection:
            if principal_id is None:
                row = connection.execute("SELECT * FROM fleet_proposals WHERE proposal_id=?",
                                         (proposal_id,)).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM fleet_proposals WHERE proposal_id=? AND principal_id=?",
                    (proposal_id, _text("principal_id", principal_id, limit=96)),
                ).fetchone()
        return self._row(row)

    def get_in_transaction(self, connection, proposal_id: str) -> dict[str, Any] | None:
        """Read current metadata without acquiring a second writer to purge expiry."""
        row = connection.execute("SELECT * FROM fleet_proposals WHERE proposal_id=?",
                                 (_text("proposal_id", proposal_id),)).fetchone()
        if row is None or row['expires_at'] <= datetime.now(timezone.utc).isoformat():
            return None
        return self._row(row)

    def by_request(self, *, principal_id: str, request_key: str) -> dict[str, Any] | None:
        self.purge_expired()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM fleet_proposals WHERE principal_id=? AND request_key=?",
                (_text("principal_id", principal_id, limit=96),
                 _text("request_key", request_key, limit=160)),
            ).fetchone()
        return self._row(row)

    def set_resolution(self, proposal_id: str, *, state: str,
                       resolution: Mapping[str, Any] | None = None,
                       mission_id: str | None = None, reason: str | None = None) -> dict[str, Any]:
        if state not in {"UNRESOLVED", "RESOLVED", "REJECTED"}:
            raise ValueError("invalid proposal resolution state")
        if state == "RESOLVED" and (resolution is None or mission_id is None):
            raise ValueError("resolved proposal requires a resolution and mission_id")
        if state != "RESOLVED" and resolution is not None:
            raise ValueError("only resolved proposals may contain a resolution")
        resolution_json = _json(dict(resolution)) if resolution is not None else None
        reason = _text("reason", reason, limit=96) if reason is not None else None
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM fleet_proposals WHERE proposal_id=?",
                                     (proposal_id,)).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            if row["state"] not in {"PROPOSED", "RESOLVING"}:
                if row["state"] == state and row["mission_id"] == mission_id:
                    connection.commit()
                    return self._row(row)
                raise ProposalConflict("proposal resolution is immutable")
            connection.execute(
                """UPDATE fleet_proposals SET state=?, resolved_json=?, mission_id=?,
                   reason=?, updated_at=? WHERE proposal_id=?""",
                (state, resolution_json, mission_id, reason, _now(), proposal_id),
            )
            updated = connection.execute("SELECT * FROM fleet_proposals WHERE proposal_id=?",
                                         (proposal_id,)).fetchone()
            connection.commit()
        return self._row(updated)

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Delete expired candidate metadata while leaving Mission history intact."""
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("proposal expiry time must be timezone-aware")
        stamp = current.astimezone(timezone.utc).isoformat()
        with closing(self._connect()) as connection:
            cursor = connection.execute("DELETE FROM fleet_proposals WHERE expires_at<=?", (stamp,))
            return cursor.rowcount
