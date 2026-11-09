"""Per-source calibration health: what the approved fit looks like against Vision's fresh paint fit (D-1006).

``tracking_drift`` only judged *accepted* fits, so a camera whose fit Vision rejects (a
re-aimed or half-hidden view, a changed floor) stayed silent. This module classifies every
poll, rejected and unreachable ones included, and turns the polls into one state per source
with hysteresis:

``fresh``                  an accepted fit agrees with the approved record
``drifting``               an accepted fit disagrees (move > 0.3 m or rotation > 3 deg)
``mismatch``               no fit passes although enough paint is in view (the picture and the
                           map disagree; camera moved or floor changed, not decidable here)
``insufficient_coverage``  too little paint in view, or no fit at all: cannot be verified
``unknown``                no usable answer within ``UNKNOWN_AFTER_S`` (or nothing seen yet)

Observation only (D-457). The one optional effect is the sighting gate: with ``gate`` on,
``blocks()`` is true in ``drifting``/``mismatch`` and ``TrackingService.approved_revision``
then stops offering the approved revision to camera-derived map poses. ``unknown`` and
``insufficient_coverage`` never block: absence of evidence must not switch localization off.
It never writes a calibration (D-595) and never commands motion.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Callable, Mapping, Optional

from .sqlite_policy import configure_connection, enable_wal

AGREE, DISAGREE, MISMATCH, LOW_COVERAGE = "agree", "disagree", "mismatch", "low_coverage"
INCONCLUSIVE, NO_RESPONSE = "inconclusive", "no_response"

#: Rejected-fit thresholds (Vision gates: MIN_COVERAGE 0.2, MIN_RECALL 0.8). A rejected fit
#: is a mismatch only with real paint in view (coverage) and a clearly poor match (score);
#: the band in between is inconclusive. Starting values from the 2026-11-09 incident
#: (score 0.51-0.60, coverage 0.43-0.59); the journal exists to tune them.
LOW_COVERAGE_BELOW = 0.20
MISMATCH_COVERAGE_AT_LEAST = 0.40
MISMATCH_SCORE_BELOW = 0.70
#: Consecutive same-kind polls (60 s apart) before the state changes; leaving a blocking
#: state needs more agreeing polls than entering a benign one.
NEED_POLLS = {"fresh": 3, "drifting": 3, "mismatch": 5, "insufficient_coverage": 3}
NEED_POLLS_LEAVE_BLOCKING = 5
UNKNOWN_AFTER_S = 180.0
BLOCKING = frozenset({"drifting", "mismatch"})
_TARGET = {AGREE: "fresh", DISAGREE: "drifting", MISMATCH: "mismatch", LOW_COVERAGE: "insufficient_coverage"}
JOURNAL_KEEP = 5000

_LOG = logging.getLogger(__name__)


def classify(body: Optional[Mapping], verdict: Optional[Mapping]) -> tuple[str, dict]:
    """One poll -> ``(category, metrics)``. ``verdict`` is ``calibration_drift_verdict``'s output."""
    if not isinstance(body, Mapping):
        return NO_RESPONSE, {}
    if body.get("accepted") is True:
        if verdict is None:
            return INCONCLUSIVE, {}  # accepted, but a different pixel grid or incomparable corners
        return (DISAGREE if verdict["state"] == "stale" else AGREE), {
            "move_m": verdict["max_move_m"], "rotation_deg": verdict["rotation_deg"]}
    fit = body.get("rejected_fit")
    if not isinstance(fit, Mapping):
        return LOW_COVERAGE, {}  # no fit at all: nothing of the paint could be registered
    score, coverage = _num(fit.get("score")), _num(fit.get("coverage"))
    metrics = {"score": score, "coverage": coverage, "cut_sides": list(fit.get("cut_sides") or ())}
    if coverage is None or score is None:
        return INCONCLUSIVE, metrics
    if coverage < LOW_COVERAGE_BELOW:
        return LOW_COVERAGE, metrics
    if coverage >= MISMATCH_COVERAGE_AT_LEAST and score < MISMATCH_SCORE_BELOW:
        return MISMATCH, metrics
    return INCONCLUSIVE, metrics


