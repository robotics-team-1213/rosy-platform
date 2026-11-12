"""Lifecycle transition methods and constants for ``CellJobStore`` (D-403)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Mapping

from . import cell_arm_jobs as arm_jobs, cell_job_read_model as read_model, cell_sheet_checkpoints as sheets
from .dispatch_admission import release as release_claims, reserve as reserve_claims
from .mission_store import MissionConflict, _json, _nonempty, _now
from .step_action_kinds import parse_step_grant, step_grant_digest, validate_step_grant

_IDENTIFIER_HASH_FIELDS = ("recipe_digest", "cell_digest", "process_artifact_digest")
# Claim phases (D-403 §4 보강 2026-10-03): a Cell Job holds its claims from admission until it is
# terminal. CLAIMED = admitted and runnable; DISPATCHING = an Action is in flight; UNKNOWN = the
# device outcome is unresolved (blocks rearm); HELD = the Job is in HOLD with a confirmed device
# state (the stop latch skips it, rearm ignores it, admission of the same resources is refused).
# Device outcome -> (step and Job status, claim phase).
_OUTCOMES = {
    "SUCCEEDED": ("ACTION_SUCCEEDED", "CLAIMED"),
    "FAILED": ("HOLD", "HELD"),
    "REJECTED": ("HOLD", "HELD"),
    "UNKNOWN": ("HOLD", "UNKNOWN"),
    # The owner answered GetAction 404: it never journaled the attempt, so nothing ran.
    "NOT_FOUND": ("HOLD", "HELD"),
}
# A cancelled Job is terminal. The status column has no CANCELLED value and 1b makes no schema
# change, so it is HOLD with this reason and no claims; resume refuses it (D-420 v2 adds a status).
CANCELLED_REASON = "CANCELLED_BY_OPERATOR"
_HOLDABLE = frozenset({"READY", "RUNNING", "ACTION_SUCCEEDED"})


def create_in_transaction(connection: sqlite3.Connection, *, mission_id: str,
                          proposal_principal_id: str, request_key: str,
                          request_digest: str, submission: Mapping[str, Any]) -> dict[str, Any]:
    """Insert a fully recompiled proposal and its ordered steps in caller's transaction."""
    mission_id = _nonempty("mission_id", mission_id)
    proposal_principal_id = _nonempty("proposal_principal_id", proposal_principal_id, limit=96)
    request_key = _nonempty("request_key", request_key, limit=160)
    if (not isinstance(request_digest, str) or len(request_digest) != 64
            or any(char not in "0123456789abcdef" for char in request_digest)):
        raise ValueError("request_digest must be lowercase SHA-256")
    if connection.execute("SELECT 1 FROM fleet_missions WHERE mission_id=?", (mission_id,)).fetchone() is not None:
        raise ValueError("Cell Job mission_id is already used by the legacy Mission journal")
    if "arms" in submission:  # D-779 stages 2-4: a multi-arm Job keeps placement in its own tables
        arm_jobs.create(connection, mission_id=mission_id, proposal_principal_id=proposal_principal_id,
                        request_key=request_key, request_digest=request_digest, submission=submission)
        return read_model.read_cell_job(connection, mission_id)
    required = {
        "job_id", "workcell_id", "instance_id", "recipe_digest", "cell_digest",
        "process_artifact_digest", "job", "steps", "resources", "ledger_markers",
    }
    if set(submission) - {"operator_checkpoints"} != required:
        raise ValueError("compiled Cell Job submission has an invalid shape")
    steps = submission["steps"]
    resources = submission["resources"]
    markers = submission["ledger_markers"]
    if not isinstance(steps, list) or not steps or not isinstance(resources, list) or not resources:
        raise ValueError("Cell Job requires ordered steps and resource claims")
    for field in _IDENTIFIER_HASH_FIELDS:
        value = submission[field]
        if (not isinstance(value, str) or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)):
            raise ValueError(f"{field} must be lowercase SHA-256")
    now = _now()
    encoded_job = _json(submission["job"])
    resources_json = _json(resources)
    markers_json = _json(markers)
    connection.execute(
        """INSERT INTO fleet_cell_jobs
           (mission_id, proposal_principal_id, request_key, request_digest, job_id,
            workcell_id, instance_id, recipe_digest, cell_digest, process_artifact_digest,
            job_json, resources_json, ledger_markers_json, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?)""",
        (mission_id, proposal_principal_id, request_key, request_digest,
         _nonempty("job_id", submission["job_id"]),
         _nonempty("workcell_id", submission["workcell_id"], limit=96),
         _nonempty("instance_id", submission["instance_id"], limit=96),
         submission["recipe_digest"], submission["cell_digest"],
         submission["process_artifact_digest"], encoded_job, resources_json,
         markers_json, now, now),
    )
    for index, step in enumerate(steps):
        # goal_predicate: the item_at_pose predicate fixed at resolution (C4b 1b C1), optional.
        if not isinstance(step, Mapping) or set(step) - {"goal_predicate"} != {"skill_id", "version", "inputs"}:
            raise ValueError("Cell Job step has an invalid execution shape")
        if step["skill_id"] != "pallet.transfer" or step["version"] != "1.0.0":
            raise ValueError("Cell Job steps must use pallet.transfer/1.0.0")
        step_id = f"{mission_id}:step-{index + 1}"
        connection.execute(
            """INSERT INTO fleet_cell_steps
               (mission_id, step_index, step_id, action_kind, step_json, status, updated_at)
               VALUES (?, ?, ?, 'CELL_TRANSFER', ?, 'WAITING', ?)""",
            (mission_id, index, step_id, _json(dict(step)), now),
        )
    sheets.insert(connection, mission_id, submission, now)
    return read_model.read_cell_job(connection, mission_id)


