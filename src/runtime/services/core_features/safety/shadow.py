"""D-398 shadow mode: record what the safety policy would have done. ROS-free.

The policy is evaluated on every non-zero candidate but never changes the
output, the e-stop or the mode. This module only keeps the record: counters,
the last stop/unavailable, eval-time percentiles, and the events to announce.
Events are queued here and drained by CommandManager.announce_pending, after
cmd_vel has reached the wheels (SAF-002 ordering).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

VERDICTS = ("allow", "limit", "stop", "unavailable")
_REPEAT_EVERY_S = 1.0
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
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


class ShadowLog:
    def __init__(self, window: int = 512) -> None:
        self._counts = {name: 0 for name in VERDICTS}
        self._last: dict[str, dict] = {}
        self._eval_ms: deque[float] = deque(maxlen=window)
        self._pending: deque[dict] = deque(maxlen=_PENDING_MAX)
        self._state: str | None = None
        self._state_reason = ""
        self._emitted_at = float("-inf")

    def record(self, verdict: ShadowVerdict) -> None:
        self._counts[verdict.verdict] += 1
        self._eval_ms.append(verdict.eval_ms)
        if verdict.verdict in ("stop", "unavailable"):
            self._last[verdict.verdict] = {"t": verdict.t, "reason": verdict.reason, "source": verdict.source}
        changed = (verdict.verdict, verdict.reason) != (self._state, self._state_reason)
        if changed or verdict.t - self._emitted_at >= _REPEAT_EVERY_S:
            self._state, self._state_reason, self._emitted_at = verdict.verdict, verdict.reason, verdict.t
            self._pending.append({"verdict": verdict.verdict, "reason": verdict.reason,
                                  "source": verdict.source, "commanded": _pair(verdict.commanded),
                                  "limited": _pair(verdict.limited)})

    def drain(self) -> list[dict]:
        pending = list(self._pending)
        self._pending.clear()
        return pending

    def snapshot(self) -> dict:
        ordered = sorted(self._eval_ms)
        eval_ms = ({"p50": _quantile(ordered, .5), "p99": _quantile(ordered, .99), "n": len(ordered)}
                   if ordered else {"p50": None, "p99": None, "n": 0})
        return {"counts": dict(self._counts), "last_stop": self._last.get("stop"),
                "last_unavailable": self._last.get("unavailable"), "eval_ms": eval_ms}
