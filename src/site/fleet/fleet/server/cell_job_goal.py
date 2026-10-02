"""Independent Cell step goals reconcile only an exact durable successful attempt."""

from contextlib import closing
import json
from typing import Any, Mapping

from .cell_job_codec import _json
from .dispatch_admission import release as release_claims
from .mission_store import MissionConflict, _nonempty, _now


class CellJobGoalMixin:
    """Completion shares the Cell journal transaction and occupancy owner."""

    @staticmethod
    def _terminal_step_succeeded(connection, mission_id, step_index, action_id, attempt_id,
                                 expected_terminal_event_id=None):
        row = connection.execute(
            "SELECT event_id, detail_json FROM fleet_cell_events WHERE mission_id=? AND step_index=? "
            "AND event_type IN ('CELL_STEP_ACTION_SUCCEEDED', 'CELL_STEP_ACTION_UNKNOWN') "
            "ORDER BY event_id DESC LIMIT 1", (mission_id, step_index),
        ).fetchone()
        if row is None or (expected_terminal_event_id is not None and row["event_id"] != expected_terminal_event_id):
            return False
        detail = json.loads(row["detail_json"])
        return (detail["action_id"] == action_id and detail["attempt_id"] == attempt_id
                and detail["outcome"] == "SUCCEEDED")

    def terminal_step_succeeded(self, mission_id: str, *, step_index: int,
                                action_id: str, attempt_id: str) -> bool:
        with closing(self._connect()) as connection:
            return self._terminal_step_succeeded(connection, mission_id, step_index, action_id, attempt_id)

    def confirm_step_goal(self, mission_id: str, *, step_index: int,
                          action_id: str, attempt_id: str,
                          evidence: Mapping[str, Any], expected_terminal_event_id: int | None = None) -> dict[str, Any]:
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
        for field in ("producer_id", "evidence_id", "gripper_evidence_id"):
            _nonempty(field, evidence[field], limit=192)
        evidence_json = _json(dict(evidence))
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,),
            ).fetchone()
            step = connection.execute(
                "SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                (mission_id, step_index),
            ).fetchone()
            if job is None or step is None:
                raise KeyError(mission_id if job is None else (mission_id, step_index))
            if step["action_id"] != action_id or step["attempt_id"] != attempt_id:
                raise MissionConflict("independent goal evidence requires this step's terminal Action success")
            if step["status"] == "GOAL_CONFIRMED":
                if step["goal_evidence_json"] != evidence_json:
                    raise MissionConflict("confirmed Cell goal cannot be rewritten with different evidence")
                self._fence_readback(connection, mission_id)
                result = self._get(connection, mission_id)
                connection.commit()
                return result
            if (job["current_step_index"] != step_index
                    or job["status"] not in {"ACTION_SUCCEEDED", "HOLD"}
                    or step["status"] not in {"ACTION_SUCCEEDED", "HOLD"}
                    or not self._terminal_step_succeeded(connection, mission_id, step_index, action_id, attempt_id,
                                                         expected_terminal_event_id)):
                raise MissionConflict("independent goal evidence requires this step's terminal Action success")
            self._fence_readback(connection, mission_id)
            control = connection.execute("SELECT * FROM fleet_dispatch_control WHERE control_id=1").fetchone()
            can_continue = (control["dispatch_enabled"] and job["authority_epoch"] == control["authority_epoch"]
                            and job["dispatch_generation"] == control["generation"])
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
                if can_continue:
                    connection.execute(
                        "UPDATE fleet_cell_steps SET status='READY', updated_at=? "
                        "WHERE mission_id=? AND step_index=? AND status='WAITING'",
                        (now, mission_id, next_index),
                    )
                connection.execute(
                    "UPDATE fleet_cell_jobs SET status=?, current_step_index=?, "
                    "reason=?, updated_at=? WHERE mission_id=?",
                    ("READY" if can_continue else "HOLD", next_index,
                     None if can_continue else "SITE_AUTHORITY_CHANGED", now, mission_id),
                )
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
            self._event(connection, mission_id, step_index, event_type, "goal-evidence",
                        json.loads(evidence_json))
            result = self._get(connection, mission_id)
            connection.commit()
        return result
