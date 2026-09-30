"""ROS-free snapshot trigger policy (D-373 decision 4).

Input: perception/learned/shadow payloads and operator requests. Output: a
TriggerDecision when a disagreement between the learned model and the rule
based line error has lasted long enough to be worth a 60 s snapshot.

  error_delta          |error_delta| >= threshold for N consecutive frames
  visibility_mismatch  only one side sees the lane for N consecutive frames
                       (learned visible+error vs rule_error non-null)
  operator             an explicit capture/request; bypasses the cooldown

A frame whose delta is missing (stale or absent rule evidence) neither extends
nor breaks the delta streak; a numeric delta under the threshold breaks it.
Streaks restart after every trigger; automatic triggers then wait cooldown_s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .recording import SHADOW_SCHEMA

DEFAULT_DELTA_THRESHOLD = 0.35
DEFAULT_FRAMES = 3
DEFAULT_COOLDOWN_S = 30.0


@dataclass(frozen=True)
class TriggerDecision:
    reason: str
    values: dict = field(default_factory=dict)


def _number(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


class CaptureTrigger:
    def __init__(self, delta_threshold: float = DEFAULT_DELTA_THRESHOLD,
                 frames: int = DEFAULT_FRAMES, cooldown_s: float = DEFAULT_COOLDOWN_S):
        if not delta_threshold > 0:
            raise ValueError("delta_threshold must be > 0")
        if frames < 1:
            raise ValueError("frames must be >= 1")
        if cooldown_s < 0:
            raise ValueError("cooldown_s must be >= 0")
        self.delta_threshold = float(delta_threshold)
        self.frames = int(frames)
        self.cooldown_s = float(cooldown_s)
        self._last_trigger: float | None = None
        self._reset()

    def _reset(self) -> None:
        self._deltas: list[float] = []
        self._mismatch = 0

    def _fire(self, reason: str, values: dict, now: float) -> TriggerDecision:
        self._last_trigger = now
        self._reset()
        return TriggerDecision(reason, values)

    def _cooling(self, now: float) -> bool:
        return self._last_trigger is not None and now - self._last_trigger < self.cooldown_s

    def on_request(self, note: str, now: float) -> TriggerDecision:
        return self._fire("operator", {"note": str(note).strip()}, now)

    def on_shadow(self, payload, now: float) -> TriggerDecision | None:
        if not isinstance(payload, dict) or payload.get("schema") != SHADOW_SCHEMA:
            return None
        error = _number(payload.get("error"))
        rule_error = _number(payload.get("rule_error"))
        learned_visible = payload.get("visible") is True and error is not None
        rule_visible = rule_error is not None

        delta = _number(payload.get("error_delta"))
        if delta is not None:
            if abs(delta) >= self.delta_threshold:
                self._deltas.append(delta)
            else:
                self._deltas = []
        self._mismatch = self._mismatch + 1 if learned_visible != rule_visible else 0

        if self._cooling(now):
            return None
        common = {"stamp": payload.get("stamp"), "model_revision": payload.get("model_revision"),
                  "error": error, "rule_error": rule_error, "frames": self.frames}
        if len(self._deltas) >= self.frames:
            return self._fire("error_delta", {
                **common, "threshold": self.delta_threshold,
                "error_delta": self._deltas[-self.frames:]}, now)
        if self._mismatch >= self.frames:
            return self._fire("visibility_mismatch", {
                **common, "learned_visible": learned_visible,
                "rule_visible": rule_visible}, now)
        return None
