"""Legacy Cell goal confirmation; physical transfers never use this completion path."""
from contextlib import closing
import json
from typing import Any, Mapping

from .dispatch_admission import release as release_claims
from .mission_store import MissionConflict, _json, _nonempty, _now
from . import cell_sheet_checkpoints as sheets


def confirm_step_goal(self, mission_id: str, *, step_index: int,
                      action_id: str, attempt_id: str,
                      evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Record already authenticated sim-model and post-action gripper evidence."""
    required_evidence = {
        "producer_id", "evidence_id", "evidence_source", "action_id", "attempt_id",
        "satisfied", "gripper_state", "gripper_evidence_id",
    }
    if not isinstance(evidence, Mapping) or not required_evidence.issubset(evidence):
        raise ValueError("Cell step goal confirmation requires independent producer and gripper evidence")
    if (evidence["evidence_source"] != "sim_model_pose"
            or evidence["action_id"] != action_id or evidence["attempt_id"] != attempt_id
            or evidence["gripper_state"] != "OPEN"
            or type(evidence["satisfied"]) is not bool):
        raise MissionConflict("Cell step goal evidence does not match the current transfer attempt")
    if evidence["satisfied"] is not True:
        raise MissionConflict("unsatisfied Cell step goal evidence cannot advance the Job")
    for field in ("producer_id", "evidence_id", "gripper_evidence_id"):  # from main 64b4b1faa
        _nonempty(field, evidence[field], limit=192)
    evidence_json = _json(dict(evidence))
    event_id = f"goal:{step_index}:{_nonempty('evidence_id', evidence['evidence_id'])}"
    detail = {**json.loads(evidence_json), "event_id": event_id}
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
        final = connection.execute(
            "SELECT MAX(step_index) FROM fleet_cell_steps WHERE mission_id=?", (mission_id,),
        ).fetchone()[0] == step_index
        event_type = "CELL_JOB_GOAL_CONFIRMED" if final else "CELL_STEP_GOAL_CONFIRMED"
        if self._replayed(connection, mission_id, step_index, event_type, "goal-evidence",
                          event_id, detail):
            result = self._get(connection, mission_id)
            connection.commit()
            return result
        if (job["status"] != "ACTION_SUCCEEDED" or step["status"] != "ACTION_SUCCEEDED"
                or job["current_step_index"] != step_index
                or step["action_id"] != action_id or step["attempt_id"] != attempt_id
                or not self._durable_success(connection, mission_id, step_index, action_id, attempt_id)):
            raise MissionConflict("independent goal evidence requires this step's terminal Action success")
        now = _now()
        connection.execute(
            "UPDATE fleet_cell_steps SET status='GOAL_CONFIRMED', goal_evidence_json=?, "
            "reason=NULL, updated_at=? WHERE mission_id=? AND step_index=?",
            (evidence_json, now, mission_id, step_index),
        )
        next_index = step_index + 1
        next_step = connection.execute(
            "SELECT step_index FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
            (mission_id, next_index),
        ).fetchone()
        if next_step is not None:
            # From main 64b4b1faa: the next step opens only under the current fence; otherwise
            # the Job waits for re-approval with its claims parked HELD (D-403 보강).
            can_continue = self._fence_current(connection, job)
            if can_continue:
                connection.execute(
                    "UPDATE fleet_cell_steps SET status='READY', updated_at=? "
                    "WHERE mission_id=? AND step_index=? AND status='WAITING'",
                    (now, mission_id, next_index),
                )
            else:
                self._set_claims(connection, job, "HELD", strict=False, context="goal-advance")
            connection.execute(
                "UPDATE fleet_cell_jobs SET status=?, current_step_index=?, "
                "reason=?, updated_at=? WHERE mission_id=?",
                ("READY" if can_continue else "HOLD", next_index,
                 None if can_continue else "SITE_AUTHORITY_CHANGED", now, mission_id),
            )
            sheets.hold_due(connection, self._require(connection, mission_id), next_index, now, self._event)
            event_type = "CELL_STEP_GOAL_CONFIRMED"
        else:
            connection.execute(
                "UPDATE fleet_cell_jobs SET status='GOAL_CONFIRMED', current_step_index=?, "
                "reason=NULL, updated_at=? WHERE mission_id=?",
                (next_index, now, mission_id),
            )
            release_claims(connection, owner_kind="mission", owner_id=mission_id,
                           generation=job["dispatch_generation"])
            event_type = "CELL_JOB_GOAL_CONFIRMED"
        self._event(connection, mission_id, step_index, event_type, "goal-evidence", detail)
        result = self._get(connection, mission_id)
        connection.commit()
    return result
