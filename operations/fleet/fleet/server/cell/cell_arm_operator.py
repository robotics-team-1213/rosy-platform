"""Operator intervention and recovery helpers for multi-arm Cell Jobs (D-779 §1, §6)."""

from __future__ import annotations

import json
from typing import Any

from fleet.server import cell_arm_jobs as arm_jobs
from fleet.server.cell_arm_claims import phases, release_for_resume, set_phase
from fleet.server.cell_arm_jobs import CANCELLED_REASON, TIGHT_PARTNER_REASON, summarize
from fleet.server.cell_job_store import CellJobStore
from fleet.server.dispatch_admission import release as release_claims
from fleet.server.dispatch_admission import reserve as reserve_claims
from fleet.server.mission_store import MissionConflict, _nonempty, _now

_UNRESOLVED = {"DISPATCHING", "UNKNOWN"}


def hold_tight_partners_on_failure(store, connection, mission_id, step_index, role, now) -> None:
    """A tight step's partner arms HOLD with it (D-779 §6); a partner still in flight is UNKNOWN."""
    placement = store._placement(connection, mission_id, step_index)
    if placement["coupling"] != "tight":
        return
    for other in placement["assigned"]:
        row = store._action(connection, mission_id, step_index, other)
        if other == role or row is None:
            continue
        if row["status"] == "RUNNING":
            store._set_action(connection, row, now, status="HOLD", reason=TIGHT_PARTNER_REASON)
            set_phase(connection, mission_id, (step_index, other), json.loads(row["claims_json"]), "UNKNOWN")
        elif row["status"] in {"WAITING", "READY"}:
            store._set_action(connection, row, now, status="HOLD", reason=TIGHT_PARTNER_REASON)
        arm_jobs.hold_arms(connection, mission_id, [other], TIGHT_PARTNER_REASON, now, statuses=("READY", "RUNNING"))
        arm_jobs.event(connection, mission_id, step_index, "CELL_ARM_HELD", "fleet", {
            "event_id": f"tight-partner:{step_index}:{other}:{row['attempt_id'] or 'unsent'}",
            "arm_role": other, "partner_arm": role, "reason": TIGHT_PARTNER_REASON})


def apply_arm_offline(store, mission_id: str, *, arm_role: str, actor_id: str, reason: str) -> dict[str, Any]:
    """An operator or start check takes an idle arm out (D-779 §1 OFFLINE); its steps may go to alternates."""
    actor_id, reason = _nonempty("actor_id", actor_id, limit=96), _nonempty("reason", reason, limit=96)
    with store._tx(mission_id) as (connection, job):
        arm = store._arm(connection, mission_id, arm_role)
        if arm is None or arm["status"] not in {"READY", "HOLD"} or job["reason"] == CANCELLED_REASON:
            raise MissionConflict("only an idle arm of a live multi-arm Cell Job can be taken offline")
        now = _now()
        store._set_arm(connection, mission_id, arm_role, now, "OFFLINE", reason, arm["running_step_index"])
        arm_jobs.event(connection, mission_id, None, "CELL_ARM_OFFLINE", actor_id, {
            "arm_role": arm_role, "reason": reason, "previous_status": arm["status"]})
        summarize(connection, mission_id, now, reason=reason)
        return store._finish(connection, mission_id)


def build_resume_actions(store, connection, job, rows, now) -> None:
    """A held Action goes back to READY, or ACTION_SUCCEEDED when its device last reported success
    (the transfer is never sent again; goal evidence decides), as single-arm resume does."""
    for row in rows:
        last = store._last_outcome(connection, job["mission_id"], row["action_id"]) if row["action_id"] else None
        succeeded = (last is not None and last["event_type"] == "CELL_STEP_ACTION_SUCCEEDED"
                     and json.loads(last["detail_json"]).get("attempt_id") == row["attempt_id"])
        if succeeded:
            store._set_action(connection, row, now, status="ACTION_SUCCEEDED", reason=None)
        else:
            store._set_action(connection, row, now, status="READY", reason=None, action_id=None, attempt_id=None,
                              request_digest=None, grant_json=None, claims_json="[]")


