"""Phase-level transitions of the ActionStore journal (mixin of ActionStore)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Mapping

from .action_store_readback import _nonempty


class ActionConflict(ValueError):
    """An idempotency key was reused with a different semantic request."""


class InvalidActionTransition(ValueError):
    """The Action is not in a state that permits the requested transition."""


_TERMINAL = {"SUCCEEDED", "FAILED"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Action data must be finite JSON") from exc


class _ActionPhaseOps:
    """Phase rows of one Action attempt; relies on ActionStore._connect/_append_event."""

    @staticmethod
    def _phase_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["ordinal"] = int(result["ordinal"])
        result["cancel_acknowledged"] = (
            None if result["cancel_acknowledged"] is None
            else bool(result["cancel_acknowledged"])
        )
        if result["result_json"] is not None:
            result["result"] = json.loads(result.pop("result_json"))
        else:
            result.pop("result_json")
        return result

    def begin_phase(self, action_id: str, attempt_id: str, *, phase_id: str,
                    ordinal: int, command_digest: str) -> dict[str, Any]:
        """Persist one ordered phase intent before its ROS goal is submitted."""
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        if type(ordinal) is not int or ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        command_digest = _nonempty("command_digest", command_digest, maximum=64)
        if (len(command_digest) != 64
                or any(char not in "0123456789abcdef" for char in command_digest)):
            raise ValueError("command_digest must be a lowercase SHA-256 hex digest")
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id,
                {"SUBMITTING", "ACCEPTED", "RUNNING"},
            )
            previous = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? "
                "ORDER BY ordinal DESC LIMIT 1",
                (action_id, attempt_id),
            ).fetchone()
            expected_ordinal = 0 if previous is None else int(previous["ordinal"]) + 1
            if ordinal != expected_ordinal:
                raise InvalidActionTransition("phase ordinal must be contiguous and ordered")
            if action["state"] == "SUBMITTING" and (ordinal != 0 or previous is not None):
                raise InvalidActionTransition(
                    "only the first phase intent may be written while the Action is SUBMITTING",
                )
            if previous is not None and previous["state"] != "SUCCEEDED":
                raise InvalidActionTransition("next phase requires successful terminal result for previous phase")
            duplicate_id = connection.execute(
                """SELECT 1 FROM omx_action_phases WHERE action_id=? AND attempt_id=?
                   AND phase_id=?""",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            if duplicate_id is not None:
                raise InvalidActionTransition("phase_id is already used by this Action attempt")
            connection.execute(
                """INSERT INTO omx_action_phases
                   (action_id, attempt_id, phase_id, ordinal, command_digest, state,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'SUBMITTING', ?, ?)""",
                (action_id, attempt_id, phase_id, ordinal, command_digest, now, now),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=action["state"], event_type="ACTION_PHASE_SUBMISSION_STARTED",
                actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "ordinal": ordinal,
                        "command_digest": command_digest}, created_at=now,
            )
            row = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return self._phase_dict(row)

    def record_phase_submission(self, action_id: str, attempt_id: str, *, phase_id: str,
                                accepted: bool | None,
                                driver_goal_id: str | None) -> dict[str, Any]:
        if accepted is not True and accepted is not False and accepted is not None:
            raise ValueError("accepted must be true, false, or unknown")
        if accepted is True and driver_goal_id is None:
            raise ValueError("positive phase acceptance requires driver_goal_id")
        if accepted is False and driver_goal_id is not None:
            raise ValueError("rejected phase cannot have a driver_goal_id")
        if accepted is None and driver_goal_id is not None:
            raise ValueError("unknown phase acceptance cannot have a driver_goal_id")
        if driver_goal_id is not None:
            driver_goal_id = _nonempty("driver_goal_id", driver_goal_id)
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        state = "ACCEPTED" if accepted is True else "FAILED" if accepted is False else "UNKNOWN"
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id, {"ACCEPTED", "RUNNING"},
            )
            phase = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            if phase is None or phase["state"] != "SUBMITTING":
                raise InvalidActionTransition("phase is not awaiting driver acceptance")
            connection.execute(
                """UPDATE omx_action_phases SET state=?, driver_goal_id=?, reason=?, updated_at=?
                   WHERE action_id=? AND attempt_id=? AND phase_id=?""",
                (state, driver_goal_id,
                 "DRIVER_ACCEPTANCE_UNKNOWN" if accepted is None else None, now,
                 action_id, attempt_id, phase_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state=state,
                event_type="ACTION_PHASE_ACCEPTANCE_RECORDED", actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "accepted": accepted,
                        "driver_goal_id": driver_goal_id}, created_at=now,
            )
            updated = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return self._phase_dict(updated)

    def record_first_phase_submission(
        self, action_id: str, attempt_id: str, *, phase_id: str,
        accepted: bool | None, driver_goal_id: str | None,
    ) -> dict[str, Any]:
        """Atomically persist the parent and first ROS phase response.

        The phase intent must already be durable while the parent Action is
        SUBMITTING. A lost response or process restart is reconciled as
        UNKNOWN; this method never resubmits a goal.
        """
        if accepted is not True and accepted is not False and accepted is not None:
            raise ValueError("accepted must be true, false, or unknown")
        if accepted is True and driver_goal_id is None:
            raise ValueError("positive first-phase acceptance requires driver_goal_id")
        if accepted is not True and driver_goal_id is not None:
            raise ValueError("unaccepted first phase cannot have a driver_goal_id")
        if driver_goal_id is not None:
            driver_goal_id = _nonempty("driver_goal_id", driver_goal_id, maximum=192)
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        parent_state = "ACCEPTED" if accepted is True else "FAILED" if accepted is False else "UNKNOWN"
        phase_state = parent_state
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(connection, action_id, attempt_id, {"SUBMITTING"})
            phase = self._require_phase(
                connection, action_id, attempt_id, phase_id, {"SUBMITTING"},
            )
            if phase["ordinal"] != 0:
                raise InvalidActionTransition("first ROS phase ordinal must be zero")
            phase_count = connection.execute(
                "SELECT COUNT(*) FROM omx_action_phases WHERE action_id=? AND attempt_id=?",
                (action_id, attempt_id),
            ).fetchone()[0]
            if phase_count != 1:
                raise InvalidActionTransition("first ROS response requires exactly one phase intent")

            reason = "DRIVER_ACCEPTANCE_UNKNOWN" if accepted is None else None
            phase_reason = "DRIVER_ACCEPTANCE_UNKNOWN" if accepted is None else None
            connection.execute(
                """UPDATE omx_actions SET state=?, driver_goal_id=?, reason=?, updated_at=?
                   WHERE action_id=? AND attempt_id=? AND state='SUBMITTING'""",
                (parent_state, driver_goal_id, reason, now, action_id, attempt_id),
            )
            connection.execute(
                """UPDATE omx_action_phases SET state=?, driver_goal_id=?, reason=?, updated_at=?
                   WHERE action_id=? AND attempt_id=? AND phase_id=? AND state='SUBMITTING'""",
                (phase_state, driver_goal_id, phase_reason, now,
                 action_id, attempt_id, phase_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=parent_state, event_type="DRIVER_ACCEPTANCE_RECORDED",
                actor_id=action["principal_id"],
                detail={"accepted": accepted, "driver_goal_id": driver_goal_id,
                        "first_phase_id": phase_id}, created_at=now,
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=phase_state, event_type="ACTION_PHASE_ACCEPTANCE_RECORDED",
                actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "ordinal": 0, "accepted": accepted,
                        "driver_goal_id": driver_goal_id}, created_at=now,
            )
            updated_action = connection.execute(
                "SELECT * FROM omx_actions WHERE action_id=?", (action_id,),
            ).fetchone()
            updated_phase = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return {"action": self._dict(updated_action), "phase": self._phase_dict(updated_phase)}

    def record_late_phase_acceptance(
        self, action_id: str, attempt_id: str, *, phase_id: str,
        driver_goal_id: str,
    ) -> dict[str, Any]:
        """Attach a late ROS UUID to an already held UNKNOWN phase without reopening it."""
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        driver_goal_id = _nonempty("driver_goal_id", driver_goal_id, maximum=192)
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(connection, action_id, attempt_id, {"UNKNOWN", "HOLD"})
            phase = self._require_phase(connection, action_id, attempt_id, phase_id, {"UNKNOWN"})
            if phase["driver_goal_id"] not in {None, driver_goal_id}:
                raise InvalidActionTransition("late ROS acceptance UUID conflicts with the phase journal")
            connection.execute(
                """UPDATE omx_action_phases SET driver_goal_id=?, updated_at=?
                   WHERE action_id=? AND attempt_id=? AND phase_id=? AND state='UNKNOWN'""",
                (driver_goal_id, now, action_id, attempt_id, phase_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=action["state"], event_type="ACTION_PHASE_LATE_GOAL_ACCEPTANCE_RECORDED",
                actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "driver_goal_id": driver_goal_id,
                        "action_state_remains_held": True},
                created_at=now,
            )
            updated = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return self._phase_dict(updated)

    def record_late_phase_cancel_request(
        self, action_id: str, attempt_id: str, *, phase_id: str,
        driver_goal_id: str,
    ) -> dict[str, Any]:
        """Journal exact-goal cancellation while preserving an UNKNOWN/HOLD phase."""
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        driver_goal_id = _nonempty("driver_goal_id", driver_goal_id, maximum=192)
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(connection, action_id, attempt_id, {"UNKNOWN", "HOLD"})
            phase = self._require_phase(connection, action_id, attempt_id, phase_id, {"UNKNOWN"})
            if phase["driver_goal_id"] != driver_goal_id:
                raise InvalidActionTransition("late cancel UUID does not match the held phase")
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=action["state"], event_type="ACTION_PHASE_LATE_CANCEL_REQUESTED",
                actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "driver_goal_id": driver_goal_id,
                        "phase_state_remains_unknown": True},
                created_at=now,
            )
            updated = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return self._phase_dict(updated)

    def mark_phase_running(self, action_id: str, attempt_id: str, *, phase_id: str,
                           driver_goal_id: str) -> dict[str, Any]:
        return self._transition_phase(
            action_id, attempt_id, phase_id=phase_id,
            allowed={"ACCEPTED"}, target="RUNNING", event_type="ACTION_PHASE_RUNNING",
            driver_goal_id=driver_goal_id,
        )

    def request_phase_cancel(self, action_id: str, attempt_id: str, *,
                             phase_id: str) -> dict[str, Any]:
        return self._transition_phase(
            action_id, attempt_id, phase_id=phase_id,
            allowed={"ACCEPTED", "RUNNING"}, target="CANCEL_REQUESTED",
            event_type="ACTION_PHASE_CANCEL_REQUESTED",
        )

    def record_phase_cancel_ack(self, action_id: str, attempt_id: str, *,
                                phase_id: str, acknowledged: bool) -> dict[str, Any]:
        if type(acknowledged) is not bool:
            raise ValueError("acknowledged must be boolean")
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id,
                {"ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "HOLD"},
            )
            phase = self._require_phase(
                connection, action_id, attempt_id, phase_id, {"CANCEL_REQUESTED", "UNKNOWN"},
            )
            connection.execute(
                """UPDATE omx_action_phases SET cancel_acknowledged=?, updated_at=?
                   WHERE action_id=? AND attempt_id=? AND phase_id=?""",
                (int(acknowledged), now, action_id, attempt_id, phase_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=phase["state"], event_type="ACTION_PHASE_CANCEL_ACK_RECORDED",
                actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "driver_goal_id": phase["driver_goal_id"],
                        "acknowledged": acknowledged}, created_at=now,
            )
            updated = self._require_phase(
                connection, action_id, attempt_id, phase_id,
                {"CANCEL_REQUESTED", "UNKNOWN"},
            )
            connection.commit()
        return self._phase_dict(updated)

    def record_phase_terminal(self, action_id: str, attempt_id: str, *, phase_id: str,
                              driver_goal_id: str, outcome: str, result_source: str,
                              result_observed_at: str,
                              result: Mapping[str, Any]) -> dict[str, Any]:
        if outcome not in {"SUCCEEDED", "FAILED", "CANCELED"}:
            raise ValueError("phase outcome must be SUCCEEDED, FAILED, or CANCELED")
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        driver_goal_id = _nonempty("driver_goal_id", driver_goal_id)
        result_source = _nonempty("result_source", result_source, maximum=96)
        result_observed_at = _nonempty("result_observed_at", result_observed_at)
        if not isinstance(result, Mapping):
            raise ValueError("result must be a JSON object")
        result_json = _json(dict(result))
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id,
                {"ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "HOLD"},
            )
            phase = self._require_phase(
                connection, action_id, attempt_id, phase_id,
                {"ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN"},
            )
            if phase["driver_goal_id"] != driver_goal_id:
                raise InvalidActionTransition("ROS goal identity does not match Action phase")
            connection.execute(
                """UPDATE omx_action_phases SET state=?, result_source=?, result_observed_at=?,
                   result_json=?, reason=NULL, updated_at=?
                   WHERE action_id=? AND attempt_id=? AND phase_id=?""",
                (outcome, result_source, result_observed_at, result_json, now,
                 action_id, attempt_id, phase_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state=outcome,
                event_type="ACTION_PHASE_TERMINAL_RESULT", actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "ordinal": phase["ordinal"],
                        "driver_goal_id": driver_goal_id, "result_source": result_source,
                        "result_observed_at": result_observed_at, "result": dict(result)},
                created_at=now,
            )
            if outcome == "CANCELED" and action["state"] != "HOLD":
                reason = "ROS_PHASE_CANCELED_ACTION_INCOMPLETE"
                connection.execute(
                    "UPDATE omx_actions SET state='HOLD', reason=?, updated_at=? WHERE action_id=?",
                    (reason, now, action_id),
                )
                self._append_event(
                    connection, action_id=action_id, attempt_id=attempt_id, state="HOLD",
                    event_type="ACTION_HELD", actor_id="system", detail={"reason": reason},
                    created_at=now,
                )
            updated = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return self._phase_dict(updated)
