"""Readback and recovery transaction boundary of the same ActionStore journal."""

from __future__ import annotations

import json
from contextlib import closing
from typing import Any, Callable


def _nonempty(name: str, value: object, *, maximum: int = 192) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > maximum or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{name} must be a non-empty trimmed string of at most {maximum} characters")
    return value


class ActionStoreReadback:
    """Public journal read operations, inherited by its sole ActionStore owner."""

    def unresolved_actions(self, *, workcell_id: str | None = None) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            if workcell_id is None:
                rows = connection.execute(
                    "SELECT * FROM omx_actions WHERE state IN "
                    "('SUBMITTING', 'ACCEPTED', 'RUNNING', 'CANCEL_REQUESTED', 'UNKNOWN', 'HOLD') "
                    "ORDER BY created_at, action_id"
                ).fetchall()
            else:
                workcell_id = _nonempty("workcell_id", workcell_id, maximum=96)
                rows = connection.execute(
                    "SELECT * FROM omx_actions WHERE workcell_id=? AND state IN "
                    "('SUBMITTING', 'ACCEPTED', 'RUNNING', 'CANCEL_REQUESTED', 'UNKNOWN', 'HOLD') "
                    "ORDER BY created_at, action_id",
                    (workcell_id,),
                ).fetchall()
        return [self._dict(row) for row in rows]

    def get_action(self, action_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM omx_actions WHERE action_id=?",
                                     (action_id,)).fetchone()
            latest_event = connection.execute(
                "SELECT MAX(event_id) FROM omx_action_events WHERE action_id=?",
                (action_id,),
            ).fetchone()
        result = self._dict(row)
        if result is not None:
            result["journal_event_id"] = latest_event[0]
        return result

    def latest_event_id(self, action_id: str) -> int | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT MAX(event_id) FROM omx_action_events WHERE action_id=?",
                (action_id,),
            ).fetchone()
        return int(row[0]) if row is not None and row[0] is not None else None

    def get_by_request(self, *, workcell_id: str, principal_id: str,
                       request_key: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT * FROM omx_actions WHERE workcell_id=? AND principal_id=?
                   AND request_key=?""",
                (workcell_id, principal_id, request_key),
            ).fetchone()
        return self._dict(row)

    def history(self, action_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM omx_action_events WHERE action_id=? ORDER BY event_id",
                (action_id,),
            ).fetchall()
        events = [dict(row) for row in rows]
        for event in events:
            event["detail"] = json.loads(event.pop("detail_json"))
        return events

    def run_if_no_unresolved(self, *, workcell_id: str, instance_id: str, operation: Callable):
        """Serialize recovery with journal claims; PREPARED also blocks recovery.

        Caller already holds the local-stop fence and owner readback lock.
        No callback may acquire either lock or start another journal write.
        """
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT 1 FROM omx_actions WHERE workcell_id=? AND instance_id=? "
                "AND state NOT IN ('SUCCEEDED', 'FAILED') LIMIT 1",
                (workcell_id, instance_id),
            ).fetchone()
            if row is not None:
                raise PermissionError("unresolved local Actions block owner recovery")
            result = operation()
            connection.commit()
            return result
