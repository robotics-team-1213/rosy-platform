"""Hold, resume, cancel, and pre-send release helpers for ``CellJobStore`` (D-403)."""

from __future__ import annotations

import json
from contextlib import closing
from typing import Any

from . import cell_sheet_checkpoints as sheets
from .dispatch_admission import release as release_claims, reserve as reserve_claims
from .mission_store import MissionConflict, _nonempty, _now

# A cancelled Job is terminal. The status column has no CANCELLED value and 1b makes no schema
# change, so it is HOLD with this reason and no claims; resume refuses it (D-420 v2 adds a status).
CANCELLED_REASON = "CANCELLED_BY_OPERATOR"
_HOLDABLE = frozenset({"READY", "RUNNING", "ACTION_SUCCEEDED"})


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
