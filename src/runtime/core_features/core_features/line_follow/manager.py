"""NAV-007 / D-143 line-follow selection and fail-closed control policy."""

from __future__ import annotations

import enum
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from core_common.protocol.schemas import LineFollowStatus
from core_features.decision.contract import DecisionRequest
from core_features.decision.lane import FOLLOW, LANE_ACTIONS, STOP, lane_recovery_rule


class LineFollowMode(str, enum.Enum):
    OFF = "OFF"
    IR_LINE = "IR_LINE"
    CAMERA_LINE = "CAMERA_LINE"


@dataclass(frozen=True)
class LineObservation:
    source: LineFollowMode
    stamp: float
    visible: bool
    error: Optional[float]
    confidence: float

    def __post_init__(self) -> None:
        if self.source is LineFollowMode.OFF:
            raise ValueError("OFF cannot be an observation source")
        if not _finite(self.stamp):
            raise ValueError("observation stamp must be finite")
        if not _finite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.visible:
            if not _finite(self.error) or not -1.0 <= float(self.error) <= 1.0:
                raise ValueError("visible observation error must be in [-1, 1]")
        elif self.error is not None:
            raise ValueError("invisible observation cannot carry an error")


@dataclass(frozen=True)
class LineFollowConfig:
    cruise_speed: float = 0.08
    max_linear: float = 0.10
    steering_gain: float = 0.8
    max_angular: float = 0.7
    min_confidence: float = 0.35
    stale_after_s: float = 0.3
    lost_after_s: float = 3.0

    def __post_init__(self) -> None:
        values = (self.cruise_speed, self.max_linear, self.steering_gain,
                  self.max_angular, self.min_confidence,
                  self.stale_after_s, self.lost_after_s)
        if not all(_finite(value) for value in values):
            raise ValueError("line-follow config must be finite")
        if not 0.0 < self.cruise_speed <= self.max_linear <= 0.10:
            raise ValueError("line-follow speed must be positive and capped at 0.10 m/s")
        if self.steering_gain <= 0 or self.max_angular <= 0:
            raise ValueError("line-follow steering limits must be positive")
        if not 0.0 < self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be in (0, 1]")
        if self.stale_after_s <= 0 or self.lost_after_s <= 0:
            raise ValueError("line-follow timeouts must be positive")


@dataclass(frozen=True)
class LineFollowDecision:
    linear: float = 0.0
    angular: float = 0.0
    generation: int = 0
    evidence_revision: int = 0
    mode: LineFollowMode = LineFollowMode.OFF


def _finite(value) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(float(value)))