def admit(self, mission_id: str, *, actor_id: str, expected_generation: int) -> dict[str, Any]:
    actor_id = _nonempty("actor_id", actor_id, limit=96)
    if type(expected_generation) is not int or expected_generation < 0:
        raise ValueError("expected_generation must be a non-negative integer")
    with closing(self._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        job = connection.execute(
            "SELECT * FROM fleet_cell_jobs WHERE mission_id=? AND provenance_kind='legacy'", (mission_id,),
        ).fetchone()
        if job is None:
            raise KeyError(mission_id)
        if job["status"] != "PROPOSED":
            raise MissionConflict("only a proposed Cell Job can be admitted")
        control = connection.execute(
            "SELECT authority_epoch, generation, dispatch_enabled "
            "FROM fleet_dispatch_control WHERE control_id=1",
        ).fetchone()
        if (control is None or not control["dispatch_enabled"]
                or control["generation"] != expected_generation):
            raise MissionConflict("stop generation is closed or changed")
        if not reserve_claims(
                connection, owner_kind="mission", owner_id=mission_id,
                generation=expected_generation,
                resources=[tuple(item) for item in json.loads(job["resources_json"])],
                phase="CLAIMED"):
            raise MissionConflict("Cell Job resource claim conflicts with another action")
        now = _now()
        connection.execute(
            "UPDATE fleet_cell_jobs SET status='READY', authority_epoch=?, "
            "dispatch_generation=?, updated_at=? WHERE mission_id=?",
            (control["authority_epoch"], expected_generation, now, mission_id),
        )
        connection.execute(
            "UPDATE fleet_cell_steps SET status='READY', updated_at=? "
            "WHERE mission_id=? AND step_index=0 AND status='WAITING'",
            (now, mission_id),
        )
        self._event(connection, mission_id, None, "CELL_JOB_ADMITTED", actor_id,
                    {"authority_epoch": control["authority_epoch"],
                     "dispatch_generation": expected_generation})
        sheets.hold_due(connection, self._require(connection, mission_id), 0, now, self._event)
        result = self._get(connection, mission_id)
        connection.commit()
    return result


def guard_sheet_checkpoint(self, mission_id: str, *, step_index: int) -> dict[str, Any]:
    """Fence due manual work before identity discovery or grant creation; final start repeats it."""
    with closing(self._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        sheets.guard_ready(connection, mission_id, step_index, _now(), self._event)
        result = self._get(connection, mission_id)
        connection.commit()
        return result


def start_step(self, mission_id: str, *, step_index: int, action_id: str,
               attempt_id: str, grant: Mapping[str, Any],
               now: datetime | None = None, owner_journal_id: str | None = None) -> dict[str, Any]:
    action_id = _nonempty("action_id", action_id)
    attempt_id = _nonempty("attempt_id", attempt_id)
    parsed = parse_step_grant(grant)
    canonical_grant = parsed.model_dump(mode="json")
    if step_grant_digest(parsed) != parsed.request_digest:
        raise ValueError(f"{parsed.action_kind} request digest does not match the complete grant")
    now_dt = now or datetime.now(timezone.utc)  # the dispatcher passes its own clock (1b B4)
    if parsed.issued_at > now_dt or parsed.expires_at <= now_dt:
        raise MissionConflict(f"{parsed.action_kind} grant is not current")
    now_str = _now()
    with closing(self._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        job = connection.execute(
            "SELECT * FROM fleet_cell_jobs WHERE mission_id=? AND provenance_kind='legacy'", (mission_id,),
        ).fetchone()
        if job is None:
            raise KeyError(mission_id)
        step = connection.execute(
            "SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
            (mission_id, step_index),
        ).fetchone()
        if step is None:
            raise KeyError((mission_id, step_index))
        if (job["status"] != "READY" or step["status"] != "READY"
                or job["current_step_index"] != step_index):
            raise MissionConflict("only the current READY Cell Job step may start")
        if sheets.hold_due(connection, job, step_index, now_str, self._event):
            result = self._get(connection, mission_id)
            connection.commit()
            return result
        control = connection.execute(
            "SELECT authority_epoch, generation, dispatch_enabled "
            "FROM fleet_dispatch_control WHERE control_id=1",
        ).fetchone()
        if (control is None or not control["dispatch_enabled"]
                or control["authority_epoch"] != job["authority_epoch"]
                or control["generation"] != job["dispatch_generation"]):
            # Nothing was sent. The claims are released only if the Job has no progress yet;
            # otherwise they are parked HELD for operator re-approval (1c item 2b, D-420 §4.1).
            self._hold_in_transaction(
                connection, job, reason="FLEET_FENCE_CHANGED_BEFORE_SUBMISSION",
                claim_phase=self._pre_send_claim_phase(connection, job), actor_id="fleet", strict=False,
                event_key=f"hold-before-submit:{step_index}:{self._approvals(connection, job)}",
                detail={"current_authority_epoch": None if control is None else control["authority_epoch"],
                        "current_generation": None if control is None else control["generation"],
                        "dispatch_enabled": bool(control and control["dispatch_enabled"])},
            )
            result = self._get(connection, mission_id)
            connection.commit()
            return result
        validate_step_grant(parsed, job, step, step_index=step_index,
                            action_id=action_id, attempt_id=attempt_id)
        if not self._owns_runnable_claims(connection, job):
            # Nothing was sent: a pre-send hold releases what is left (D-420 §4.5 row 1).
            self._hold_in_transaction(
                connection, job, reason="FLEET_CLAIM_MISSING_BEFORE_SUBMISSION",
                claim_phase=self._pre_send_claim_phase(connection, job), actor_id="fleet", strict=False,
                event_key=f"claim-missing:{step_index}:{self._approvals(connection, job)}", detail={})
            result = self._get(connection, mission_id)
            connection.commit()
            return result
        self._set_claims(connection, job, "DISPATCHING")
        connection.execute(
            """UPDATE fleet_cell_steps SET status='RUNNING', action_id=?, attempt_id=?,
               request_digest=?, grant_json=?, updated_at=?
               WHERE mission_id=? AND step_index=?""",
            (action_id, attempt_id, parsed.request_digest,
             _json(canonical_grant), now_str, mission_id, step_index),
        )
        connection.execute(
            "UPDATE fleet_cell_jobs SET status='RUNNING', updated_at=? WHERE mission_id=?",
            (now_str, mission_id),
        )
        self._event(connection, mission_id, step_index, "CELL_STEP_SUBMITTING", "fleet",
                    {"action_id": action_id, "attempt_id": attempt_id,
                     "request_digest": parsed.request_digest,
                     "authority_epoch": parsed.authority_epoch,
                     "dispatch_generation": parsed.dispatch_generation,
                     "owner_journal_id": owner_journal_id})
        result = self._get(connection, mission_id)
        connection.commit()
    return result


def record_action_result(self, mission_id: str, *, step_index: int, event_id: str,
                         action_id: str, attempt_id: str, outcome: str,
                         result: Mapping[str, Any], reason: str | None = None) -> dict[str, Any]:
    """Record one device outcome under the caller's ``event_id``; a replay is a no-op."""
    event_id = _nonempty("event_id", event_id)
    if outcome not in _OUTCOMES:
        raise ValueError("unsupported Action outcome")
    if outcome == "SUCCEEDED":
        if reason is not None:
            raise ValueError("a successful Action result carries no hold reason")
    else:
        reason = _nonempty("reason", reason, limit=96)
    step_state, claim_phase = _OUTCOMES[outcome]
    detail = {"event_id": event_id, "action_id": action_id, "attempt_id": attempt_id,
              "outcome": outcome, "reason": reason, "result": dict(result)}
    event_type = f"CELL_STEP_ACTION_{outcome}"
    now = _now()
    with closing(self._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        job = connection.execute(
            "SELECT * FROM fleet_cell_jobs WHERE mission_id=? AND provenance_kind='legacy'", (mission_id,),
        ).fetchone()
        step = connection.execute(
            "SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
            (mission_id, step_index),
        ).fetchone()
        if job is None or step is None:
            raise KeyError(mission_id if job is None else (mission_id, step_index))
        if self._replayed(connection, mission_id, step_index, event_type, "device", event_id, detail):
            result_row = self._get(connection, mission_id)
            connection.commit()
            return result_row
        # RUNNING, or a readback of a HOLD whose claims are still UNKNOWN (1b A3).
        phases = self._claim_phases(connection, job)
        readback = step["status"] == "HOLD" and bool(phases) and phases <= {"UNKNOWN", "DISPATCHING"}
        if ((step["status"] != "RUNNING" and not readback) or step["action_id"] != action_id
                or step["attempt_id"] != attempt_id or (readback and outcome == "UNKNOWN")):
            raise MissionConflict("Action result does not match the current Cell transfer attempt")
        job_reason = reason
        if outcome == "SUCCEEDED" and not self._fence_current(connection, job):
            # 1c item 2a: the Action ended after a stop or authority change. Keep the success
            # event (resume returns the step to ACTION_SUCCEEDED) but park the Job and claims.
            step_state, claim_phase = "HOLD", "HELD"
            job_reason = job["reason"] if job["status"] == "HOLD" else "site_stop"
        connection.execute(
            "UPDATE fleet_cell_steps SET status=?, result_json=?, reason=?, updated_at=? "
            "WHERE mission_id=? AND step_index=?",
            (step_state, _json(dict(result)), job_reason, now, mission_id, step_index),
        )
        connection.execute(
            "UPDATE fleet_cell_jobs SET status=?, reason=?, updated_at=? WHERE mission_id=?",
            (step_state, job_reason, now, mission_id),
        )
        self._set_claims(connection, job, claim_phase)
        self._event(connection, mission_id, step_index, event_type, "device", detail)
        result_row = self._get(connection, mission_id)
        connection.commit()
    return result_row


def resume(self, mission_id: str, *, actor_id: str, expected_generation: int) -> dict[str, Any]:
    """Operator re-approval of a HOLD Job under the current fence (D-420 item 18)."""
    actor_id = _nonempty("actor_id", actor_id, limit=96)
    with closing(self._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        job = self._require(connection, mission_id)
        phases = self._claim_phases(connection, job)
        if job["status"] != "HOLD" or job["reason"] == CANCELLED_REASON:
            raise MissionConflict("only a held, uncancelled Cell Job can resume")
        if phases & {"DISPATCHING", "UNKNOWN"}:
            raise MissionConflict("resume is refused while a claim is DISPATCHING or UNKNOWN")
        if sheets.due(connection, mission_id, job["current_step_index"]):
            raise MissionConflict("operator sheet checkpoint requires an unavailable owner access contract")
        control = connection.execute(
            "SELECT authority_epoch, generation, dispatch_enabled FROM fleet_dispatch_control "
            "WHERE control_id=1").fetchone()
        if not control["dispatch_enabled"] or control["generation"] != expected_generation:
            raise MissionConflict("stop generation is closed or changed")
        release_claims(connection, owner_kind="mission", owner_id=mission_id)
        if not reserve_claims(connection, owner_kind="mission", owner_id=mission_id,
                              generation=expected_generation, phase="CLAIMED",
                              resources=[tuple(item) for item in json.loads(job["resources_json"])]):
            raise MissionConflict("Cell Job resource claim conflicts with another action")
        index = connection.execute(
            "SELECT MIN(step_index) FROM fleet_cell_steps WHERE mission_id=? AND status!='GOAL_CONFIRMED'",
            (mission_id,)).fetchone()[0]
        if index is not None and sheets.due(connection, mission_id, index):
            raise MissionConflict("operator sheet checkpoint requires an unavailable owner access contract")
        last = connection.execute(
            "SELECT event_type FROM fleet_cell_events WHERE mission_id=? AND step_index=? "
            "AND event_type LIKE 'CELL_STEP_ACTION_%' ORDER BY event_id DESC LIMIT 1",
            (mission_id, index)).fetchone()
        succeeded = last is not None and last["event_type"] == "CELL_STEP_ACTION_SUCCEEDED"
        state, now = ("ACTION_SUCCEEDED" if succeeded else "READY"), _now()
        clear = "" if succeeded else ", action_id=NULL, attempt_id=NULL, request_digest=NULL, grant_json=NULL"
        connection.execute(
            f"UPDATE fleet_cell_steps SET status=?, reason=NULL, updated_at=?{clear} "
            "WHERE mission_id=? AND step_index=?", (state, now, mission_id, index))
        connection.execute(
            "UPDATE fleet_cell_jobs SET status=?, reason=NULL, current_step_index=?, authority_epoch=?, "
            "dispatch_generation=?, updated_at=? WHERE mission_id=?",
            (state, index, control["authority_epoch"], expected_generation, now, mission_id))
        self._event(connection, mission_id, index, "CELL_JOB_RESUMED", actor_id, {
            "authority_epoch": control["authority_epoch"], "dispatch_generation": expected_generation,
            "previous_generation": job["dispatch_generation"], "step_status": state,
            "approvals": self._approvals(connection, job)})  # a later resume at the same fence is a new event
        result = self._get(connection, mission_id)
        connection.commit()
    return result


def cancel(self, mission_id: str, *, actor_id: str, decision: str | None = None,
           expected_generation: int | None = None) -> dict[str, Any]:
    """Operator abort: terminal, and the claims are released in the same transaction."""
    actor_id = _nonempty("actor_id", actor_id, limit=96)
    with closing(self._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        job = self._require(connection, mission_id)
        control = connection.execute("SELECT generation FROM fleet_dispatch_control WHERE control_id=1").fetchone()
        if decision is not None and (job["status"] != "PROPOSED" or control is None
                                     or control[0] != expected_generation):
            raise MissionConflict("only a PROPOSED Cell Job at the current stop generation can be rejected")
        if decision is None and (job["status"] in {"PROPOSED", "GOAL_CONFIRMED", "RUNNING"}
                                 or job["reason"] == CANCELLED_REASON):
            raise MissionConflict(f"a {job['status']} Cell Job cannot be cancelled")
        if self._claim_phases(connection, job) & {"DISPATCHING", "UNKNOWN"}:
            raise MissionConflict("cancel is refused while a claim is DISPATCHING or UNKNOWN")
        now = _now()
        connection.execute(
            "UPDATE fleet_cell_steps SET status='HOLD', reason=?, updated_at=? WHERE mission_id=? "
            "AND status IN ('READY', 'ACTION_SUCCEEDED')", (CANCELLED_REASON, now, mission_id))
        connection.execute("UPDATE fleet_cell_jobs SET status='HOLD', reason=?, updated_at=? WHERE mission_id=?",
                           (CANCELLED_REASON, now, mission_id))
        release_claims(connection, owner_kind="mission", owner_id=mission_id)
        self._event(connection, mission_id, job["current_step_index"],
                    "CELL_JOB_REJECTED" if decision else "CELL_JOB_CANCELLED", actor_id,
                    {"previous_status": job["status"], "previous_reason": job["reason"],
                     **({"decision": decision} if decision else {})})
        result = self._get(connection, mission_id)
        connection.commit()
    return result


def hold(self, mission_id: str, *, reason: str, claim_phase: str | None, actor_id: str,
         event_key: str) -> dict[str, Any]:
    """HOLD a READY, RUNNING or ACTION_SUCCEEDED Job and its current step (idempotent)."""
    reason = _nonempty("reason", reason, limit=96)
    actor_id = _nonempty("actor_id", actor_id, limit=96)
    event_key = _nonempty("event_key", event_key)
    if claim_phase not in {"HELD", "UNKNOWN"}:
        raise ValueError("claim_phase must be HELD or UNKNOWN; hold() never releases claims")
    with closing(self._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        job = connection.execute(
            "SELECT * FROM fleet_cell_jobs WHERE mission_id=? AND provenance_kind='legacy'", (mission_id,),
        ).fetchone()
        if job is None:
            raise KeyError(mission_id)
        event_key = f"{event_key}@{self._approvals(connection, job)}"
        detail = {"event_id": event_key, "reason": reason, "claim_phase": claim_phase}
        if not self._replayed(connection, mission_id, job["current_step_index"], "CELL_JOB_HELD",
                              actor_id, event_key, detail):
            if job["status"] not in _HOLDABLE:
                raise MissionConflict(f"a {job['status']} Cell Job cannot be held")
            allowed = {"UNKNOWN"} if job["status"] == "RUNNING" else {"HELD"}
            if claim_phase not in allowed:
                raise MissionConflict(f"a {job['status']} Cell Job cannot hold its claims as {claim_phase}")
            self._hold_in_transaction(connection, job, reason=reason, claim_phase=claim_phase,
                                      actor_id=actor_id, event_key=event_key, detail={})
        result = self._get(connection, mission_id)
        connection.commit()
    return result


def hold_unsent(self, mission_id: str, *, action_id: str, reason: str) -> dict[str, Any]:
    """RUNNING -> HOLD with DISPATCHING -> HELD for a started step that was never sent (1d item 1)."""
    reason = _nonempty("reason", reason, limit=96)
    with closing(self._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        job = self._require(connection, mission_id)
        step = connection.execute("SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                                  (mission_id, job["current_step_index"])).fetchone()
        seen = connection.execute(
            "SELECT 1 FROM fleet_cell_events WHERE mission_id=? AND (event_key=? OR "
            "(event_type LIKE 'CELL_STEP_ACTION_%' AND json_extract(detail_json, '$.action_id')=?)) LIMIT 1",
            (mission_id, f"{mission_id}:device-receipt:{action_id}:{step['attempt_id'] if step else ''}",
             action_id)).fetchone()
        if job["status"] != "RUNNING" or step is None or step["action_id"] != action_id or seen is not None:
            raise MissionConflict("only a started, never answered step can be held as unsent")
        self._hold_in_transaction(connection, job, reason=reason, claim_phase="HELD", actor_id="fleet",
                                  event_key=f"unsent:{action_id}", detail={"action_id": action_id})
        result = self._get(connection, mission_id)
        connection.commit()
    return result


def release_before_send(self, mission_id: str, *, reason: str, event_key: str) -> dict[str, Any]:
    """HOLD a READY Job whose current step was never started; release its claims only if the
    Job has no progress (step 0, nothing ever submitted), else park them HELD (1c item 2b)."""
    reason = _nonempty("reason", reason, limit=96)
    event_key = _nonempty("event_key", event_key)
    with closing(self._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        job = self._require(connection, mission_id)
        step = connection.execute("SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                                  (mission_id, job["current_step_index"])).fetchone()
        if job["status"] != "READY" or step is None or step["action_id"] is not None:
            raise MissionConflict("only a READY step that was never started can be released before send")
        event_key = f"{event_key}@{self._approvals(connection, job)}"
        phase = self._pre_send_claim_phase(connection, job)
        detail = {"event_id": event_key, "reason": reason, "claim_phase": phase}
        if not self._replayed(connection, mission_id, job["current_step_index"], "CELL_JOB_HELD",
                              "mission-dispatcher", event_key, detail):
            self._hold_in_transaction(connection, job, reason=reason, claim_phase=phase,
                                      actor_id="mission-dispatcher", event_key=event_key, detail={})
        result = self._get(connection, mission_id)
        connection.commit()
    return result
