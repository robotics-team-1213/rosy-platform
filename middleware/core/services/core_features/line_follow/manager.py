"""NAV-007 / D-143 line-follow selection and fail-closed control policy."""

from __future__ import annotations

import dataclasses
import math
import threading
import time
from typing import Callable, Optional

from core_common.protocol.schemas import LineCrosswalkStatus, LineFollowStatus
from core_features.line_follow.authority import AuthorityMixin
from core_features.line_follow.arc.lane_arc import ArcMixin
from core_features.line_follow.body_stop import BodyStopMixin
from core_features.line_follow.crosswalk_gate import CrosswalkGateMixin
from core_features.line_follow.cue.lane_cue import LaneCueMixin
from core_features.line_follow.crosswalk_report import CrosswalkReportMixin
from core_features.line_follow.clearance import Point, path_clearance
from core_features.line_follow.recovery.junction.gate import JunctionMixin
from core_features.line_follow.recovery.stuck_wiring import StuckRecoveryMixin
from core_features.line_follow.recovery.lane_return_wiring import LaneReturnMixin
from core_features.line_follow.route_context import route_context as build_route_context
from core_features.line_follow.model import (  # noqa: F401 — re-exported
    LineFollowConfig,
    LineFollowDecision,
    LineFollowMode,
    LineObservation,
    SOURCE_FUTURE_TOLERANCE_S,
    _finite,
)
from core_features.decision.contract import DecisionRequest
from core_features.decision.lane import FOLLOW, LANE_ACTIONS, STOP, lane_recovery_rule


