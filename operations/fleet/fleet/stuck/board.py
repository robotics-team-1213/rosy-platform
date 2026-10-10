"""D-407 lane stuck decisions, Fleet side: list the robots' open stucks, relay one answer.

CORE owns the stuck (``state.line_follow.stuck``) and judges every answer; Fleet only shows
it and forwards the operator's choice to that robot's ``POST /api/v1/line-follow/stuck/
decision`` with the robot credential it already uses. Nothing here refuses on CORE's behalf:
a late or wrong ``stuck_id`` and a refused RESUME come back as CORE's own 409 and are passed
to the operator verbatim. The clearances and preview seq live only in the
``nav.line_stuck_opened`` event, so they appear when the FleetAgent link delivered it.
"""

from __future__ import annotations

import base64
import logging
import sqlite3
import time
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Iterable, Optional

from .lane_lost import peer_ahead
from .resolver import ResolverConfig

if TYPE_CHECKING:
    from .reports import LineStuckAnswerLog

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
                 log: Optional["LineStuckAnswerLog"] = None,
                 wall: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._wall = wall
        self._open: dict[str, dict] = {}
        self._answers: deque = deque(maxlen=history)
        self._log = log
        self._observed_at: Optional[float] = None
        self._resolver: dict[tuple[str, str], dict] = {}
        # D-577 8: one front-camera frame per open stuck, memory only (never disk, bus or event).
        self._previews: dict[tuple[str, str], dict] = {}
        # Episode context, injected by the app once the services exist (None = not known).
        self.trip_busy: Optional[Callable[[str], bool]] = None
        self.ai_view: Optional[Callable[[str, str], dict]] = None   # D-577 8: AI chip, facts, proposal
        self.map_pose: Optional[Callable[[str], object]] = None
        self.peer_config = ResolverConfig()   # the app sets the resolver's own when it runs
        self._peaks: dict[str, dict] = {}     # robot_id -> held_s / attempts maxima
        # Episode writes queued by observe(), in order; flush() runs them (off the event loop).
        self._pending: list[Callable[[], None]] = []
        if log is not None:
            self._durable(lambda: log.close_orphans(self._now_iso()))

    def note_resolver(self, robot_id: str, stuck_id: str, *, tier: str, rule: Optional[str],
                      decision: Optional[str], escalated: Optional[str]) -> None:
        """D-438: what the resolver did for this stuck (shown on the console row)."""
        self._resolver[(robot_id, stuck_id)] = {
            "tier": tier, "rule": rule, "decision": decision, "escalated": escalated,
            "at": self._clock()}

    def resolver_note(self, robot_id: str, stuck_id: str) -> Optional[dict]:
        return self._resolver.get((robot_id, stuck_id))

    def _drop_notes(self, robot_id: str, keep: Optional[str] = None) -> None:
        for notes in (self._resolver, self._previews):
            for key in [k for k in notes if k[0] == robot_id and k[1] != keep]:
                del notes[key]

    def is_open(self, robot_id: str, stuck_id: str) -> bool:
        entry = self._open.get(robot_id)
        return entry is not None and entry["stuck_id"] == stuck_id

    def keep_preview(self, robot_id: str, stuck_id: str, jpeg: bytes, status: dict) -> None:
        """D-577 8: hold this stuck's one picture until the stuck closes (a closed one is not kept)."""
        if self.is_open(robot_id, stuck_id) and (robot_id, stuck_id) not in self._previews:
            age_ms = status.get("age_ms")
            self._previews[(robot_id, stuck_id)] = {
                "jpeg": bytes(jpeg), "sequence": status.get("sequence"), "source": status.get("source"),
                "age_at_fetch_s": age_ms / 1000.0 if isinstance(age_ms, (int, float)) else 0.0,
                "fetched_at": self._clock()}

    def preview(self, robot_id: str, stuck_id: str) -> Optional[dict]:
        kept = self._previews.get((robot_id, stuck_id))
        if kept is None:
            return None
        return {"robot_id": robot_id, "stuck_id": stuck_id, "sequence": kept["sequence"],
                "source": kept["source"], "media_type": "image/jpeg",
                "age_s": round(kept["age_at_fetch_s"] + max(0.0, self._clock() - kept["fetched_at"]), 2),
                "jpeg_base64": base64.b64encode(kept["jpeg"]).decode("ascii")}

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
        robots = list(robots)
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
                if self._open.pop(robot_id, None) is not None:
                    self._close_episode(robot_id, "cleared")
                self._drop_notes(robot_id)
                continue
            previous = self._open.get(robot_id)
            entry = {"robot_id": robot_id, **{k: stuck.get(k) for k in _STATUS_KEYS},
                     "robot_online": True, "observed_at": now}
            if previous is not None and previous["stuck_id"] != entry["stuck_id"]:
                self._drop_notes(robot_id, keep=entry["stuck_id"])   # replaced stuck
                self._close_episode(robot_id, "replaced")
            if previous is None or previous["stuck_id"] != entry["stuck_id"]:
                self._open_episode(row, stuck, robots)
            self._peak(robot_id, stuck)
            entry.update(self._opened(robot_id, entry["stuck_id"], previous, events_of))
            self._open[robot_id] = entry
        for robot_id in set(self._open) - seen:
            del self._open[robot_id]   # left the roster
            self._drop_notes(robot_id)
            self._close_episode(robot_id, "left_roster")

    # ---- episode log: one write per open / close transition, never per poll -------------

    def episodes(self, limit: int = 100) -> list[dict]:
        return self._log.episodes(limit) if self._log is not None else []

    def reports(self, limit: int = 100) -> list[dict]:
        return self._log.reports(limit) if self._log is not None else []

    def traffic_reports(self, limit: int = 100) -> list[dict]:
        return self._log.traffic_reports(limit) if self._log is not None else []

    def review(self, robot_id: str, stuck_id: str, *, principal_id: str,
               root_cause: str, note: str) -> bool:
        return self._log.review(robot_id, stuck_id, principal_id=principal_id,
                                root_cause=root_cause, note=note) if self._log is not None else False

    def review_traffic_fact(self, fact_row: int, *, principal_id: str,
                            root_cause: str, note: str) -> bool:
        return self._log.review_traffic_fact(fact_row, principal_id=principal_id,
                                             root_cause=root_cause, note=note) if self._log is not None else False

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self._wall(), timezone.utc).isoformat(timespec="milliseconds")

    def flush(self) -> None:
        """Run the queued episode writes in observe() order. Blocking SQLite: the shared
        gather calls this through ``asyncio.to_thread`` under its lock, so writes for one
        robot never reorder."""
        pending, self._pending = self._pending, []
        for write in pending:
            self._durable(write)

    @staticmethod
    def _durable(write: Callable[[], None]) -> None:
        try:
            write()
        except (OSError, sqlite3.Error):
            _LOG.exception("line stuck episode was not durably recorded")

    def _peak(self, robot_id: str, stuck: dict) -> None:
        peak = self._peaks[robot_id]
        for key, value in (("held_s_max", stuck.get("held_s")), ("attempts_max", stuck.get("attempts"))):
            if isinstance(value, (int, float)) and (peak[key] is None or value > peak[key]):
                peak[key] = value

    def _open_episode(self, row: dict, stuck: dict, robots: list) -> None:
        robot_id = row["robot_id"]
        self._peaks[robot_id] = {"stuck_id": stuck["stuck_id"], "held_s_max": None,
                                 "attempts_max": None}
        if self._log is None:
            return
        pose = None
        if self.map_pose is not None:
            try:
                pose = self.map_pose(robot_id)
            except Exception:  # noqa: BLE001 - context only; the episode is from state
                _LOG.debug("map pose for stuck episode of %s failed", robot_id, exc_info=True)
        busy = self.trip_busy(robot_id) if self.trip_busy is not None else None
        peer = peer_ahead(row, robots, self.peer_config)
        local = stuck.get("local_enabled")
        record = {"robot_id": robot_id, "stuck_id": stuck["stuck_id"], "source": "fleet_poll",
                  "cause": stuck.get("cause"), "phase_at_open": stuck.get("phase"),
                  "local_enabled_at_open": None if local is None else int(bool(local)),
                  "trip_busy_at_open": None if busy is None else int(bool(busy)),
                  "peer_ahead_at_open": None if peer is None else int(peer),
                  "opened_at": self._now_iso()}
        if pose is not None:
            record.update(pose_x=pose.x, pose_y=pose.y, pose_yaw=pose.yaw,
                          pose_state=pose.state, pose_age_s=pose.age_s)
        log = self._log
        self._pending.append(lambda: log.open_episode(record))

    def _close_episode(self, robot_id: str, reason: str) -> None:
        peak = self._peaks.pop(robot_id, None)
        if peak is None or self._log is None:
            return
        log, closed_at = self._log, self._now_iso()
        self._pending.append(lambda: log.close_episode(
            robot_id, peak["stuck_id"], closed_at=closed_at, close_reason=reason,
            held_s_max=peak["held_s_max"], attempts_max=peak["attempts_max"]))

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
                     if a["robot_id"] == robot_id and a["stuck_id"] == entry["stuck_id"]
                     and a["decision"] != "ESCALATE"), None)
        shown["fleet_answer"] = last
        note = self._resolver.get((robot_id, entry["stuck_id"]))
        # D-577 8: the console's human deadline counts from the resolver's note.
        shown["resolver"] = None if note is None else {
            **note, "age_s": round(max(0.0, self._clock() - note["at"]), 2)}
        if self.ai_view is not None:
            shown.update(self.ai_view(robot_id, entry["stuck_id"]))
        return shown

    def last_resolver_answer(self, robot_id: str) -> Optional[dict]:
        """The resolver's newest audited answer or hand-off for this robot (supervision row)."""
        row = next((a for a in reversed(self._answers)
                    if a["robot_id"] == robot_id and a["principal_id"] == "fleet-resolver"), None)
        return None if row is None else {key: row[key] for key in
                                         ("stuck_id", "decision", "tier", "rule", "accepted", "code", "escalated", "at")}

    def pending(self) -> list[dict]:
        return [self.view(robot_id) for robot_id in sorted(self._open)]

    def answers(self) -> list[dict]:
        return list(self._answers)

    def record(self, *, robot_id: str, stuck_id: str, decision: str, principal_id: str,
               accepted: Optional[bool], outcome: Optional[str] = None,
               code: Optional[str] = None, message: Optional[str] = None,
               audit_id: Optional[str] = None, tier: Optional[str] = None,
               rule: Optional[str] = None, escalated: Optional[str] = None) -> dict:
        """Audit one forwarded answer (who, what, CORE's verdict; accepted None = unknown).

        D-438 §8: ``tier`` (human / rule) and ``rule`` say who decided; a resolver hand-off to
        a human is its own row with decision ``ESCALATE`` and the reason in ``escalated``.
        The row also goes to the durable log next to the API audit row (``audit_id``). The
        robot has already been asked, so a log failure is logged, never turned into an error."""
        row = {"robot_id": robot_id, "stuck_id": stuck_id, "decision": decision,
               "principal_id": principal_id, "accepted": accepted, "outcome": outcome,
               "code": code, "message": message, "audit_id": audit_id,
               "tier": tier, "rule": rule, "escalated": escalated,
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
