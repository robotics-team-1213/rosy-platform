"""Claim, submission fence, and state transitions for ER 2 reasoning turns."""

from __future__ import annotations

import re
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _reason(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value) is None:
        raise ValueError("reason_code must be a stable uppercase code")
    return value


class MissionModelTurnClaimMixin:
    """Worker claim, fenced submission, and turn state transitions."""

    def claim(self, turn_id: str, *, worker_id: str) -> dict[str, Any] | None:
        if not worker_id or worker_id != worker_id.strip() or len(worker_id) > 96:
            raise ValueError("worker_id must be a trimmed identifier")
        now = _now()
        lease = _stamp(now + timedelta(seconds=self.claim_lease_seconds))
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fleet_mission_model_turns WHERE turn_id=?", (turn_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            reclaim = (row["state"] == "CLAIMED" and row["lease_until"]
                       and row["lease_until"] <= _stamp(now))
            if row["state"] != "PENDING" and not reclaim:
                connection.rollback()
                return None
            connection.execute(
                """UPDATE fleet_mission_model_turns SET state='CLAIMED', claimed_by=?,
                   lease_until=?, updated_at=? WHERE turn_id=?""",
                (worker_id, lease, _stamp(now), turn_id),
            )
            updated = connection.execute(
                "SELECT * FROM fleet_mission_model_turns WHERE turn_id=?", (turn_id,),
            ).fetchone()
            connection.commit()
        return self._row(updated)

    def claim_next(self, *, worker_id: str) -> dict[str, Any] | None:
        """Atomically claim the oldest pending turn for one worker."""
        if not worker_id or worker_id != worker_id.strip() or len(worker_id) > 96:
            raise ValueError("worker_id must be a trimmed identifier")
        now = _now()
        lease = _stamp(now + timedelta(seconds=self.claim_lease_seconds))
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT turn_id FROM fleet_mission_model_turns
                   WHERE state='PENDING' ORDER BY created_at, turn_id LIMIT 1""",
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            turn_id = row["turn_id"]
            changed = connection.execute(
                """UPDATE fleet_mission_model_turns SET state='CLAIMED',
                   claimed_by=?, lease_until=?, updated_at=?
                   WHERE turn_id=? AND state='PENDING'""",
                (worker_id, lease, _stamp(now), turn_id),
            ).rowcount
            if changed != 1:
                connection.rollback()
                return None
            updated = connection.execute(
                "SELECT * FROM fleet_mission_model_turns WHERE turn_id=?", (turn_id,),
            ).fetchone()
            connection.commit()
        return self._row(updated)

    def mark_submitting(self, turn_id: str, *, worker_id: str) -> dict[str, Any] | None:
        return self._transition(turn_id, expected="CLAIMED", state="SUBMITTING",
                                worker_id=worker_id, increment_attempt=True)

    def begin_submission_fenced(self, turn_id: str, *, worker_id: str
                                ) -> dict[str, Any] | None:
        """Atomically recheck dispatch latch, generation, Mission attempt and watermark."""
        now = _stamp(_now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fleet_mission_model_turns WHERE turn_id=?", (turn_id,),
            ).fetchone()
            if (row is None or row["state"] != "CLAIMED"
                    or row["claimed_by"] != worker_id or row["attempt_count"] != 0):
                connection.rollback()
                return None
            control = connection.execute(
                "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            mission = connection.execute(
                "SELECT principal_id, workcell_id, action_kind, action_id, attempt_id, dispatch_generation, status "
                "FROM fleet_missions WHERE mission_id=?", (row["mission_id"],),
            ).fetchone()
            latest_event_id = connection.execute(
                "SELECT COALESCE(MAX(event_id), 0) FROM fleet_mission_events "
                "WHERE mission_id=?", (row["mission_id"],),
            ).fetchone()[0]
            reason = None
            if control is None or not control["dispatch_enabled"]:
                reason = "STOP_FENCE_CLOSED"
            elif control["generation"] != row["dispatch_generation"]:
                reason = "STOP_GENERATION_CHANGED"
            elif (mission is None
                  or mission["principal_id"] != row["principal_id"]
                  or mission["workcell_id"] != row["workcell_id"]
                  or mission["action_kind"] != "PICK_PLACE"
                  or mission["action_id"] != row["action_id"]
                  or mission["attempt_id"] != row["attempt_id"]
                  or mission["dispatch_generation"] != row["dispatch_generation"]
                  or mission["status"] not in {"ACTION_SUCCEEDED", "GOAL_CONFIRMED", "HOLD"}):
                reason = "TURN_SCOPE_STALE"
            elif latest_event_id != row["event_watermark"]:
                reason = "EVENT_WATERMARK_STALE"
            if reason is not None:
                connection.execute(
                    """UPDATE fleet_mission_model_turns SET state='SUPPRESSED',
                       claimed_by=NULL, lease_until=NULL, reason_code=?, updated_at=?
                       WHERE turn_id=? AND state='CLAIMED'""",
                    (reason, now, turn_id),
                )
            else:
                connection.execute(
                    """UPDATE fleet_mission_model_turns SET state='SUBMITTING',
                       attempt_count=1, updated_at=? WHERE turn_id=? AND state='CLAIMED'""",
                    (now, turn_id),
                )
            updated = connection.execute(
                "SELECT * FROM fleet_mission_model_turns WHERE turn_id=?", (turn_id,),
            ).fetchone()
            connection.commit()
        return self._row(updated)

    def mark_unknown(self, turn_id: str, *, reason_code: str) -> dict[str, Any] | None:
        return self._transition(turn_id, expected="SUBMITTING", state="UNKNOWN",
                                reason_code=reason_code, clear_claim=True)

    def mark_responded(self, turn_id: str) -> dict[str, Any] | None:
        return self._transition(turn_id, expected="SUBMITTING", state="RESPONDED",
                                clear_claim=True)

    def release_preflight(self, turn_id: str, *, worker_id: str,
                          reason_code: str) -> dict[str, Any] | None:
        return self._transition(turn_id, expected="CLAIMED", state="PENDING",
                                worker_id=worker_id, reason_code=reason_code,
                                clear_claim=True)

    def suppress(self, turn_id: str, *, reason_code: str) -> dict[str, Any] | None:
        return self._transition(turn_id, expected="PENDING", state="SUPPRESSED",
                                reason_code=reason_code)

    def suppress_claim(self, turn_id: str, *, worker_id: str,
                       reason_code: str) -> dict[str, Any] | None:
        reason = _reason(reason_code)
        now = _stamp(_now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fleet_mission_model_turns WHERE turn_id=?", (turn_id,),
            ).fetchone()
            if (row is None or row["state"] != "CLAIMED"
                    or row["claimed_by"] != worker_id):
                connection.rollback()
                return None
            connection.execute(
                """UPDATE fleet_mission_model_turns SET state='SUPPRESSED',
                   claimed_by=NULL, lease_until=NULL, reason_code=?, updated_at=?
                   WHERE turn_id=? AND state='CLAIMED'""",
                (reason, now, turn_id),
            )
            updated = connection.execute(
                "SELECT * FROM fleet_mission_model_turns WHERE turn_id=?", (turn_id,),
            ).fetchone()
            connection.commit()
        return self._row(updated)

    def expire_claims(self, *, now: datetime | None = None) -> int:
        """Requeue expired pre-invocation claims; make expired POSTs UNKNOWN."""
        current = _stamp(now or _now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE fleet_mission_model_turns SET state='PENDING', claimed_by=NULL,
                   lease_until=NULL, reason_code='CLAIM_EXPIRED', updated_at=?
                   WHERE state='CLAIMED' AND lease_until<=?""", (current, current),
            )
            claimed = connection.execute("SELECT changes()").fetchone()[0]
            connection.execute(
                """UPDATE fleet_mission_model_turns SET state='UNKNOWN', claimed_by=NULL,
                   lease_until=NULL, reason_code='SUBMISSION_OUTCOME_UNKNOWN', updated_at=?
                   WHERE state='SUBMITTING' AND lease_until<=?""", (current, current),
            )
            connection.commit()
        return int(claimed)

    def _transition(self, turn_id: str, *, expected: str, state: str,
                    worker_id: str | None = None, reason_code: str | None = None,
                    increment_attempt: bool = False,
                    clear_claim: bool = False) -> dict[str, Any] | None:
        now = _stamp(_now())
        reason = _reason(reason_code) if reason_code is not None else None
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fleet_mission_model_turns WHERE turn_id=?", (turn_id,),
            ).fetchone()
            if row is None or row["state"] != expected:
                connection.rollback()
                return None
            if worker_id is not None and row["claimed_by"] != worker_id:
                connection.rollback()
                return None
            if increment_attempt and row["attempt_count"] != 0:
                connection.rollback()
                return None
            claim_fields = ", claimed_by=NULL, lease_until=NULL" if clear_claim else ""
            connection.execute(
                f"""UPDATE fleet_mission_model_turns SET state=?, updated_at=?,
                    reason_code=?{claim_fields},
                    attempt_count=attempt_count+? WHERE turn_id=? AND state=?""",
                (state, now, reason, int(increment_attempt), turn_id, expected),
            )
            updated = connection.execute(
                "SELECT * FROM fleet_mission_model_turns WHERE turn_id=?", (turn_id,),
            ).fetchone()
            connection.commit()
        return self._row(updated)


__all__ = ["MissionModelTurnClaimMixin", "_now", "_reason", "_stamp"]