class LineFollowManager(LaneCueMixin, BodyStopMixin, StuckRecoveryMixin, AuthorityMixin, LaneReturnMixin, JunctionMixin,
                        ArcMixin, CrosswalkGateMixin, CrosswalkReportMixin):
    def __init__(self, events, *, config: Optional[LineFollowConfig] = None,
                 clock: Callable[[], float] = time.monotonic,
                 angular_ceiling: Optional[Callable[[], float]] = None) -> None:
        self._events = events
        # D-344 §13: 살아 있는 수동 각속도 한도(D-342 계단). 관리자 API 로 바뀌면 바로 따른다.
        self._angular_ceiling = angular_ceiling
        self._lock = threading.RLock()
        self._config = config or LineFollowConfig()
        self._lidar_forward_source = "line_follow lidar_forward_deg (config)"
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
        self._resume_streak: tuple[int, Optional[float]] = (0, None)  # D-407 개정 2026-10-10
        self._invalid_observation = False
        self._status = LineFollowStatus()
        self._route_context_current = None
        self._route_context_published_at_s = None
        # D-344 §8: 운전자 확인 만료. hold_s 가 있으면 hold() 가 그 안에 계속 와야 한다.
        self._hold_s: Optional[float] = None
        self._hold_until: Optional[float] = None
        # D-344 §11: 정면 LiDAR 여유 거리. 한 번도 안 왔으면 판정하지 않는다(LiDAR 없는 벤치).
        self._clearance: Optional[float] = None
        self._clearance_at: Optional[float] = None
        self._obstacle_blocked = False
        # path 판정용 로봇 좌표 점. 있으면 틱마다 의도 조향의 호로 여유 거리를 다시 잰다.
        self._scan_points: Optional[tuple[Point, ...]] = None
        self._intended: tuple[float, float] = (self._config.cruise_speed, 0.0)
        self._clear_since: Optional[float] = None
        self._path_evaluated = False
        self._blocked_since: Optional[float] = None
        self._escalated = False
        self._init_body_stop()  # D-422 (body_stop.py)
        self._init_recovery()  # D-407 (stuck_wiring.py)
        self._init_lane_return()  # D-468 source-time odometry and corridor evidence.
        self._init_junction()  # D-494 decision 4 (junction.py)
        self._init_arc()  # D-520 (arc/lane_arc.py)
        self._init_authority()  # D-517 4 (authority.py)
        self._init_crosswalk_gate()  # D-573 (crosswalk_gate.py)
        self._init_lane_cue()  # D-511 rev 1/2 (lane_cue.py)
        self._cue_spot_turning = False
        self._init_crosswalk_report()  # D-573 6 (crosswalk_report.py)

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
    def lidar_forward_source(self) -> str:
        return self._lidar_forward_source

    def use_lidar_forward(self, forward_deg: float, source: str) -> None:
        """Bind the LiDAR mount yaw resolved at startup (core/lidar_mount.py, D-47 addendum)."""
        with self._lock:
            self._config = dataclasses.replace(self._config, lidar_forward_deg=float(forward_deg))
            self._lidar_forward_source = str(source)

    @property
    def active(self) -> bool:
        with self._lock:
            return self._mode is not LineFollowMode.OFF

    def set_mode(self, mode: LineFollowMode | str,
                 hold_s: Optional[float] = None, *, reason: Optional[str] = None) -> LineFollowStatus:
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
            default = "mode_off" if selected is LineFollowMode.OFF else "mode_changed"
            self._recovery_reset(reason or default, self._clock())
            self._reset_lane_return()
            self._reset_junction()
            self._reset_arc(reason or default)
            self._init_authority()
            self._xwalk.reset()
            self._init_lane_cue()  # D-430 review 10: a mode change (and E-stop) drops the cue and its latch
            self._generation += 1
            self._mode = selected
            self._observation = None
            self._intended = (self._config.cruise_speed, 0.0)
            # 앞 물체 상태는 세션마다 새로 — 다시 고른 뒤의 정지는 다시 알린다. sector 는 마지막
            # 거리가 재출발 거리 안이면 막힌 채로 시작한다(다음 스캔 전 한 틱도 그냥 가지 않게).
            self._obstacle_blocked = (self._scan_points is None and self._clearance is not None
                                      and self._clearance < self._config.sector_resume_m)
            self._reset_body_stop()
            self._clear_since = None
            self._blocked_since = None
            self._escalated = False
            self._received_at = None
            self._lost_latched = False
            self._resume_streak = (0, None)
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

    def stop(self, reason: str = "mode_off") -> LineFollowStatus:
        """reason: why an open D-407 stuck closes (e.g. "estop" from the safety listener)."""
        return self.set_mode(LineFollowMode.OFF, reason=reason)

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
            if source_age < -SOURCE_FUTURE_TOLERANCE_S:
                raise ValueError("observation timestamp is in the future")
            effective_received_at -= max(0.0, source_age)
        with self._lock:
            if observation.source is LineFollowMode.IR_LINE:
                self._ir_observation = observation
                self._ir_received_at = effective_received_at
            if observation.source is not self._mode:
                return False
            if not self._observe_return_lane(observation, effective_received_at):
                return False  # Source-clock replay cannot refresh steering authority.
            self._invalid_observation = False
            self._observation = observation
            self._received_at = effective_received_at
            self._evidence_revision += 1
            if observation.visible and observation.confidence >= self._config.min_confidence:
                count, since = self._resume_streak
                self._resume_streak = (count + 1, effective_received_at if count == 0 else since)
                if not self._lost_latched:
                    self._loss_started_at = None
            else:
                self._resume_streak = (0, None)
                if self._loss_started_at is None:
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

    def status(self) -> LineFollowStatus:
        with self._lock:
            zone = self._crosswalk_view(self._clock())  # D-573 6 개정 2026-10-10: gate on or off
            return self._status.model_copy(update={'crosswalk': None if zone is None else LineCrosswalkStatus(**zone),
                                                   'crosswalk_reported': True, 'junction': self._junction_status(),
                                                   'arc': self._arc_status(),
                                                   'lane_cue': self._lane_cue_view(self._clock()),
                                                   'route_context': self._route_context_current,
                                                   'route_context_published_at_s':
                                                   self._route_context_published_at_s})

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

    def observe_scan_points(self, points, received_at: Optional[float] = None) -> None:
        """path 판정: 로봇 좌표(x 앞, y 왼쪽) 점. 여유 거리는 틱이 의도 조향으로 잰다."""
        now = self._clock() if received_at is None else received_at
        with self._lock:
            self._scan_points = tuple((float(x), float(y)) for x, y in points)
            self._clearance_at = float(now)
            self._remember_near(float(now))  # D-422: returns that slip under range_min

    def obstacle_gap(self, linear: float, angular: float, now: Optional[float] = None):
        """D-559: this obstacle judgement for another CORE mode's twist (swarm trail follow).

        (gap, stop, resume), gap None = nothing in the way; None = no fresh obstacle sensor.
        Path mode with the URDF body is the D-422 sweep; sector mode is the front distance.
        Line-follow's own intent and gap status are left as they were.
        """
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
        """여유 거리와 떨림 방지(stop < resume) 판정. 잠금 안에서 부른다.

        now 가 있으면(path) 막힘은 obstacle_release_s 동안 계속 비어 있어야 풀린다.
        stop/resume 이 없으면 LiDAR 원점 기준(sector_stop_m/sector_resume_m)이다. 몸에 닿은
        점(거리 0)은 정지 간격이 0 으로 줄어도 막힌다(D-422).
        """
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
        angular = max(-self._config.max_angular,
                      min(self._config.max_angular, -self._config.steering_gain * error))
        reason = "tracking"
        if guard in ("left", "right", "centre") and linear < self._config.ir_guard_min_linear:
            # D-344 §12 개정 2: turning in place with a line under the IR row: keep the camera turn and
            # creep backwards so the front swings away from the line instead of over it (the user's
            # forward/back manoeuvre). Rear not seen clear: turn in place only.
            if self._config.ir_guard_back_speed > 0.0 and self._rear_clear_now():
                linear = -self._config.ir_guard_back_speed
        elif guard in ("left", "right"):
            # 경계선이 왼쪽 IR 밑이면 오른쪽(음의 각속도, REP-103)으로 비킨다.
            turn = min(self._config.ir_guard_turn, self._config.max_angular)
            angular = -turn if guard == "left" else turn
            linear *= self._config.ir_guard_speed_scale
            reason = f"lane_edge_{guard}"
        elif guard in ("cue_left", "cue_right"):
            # D-511: Fleet says the lane centre is on that side; the IR edge turn toward it, no back-creep.
            turn = min(self._config.ir_guard_turn, self._config.max_angular)
            angular = turn if guard == "cue_left" else -turn
            linear *= self._config.ir_guard_speed_scale
            reason = f"fleet_{guard}"
        elif guard == "crosswalk":
            reason = "ir_guard_crosswalk"
        if abs(angular) > cap:
            # D-344 §13: 계단 상한으로 자를 때 선속도도 같은 비율로 — 같은 호를 더 천천히 돈다.
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
            if ((isinstance(self._bridge, dict) or (self._return_controller is not None
                    and self._return_controller.phase != 'tracking'))
                    and (decision.linear or decision.angular)
                    and not self._return_submission_valid(self._clock(),decision)):
                return False
            apply(decision)
            return True

    def tick(self, now: Optional[float] = None) -> LineFollowDecision:
        current = self._clock() if now is None else now
        if not _finite(current):
            raise ValueError("line-follow clock must be finite")
        current = float(current)
        with self._lock:
            self._path_evaluated = False
            try:
                decision = self._tick_locked(current)
                # D-468 trail feed; observe() still raises on an invalid epoch, as tick() did.
                self._feed_return_trail(current)
                if self._cue_spot_turning:  # D-511 rev 5: a turn-spot pivot; only D-517 4 / D-573 lower it
                    self._still_since = None
                    return self._crosswalk_gate(current, self._authority_gate(current, decision))
                if decision is self._arc_out:  # D-520: the arc owns this tick (no D-468/D-476/D-407,
                    self._still_since = None
                    # no junction gate); D-517 4 and D-573 only ever lower it
                    return self._crosswalk_gate(current, self._authority_gate(current, decision))
                if (self._mode is LineFollowMode.CAMERA_LINE and self._observation is not None
                        and self._observation.quality_reason in ('low_light', 'overexposed')):
                    self._recovery_reset('camera_' + self._observation.quality_reason, current)
                    self._end_bridge()  # D-476: invalid vision ends a bridge for good
                    # LOST also bypasses back-off. D-517 4: the authority gate only ever zeroes.
                    return self._crosswalk_gate(current, self._authority_gate(
                        current, self._junction_gate(current, decision)))
                local = self._apply_lane_return(current, decision)
                if local is not None:
                    self._still_since = None  # D-468 owns the tick: no_motion restarts
                return self._crosswalk_gate(current, self._authority_gate(current, self._junction_gate(
                    current, local if local is not None else self._apply_recovery(current, decision))))
            finally:
                if not self._path_evaluated:
                    # 풀림 지연은 연속으로 잰 틱만 센다 — LiDAR 끊김·계단 정지·OFF 틱이 끼면 처음부터.
                    self._clear_since = None

    def _tick_locked(self, current: float) -> LineFollowDecision:
        self._cue_spot_turning = False
        if self._mode is LineFollowMode.OFF:
            return self._stop_decision("OFF", "mode_off")
        if self._hold_until is not None and current > self._hold_until:
            # 운전자가 손을 뗐거나 링크가 끊겼다 — 스스로 내린다(D-344 §8).
            previous = self._mode
            self._generation += 1
            self._mode = LineFollowMode.OFF
            self._hold_s = None
            self._hold_until = None
            self._loss_started_at = None
            self._recovery_reset("driver_released", current)
            self._reset_arc("driver_released")
            self._events.publish(
                "nav.line_driver_released", source="line_follow_manager",
                data={"mode": previous.value},
            )
            return self._stop_decision("OFF", "driver_released")
        arc = self._arc_tick(current)  # D-520: a live arc ignores the keeper and its loss clock
        if arc is not None:
            return arc
        cap = self._angular_cap()
        if cap <= 0.0:
            # 조향할 수 없는데 선속도만 내면 차선을 벗어난다(D-344 §13).
            return self._stop_decision("HOLD", "angular_limit_zero")
        if self._below_lane_auto_level():
            # 차선 자동은 수동 한도 L1 이상에서만(D-344 §13, 사용자 결정).
            return self._stop_decision("HOLD", "limit_level_too_low")
        if (self._mode is LineFollowMode.CAMERA_LINE and self._observation is not None
                and self._observation.quality_reason in ('low_light', 'overexposed')):
            # Invalid vision cannot authorize obstacle back-off or remembered steering.
            age = None if self._received_at is None else current - self._received_at
            if self._lost_latched:
                return self._stop_decision("LOST", "camera_reselection_required", age)
            return self._loss_or_stop(current, "HOLD", self._observation.quality_reason, age)
        guard = None
        if self._mode is LineFollowMode.CAMERA_LINE and self._config.ir_guard_enabled:
            guard = self._ir_guard(current)
            if self._crosswalk_rest(current, guard):
                guard = "crosswalk"  # D-491: known crosswalk under the IR row
            elif guard == "centre" and self._centre_on_cross_line(current):
                guard = "cross_line"  # D-507 6: a straight crossing's measured cross line
        cue = None
        if self._mode is LineFollowMode.CAMERA_LINE and self._config.fleet_lane_cue_enabled:
            # D-511 rev 1/2: before the body stop so D-422 measures the twist the cue produces.
            cue = self._lane_cue_plan(current, cap)
            if cue is not None and cue[0] == "hold":
                return self._stop_decision("HOLD", cue[1])
            if cue is not None and cue[0] == "side" and guard in (None, "clear"):
                guard = "cue_" + cue[1]   # IR first: only an IR that sees no line takes Fleet's side
        if self._clearance_at is not None:
            # 앞 물체 정지는 차선 상실이 아니다 — LOST 로 누적하지 않고 치워지면 곧바로 간다.
            if current - self._clearance_at > self._config.clearance_stale_s:
                self._clear_gap()
                return self._stop_decision("HOLD", "obstacle_sensor_stale")
            if self._scan_points is not None and self._observation is not None:
                # 관측이 하나도 없으면 의도가 없다 — 재지 않고 WAITING 으로 둔다.
                self._update_intended(guard, cap)
                if cue is not None and cue[0] == "turn":
                    self._intended = (0.0, cue[1])   # D-422: a pivot is checked on its rotation circle
                if self._config.body_stop_known:
                    # D-422: 몸 윤곽이 의도 경로를 따라 쓸고 갈 때 첫 접촉까지의 거리.
                    self._set_clearance(*self._body_clearance(current))
                else:
                    self._clear_gap()
                    self._set_clearance(self._path_clearance(), current)
                self._path_evaluated = True
            if self._obstacle_blocked:
                return self._obstacle_hold(current)
        self._blocked_since = None
        self._escalated = False
        # D-511 rev 5: a turn-spot pivot that already turned runs through camera loss and LOST, with the
        # IR centre exemption (D-344 §12, turn spots only); the body stop ran above, the gates run after.
        spot = cue is not None and cue[0] == "turn" and self._lane_cue_spot_running()
        if guard is not None:
            # 차선 이탈 감시는 차선 상실이 아니다 — LOST 로 누적하지 않는다(D-344 §12).
            if guard == "stale":
                return self._stop_decision("HOLD", "lane_guard_stale")
            if guard == "centre" and not spot and not self._camera_turning_in_place(cap):
                # D-344 §12 개정: a camera turn in place sweeps the IR row ~0.03 m; it does not cross.
                return self._stop_decision("HOLD", "lane_departure")
        if spot:
            self._cue_spot_turning = True
            return self._lane_cue_turn(cue)
        if self._lost_latched and not self._lost_resumed(current, guard):
            reason = ("camera_reselection_required"
                      if self._mode is LineFollowMode.CAMERA_LINE
                      else "reselection_required")
            return self._stop_decision("LOST", reason)

        observation = self._observation
        age = None if self._received_at is None else current - self._received_at
        if (observation is not None and observation.ground == "NOMINAL"
                and self._hold_s is None):
            # 교정 없는 공칭 지면은 운전자가 누르고 있을 때만 쓴다(D-364 §3).
            return self._stop_decision("HOLD", "nominal_ground_requires_driver", age)
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
        if cue is not None and cue[0] == "turn":
            # After the LOST latch, NOMINAL ground and a fresh camera FOLLOW (D-430 review 3).
            return self._lane_cue_turn(cue)
        error = float(observation.error)
        linear, angular, reason = self._steer(observation, guard, cap)
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
            **self._gap_status,
        )
        return decision

    def _update_intended(self, guard: Optional[str], cap: float) -> None:
        """의도 조향(지금 관측이 시킬 명령). 실제 출력이 아니라 의도를 쓴다 — 멈춘 뒤 출력은 0 이라
        직진 호가 되어 모서리 벽에 영영 막힌다. 쓸 관측이 없으면 마지막 의도(처음이면 직진)."""
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
        if not observation.visible or observation.error is None                 or observation.confidence < self._config.min_confidence:
            return "clear"
        if observation.error <= -self._config.ir_guard_edge_error:
            return "left"
        if observation.error >= self._config.ir_guard_edge_error:
            return "right"
        return "centre"

    def _lost_resumed(self, now: float, guard: Optional[str]) -> bool:
        """D-407 개정 2026-10-10: a CAMERA_LINE LOST unlatches in the same mode once the lane is back.

        Reached only after the obstacle hold, a stale IR guard and an IR centre departure have
        already returned. Needs lost_resume_frames consecutive fresh confident camera frames
        spanning lost_resume_s and the IR guard clear (or off); E-stop, OFF and driver-hold loss
        still go through set_mode(OFF). The normal FOLLOW path below decides the twist.
        """
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
