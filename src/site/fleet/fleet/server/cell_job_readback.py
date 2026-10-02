"""Attempt-bound Cell Job readback and terminal journal operations."""

from contextlib import closing
import json
from typing import Any, Mapping

from core_common.protocol.schemas import FleetCellTransferGrant

from .action_receipts import verify_phase_receipt
from .cell_job_codec import _json
from .cell_job_phase_history import verify_cell_phase_history
from .mission_store import MissionConflict, _nonempty, _now


class CellJobReadbackMixin:
    """Operations sharing CellJobStore's connection, event and row projections."""

    def _fence_readback(self, connection, mission_id):
        job = connection.execute(
            "SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,),
        ).fetchone()
        control = connection.execute(
            "SELECT * FROM fleet_dispatch_control WHERE control_id=1",
        ).fetchone()
        if (job["status"] in {"READY", "RUNNING", "ACTION_SUCCEEDED"}
                and (not control["dispatch_enabled"]
                     or job["authority_epoch"] != control["authority_epoch"]
                     or job["dispatch_generation"] != control["generation"])):
            now = _now()
            connection.execute(
                "UPDATE fleet_cell_jobs SET status='HOLD', reason='SITE_AUTHORITY_CHANGED', "
                "updated_at=? WHERE mission_id=?", (now, mission_id),
            )
            connection.execute(
                "UPDATE fleet_cell_steps SET status='HOLD', reason='SITE_AUTHORITY_CHANGED', "
                "updated_at=? WHERE mission_id=? AND step_index=? "
                "AND status IN ('READY', 'RUNNING', 'ACTION_SUCCEEDED')",
                (now, mission_id, job["current_step_index"]),
            )
            self._event(connection, mission_id, job["current_step_index"],
                        "CELL_JOB_READBACK_HOLD", "system", {
                            "reason": "SITE_AUTHORITY_CHANGED",
                            "authority_epoch": control["authority_epoch"],
                            "dispatch_generation": control["generation"],
                        })

    def dispatch_candidates(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            identifiers = connection.execute(
                """SELECT j.mission_id FROM fleet_cell_jobs j
                   JOIN fleet_cell_steps s ON s.mission_id=j.mission_id
                     AND s.step_index=j.current_step_index
                   WHERE j.status IN ('READY', 'RUNNING') OR
                     (j.status='HOLD' AND s.grant_json IS NOT NULL
                      AND COALESCE(json_extract(s.result_json, '$.state'), '')
                          NOT IN ('SUCCEEDED', 'FAILED', 'HOLD'))
                   ORDER BY j.created_at, j.mission_id""",
            ).fetchall()
            return [self._get(connection, row["mission_id"]) for row in identifiers]

    @staticmethod
    def _current_attempt(connection, mission_id, step_index, action_id, attempt_id):
        job = connection.execute("SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,)).fetchone()
        step = connection.execute(
            "SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?", (mission_id, step_index),
        ).fetchone()
        if job is None or step is None:
            raise KeyError(mission_id if job is None else (mission_id, step_index))
        if (job["current_step_index"] != step_index or step["action_id"] != action_id
                or step["attempt_id"] != attempt_id):
            raise MissionConflict("Action result does not match the current Cell transfer attempt")
        return job, step

    def _apply_action_result(self, connection, job, step, *, event_id, outcome, result):
        if outcome not in {"SUCCEEDED", "FAILED", "UNKNOWN", "HOLD"}:
            raise ValueError("unsupported Cell Action outcome")
        event_type = "CELL_STEP_ACTION_SUCCEEDED" if outcome == "SUCCEEDED" else "CELL_STEP_ACTION_UNKNOWN"
        detail = {"event_id": event_id, "action_id": step["action_id"], "attempt_id": step["attempt_id"],
                  "outcome": outcome, "result": dict(result)}
        prior = connection.execute(
            "SELECT 1 FROM fleet_cell_events WHERE event_key=?", (f"{job['mission_id']}:{event_id}",),
        ).fetchone()
        if prior is not None:
            self._event(connection, job["mission_id"], step["step_index"], event_type, "device", detail)
            return
        if step["status"] not in {"RUNNING", "HOLD"}:
            raise MissionConflict("Action result does not match the current Cell transfer attempt")
        if outcome == "SUCCEEDED" and step["status"] == "RUNNING":
            state, reason = "ACTION_SUCCEEDED", None
        else:
            state = "HOLD"
            reason = ("LATE_SUCCESS_REQUIRES_INDEPENDENT_GOAL_EVIDENCE" if outcome == "SUCCEEDED"
                      else "ACTION_OUTCOME_UNKNOWN")
        now = _now()
        connection.execute(
            "UPDATE fleet_cell_steps SET status=?, result_json=?, reason=?, updated_at=? "
            "WHERE mission_id=? AND step_index=?",
            (state, _json(dict(result)), reason, now, job["mission_id"], step["step_index"]),
        )
        connection.execute(
            "UPDATE fleet_cell_jobs SET status=?, reason=?, updated_at=? WHERE mission_id=?",
            (state, reason, now, job["mission_id"]),
        )
        self._event(connection, job["mission_id"], step["step_index"], event_type, "device", detail)

    def record_action_result(self, mission_id: str, *, step_index: int, event_id: str,
                             action_id: str, attempt_id: str, outcome: str,
                             result: Mapping[str, Any]) -> dict[str, Any]:
        event_id = _nonempty("event_id", event_id)
        _json(dict(result))
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._fence_readback(connection, mission_id)
            job, step = self._current_attempt(connection, mission_id, step_index, action_id, attempt_id)
            self._apply_action_result(connection, job, step, event_id=event_id, outcome=outcome, result=result)
            row = self._get(connection, mission_id)
            connection.commit()
        return row

    def record_action_receipt(self, mission_id: str, *, step_index: int,
                              receipt: object) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            step = connection.execute(
                "SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?", (mission_id, step_index),
            ).fetchone()
            if step is None:
                raise KeyError((mission_id, step_index))
            grant = FleetCellTransferGrant.model_validate(json.loads(step["grant_json"]))
            verified = verify_phase_receipt(grant, receipt)
            document = verified.model_dump(mode="json")
            identity = (f"cell-receipt:{verified.instance_id}:{verified.action_id}:"
                        f"{verified.attempt_id}:{verified.journal_event_id}")
            self._fence_readback(connection, mission_id)
            prior = connection.execute("SELECT 1 FROM fleet_cell_events WHERE event_key=?",
                                       (f"{mission_id}:{identity}",)).fetchone()
            if prior is not None:
                self._event(connection, mission_id, step_index, "CELL_STEP_ACTION_READBACK", "device",
                            {**document, "event_id": identity})
                row = self._get(connection, mission_id)
                connection.commit()
                return row
            job, step = self._current_attempt(connection, mission_id, step_index,
                                              verified.action_id, verified.attempt_id)
            previous = connection.execute(
                "SELECT detail_json FROM fleet_cell_events WHERE mission_id=? AND step_index=? "
                "AND event_type='CELL_STEP_ACTION_READBACK' ORDER BY event_id DESC LIMIT 1",
                (mission_id, step_index),
            ).fetchone()
            if previous is not None and verified.journal_event_id < json.loads(previous["detail_json"])[
                    "journal_event_id"]:
                connection.commit()
                return self._get(connection, mission_id)
            if step["status"] not in {"RUNNING", "HOLD"}:
                raise MissionConflict("Cell receipt does not match an unresolved transfer")
            verify_cell_phase_history(connection, mission_id, step_index, document)
            self._event(connection, mission_id, step_index, "CELL_STEP_ACTION_READBACK", "device",
                        {**document, "event_id": identity})
            state = verified.state.value
            if state in {"SUCCEEDED", "FAILED", "UNKNOWN", "HOLD"}:
                self._apply_action_result(connection, job, step, event_id=identity + ":terminal",
                                          outcome=state, result=document)
            else:
                connection.execute(
                    "UPDATE fleet_cell_steps SET result_json=?, updated_at=? WHERE mission_id=? AND step_index=?",
                    (_json(document), _now(), mission_id, step_index),
                )
            row = self._get(connection, mission_id)
            connection.commit()
        return row