def _num(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        and value == value and abs(value) != float("inf") else None


class CalibrationHealth:
    def __init__(self, *, clock: Callable[[], float] = time.time, gate: bool = False,
                 journal_path: Path | str | None = None) -> None:
        self._clock = clock
        self.gate = bool(gate)
        self._journal = Path(journal_path) if journal_path is not None else None
        self._rows: dict[str, dict] = {}
        if self._journal is not None:
            with closing(self._connect()) as connection:
                enable_wal(connection)
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS calibration_health_log (
                           log_id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                           source_id TEXT NOT NULL, calibration_revision TEXT, category TEXT NOT NULL,
                           state TEXT NOT NULL, score REAL, coverage REAL, cut_sides TEXT,
                           move_m REAL, rotation_deg REAL, frame_seq INTEGER)""")

    def forget(self, source_id: str) -> None:
        self._rows.pop(source_id, None)

    def observe(self, source_id: str, calibration_revision: str, body: Optional[Mapping],
                verdict: Optional[Mapping]) -> None:
        now = self._clock()
        row = self._rows.get(source_id)
        if row is None or row["calibration_revision"] != calibration_revision:
            # A new approval is a fresh start: the operator has just re-fitted (D-595).
            row = self._rows[source_id] = {
                "calibration_revision": calibration_revision, "state": "unknown", "since": now,
                "streak_kind": None, "streak": 0, "last_response_at": None, "metrics": {}}
        category, metrics = classify(body, verdict)
        before = row["state"]
        if category != NO_RESPONSE:
            row["last_response_at"] = now
            row["metrics"] = {**metrics, "category": category, "checked_at": now}
            if category == row["streak_kind"]:
                row["streak"] += 1
            else:
                row["streak_kind"], row["streak"] = category, 1
            target = _TARGET.get(category)
            need = NEED_POLLS.get(target, 0)
            if target == "fresh" and before in BLOCKING:
                need = NEED_POLLS_LEAVE_BLOCKING
            if target is not None and row["streak"] >= need and target != before:
                row["state"], row["since"] = target, now
                _LOG.warning("calibration health %s: %s -> %s (%s)", source_id, before, target, metrics)
        self._log(now, source_id, calibration_revision, category, row["state"], metrics, body)

    def view(self, source_id: str) -> Optional[dict]:
        """The source-row payload (display only), or None when the watch has seen no record."""
        row = self._rows.get(source_id)
        if row is None:
            return None
        now = self._clock()
        last = row["last_response_at"]
        timed_out = last is None or now - last > UNKNOWN_AFTER_S
        state = "unknown" if timed_out else row["state"]
        return {"state": state, "since": row["since"], "cause": "undetermined",
                "calibration_revision": row["calibration_revision"],
                "streak": {"kind": row["streak_kind"], "polls": row["streak"]},
                "last": dict(row["metrics"]), "blocking": self.gate and state in BLOCKING,
                "gate": self.gate}

    def blocks(self, source_id: str) -> bool:
        view = self.view(source_id)
        return bool(view and view["blocking"])

    def _log(self, now, source_id, revision, category, state, metrics, body) -> None:
        if self._journal is None:
            return
        frame_seq = body.get("frame_seq") if isinstance(body, Mapping) else None
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    "INSERT INTO calibration_health_log(at, source_id, calibration_revision, category,"
                    " state, score, coverage, cut_sides, move_m, rotation_deg, frame_seq)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (now, source_id, revision, category, state, metrics.get("score"),
                     metrics.get("coverage"), ",".join(metrics.get("cut_sides") or ()) or None,
                     metrics.get("move_m"), metrics.get("rotation_deg"),
                     frame_seq if type(frame_seq) is int else None))
                connection.execute(
                    "DELETE FROM calibration_health_log WHERE log_id <= "
                    "(SELECT MAX(log_id) FROM calibration_health_log) - ?", (JOURNAL_KEEP,))
        except sqlite3.Error:
            _LOG.exception("calibration health journal write failed")  # observation only: never raise

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._journal, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)
