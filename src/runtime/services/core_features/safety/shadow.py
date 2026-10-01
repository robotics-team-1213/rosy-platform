"""D-400 shadow mode: record what the safety policy would have done. ROS-free.

The policy is evaluated on every non-zero candidate but never changes the
output, the e-stop or the mode. This module only keeps the record: counters,
the last stop/unavailable, eval-time percentiles, and the events to announce.
Events are queued here and drained by CommandManager.announce_pending, after
cmd_vel has reached the wheels (SAF-002 ordering).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

VERDICTS = ("allow", "limit", "stop", "unavailable")
_REPEAT_EVERY_S = 1.0
_MIN_EVENT_INTERVAL_S = 0.2
# announce_pending drains every 20 ms cycle; 64 is a net for a skipped announce
_PENDING_MAX = 64


@dataclass(frozen=True)
class ShadowVerdict:
    t: float
    source: str
    commanded: tuple[float, float]
    output: tuple[float, float]
    verdict: str
    limited: tuple[float, float]
    reason: str
    eval_ms: float


def _pair(values: tuple[float, float]) -> list[float]:
    return [round(values[0], 4), round(values[1], 4)]


def _quantile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank on the sorted window; biased high for even n (conservative for the 10 ms budget gate)."""
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


class ShadowLog:
    """Thread contract: record/drain on the cmd_vel executor thread, snapshot from any thread.

    An event is a change of verdict (reason is payload, not key) or a repeat
    after 1 s, and never more often than every 0.2 s. A verdict change that
    arrives too soon is counted as suppressed (verdict changes, not records)
    and emitted later if it is still current; the next event carries the count
    since the previous one. A change suppressed by the 0.2 s floor is reported
    by the next emitted event; if records stop before then (the robot stops
    commanding), it stays visible only in counts, last_stop/last_unavailable
    and suppressed_events.
    """

    def __init__(self, window: int = 512) -> None:
        if window < 1:
            raise ValueError("window must be >= 1")
        self._lock = threading.Lock()
        self._counts = {name: 0 for name in VERDICTS}
        self._last: dict[str, dict] = {}
        self._eval_ms: deque[float] = deque(maxlen=window)
        self._pending: deque[dict] = deque(maxlen=_PENDING_MAX)
        self._emitted_verdict: str | None = None
        self._emitted_at = float("-inf")
        self._last_seen_verdict: str | None = None
        self._suppressed = 0
        self._suppressed_total = 0
        self._dropped = 0

    def record(self, verdict: ShadowVerdict) -> None:
        with self._lock:
            self._counts[verdict.verdict] += 1
            self._eval_ms.append(verdict.eval_ms)
            if verdict.verdict in ("stop", "unavailable"):
                self._last[verdict.verdict] = {"t": round(verdict.t, 3), "reason": verdict.reason, "source": verdict.source}
            previous, self._last_seen_verdict = self._last_seen_verdict, verdict.verdict
            since = verdict.t - self._emitted_at
            if since < 0:  # clock stepped back: treat this record as the first
                self._emitted_at = float("-inf")
                since = float("inf")
            if verdict.verdict == self._emitted_verdict and since < _REPEAT_EVERY_S:
                return
            if since < _MIN_EVENT_INTERVAL_S:
                if verdict.verdict != previous:
                    self._suppressed += 1
                    self._suppressed_total += 1
                return
            if len(self._pending) == _PENDING_MAX:
                self._dropped += 1
            self._pending.append({"verdict": verdict.verdict, "reason": verdict.reason,
                                  "source": verdict.source, "t": round(verdict.t, 3),
                                  "commanded": _pair(verdict.commanded), "output": _pair(verdict.output),
                                  "limited": _pair(verdict.limited), "suppressed": self._suppressed})
            self._emitted_verdict, self._emitted_at, self._suppressed = verdict.verdict, verdict.t, 0

    def drain(self) -> list[dict]:
        with self._lock:
            pending, self._pending = self._pending, deque(maxlen=_PENDING_MAX)
        return list(pending)

    def snapshot(self) -> dict:
        with self._lock:
            window = list(self._eval_ms)
            counts, last = dict(self._counts), dict(self._last)
            dropped, suppressed = self._dropped, self._suppressed_total
        ordered = sorted(window)
        eval_ms = ({"p50": _quantile(ordered, .5), "p99": _quantile(ordered, .99), "n": len(ordered)}
                   if ordered else {"p50": None, "p99": None, "n": 0})
        return {"counts": counts, "last_stop": last.get("stop"), "last_unavailable": last.get("unavailable"),
                "eval_ms": eval_ms, "dropped_events": dropped, "suppressed_events": suppressed}