class LineFollowManager:
    def __init__(self, events, *, config: Optional[LineFollowConfig] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._events = events
        self._lock = threading.RLock()
        self._config = config or LineFollowConfig()
        self._clock = clock
        self._mode = LineFollowMode.OFF
        self._generation = 0
        self._evidence_revision = 0
        self._observation: Optional[LineObservation] = None
        self._received_at: Optional[float] = None
        self._loss_started_at: Optional[float] = None
        self._lost_latched = False
        self._invalid_observation = False
        self._status = LineFollowStatus()

    def bind_clock(self, clock: Callable[[], float]) -> None:
        """Use the bridge's line clock for defaults (mode change, loss start)."""
        if not callable(clock):
            raise ValueError("line-follow clock must be callable")
        with self._lock:
            self._clock = clock

    @property
    def mode(self) -> LineFollowMode:
        with self._lock:
            return self._mode

    @property
    def active(self) -> bool:
        with self._lock:
            return self._mode is not LineFollowMode.OFF

    def set_mode(self, mode: LineFollowMode | str) -> LineFollowStatus:
        selected = mode if isinstance(mode, LineFollowMode) else LineFollowMode(mode)
        with self._lock:
            previous = self._mode
            self._generation += 1
            self._mode = selected
            self._observation = None
            self._received_at = None
            self._lost_latched = False
            self._invalid_observation = False
            self._loss_started_at = None if selected is LineFollowMode.OFF else self._clock()
            self._status = LineFollowStatus(
                mode=selected.value,
                state="OFF" if selected is LineFollowMode.OFF else "WAITING",
                source=None if selected is LineFollowMode.OFF else selected.value,
                reason="mode_off" if selected is LineFollowMode.OFF else "no_observation",
            )
            if previous is not selected:
                self._events.publish(
                    "nav.line_mode_changed", source="line_follow_manager",
                    data={"from": previous.value, "to": selected.value},
                )
            return self._status.model_copy()

    def stop(self) -> LineFollowStatus:
        return self.set_mode(LineFollowMode.OFF)

    def observe(self, observation: LineObservation, received_at: Optional[float] = None,
                source_now: Optional[float] = None) -> bool:
        now = self._clock() if received_at is None else received_at
        if not _finite(now):
            raise ValueError("received_at must be finite")
        effective_received_at = float(now)
        if source_now is not None:
            if not _finite(source_now):
                raise ValueError("source_now must be finite")
            source_age = float(source_now) - observation.stamp
            if source_age < -0.1:
                raise ValueError("observation timestamp is in the future")
            effective_received_at -= max(0.0, source_age)
        with self._lock:
            if observation.source is not self._mode:
                return False
            self._invalid_observation = False
            self._observation = observation
            self._received_at = effective_received_at
            self._evidence_revision += 1
            if observation.visible and observation.confidence >= self._config.min_confidence:
                if not self._lost_latched:
                    self._loss_started_at = None
            elif self._loss_started_at is None:
                self._loss_started_at = float(now)
            return True

    def invalidate(self, received_at: Optional[float] = None) -> bool:
        """Replace an active command candidate with explicit invalid evidence."""
        now = self._clock() if received_at is None else received_at
        if not _finite(now):
            raise ValueError("received_at must be finite")
        with self._lock:
            if self._mode is LineFollowMode.OFF:
                return False
            self._observation = LineObservation(
                source=self._mode, stamp=float(now), visible=False,
                error=None, confidence=0.0)
            self._received_at = float(now)
            self._invalid_observation = True
            self._evidence_revision += 1
            if self._loss_started_at is None:
                self._loss_started_at = float(now)
            return True

    def status(self) -> LineFollowStatus:
        with self._lock:
            return self._status.model_copy()

    def apply_if_current(self, decision: LineFollowDecision,
                         apply: Callable[[LineFollowDecision], None]) -> bool:
        """Apply a decision only while its mode and sensor evidence stay current.

        The callback runs inside the same lock as ``set_mode``. Therefore either
        the old command is written before a transition (whose caller then clears
        it), or the transition wins and this write is rejected. Observations and
        invalidations also advance an evidence revision so fail-closed evidence
        cannot be overtaken by a command computed from an older frame.
        """
        with self._lock:
            if (decision.generation != self._generation
                    or decision.evidence_revision != self._evidence_revision
                    or decision.mode is not self._mode
                    or self._mode is LineFollowMode.OFF):
                return False
            apply(decision)
            return True

    def tick(self, now: Optional[float] = None) -> LineFollowDecision:
        current = self._clock() if now is None else now
        if not _finite(current):
            raise ValueError("line-follow clock must be finite")
        current = float(current)
        with self._lock:
            if self._mode is LineFollowMode.OFF:
                return self._stop_decision("OFF", "mode_off")
            if self._lost_latched:
                return self._stop_decision("LOST", "reselection_required")

            observation = self._observation
            age = None if self._received_at is None else current - self._received_at
            choice = lane_recovery_rule(
                DecisionRequest(
                    decision_id=f"line-{self._generation}",
                    decision_type="lane_recovery",
                    allowed_actions=LANE_ACTIONS,
                    snapshot_age_ms=0,
                    max_age_ms=1,
                    deadline_ms=1,
                    elapsed_ms=0,
                    mode="NAVIGATION",
                    safety_state="NORMAL",
                    context={
                        "visible": bool(observation and observation.visible),
                        "confidence": 0.0 if observation is None else float(observation.confidence),
                        "min_confidence": self._config.min_confidence,
                        "age_s": None if observation is None or self._received_at is None else age,
                        "stale_after_s": self._config.stale_after_s,
                        "source_matches": bool(observation and observation.source is self._mode),
                    },
                    fallback_action=STOP,
                ),
                LANE_ACTIONS,
            )
            if choice != FOLLOW:
                if observation is None or self._received_at is None:
                    return self._loss_or_stop(current, "WAITING", "no_observation", age)
                if observation.source is not self._mode:
                    return self._loss_or_stop(current, "HOLD", "source_mismatch", age)
                if age < 0.0 or age > self._config.stale_after_s:
                    if self._loss_started_at is None:
                        self._loss_started_at = min(current, self._received_at + self._config.stale_after_s)
                    return self._loss_or_stop(current, "HOLD", "observation_stale", age)
                if not observation.visible:
                    reason = "invalid_observation" if self._invalid_observation else "line_not_visible"
                    return self._loss_or_stop(current, "HOLD", reason, age)
                if observation.confidence < self._config.min_confidence:
                    return self._loss_or_stop(current, "HOLD", "low_confidence", age)
                return self._loss_or_stop(current, "HOLD", "lane_recovery", age)

            self._loss_started_at = None
            error = float(observation.error)
            confidence_span = 1.0 - self._config.min_confidence
            confidence_scale = (1.0 if confidence_span == 0.0 else
                                (observation.confidence - self._config.min_confidence)
                                / confidence_span)
            confidence_scale = max(0.0, min(1.0, confidence_scale))
            curve_scale = max(0.2, 1.0 - 0.65 * abs(error))
            linear = min(self._config.cruise_speed, self._config.max_linear)
            linear *= confidence_scale * curve_scale
            angular = max(-self._config.max_angular,
                          min(self._config.max_angular, -self._config.steering_gain * error))
            decision = LineFollowDecision(
                linear=linear, angular=angular,
                generation=self._generation,
                evidence_revision=self._evidence_revision,
                mode=self._mode)
            self._status = LineFollowStatus(
                mode=self._mode.value,
                state="TRACKING",
                source=observation.source.value,
                error=error,
                confidence=observation.confidence,
                age_s=round(age, 3),
                linear=linear,
                angular=angular,
                reason="tracking",
            )
            return decision

    def _loss_or_stop(self, now: float, state: str, reason: str,
                      age: Optional[float]) -> LineFollowDecision:
        if self._loss_started_at is None:
            self._loss_started_at = now
        if now - self._loss_started_at > self._config.lost_after_s:
            self._lost_latched = True
            self._events.publish(
                "nav.lane_lost", severity="warning", source="line_follow_manager",
                data={"mode": self._mode.value, "reason": reason,
                      "lost_after_s": self._config.lost_after_s},
            )
            return self._stop_decision("LOST", "reselection_required", age)
        return self._stop_decision(state, reason, age)

    def _stop_decision(self, state: str, reason: str,
                       age: Optional[float] = None) -> LineFollowDecision:
        observation = self._observation
        self._status = LineFollowStatus(
            mode=self._mode.value,
            state=state,
            source=None if self._mode is LineFollowMode.OFF else self._mode.value,
            error=(observation.error if observation and observation.visible else None),
            confidence=(observation.confidence if observation else 0.0),
            age_s=None if age is None else round(max(0.0, age), 3),
            reason=reason,
        )
        return LineFollowDecision(
            generation=self._generation,
            evidence_revision=self._evidence_revision,
            mode=self._mode,
        )
