"""NAV-007 / D-143 line-follow selection and fail-closed control policy."""

from __future__ import annotations

import enum
import re
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
    ir_calibrated: bool = False
    calibration_revision: Optional[str] = None

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
        if type(self.ir_calibrated) is not bool:
            raise ValueError("IR calibration marker must be a boolean")
        if self.ir_calibrated and (not isinstance(self.calibration_revision, str)
                                   or not self.calibration_revision.strip()):
            raise ValueError("calibrated IR evidence requires a revision")


@dataclass(frozen=True)
class LineFollowConfig:
    cruise_speed: float = 0.08
    max_linear: float = 0.10
    steering_gain: float = 0.8
    max_angular: float = 0.7
    min_confidence: float = 0.35
    stale_after_s: float = 0.3
    lost_after_s: float = 3.0
    ir_calibration_revision: Optional[str] = None
    # D-349 §11: 앞 물체 정지. LiDAR 정면 부채꼴 최소 거리가 stop 보다 가까우면 멈추고
    # resume 보다 멀어지면 다시 간다(떨림 방지). lidar_forward_deg 는 장착 방향.
    obstacle_stop_m: float = 0.20
    obstacle_resume_m: float = 0.28
    obstacle_half_angle_deg: float = 20.0
    lidar_forward_deg: float = 0.0
    clearance_stale_s: float = 0.5
    # D-349 §12: 카메라 차선 추종 중 IR 이탈 감시. 바닥을 보는 좌·중·우 IR 이 경계선을
    # 한쪽에서 보면 반대로 비키고(ir_guard_turn, 속도 ir_guard_speed_scale 배), 가운데에서
    # 보면 선을 밟고 넘는 중이라 멈춘다. 켜져 있는데 IR 이 끊기거나 미교정이면 멈춘다.
    ir_guard_enabled: bool = False
    ir_guard_edge_error: float = 0.3
    ir_guard_turn: float = 0.5
    ir_guard_speed_scale: float = 0.5

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
        obstacle = (self.obstacle_stop_m, self.obstacle_resume_m, self.obstacle_half_angle_deg,
                    self.lidar_forward_deg, self.clearance_stale_s)
        if not all(_finite(value) for value in obstacle):
            raise ValueError("line-follow obstacle config must be finite")
        if not 0.0 < self.obstacle_stop_m < self.obstacle_resume_m <= 2.0:
            raise ValueError("obstacle_stop_m must be positive and below obstacle_resume_m")
        if not 0.0 < self.obstacle_half_angle_deg <= 90.0 or self.clearance_stale_s <= 0:
            raise ValueError("obstacle sector and clearance staleness must be positive")
        if type(self.ir_guard_enabled) is not bool:
            raise ValueError("ir_guard_enabled must be a boolean")
        guard = (self.ir_guard_edge_error, self.ir_guard_turn, self.ir_guard_speed_scale)
        if not all(_finite(value) for value in guard):
            raise ValueError("line-follow IR guard config must be finite")
        if not 0.0 < self.ir_guard_edge_error < 1.0 or self.ir_guard_turn <= 0:
            raise ValueError("IR guard edge error must be in (0, 1) and turn positive")
        if not 0.0 <= self.ir_guard_speed_scale <= 1.0:
            raise ValueError("ir_guard_speed_scale must be in [0, 1]")
        if (self.ir_calibration_revision is not None
                and (not isinstance(self.ir_calibration_revision, str)
                     or not re.fullmatch(r"[0-9a-f]{64}", self.ir_calibration_revision))):
            raise ValueError("IR calibration revision must be a lowercase SHA-256 digest")


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
        self._ir_observation: Optional[LineObservation] = None
        self._ir_received_at: Optional[float] = None
        self._loss_started_at: Optional[float] = None
        self._lost_latched = False
        self._invalid_observation = False
        self._status = LineFollowStatus()
        # D-349 §8: 운전자 확인 만료. hold_s 가 있으면 hold() 가 그 안에 계속 와야 한다.
        self._hold_s: Optional[float] = None
        self._hold_until: Optional[float] = None
        # D-349 §11: 정면 LiDAR 여유 거리. 한 번도 안 왔으면 판정하지 않는다(LiDAR 없는 벤치).
        self._clearance: Optional[float] = None
        self._clearance_at: Optional[float] = None
        self._obstacle_blocked = False

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
    def config(self) -> LineFollowConfig:
        return self._config

    @property
    def active(self) -> bool:
        with self._lock:
            return self._mode is not LineFollowMode.OFF

    def set_mode(self, mode: LineFollowMode | str,
                 hold_s: Optional[float] = None) -> LineFollowStatus:
        selected = mode if isinstance(mode, LineFollowMode) else LineFollowMode(mode)
        if hold_s is not None and (not _finite(hold_s) or not 0.0 < float(hold_s) <= 2.0):
            raise ValueError("line-follow hold_s must be in (0, 2]")
        with self._lock:
            if selected is LineFollowMode.OFF or hold_s is None:
                self._hold_s = None
                self._hold_until = None
            else:
                self._hold_s = float(hold_s)
                self._hold_until = self._clock() + self._hold_s
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
            if observation.source is LineFollowMode.IR_LINE:
                self._ir_observation = observation
                self._ir_received_at = effective_received_at
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

    def ir_fallback_readiness(self, *, now: Optional[float] = None) -> tuple[bool, tuple[str, ...]]:
        """Return current CORE-owned evidence for an operator-selected IR fallback."""
        current = self._clock() if now is None else now
        if not _finite(current):
            raise ValueError("IR readiness time must be finite")
        with self._lock:
            observation = self._ir_observation
            received_at = self._ir_received_at
            reasons: set[str] = set()
            expected = self._config.ir_calibration_revision
            if expected is None:
                reasons.add("IR_CALIBRATION_REVISION_NOT_CONFIGURED")
            if observation is None or received_at is None:
                reasons.add("IR_EVIDENCE_MISSING")
            else:
                age = float(current) - received_at
                if age < 0.0 or age > self._config.stale_after_s:
                    reasons.add("IR_EVIDENCE_STALE")
                if not observation.ir_calibrated:
                    reasons.add("IR_NOT_CALIBRATED")
                if (expected is not None
                        and observation.calibration_revision != expected):
                    reasons.add("IR_CALIBRATION_REVISION_MISMATCH")
                if not observation.visible:
                    reasons.add("IR_LINE_NOT_VISIBLE")
                if observation.confidence < self._config.min_confidence:
                    reasons.add("IR_LINE_CONFIDENCE_LOW")
            return not reasons, tuple(sorted(reasons))

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

    def invalidate_ir(self, received_at: Optional[float] = None) -> None:
        """Invalidate the cached IR fallback evidence without changing camera state."""
        now = self._clock() if received_at is None else received_at
        if not _finite(now):
            raise ValueError("received_at must be finite")
        with self._lock:
            self._ir_observation = LineObservation(
                source=LineFollowMode.IR_LINE, stamp=float(now), visible=False,
                error=None, confidence=0.0, ir_calibrated=False,
            )
            self._ir_received_at = float(now)

    def status(self) -> LineFollowStatus:
        with self._lock:
            return self._status.model_copy()

    def observe_clearance(self, distance: Optional[float],
                          received_at: Optional[float] = None) -> None:
        """정면 최소 거리(None = 부채꼴 안에 유효 표본 없음 = 막힌 것 없음)."""
        now = self._clock() if received_at is None else received_at
        with self._lock:
            self._clearance = None if distance is None or not _finite(distance) else float(distance)
            self._clearance_at = float(now)
            if self._clearance is None or self._clearance >= self._config.obstacle_resume_m:
                self._obstacle_blocked = False
            elif self._clearance < self._config.obstacle_stop_m:
                self._obstacle_blocked = True

    @property
    def hold_required(self) -> bool:
        with self._lock:
            return self._hold_s is not None

    def hold(self, now: Optional[float] = None) -> bool:
        """운전자가 아직 "진행"을 누르고 있다(D-349 §8). 활성 hold 세션만 연장한다."""
        current = self._clock() if now is None else now
        with self._lock:
            if self._mode is LineFollowMode.OFF or self._hold_s is None:
                return False
            self._hold_until = float(current) + self._hold_s
            return True

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
            if self._hold_until is not None and current > self._hold_until:
                # 운전자가 손을 뗐거나 링크가 끊겼다 — 스스로 내린다(D-349 §8).
                previous = self._mode
                self._generation += 1
                self._mode = LineFollowMode.OFF
                self._hold_s = None
                self._hold_until = None
                self._loss_started_at = None
                self._events.publish(
                    "nav.line_driver_released", source="line_follow_manager",
                    data={"mode": previous.value},
                )
                return self._stop_decision("OFF", "driver_released")
            if self._clearance_at is not None:
                # 앞 물체 정지는 차선 상실이 아니다 — LOST 로 누적하지 않고 치워지면 곧바로 간다.
                if current - self._clearance_at > self._config.clearance_stale_s:
                    return self._stop_decision("HOLD", "obstacle_sensor_stale")
                if self._obstacle_blocked:
                    return self._stop_decision("HOLD", "obstacle_ahead")
            guard = None
            if self._mode is LineFollowMode.CAMERA_LINE and self._config.ir_guard_enabled:
                # 차선 이탈 감시는 차선 상실이 아니다 — LOST 로 누적하지 않는다(D-349 §12).
                guard = self._ir_guard(current)
                if guard == "stale":
                    return self._stop_decision("HOLD", "lane_guard_stale")
                if guard == "centre":
                    return self._stop_decision("HOLD", "lane_departure")
            if self._lost_latched:
                reason = ("camera_reselection_required"
                          if self._mode is LineFollowMode.CAMERA_LINE
                          else "reselection_required")
                return self._stop_decision("LOST", reason)

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
            reason = "tracking"
            if guard in ("left", "right"):
                # 경계선이 왼쪽 IR 밑이면 오른쪽(음의 각속도, REP-103)으로 비킨다.
                turn = min(self._config.ir_guard_turn, self._config.max_angular)
                angular = -turn if guard == "left" else turn
                linear *= self._config.ir_guard_speed_scale
                reason = f"lane_edge_{guard}"
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
                reason=reason,
                clearance_m=self._clearance,
            )
            return decision

    def _ir_guard(self, now: float) -> str:
        """stale | clear | left | right | centre — IR 이 본 경계선 위치."""
        observation = self._ir_observation
        received_at = self._ir_received_at
        if observation is None or received_at is None:
            return "stale"
        age = now - received_at
        if age < 0.0 or age > self._config.stale_after_s:
            return "stale"
        expected = self._config.ir_calibration_revision
        if not observation.ir_calibrated or (
                expected is not None and observation.calibration_revision != expected):
            return "stale"
        if not observation.visible or observation.error is None                 or observation.confidence < self._config.min_confidence:
            return "clear"
        if observation.error <= -self._config.ir_guard_edge_error:
            return "left"
        if observation.error >= self._config.ir_guard_edge_error:
            return "right"
        return "centre"

    def _loss_or_stop(self, now: float, state: str, reason: str,
                      age: Optional[float]) -> LineFollowDecision:
        if self._mode is LineFollowMode.CAMERA_LINE:
            reason = f"camera_{reason}"
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
            clearance_m=self._clearance,
        )
        return LineFollowDecision(
            generation=self._generation,
            evidence_revision=self._evidence_revision,
            mode=self._mode,
        )
