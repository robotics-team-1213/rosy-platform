"""Helper mixin for LineFollowManager: steering, IR guard, obstacle clearance, and loss state."""

from __future__ import annotations

import math
from typing import Optional

from core_common.protocol.schemas import LineFollowStatus
from core_features.line_follow.clearance import Point, path_clearance
from core_features.line_follow.model import (
    LineFollowDecision,
    LineFollowMode,
    LineObservation,
    _finite,
)
from core_features.line_follow.route_context import route_context as build_route_context


class LineFollowHelpersMixin:
    """Obstacle clearance, steering, IR guard, driver hold, and loss/stop helpers."""

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
                if expected is not None and observation.calibration_revision != expected:
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
            self._return_evidence.invalidate_lane()
            self._confident_frames = 0  # D-476: an invalid frame breaks the arming streak
            self._resume_streak = (0, None)
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

    def set_route_context_publication(self, context, stamp_s: float) -> None:
        with self._lock:
            self._route_context_current = context
            self._route_context_published_at_s = stamp_s if context is not None else None

    def route_context(self, *, ros_now: float, now: Optional[float] = None):
        """The active instruction in image clock coordinates, or no usable context."""
        if not self._config.route_context_enabled:
            return None
        now = self._clock() if now is None else now
        with self._lock:
            pose = self._fresh_pose(now)
            if pose is None:
                return None
            return build_route_context(
                self._junction, self._arc, mono_now=now, ros_now=ros_now,
                odom_key=(self._return_evidence.epoch, pose.frame),
                odometer=self._return_evidence.trail.odometer, mode=self._mode.value)

    def observe_clearance(self, distance: Optional[float],
                          received_at: Optional[float] = None) -> None:
        """정면 최소 거리(None = 부채꼴 안에 유효 표본 없음 = 막힌 것 없음)."""
        now = self._clock() if received_at is None else received_at
        with self._lock:
            self._scan_points = None
            self._clearance_at = float(now)
            self._set_clearance(distance)

    def observe_scan_points(self, points, received_at: Optional[float] = None,
                            *, lag_s: float = 0.0) -> None:
        """path 판정: 로봇 좌표(x 앞, y 왼쪽) 점. 여유 거리는 틱이 의도 조향으로 잰다."""
        now = self._clock() if received_at is None else received_at
        with self._lock:
            self._scan_points = tuple((float(x), float(y)) for x, y in points)
            self._clearance_at = float(now) - max(0.0, lag_s)
            self._remember_near(float(now))  # D-422: returns that slip under range_min

    def obstacle_gap(self, linear: float, angular: float, now: Optional[float] = None):
        """D-559: this obstacle judgement for another CORE mode's twist (swarm trail follow)."""
        c = self._config
        current = self._clock() if now is None else now
        with self._lock:
            if self._clearance_at is None or current - self._clearance_at > c.clearance_stale_s:
                return None
            if self._scan_points is None:
                return self._clearance, c.sector_stop_m, c.sector_resume_m
            saved = self._intended, self._gap_status, self._gap_resume
            self._intended = (float(linear), float(angular))
            try:
                if c.body_stop_known:
                    gap, _, stop, resume = self._body_clearance(current)
                    return gap, stop, resume
                return self._path_clearance(), c.sector_stop_m, c.sector_resume_m
            finally:
                self._intended, self._gap_status, self._gap_resume = saved

    def _set_clearance(self, distance: Optional[float], now: Optional[float] = None,
                       stop: Optional[float] = None, resume: Optional[float] = None) -> None:
        """여유 거리와 떨림 방지(stop < resume) 판정. 잠금 안에서 부른다."""
        stop = self._config.sector_stop_m if stop is None else stop
        resume = self._config.sector_resume_m if resume is None else resume
        self._clearance = None if distance is None or not _finite(distance) else float(distance)
        clear = self._clearance is None or (self._clearance >= resume and self._clearance > 0.0)
        if not clear:
            self._clear_since = None
            if self._clearance < stop or self._clearance <= 0.0:
                self._obstacle_blocked = True
            return
        if not self._obstacle_blocked:
            return
        if now is None or self._config.obstacle_release_s <= 0.0:
            self._obstacle_blocked = False
            return
        if self._clear_since is None:
            self._clear_since = now
        if now - self._clear_since >= self._config.obstacle_release_s:
            self._obstacle_blocked = False
            self._clear_since = None

    def _obstacle_hold(self, now: float) -> LineFollowDecision:
        """앞 물체 정지. 오래 이어지면 한 번 알린다(모서리 벽이 띠 안이면 스스로 풀리지 않는다)."""
        if self._blocked_since is None:
            self._blocked_since = now
        elif (not self._escalated
              and now - self._blocked_since >= self._config.obstacle_escalate_s):
            self._escalated = True
            self._events.publish(
                "nav.line_obstacle_hold", severity="warning", source="line_follow_manager",
                data={"mode": self._mode.value, "clearance_m": self._clearance,
                      "held_s": round(now - self._blocked_since, 2), **self._gap_status},
            )
        return self._stop_decision("HOLD", "obstacle_ahead")

    def _angular_cap(self) -> float:
        """유효 각속도 상한 = min(max_angular, 살아 있는 수동 한도). 읽을 수 없으면 0(정지)."""
        cap = self._config.max_angular
        if self._config.max_angular_follows_manual and self._angular_ceiling is not None:
            try:
                ceiling = self._angular_ceiling()
            except Exception:  # noqa: BLE001 — 한도를 못 읽으면 조향할 수 없다: 멈춘다
                return 0.0
            if not _finite(ceiling):
                return 0.0
            cap = min(cap, float(ceiling))
        return max(0.0, cap)

    def _steer(self, observation: LineObservation, guard: Optional[str],
               cap: float) -> tuple[float, float, str]:
        """(linear, angular, reason). 한도 계단이 조향을 자르면 곡률을 지키도록 속도도 줄인다."""
        error = float(observation.error)
        confidence_span = 1.0 - self._config.min_confidence
        confidence_scale = (1.0 if confidence_span == 0.0 else
                            (observation.confidence - self._config.min_confidence)
                            / confidence_span)
        confidence_scale = max(0.0, min(1.0, confidence_scale))
        curve_scale = max(0.2, 1.0 - 0.65 * abs(error))
        linear = min(self._config.cruise_speed, self._config.max_linear)
        linear *= confidence_scale * curve_scale
        angular = -self._config.steering_gain * error
        reason = "tracking"
        if guard in ("left", "right", "centre") and linear < self._config.ir_guard_min_linear:
            if self._config.ir_guard_back_speed > 0.0 and self._rear_clear_now():
                linear = -self._config.ir_guard_back_speed
        elif guard in ("left", "right"):
            turn = min(self._config.ir_guard_turn, self._config.max_angular)
            angular = -turn if guard == "left" else turn
            linear *= self._config.ir_guard_speed_scale
            reason = f"lane_edge_{guard}"
        elif guard in ("cue_left", "cue_right"):
            turn = min(self._config.ir_guard_turn, self._config.max_angular)
            angular = turn if guard == "cue_left" else -turn
            linear *= self._config.ir_guard_speed_scale
            reason = f"fleet_{guard}"
        elif guard == "crosswalk":
            reason = "ir_guard_crosswalk"
        if abs(angular) > cap:
            linear *= cap / abs(angular)
            angular = math.copysign(cap, angular)
        return linear, angular, reason

    @property
    def hold_required(self) -> bool:
        with self._lock:
            return self._hold_s is not None

    def hold(self, now: Optional[float] = None) -> bool:
        """운전자가 아직 "진행"을 누르고 있다(D-344 §8). 활성 hold 세션만 연장한다."""
        current = self._clock() if now is None else now
        with self._lock:
            if self._mode is LineFollowMode.OFF or self._hold_s is None:
                return False
            self._hold_until = float(current) + self._hold_s
            return True

    def _update_intended(self, guard: Optional[str], cap: float) -> None:
        """의도 조향(지금 관측이 시킬 명령)."""
        observation = self._observation
        if (observation is not None and observation.visible and observation.error is not None
                and observation.source is self._mode):
            linear, angular, _ = self._steer(observation, guard, cap)
            self._intended = (linear, angular)

    def _path_clearance(self) -> Optional[float]:
        """몸 기하가 없을 때(D-344 §11 보강): 의도 호 둘레 띠, LiDAR 원점 기준."""
        linear, angular = self._intended
        return path_clearance(
            self._scan_points or (), linear=linear, angular=angular,
            half_width_m=self._config.obstacle_corridor_half_width_m,
            horizon_m=self._config.obstacle_path_horizon_m,
            window_m=self._config.sector_resume_m,
            near_m=self._config.sector_stop_m)

    def _below_lane_auto_level(self) -> bool:
        floor = self._config.lane_auto_min_manual_angular
        if floor <= 0.0 or self._angular_ceiling is None:
            return False
        try:
            ceiling = self._angular_ceiling()
        except Exception:  # noqa: BLE001 — 읽을 수 없으면 계단을 모른다: 멈춘다
            return True
        return not _finite(ceiling) or float(ceiling) < floor - 1e-9

    def _camera_turning_in_place(self, cap: float) -> bool:
        """D-344 §12 개정: the fresh camera command turns with linear under ir_guard_min_linear."""
        observation = self._observation
        if (self._config.ir_guard_min_linear <= 0.0 or observation is None or not observation.visible
                or observation.error is None or observation.confidence < self._config.min_confidence):
            return False
        return self._steer(observation, None, cap)[0] < self._config.ir_guard_min_linear

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
        if (not observation.visible or observation.error is None
                or observation.confidence < self._config.min_confidence):
            return "clear"
        if observation.error <= -self._config.ir_guard_edge_error:
            return "left"
        if observation.error >= self._config.ir_guard_edge_error:
            return "right"
        return "centre"

    def _lost_resumed(self, now: float, guard: Optional[str]) -> bool:
        """D-407 개정 2026-10-10: a CAMERA_LINE LOST unlatches in the same mode once the lane is back."""
        config = self._config
        count, since = self._resume_streak
        if (self._mode is not LineFollowMode.CAMERA_LINE or not config.lost_auto_resume
                or guard not in (None, "clear") or self._invalid_observation
                or count < config.lost_resume_frames or since is None or self._received_at is None
                or now - since < config.lost_resume_s
                or not 0.0 <= now - self._received_at <= config.stale_after_s):
            return False
        self._lost_latched = False
        self._loss_started_at = None
        self._events.publish(
            "nav.lane_reacquired", source="line_follow_manager",
            data={"mode": self._mode.value, "frames": count, "since_s": round(now - since, 3)},
        )
        return True

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
            **self._gap_status,
        )
        return LineFollowDecision(
            generation=self._generation,
            evidence_revision=self._evidence_revision,
            mode=self._mode,
        )


__all__ = ["LineFollowHelpersMixin", "Point"]
