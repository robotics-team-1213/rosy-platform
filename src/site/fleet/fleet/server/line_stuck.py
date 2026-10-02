"""D-407 lane stuck decisions, Fleet side: list the robots' open stucks, relay one answer.

CORE owns the stuck (``state.line_follow.stuck``) and judges every answer; Fleet only shows
it and forwards the operator's choice to that robot's ``POST /api/v1/line-follow/stuck/
decision`` with the robot credential it already uses. Nothing here refuses on CORE's behalf:
a late or wrong ``stuck_id`` and a refused RESUME come back as CORE's own 409 and are passed
to the operator verbatim. The clearances and preview seq live only in the
``nav.line_stuck_opened`` event, so they appear when the FleetAgent link delivered it.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

from .sqlite_policy import configure_connection

DECISIONS = ("WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT")
_STATUS_KEYS = ("stuck_id", "cause", "phase", "held_s", "attempts", "max_attempts",
                "local_enabled", "ask_remaining_s", "last_answer", "decisions")
_OPENED_KEYS = ("front_clearance_m", "rear_clearance_m", "rear_state", "turn_clearance_m",
                "rear_blind_m", "preview_seq")

_LOG = logging.getLogger(__name__)


def _event_dict(event) -> dict:
    return event.model_dump(mode="json") if hasattr(event, "model_dump") else dict(event)


class LineStuckBoard:
    """Open stucks per robot from the gathered state, plus who answered what."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, history: int = 50,
                 log: Optional["LineStuckAnswerLog"] = None) -> None:
        self._clock = clock
        self._open: dict[str, dict] = {}
        self._answers: deque = deque(maxlen=history)
        self._log = log
        self._observed_at: Optional[float] = None

    def observed_age_s(self) -> Optional[float]:
        """Seconds since the last gather (None = never gathered since start)."""
        if self._observed_at is None:
            return None
        return round(max(0.0, self._clock() - self._observed_at), 2)

    def observe(self, robots: Iterable[dict],
                events_of: Callable[[str, int], Iterable] = lambda _rid, _seq: ()) -> None:
        """One gathered snapshot. A robot that did not answer keeps its last stuck, marked
        unreachable: the operator must still see it, and CORE refuses an answer it cannot take."""
        now = self._observed_at = self._clock()
        seen = set()
        for row in robots:
            robot_id = row["robot_id"]
            seen.add(robot_id)
            state = row.get("state")
            if not row.get("online") or not isinstance(state, dict):
                if robot_id in self._open:
                    self._open[robot_id]["robot_online"] = False
                continue
            stuck = (state.get("line_follow") or {}).get("stuck")
            if not isinstance(stuck, dict) or not stuck.get("stuck_id"):
                self._open.pop(robot_id, None)
                continue
            previous = self._open.get(robot_id)
            entry = {"robot_id": robot_id, **{k: stuck.get(k) for k in _STATUS_KEYS},
                     "robot_online": True, "observed_at": now}
            entry.update(self._opened(robot_id, entry["stuck_id"], previous, events_of))
            self._open[robot_id] = entry
        for robot_id in set(self._open) - seen:
            del self._open[robot_id]   # left the roster

    @staticmethod
    def _opened(robot_id: str, stuck_id: str, previous: Optional[dict], events_of) -> dict:
        if previous is not None and previous["stuck_id"] == stuck_id and previous["opened_event"]:
            return {k: previous[k] for k in (*_OPENED_KEYS, "opened_event")}
        found = {k: None for k in _OPENED_KEYS}
        found["opened_event"] = False
        try:
            events = list(events_of(robot_id, 0))
        except Exception:  # noqa: BLE001 - enrichment only; the stuck itself is from state
            events = []
        for event in reversed(events):
            body = _event_dict(event)
            data = body.get("data") or {}
            if body.get("type") == "nav.line_stuck_opened" and data.get("stuck_id") == stuck_id:
                found.update({k: data.get(k) for k in _OPENED_KEYS})
                found["opened_event"] = True
                break
        return found

    def view(self, robot_id: str) -> Optional[dict]:
        entry = self._open.get(robot_id)
        if entry is None:
            return None
        shown = dict(entry)
        shown["observed_age_s"] = round(max(0.0, self._clock() - shown.pop("observed_at")), 2)
        last = next((a for a in reversed(self._answers)
                     if a["robot_id"] == robot_id and a["stuck_id"] == entry["stuck_id"]), None)
        shown["fleet_answer"] = last
        return shown

    def pending(self) -> list[dict]:
        return [self.view(robot_id) for robot_id in sorted(self._open)]

    def answers(self) -> list[dict]:
        return list(self._answers)

    def record(self, *, robot_id: str, stuck_id: str, decision: str, principal_id: str,
               accepted: Optional[bool], outcome: Optional[str] = None,
               code: Optional[str] = None, message: Optional[str] = None,
               audit_id: Optional[str] = None) -> dict:
        """Audit one forwarded answer (who, what, CORE's verdict; accepted None = unknown).

        The row also goes to the durable log next to the API audit row (``audit_id``). The
        robot has already been asked, so a log failure is logged, never turned into an error."""
        row = {"robot_id": robot_id, "stuck_id": stuck_id, "decision": decision,
               "principal_id": principal_id, "accepted": accepted, "outcome": outcome,
               "code": code, "message": message, "audit_id": audit_id,
               "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
        self._answers.append(row)
        _LOG.info("line stuck answer robot=%s stuck=%s decision=%s by=%s accepted=%s code=%s",
                  robot_id, stuck_id, decision, principal_id, accepted, code)
        if self._log is not None:
            try:
                self._log.append(row)
            except (OSError, sqlite3.Error):
                _LOG.exception("line stuck answer was not durably recorded robot=%s stuck=%s",
                               robot_id, stuck_id)
        return row


class LineStuckAnswerLog:
    """Durable answer record in the Fleet journal database (beside ``fleet_api_audit``)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS fleet_line_stuck_answers (
                       answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                       at TEXT NOT NULL, audit_id TEXT, robot_id TEXT NOT NULL,
                       stuck_id TEXT NOT NULL, decision TEXT NOT NULL,
                       principal_id TEXT NOT NULL, accepted INTEGER, outcome TEXT,
                       code TEXT, message TEXT)""")

    def append(self, row: dict) -> None:
        accepted = None if row["accepted"] is None else int(bool(row["accepted"]))
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """INSERT INTO fleet_line_stuck_answers (at, audit_id, robot_id, stuck_id,
                   decision, principal_id, accepted, outcome, code, message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (row["at"], row["audit_id"], row["robot_id"], row["stuck_id"], row["decision"],
                 row["principal_id"], accepted, row["outcome"], row["code"],
                 (row["message"] or "")[:512] or None))

    def rows(self, limit: int = 100) -> list[dict]:
        with closing(self._connect()) as connection:
            found = connection.execute(
                "SELECT * FROM fleet_line_stuck_answers ORDER BY answer_id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(row) for row in found]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)
