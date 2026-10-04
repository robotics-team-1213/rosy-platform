"""Subject: the perception/learned/shadow wire shape (D-356).

Shadow evidence has no consumer in the control path. It carries the model's
lane error next to the rule-based one so disagreement can be logged and later
used as a recording trigger and as replay-gate input (D-205)."""

from __future__ import annotations

import math
from collections import deque

from .runner import InferResult

SHADOW_SCHEMA = "rosy.perception.learned_shadow/1"
TOPIC = "perception/learned/shadow"


RULE_WINDOW_S = 2.0  # rule observations kept for matching
RULE_EXACT_S = 1e-3  # same camera frame (stamps round-trip through JSON floats)
RULE_NEAR_S = 0.2  # else the nearest observation within this is still the same scene


def _finite(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


class RuleRing:
    """Recent CAMERA_LINE observations keyed by their image stamp.

    The shadow result for a frame must be compared with the rule answer for
    that frame, not the newest one: inference lags the rule observer, and a
    lag past a fixed age used to read as "rule saw no lane" (D-373 WSL run).
    match() returns (rule_visible, rule_error); (None, None) means unknown."""

    def __init__(self, window_s: float = RULE_WINDOW_S):
        self._window_s = float(window_s)
        self._rows: deque[tuple[float, bool, float | None]] = deque()

    def add(self, stamp: float, visible: bool, error) -> None:
        err = _finite(error)
        seen = bool(visible) and err is not None
        self._rows.append((float(stamp), seen, err if seen else None))
        newest = max(r[0] for r in self._rows)
        while self._rows and self._rows[0][0] < newest - self._window_s:
            self._rows.popleft()

    def match(self, stamp: float) -> tuple[bool | None, float | None]:
        best = None
        for row in self._rows:
            gap = abs(row[0] - stamp)
            if gap <= RULE_EXACT_S:
                return row[1], row[2]
            if gap <= RULE_NEAR_S and (best is None or gap < best[0]):
                best = (gap, row)
        if best is None:
            return None, None
        return best[1][1], best[1][2]


def shadow_payload(result: InferResult, *, stamp: float, rule_error: float | None,
                   rule_visible: bool | None = None) -> dict:
    """rule_visible: True/False when the rule observer answered for this frame,
    None when its answer is unknown (missing or too far in time)."""
    if rule_error is not None:
        rule_visible = True
    ev = result.evidence
    delta = (round(ev.error - rule_error, 6)
             if ev.visible and ev.error is not None and rule_error is not None else None)
    return {
        "schema": SHADOW_SCHEMA,
        "stamp": float(stamp),
        "model_revision": result.model_revision,
        "visible": ev.visible,
        "error": ev.error,
        "confidence": ev.confidence,
        "latency_ms": round(result.latency_ms, 3),
        "class_fractions": dict(ev.class_fractions),
        "wall_fraction": ev.wall_fraction,
        "rule_error": rule_error,
        "rule_visible": rule_visible,
        "error_delta": delta,
    }
