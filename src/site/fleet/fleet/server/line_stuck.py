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
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

DECISIONS = ("WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT")
_STATUS_KEYS = ("stuck_id", "cause", "phase", "held_s", "attempts", "max_attempts",
                "local_enabled", "ask_remaining_s", "last_answer", "decisions")
_OPENED_KEYS = ("front_clearance_m", "rear_clearance_m", "turn_clearance_m",
                "rear_blind_m", "preview_seq")

_LOG = logging.getLogger(__name__)


def _event_dict(event) -> dict:
    return event.model_dump(mode="json") if hasattr(event, "model_dump") else dict(event)


class LineStuckBoard:
    """Open stucks per robot from the gathered state, plus who answered what."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, history: int = 50) -> None:
        self._clock = clock
        self._open: dict[str, dict] = {}
        self._answers: deque = deque(maxlen=history)

    def observe(self, robots: Iterable[dict],
                events_of: Callable[[str, int], Iterable] = lambda _rid, _seq: ()) -> None:
        """One gathered snapshot. A robot that did not answer keeps its last stuck, marked
        unreachable: the operator must still see it, and CORE refuses an answer it cannot take."""
        now = self._clock()
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
               accepted: bool, outcome: Optional[str] = None, code: Optional[str] = None,
               message: Optional[str] = None) -> dict:
        """Audit one forwarded answer (who, what, CORE's verdict)."""
        row = {"robot_id": robot_id, "stuck_id": stuck_id, "decision": decision,
               "principal_id": principal_id, "accepted": accepted, "outcome": outcome,
               "code": code, "message": message,
               "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
        self._answers.append(row)
        _LOG.info("line stuck answer robot=%s stuck=%s decision=%s by=%s accepted=%s code=%s",
                  robot_id, stuck_id, decision, principal_id, accepted, code)
        return row
