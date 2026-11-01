"""Workflow state, receipts and HOLD of the ActionStore journal (mixin of ActionStore)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Any, Mapping

from .action_store_readback import _nonempty
from .action_store_phases import InvalidActionTransition, _json, _utc_now
from .workflow_states import _PICK_PLACE_PHASES, _WORKFLOW_STATES, _WORKFLOW_EVIDENCE_KEYS, _COMPLETION_BY_KIND


class _ActionWorkflowOps:
    """Workflow/receipt/hold operations; relies on ActionStore._connect/_append_event."""

    def record_workflow_state(
        self, action_id: str, attempt_id: str, *, workflow_state: str,
        object_may_be_held: bool, evidence_refs: Mapping[str, object],
    ) -> dict[str, Any]:
        """Append bounded semantic workflow evidence without inventing ROS goals."""
        if workflow_state not in _WORKFLOW_STATES:
            raise ValueError("unsupported pick-place workflow state")
        if type(object_may_be_held) is not bool:
            raise ValueError("object_may_be_held must be boolean")
        if not isinstance(evidence_refs, Mapping) or not set(evidence_refs) <= _WORKFLOW_EVIDENCE_KEYS:
            raise ValueError("workflow evidence refs contain unsupported fields")
        refs = dict(evidence_refs)
        for name, value in refs.items():
            if name.endswith("_sequence"):
                if type(value) is not int or value < 0:
                    raise ValueError(f"{name} must be a non-negative integer")
            else:
                _nonempty(name, value, maximum=192)
        _json(refs)
        if workflow_state == "ACTION_SUCCEEDED":
            if object_may_be_held or not {
                "gripper_hold_sequence", "gripper_release_sequence",
            } <= set(refs):
                raise InvalidActionTransition(
                    "Action success requires released-object readback evidence",
                )
            if refs["gripper_release_sequence"] <= refs["gripper_hold_sequence"]:
                raise InvalidActionTransition("release readback must follow the hold readback")
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id,
                {"SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "HOLD"},
            )
            if action["state"] in {"UNKNOWN", "HOLD", "CANCEL_REQUESTED"} \
                    and workflow_state != "HOLD":
                raise InvalidActionTransition(
                    "unresolved or canceling Action can record HOLD only",
                )
            if workflow_state == "ACTION_SUCCEEDED":
                if action["state"] not in {"ACCEPTED", "RUNNING"}:
                    raise InvalidActionTransition("held or unresolved Action cannot complete")
                phases = connection.execute(
                    "SELECT phase_id, ordinal, state FROM omx_action_phases "
                    "WHERE action_id=? AND attempt_id=? ORDER BY ordinal",
                    (action_id, attempt_id),
                ).fetchall()
                if (tuple(row["phase_id"] for row in phases) != _PICK_PLACE_PHASES
                        or tuple(row["ordinal"] for row in phases) != tuple(range(4))
                        or any(row["state"] != "SUCCEEDED" for row in phases)):
                    raise InvalidActionTransition(
                        "completed workflow requires four successful ROS motion phases",
                    )
            detail = {
                "workflow_state": workflow_state,
                "object_may_be_held": object_may_be_held,
                "evidence_refs": refs,
            }
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=workflow_state, event_type="ACTION_WORKFLOW_STATE",
                actor_id=action["principal_id"], detail=detail, created_at=now,
            )
            event = connection.execute(
                "SELECT * FROM omx_action_events WHERE action_id=? ORDER BY event_id DESC LIMIT 1",
                (action_id,),
            ).fetchone()
            connection.commit()
        result = dict(event)
        result["detail"] = json.loads(result.pop("detail_json"))
        return result

    def complete_pick_place(self, action_id: str, attempt_id: str, *,
                            result_observed_at: str,
                            result: Mapping[str, Any]) -> dict[str, Any]:
        """Complete a local Action only after all phase and workflow evidence is durable."""
        result_observed_at = _nonempty("result_observed_at", result_observed_at)
        if not isinstance(result, Mapping):
            raise ValueError("result must be a JSON object")
        result_json = _json(dict(result))
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id, {"ACCEPTED", "RUNNING"},
            )
            phases = connection.execute(
                "SELECT phase_id, ordinal, state FROM omx_action_phases "
                "WHERE action_id=? AND attempt_id=? ORDER BY ordinal",
                (action_id, attempt_id),
            ).fetchall()
            latest_workflow = connection.execute(
                "SELECT detail_json FROM omx_action_events WHERE action_id=? AND attempt_id=? "
                "AND event_type='ACTION_WORKFLOW_STATE' ORDER BY event_id DESC LIMIT 1",
                (action_id, attempt_id),
            ).fetchone()
            if (tuple(row["phase_id"] for row in phases) != _PICK_PLACE_PHASES
                    or tuple(row["ordinal"] for row in phases) != tuple(range(4))
                    or any(row["state"] != "SUCCEEDED" for row in phases)):
                raise InvalidActionTransition("Action completion requires four successful ROS phases")
            if latest_workflow is None:
                raise InvalidActionTransition("Action completion requires durable workflow evidence")
            workflow = json.loads(latest_workflow["detail_json"])
            if (workflow.get("workflow_state") != "ACTION_SUCCEEDED"
                    or workflow.get("object_may_be_held") is not False):
                raise InvalidActionTransition("Action completion requires verified gripper release")
            refs = workflow.get("evidence_refs", {})
            if not {"gripper_hold_sequence", "gripper_release_sequence"} <= set(refs):
                raise InvalidActionTransition("Action completion evidence refs are incomplete")
            if refs["gripper_release_sequence"] <= refs["gripper_hold_sequence"]:
                raise InvalidActionTransition("release readback must follow the hold readback")
            source, completed = _COMPLETION_BY_KIND[action["action_kind"]]
            connection.execute(
                """UPDATE omx_actions SET state='SUCCEEDED', result_source=?,
                   result_observed_at=?, result_json=?, reason=NULL, updated_at=?
                   WHERE action_id=? AND attempt_id=?""",
                (source, result_observed_at, result_json, now, action_id, attempt_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state="SUCCEEDED",
                event_type=completed, actor_id=action["principal_id"],
                detail={"result_source": source, "result_observed_at": result_observed_at,
                        "phase_count": len(phases), "result": dict(result)},
                created_at=now,
            )
            updated = connection.execute("SELECT * FROM omx_actions WHERE action_id=?", (action_id,)).fetchone()
            connection.commit()
        return self._dict(updated)

    def _transition_phase(self, action_id: str, attempt_id: str, *, phase_id: str,
                          allowed: set[str], target: str, event_type: str,
                          driver_goal_id: str | None = None) -> dict[str, Any]:
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        if driver_goal_id is not None:
            driver_goal_id = _nonempty("driver_goal_id", driver_goal_id)
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id,
                {"ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "HOLD"},
            )
            phase = self._require_phase(connection, action_id, attempt_id, phase_id, allowed)
            if driver_goal_id is not None and phase["driver_goal_id"] != driver_goal_id:
                raise InvalidActionTransition("ROS goal identity does not match Action phase")
            connection.execute(
                "UPDATE omx_action_phases SET state=?, updated_at=? "
                "WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (target, now, action_id, attempt_id, phase_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state=target,
                event_type=event_type, actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "driver_goal_id": phase["driver_goal_id"]},
                created_at=now,
            )
            updated = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return self._phase_dict(updated)

    @staticmethod
    def _require_phase(connection: sqlite3.Connection, action_id: str, attempt_id: str,
                       phase_id: str, allowed: set[str]) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
            (action_id, attempt_id, phase_id),
        ).fetchone()
        if row is None or row["state"] not in allowed:
            raise InvalidActionTransition("Action phase state does not allow this transition")
        return row

    def action_phases(self, action_id: str, attempt_id: str | None = None) -> list[dict[str, Any]]:
        action_id = _nonempty("action_id", action_id)
        with closing(self._connect()) as connection:
            if attempt_id is None:
                rows = connection.execute(
                    "SELECT * FROM omx_action_phases WHERE action_id=? ORDER BY attempt_id, ordinal",
                    (action_id,),
                ).fetchall()
            else:
                attempt_id = _nonempty("attempt_id", attempt_id)
                rows = connection.execute(
                    "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? ORDER BY ordinal",
                    (action_id, attempt_id),
                ).fetchall()
        return [self._phase_dict(row) for row in rows]

    def action_phase_receipts(self, action_id: str, attempt_id: str) -> list[dict[str, Any]]:
        """Return bounded phase snapshots with each phase's latest local event ID."""
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            phase_rows = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? ORDER BY ordinal",
                (action_id, attempt_id),
            ).fetchall()
            event_rows = connection.execute(
                "SELECT * FROM omx_action_events WHERE action_id=? AND attempt_id=? "
                "AND event_type LIKE 'ACTION_PHASE_%' ORDER BY event_id",
                (action_id, attempt_id),
            ).fetchall()
        phases = [self._phase_dict(row) for row in phase_rows]
        if len(phases) > 4:
            raise InvalidActionTransition("pick-place phase journal exceeds its fixed bound")
        history = [dict(row) for row in event_rows]
        for event in history:
            event["detail"] = json.loads(event.pop("detail_json"))
        result = []
        for phase in phases:
            matching = [event for event in history
                        if event["attempt_id"] == attempt_id
                        and event["detail"].get("phase_id") == phase["phase_id"]
                        and event["event_type"].startswith("ACTION_PHASE_")]
            if not matching:
                raise InvalidActionTransition("phase journal has no durable event")
            result.append({
                "phase_id": phase["phase_id"], "ordinal": phase["ordinal"],
                "state": phase["state"], "journal_event_id": matching[-1]["event_id"],
                "observed_at": phase["updated_at"],
            })
        return result

    def latest_workflow_state(self, action_id: str, attempt_id: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT detail_json FROM omx_action_events WHERE action_id=? AND attempt_id=? "
                "AND event_type='ACTION_WORKFLOW_STATE' ORDER BY event_id DESC LIMIT 1",
                (action_id, attempt_id),
            ).fetchone()
        if row is None:
            return None
        detail = json.loads(row["detail_json"])
        state = detail.get("workflow_state")
        return state if state in _WORKFLOW_STATES else None