def held_tight_partners(store, connection, mission_id, role) -> list[str]:
    """The still held or offline partners of ``role`` on its unconfirmed tight steps."""
    confirmed = {row[0] for row in connection.execute(
        "SELECT step_index FROM fleet_cell_steps WHERE mission_id=? AND status='GOAL_CONFIRMED'", (mission_id,))}
    partners = {other for item in arm_jobs.placements(connection, mission_id)
                if item["coupling"] == "tight" and item["step_index"] not in confirmed and role in item["assigned"]
                for other in item["assigned"] if other != role}
    return sorted(other for other in partners
                  if store._arm(connection, mission_id, other)["status"] in {"HOLD", "OFFLINE"})


def apply_arm_resume(store, mission_id: str, *, arm_role: str, actor_id: str,
                     expected_generation: int) -> dict[str, Any]:
    """Operator resume of one arm under the current fence (D-779 §6): its HELD claims are released."""
    actor_id = _nonempty("actor_id", actor_id, limit=96)
    with store._tx(mission_id) as (connection, job):
        arm = store._arm(connection, mission_id, arm_role)
        if (arm is None or arm["status"] not in {"HOLD", "OFFLINE"} or job["reason"] == CANCELLED_REASON
                or job["status"] in {"PROPOSED", "GOAL_CONFIRMED"}):
            raise MissionConflict("only a held arm of a live, uncancelled Cell Job can resume")
        control = connection.execute("SELECT generation FROM fleet_dispatch_control WHERE control_id=1").fetchone()
        if (control is None or control[0] != expected_generation
                or not CellJobStore._fence_current(connection, job) or not store._job_claims_ok(connection, job)):
            raise MissionConflict("the stop generation or authority changed: resume the whole Job")
        rows = connection.execute("SELECT * FROM fleet_cell_step_actions WHERE mission_id=? AND arm_role=? "
                                  "AND status='HOLD'", (mission_id, arm_role)).fetchall()
        if TIGHT_PARTNER_REASON in {arm["reason"], *(row["reason"] for row in rows)}:
            held = store._held_tight_partners(connection, mission_id, arm_role)
            if held:
                raise MissionConflict(f"arm {arm_role} was held with its tight partner: resume "
                                      f"{', '.join(held)} first, or the whole Job")
        keys = sorted({key for row in rows for key in json.loads(row["claims_json"])})
        if phases(connection, mission_id, keys) & _UNRESOLVED:
            raise MissionConflict("resume is refused while an arm claim is DISPATCHING or UNKNOWN")
        now = _now()
        for row in rows:
            release_for_resume(connection, mission_id, job["dispatch_generation"],
                               (row["step_index"], arm_role), json.loads(row["claims_json"]))
        store._resume_actions(connection, job, rows, now)
        store._set_arm(connection, mission_id, arm_role, now, "READY", None)
        resumed = connection.execute("SELECT COUNT(*) FROM fleet_cell_events WHERE mission_id=? AND "
                                     "event_type='CELL_ARM_RESUMED'", (mission_id,)).fetchone()[0]
        arm_jobs.event(connection, mission_id, None, "CELL_ARM_RESUMED", actor_id, {
            "event_id": f"arm-resume:{arm_role}:{resumed}", "arm_role": arm_role,
            "previous_status": arm["status"], "previous_reason": arm["reason"],
            "dispatch_generation": expected_generation})
        summarize(connection, mission_id, now)
        return store._finish(connection, mission_id)


