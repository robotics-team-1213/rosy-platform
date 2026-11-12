"""Candidate validation and ER 2 model tool-call helpers for ``ProposalStore``."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from rosy.decision.model_tool_contract import ModelToolCall, ModelToolResult

from .proposal_candidate_validation import (
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
    _json,
    _now,
    _text,
    _tool_call_digest,
)


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
    if (prior is None or prior["content_digest"] != _tool_call_digest(call)
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
