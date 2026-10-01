"""Durable, non-executable operator/model candidate records for Fleet Missions."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from core_common.protocol.schemas import ER2_POST_ACTION_OBSERVATION_MAX_AGE_SECONDS
from fleet.ai.model_tool_contract import ModelToolCall, ModelToolResult

from .sqlite_policy import configure_connection, enable_wal


class ProposalConflict(ValueError):
    """A proposal identity was reused or a state transition conflicts."""


class ProposalRejected(ValueError):
    """A candidate cannot be resolved against current trusted evidence."""

    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code):
            raise ValueError("proposal rejection must use a stable uppercase reason code")
        self.code = code
        super().__init__(code)


_ALLOWED_FIELDS = {
    "request_id", "source", "model_id", "instruction", "provider_interaction_id",
    "provider_call_id", "source_observation", "target_selector", "destination_selector",
}
_SOURCE_FIELDS = {
    "observation_id", "camera_id", "frame_id", "observed_at", "image_sha256",
    "coordinate_space", "image_transform", "calibration_revision", "transform_revision",
}
_TRANSFORM_FIELDS = {
    "source_width", "source_height", "crop_xyxy", "model_width", "model_height",
    "rotation_quadrants_clockwise",
}
_SELECTOR_FIELDS = {"label", "point_yx_1000", "box_yxyx_1000"}
_MAX_CANDIDATE_BYTES = 32 * 1024
_MAX_POST_ACTION_OBSERVATION_AGE = timedelta(
    seconds=ER2_POST_ACTION_OBSERVATION_MAX_AGE_SECONDS,
)


def _text(name: str, value: object, *, limit: int = 192) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > limit or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{name} must be a non-empty trimmed string of at most {limit} characters")
    return value


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("proposal data must be finite JSON") from exc


def _check_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("candidate must be a JSON object")
    document = dict(value)

    if set(document) - _ALLOWED_FIELDS:
        forbidden = set(document) - _ALLOWED_FIELDS
        if forbidden & {"principal_id", "actor_id"}:
            raise ValueError("authenticated principal cannot come from candidate data")
        if forbidden & {"image", "image_bytes", "image_data", "raw_image", "frame_bytes",
                        "jpeg", "png", "base64"}:
            raise ValueError("candidate image bytes must not be persisted")
        raise ValueError("candidate contains fields outside the selector metadata contract")
    for field, limit in (("request_id", 160), ("source", 96), ("model_id", 128),
                         ("instruction", 2000), ("provider_interaction_id", 160),
                         ("provider_call_id", 160)):
        if field in document:
            _text(field, document[field], limit=limit)
    source = document.get("source_observation")
    if not isinstance(source, Mapping) or set(source) - _SOURCE_FIELDS:
        raise ValueError("candidate source_observation has unsupported fields")
    for field in _SOURCE_FIELDS - {"image_transform"}:
        if field in source:
            _text(f"source_observation.{field}", source[field],
                  limit=160 if field in {"observation_id", "camera_id", "frame_id"} else 96)
    transform = source.get("image_transform")
    if transform is not None and (
            not isinstance(transform, Mapping) or set(transform) - _TRANSFORM_FIELDS):
        raise ValueError("candidate image transform has unsupported fields")
    for selector_name in ("target_selector", "destination_selector"):
        selector = document.get(selector_name)
        if not isinstance(selector, Mapping) or set(selector) - _SELECTOR_FIELDS:
            raise ValueError(f"candidate {selector_name} has unsupported fields")
        if "label" in selector:
            _text(f"{selector_name}.label", selector["label"], limit=160)
    encoded = _json(document)
    if len(encoded.encode("utf-8")) > _MAX_CANDIDATE_BYTES:
        raise ValueError("candidate metadata exceeds 32 KiB")
    return json.loads(encoded)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


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

    @staticmethod
    def _tool_call_digest(call: ModelToolCall) -> str:
        material = f"{call.tool_name}\n{call.ordinal}\n{call.arguments_json}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def begin_model_tool_call(self, call: ModelToolCall) -> dict[str, Any]:
        """Claim a provider call once; return its durable result or ambiguity."""
        if not isinstance(call, ModelToolCall):
            raise TypeError("call must be a validated ModelToolCall")
        digest = self._tool_call_digest(call)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            turn = connection.execute(
                "SELECT state FROM fleet_mission_model_turns WHERE turn_id=?",
                (call.turn_id,),
            ).fetchone()
            if turn is None:
                connection.rollback()
                raise ProposalRejected("TURN_NOT_FOUND")
            if turn["state"] != "SUBMITTING":
                connection.rollback()
                raise ProposalRejected("TURN_NOT_SUBMITTING")
            row = connection.execute(
                "SELECT * FROM fleet_model_tool_call_results "
                "WHERE turn_id=? AND provider_call_id=?",
                (call.turn_id, call.provider_call_id),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO fleet_model_tool_call_results "
                    "(turn_id, provider_call_id, tool_name, ordinal, content_digest, "
                    "state, result_json, updated_at) VALUES (?, ?, ?, ?, ?, 'IN_PROGRESS', NULL, ?)",
                    (call.turn_id, call.provider_call_id, call.tool_name,
                     call.ordinal, digest, _now()),
                )
                connection.commit()
                return {"created": True, "state": "IN_PROGRESS", "result": None}
            if (row["content_digest"] != digest or row["tool_name"] != call.tool_name
                    or row["ordinal"] != call.ordinal):
                connection.rollback()
                raise ProposalConflict("provider call id reused with different content")
            connection.commit()
            result = (ModelToolResult.model_validate(json.loads(row["result_json"])).to_mapping()
                      if row["result_json"] is not None else None)
            return {"created": False, "state": row["state"], "result": result}

    def complete_model_tool_call(self, call: ModelToolCall, *,
                                 result: ModelToolResult | Mapping[str, Any]) -> dict[str, Any]:
        """Persist a correlated non-UNKNOWN outcome for a claimed call."""
        parsed = (result if isinstance(result, ModelToolResult)
                  else ModelToolResult.model_validate(result))
        if (parsed.turn_id != call.turn_id
                or parsed.provider_call_id != call.provider_call_id
                or parsed.tool_name != call.tool_name or parsed.ordinal != call.ordinal
                or parsed.outcome == "unknown"):
            raise ValueError("tool result must match its call and have a known outcome")
        encoded = json.dumps(parsed.to_mapping(), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fleet_model_tool_call_results "
                "WHERE turn_id=? AND provider_call_id=?",
                (call.turn_id, call.provider_call_id),
            ).fetchone()
            if (row is None or row["content_digest"] != self._tool_call_digest(call)
                    or row["tool_name"] != call.tool_name or row["ordinal"] != call.ordinal):
                connection.rollback()
                raise ProposalConflict("tool call was not claimed with this content")
            if row["state"] == "UNKNOWN":
                connection.rollback()
                raise ProposalConflict("unknown tool call outcome cannot be overwritten")
            if row["state"] == "COMPLETED":
                if row["result_json"] != encoded:
                    connection.rollback()
                    raise ProposalConflict("completed tool call result cannot be changed")
                connection.commit()
                return ModelToolResult.model_validate(json.loads(encoded)).to_mapping()
            connection.execute(
                "UPDATE fleet_model_tool_call_results SET state='COMPLETED', result_json=?, "
                "updated_at=? WHERE turn_id=? AND provider_call_id=? AND state='IN_PROGRESS'",
                (encoded, _now(), call.turn_id, call.provider_call_id),
            )
            connection.commit()
        return parsed.to_mapping()

    def mark_model_tool_call_unknown(self, call: ModelToolCall) -> None:
        """Fence an ambiguous provider/effect attempt against replay."""
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE fleet_model_tool_call_results SET state='UNKNOWN', updated_at=? "
                "WHERE turn_id=? AND provider_call_id=? AND content_digest=? "
                "AND state='IN_PROGRESS'",
                (_now(), call.turn_id, call.provider_call_id,
                 self._tool_call_digest(call)),
            )

    @staticmethod
    def _complete_model_tool_call_in_transaction(
        connection: sqlite3.Connection, call: ModelToolCall,
        result: ModelToolResult,
    ) -> None:
        if (result.turn_id != call.turn_id
                or result.provider_call_id != call.provider_call_id
                or result.tool_name != call.tool_name or result.ordinal != call.ordinal
                or result.outcome == "unknown"):
            raise ValueError("tool result must match its call and have a known outcome")
        encoded = json.dumps(result.to_mapping(), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False)
        prior = connection.execute(
            "SELECT content_digest, tool_name, ordinal, state, result_json "
            "FROM fleet_model_tool_call_results WHERE turn_id=? AND provider_call_id=?",
            (call.turn_id, call.provider_call_id),
        ).fetchone()
        if (prior is None or prior["content_digest"] != ProposalStore._tool_call_digest(call)
                or prior["tool_name"] != call.tool_name or prior["ordinal"] != call.ordinal):
            raise ProposalConflict("tool call was not claimed with this content")
        if prior["state"] == "UNKNOWN":
            raise ProposalConflict("unknown tool call outcome cannot be overwritten")
        if prior["state"] == "COMPLETED":
            if prior["result_json"] != encoded:
                raise ProposalConflict("completed tool call result cannot be changed")
            return
        connection.execute(
            "UPDATE fleet_model_tool_call_results SET state='COMPLETED', result_json=?, "
            "updated_at=? WHERE turn_id=? AND provider_call_id=? AND state='IN_PROGRESS'",
            (encoded, _now(), call.turn_id, call.provider_call_id),
        )

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
        from datetime import timedelta
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

    def create_feedback_candidate_fenced(
        self, *, turn_id: str, candidate: Mapping[str, Any],
        observation: Mapping[str, Any], tool_call: ModelToolCall | None = None,
    ) -> dict[str, Any]:
        """Atomically persist an ER 2 successor candidate under the live stop fence.

        ``observation`` must be supplied by the trusted post-action image reader,
        not copied from tool arguments or model output. It carries the capture
        scope Fleet must bind to the outbox turn and candidate image digest.
        """
        turn_id = _text("turn_id", turn_id, limit=96)
        if tool_call is not None and tool_call.turn_id != turn_id:
            raise ProposalRejected("TURN_SCOPE_MISMATCH")
        if not isinstance(observation, Mapping) or set(observation) != {
            "mission_id", "workcell_id", "action_id", "attempt_id",
            "dispatch_generation", "based_on_event_id", "observation_id",
            "observed_at", "image_sha256",
        }:
            raise ProposalRejected("OBSERVATION_SCOPE_MISMATCH")
        for field in ("mission_id", "workcell_id", "action_id", "attempt_id",
                      "observation_id", "observed_at", "image_sha256"):
            try:
                _text(f"observation.{field}", observation[field], limit=160)
            except ValueError as exc:
                raise ProposalRejected("OBSERVATION_SCOPE_MISMATCH") from exc
        if (type(observation["dispatch_generation"]) is not int
                or type(observation["based_on_event_id"]) is not int
                or observation["dispatch_generation"] < 0
                or observation["based_on_event_id"] < 1
                or re.fullmatch(r"[0-9a-f]{64}", observation["image_sha256"]) is None):
            raise ProposalRejected("OBSERVATION_SCOPE_MISMATCH")
        checked_candidate = _check_candidate(candidate)
        source = checked_candidate["source_observation"]
        if (source.get("observation_id") != observation["observation_id"]
                or source.get("observed_at") != observation["observed_at"]
                or source.get("image_sha256") != observation["image_sha256"]):
            raise ProposalRejected("OBSERVATION_SCOPE_MISMATCH")
        candidate_json = _json(checked_candidate)
        now = datetime.now(timezone.utc)
        try:
            observed_at = datetime.fromisoformat(
                observation["observed_at"].replace("Z", "+00:00"),
            )
        except ValueError as exc:
            raise ProposalRejected("OBSERVATION_TIME_INVALID") from exc
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ProposalRejected("OBSERVATION_TIME_INVALID")
        observed_at = observed_at.astimezone(timezone.utc)
        if observed_at > now or now - observed_at > _MAX_POST_ACTION_OBSERVATION_AGE:
            raise ProposalRejected("OBSERVATION_NOT_FRESH")

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            turn = connection.execute(
                "SELECT * FROM fleet_mission_model_turns WHERE turn_id=?", (turn_id,),
            ).fetchone()
            if (turn is None or turn["state"] != "SUBMITTING"
                    or turn["outcome_policy"] != "STATUS_AND_REPLAN"):
                connection.rollback()
                raise ProposalRejected("TURN_NOT_REPLAN_ELIGIBLE")
            control = connection.execute(
                "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1",
            ).fetchone()
            if control is None or not control["dispatch_enabled"]:
                connection.rollback()
                raise ProposalRejected("STOP_FENCE_CLOSED")
            if control["generation"] != turn["dispatch_generation"]:
                connection.rollback()
                raise ProposalRejected("STOP_GENERATION_CHANGED")
            mission = connection.execute(
                "SELECT * FROM fleet_missions WHERE mission_id=?", (turn["mission_id"],),
            ).fetchone()
            if (mission is None
                    or mission["principal_id"] != turn["principal_id"]
                    or mission["workcell_id"] != turn["workcell_id"]
                    or mission["action_kind"] != "PICK_PLACE"
                    or mission["action_id"] != turn["action_id"]
                    or mission["attempt_id"] != turn["attempt_id"]
                    or mission["dispatch_generation"] != turn["dispatch_generation"]
                    or mission["status"] != "HOLD"
                    or mission["reason"] != "GOAL_NOT_SATISFIED"):
                connection.rollback()
                raise ProposalRejected("TURN_SCOPE_STALE")
            if (observation["mission_id"] != turn["mission_id"]
                    or observation["workcell_id"] != turn["workcell_id"]
                    or observation["action_id"] != turn["action_id"]
                    or observation["attempt_id"] != turn["attempt_id"]
                    or observation["dispatch_generation"] != turn["dispatch_generation"]
                    or observation["based_on_event_id"] != turn["event_watermark"]):
                connection.rollback()
                raise ProposalRejected("OBSERVATION_SCOPE_MISMATCH")
            latest_event_id = connection.execute(
                "SELECT COALESCE(MAX(event_id), 0) FROM fleet_mission_events WHERE mission_id=?",
                (turn["mission_id"],),
            ).fetchone()[0]
            if latest_event_id != turn["event_watermark"]:
                connection.rollback()
                raise ProposalRejected("EVENT_WATERMARK_STALE")
            terminal = connection.execute(
                """SELECT created_at FROM fleet_mission_events
                   WHERE mission_id=? AND action_id=? AND attempt_id=?
                     AND event_type='ACTION_TERMINAL_RESULT'
                   ORDER BY event_id DESC LIMIT 1""",
                (turn["mission_id"], turn["action_id"], turn["attempt_id"]),
            ).fetchone()
            unsatisfied = connection.execute(
                """SELECT 1 FROM fleet_mission_events WHERE mission_id=? AND action_id=?
                   AND attempt_id=? AND event_type='GOAL_PREDICATE_UNSATISFIED'
                   AND event_id<=? ORDER BY event_id DESC LIMIT 1""",
                (turn["mission_id"], turn["action_id"], turn["attempt_id"],
                 turn["event_watermark"]),
            ).fetchone()
            if terminal is None or unsatisfied is None:
                connection.rollback()
                raise ProposalRejected("REPLAN_EVIDENCE_NOT_FRESH")
            try:
                terminal_at = datetime.fromisoformat(
                    terminal["created_at"].replace("Z", "+00:00"),
                ).astimezone(timezone.utc)
            except (ValueError, AttributeError) as exc:
                connection.rollback()
                raise ProposalRejected("ACTION_TERMINAL_TIME_INVALID") from exc
            if observed_at <= terminal_at:
                connection.rollback()
                raise ProposalRejected("OBSERVATION_PRECEDES_ACTION")
            try:
                initial_plan = json.loads(mission["plan_json"])
            except (TypeError, ValueError):
                initial_plan = {}
            original_observation = initial_plan.get("observation_id")
            original_sha = initial_plan.get("image_sha256")
            original_source = initial_plan.get("source_evidence")
            if isinstance(original_source, Mapping):
                original_sha = original_sha or original_source.get("frame_sha256")
            if (observation["observation_id"] == original_observation
                    or observation["image_sha256"] == original_sha):
                connection.rollback()
                raise ProposalRejected("OBSERVATION_NOT_POST_ACTION")

            commit_at = datetime.now(timezone.utc)
            if (observed_at > commit_at
                    or commit_at - observed_at > _MAX_POST_ACTION_OBSERVATION_AGE):
                connection.rollback()
                raise ProposalRejected("OBSERVATION_NOT_FRESH")

            request_key = f"er2-feedback:{turn_id}"
            request_digest = hashlib.sha256(_json({
                "candidate": checked_candidate,
                "observation_scope": dict(observation),
            }).encode("utf-8")).hexdigest()
            prior = connection.execute(
                "SELECT * FROM fleet_proposals WHERE principal_id=? AND request_key=?",
                (turn["principal_id"], request_key),
            ).fetchone()
            if prior is not None:
                if prior["candidate_digest"] != request_digest:
                    connection.rollback()
                    raise ProposalConflict("feedback turn already has a different candidate")
                if tool_call is not None:
                    self._complete_model_tool_call_in_transaction(
                        connection, tool_call,
                        ModelToolResult.for_call(
                            tool_call, outcome="accepted", reason_code="CANDIDATE_RECORDED",
                            event_id=turn["event_watermark"],
                            proposal_id=prior["proposal_id"],
                            payload={"successor_of_mission_id": turn["mission_id"],
                                     "executable": False},
                        ),
                    )
                connection.commit()
                return {"proposal": self._row(prior), "created": False}

            proposal_id = str(uuid.uuid4())
            stamp = commit_at.isoformat(timespec="microseconds")
            expires = (commit_at.replace(microsecond=0)
                       + timedelta(days=self.retention_days)).isoformat()
            connection.execute(
                """INSERT INTO fleet_proposals
                   (proposal_id, principal_id, request_key, workcell_id, instance_id,
                    candidate_digest, candidate_json, state, source_mission_id,
                    source_action_id, source_attempt_id, source_dispatch_generation,
                    source_event_watermark, source_observation_id, source_observed_at,
                    supersedes_mission_id, created_at, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (proposal_id, turn["principal_id"], request_key, turn["workcell_id"],
                 mission["instance_id"], request_digest, candidate_json,
                 turn["mission_id"], turn["action_id"], turn["attempt_id"],
                 turn["dispatch_generation"], turn["event_watermark"],
                 observation["observation_id"], observation["observed_at"],
                 turn["mission_id"], stamp, stamp, expires),
            )
            row = connection.execute(
                "SELECT * FROM fleet_proposals WHERE proposal_id=?", (proposal_id,),
            ).fetchone()
            if tool_call is not None:
                self._complete_model_tool_call_in_transaction(
                    connection, tool_call,
                    ModelToolResult.for_call(
                        tool_call, outcome="accepted", reason_code="CANDIDATE_RECORDED",
                        event_id=turn["event_watermark"], proposal_id=proposal_id,
                        payload={"successor_of_mission_id": turn["mission_id"],
                                 "executable": False},
                    ),
                )
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