def apply_job_resume(store, mission_id: str, *, actor_id: str, expected_generation: int) -> dict[str, Any]:
    """Operator re-approval of the whole Job under the current fence: every arm resumes (D-779 §6)."""
    actor_id = _nonempty("actor_id", actor_id, limit=96)
    with store._tx(mission_id) as (connection, job):
        if job["status"] not in {"HOLD", "READY"} or job["reason"] == CANCELLED_REASON:
            raise MissionConflict("only a held, uncancelled Cell Job can resume")
        if CellJobStore._claim_phases(connection, job) & _UNRESOLVED:
            raise MissionConflict("resume is refused while a claim is DISPATCHING or UNKNOWN")
        control = connection.execute("SELECT authority_epoch, generation, dispatch_enabled FROM "
                                     "fleet_dispatch_control WHERE control_id=1").fetchone()
        if not control["dispatch_enabled"] or control["generation"] != expected_generation:
            raise MissionConflict("stop generation is closed or changed")
        release_claims(connection, owner_kind="mission", owner_id=mission_id)
        if not reserve_claims(connection, owner_kind="mission", owner_id=mission_id,
                              generation=expected_generation, phase="CLAIMED",
                              resources=[tuple(item) for item in json.loads(job["resources_json"])]):
            raise MissionConflict("Cell Job resource claim conflicts with another action")
        now = _now()
        rows = connection.execute("SELECT * FROM fleet_cell_step_actions WHERE mission_id=? AND status='HOLD'",
                                  (mission_id,)).fetchall()
        store._resume_actions(connection, job, rows, now)
        connection.execute("UPDATE fleet_cell_job_arms SET status='READY', reason=NULL, running_step_index=NULL, "
                           "updated_at=? WHERE mission_id=?", (now, mission_id))
        connection.execute("UPDATE fleet_cell_jobs SET authority_epoch=?, dispatch_generation=?, updated_at=? "
                           "WHERE mission_id=?", (control["authority_epoch"], expected_generation, now, mission_id))
        arm_jobs.event(connection, mission_id, job["current_step_index"], "CELL_JOB_RESUMED", actor_id, {
            "authority_epoch": control["authority_epoch"], "dispatch_generation": expected_generation,
            "previous_generation": job["dispatch_generation"], "arm_roles": "all",
            "approvals": CellJobStore._approvals(connection, job)})
        summarize(connection, mission_id, now)
        return store._finish(connection, mission_id)


def apply_job_cancel(store, mission_id: str, *, actor_id: str) -> dict[str, Any]:
    """Operator cancel of the whole Job (D-779 §6), the single-arm rules in one transaction: terminal,
    refused while a claim is DISPATCHING or UNKNOWN, every claim released, every arm shows it."""
    actor_id = _nonempty("actor_id", actor_id, limit=96)
    with store._tx(mission_id) as (connection, job):
        if job["status"] in {"PROPOSED", "GOAL_CONFIRMED", "RUNNING"} or job["reason"] == CANCELLED_REASON:
            raise MissionConflict(f"a {job['status']} Cell Job cannot be cancelled")
        if CellJobStore._claim_phases(connection, job) & _UNRESOLVED:
            raise MissionConflict("cancel is refused while a claim is DISPATCHING or UNKNOWN")
        values = (CANCELLED_REASON, _now(), mission_id)
        connection.execute("UPDATE fleet_cell_steps SET status='HOLD', reason=?, updated_at=? WHERE mission_id=? "
                           "AND status IN ('READY', 'ACTION_SUCCEEDED')", values)
        connection.execute("UPDATE fleet_cell_step_actions SET status='HOLD', reason=?, updated_at=? WHERE "
                           "mission_id=? AND status IN ('WAITING', 'READY', 'ACTION_SUCCEEDED')", values)
        connection.execute("UPDATE fleet_cell_job_arms SET status='HOLD', reason=?, updated_at=? "
                           "WHERE mission_id=? AND status != 'OFFLINE'", values)
        connection.execute("UPDATE fleet_cell_jobs SET status='HOLD', reason=?, updated_at=? WHERE mission_id=?",
                           values)
        release_claims(connection, owner_kind="mission", owner_id=mission_id)
        arm_jobs.event(connection, mission_id, job["current_step_index"], "CELL_JOB_CANCELLED", actor_id,
                       {"previous_status": job["status"], "previous_reason": job["reason"]})
        return store._finish(connection, mission_id)
