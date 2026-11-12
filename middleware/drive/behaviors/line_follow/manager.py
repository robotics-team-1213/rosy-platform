"""NAV-007 / D-143 line-follow selection and fail-closed control policy."""

from __future__ import annotations

import dataclasses
import math  # noqa: F401 — re-exported
import threading
import time
from typing import Callable, Optional

from core_common.protocol.schemas import LineCrosswalkStatus, LineFollowStatus
from core_features.decision.contract import DecisionRequest
from core_features.decision.lane import FOLLOW, LANE_ACTIONS, STOP, lane_recovery_rule
from core_features.line_follow.arc.lane_arc import ArcMixin
from core_features.line_follow.authority import AuthorityMixin
from core_features.line_follow.body_stop import BodyStopMixin
from core_features.line_follow.clearance import Point, path_clearance  # noqa: F401 — re-exported
from core_features.line_follow.crosswalk.gate import CrosswalkGateMixin
from core_features.line_follow.crosswalk.report import CrosswalkReportMixin
from core_features.line_follow.cue.lane_cue import LaneCueMixin
from core_features.line_follow.manager_helpers import LineFollowHelpersMixin
from core_features.line_follow.model import (  # noqa: F401 — re-exported
    LineFollowConfig,
    LineFollowDecision,
    LineFollowMode,
    LineObservation,
    SOURCE_FUTURE_TOLERANCE_S,
    _finite,
)
from core_features.line_follow.recovery.junction.gate import JunctionMixin
from core_features.line_follow.recovery.lane_return_wiring import LaneReturnMixin
from core_features.line_follow.recovery.stuck.realign.mixin import RealignMixin
from core_features.line_follow.recovery.stuck.stuck_wiring import StuckRecoveryMixin
from core_features.line_follow.route_context import (  # noqa: F401 — re-exported
    route_context as build_route_context,
)
from core_features.safety.velocity import same_curve


class LineFollowManager(
    LineFollowHelpersMixin,
    RealignMixin,
    LaneCueMixin,
    BodyStopMixin,
    StuckRecoveryMixin,
    AuthorityMixin,
    LaneReturnMixin,
    JunctionMixin,
    ArcMixin,
    CrosswalkGateMixin,
    CrosswalkReportMixin,
):
    def __init__(self, events, *, config: Optional[LineFollowConfig] = None,
                 clock: Callable[[], float] = time.monotonic,
                 angular_ceiling: Optional[Callable[[], float]] = None) -> None:
        self._events = events
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
        self._hold_s: Optional[float] = None
        self._hold_until: Optional[float] = None
        self._clearance: Optional[float] = None
        self._clearance_at: Optional[float] = None
        self._obstacle_blocked = False
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
        self._init_lane_cue()  # D-511 (cue/lane_cue.py)
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
            self._regulated_wait_sample = None
            self._init_lane_cue()  # D-430 review 10: a mode change (and E-stop) drops the cue and its latch
            self._generation += 1
            self._mode = selected
            self._observation = None
            self._intended = (self._config.cruise_speed, 0.0)
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

    def status(self) -> LineFollowStatus:
        with self._lock:
            zone = self._crosswalk_view(self._clock())  # D-573 6 개정 2026-10-10: gate on or off
            return self._status.model_copy(update={'crosswalk': None if zone is None else LineCrosswalkStatus(**zone),
                                                   'crosswalk_reported': True, 'junction': self._junction_status(),
                                                   'arc': self._arc_status(),
                                                   'lane_cue': self._lane_cue_view(self._clock()),
                                                   'regulation_wait': None if self._mode is LineFollowMode.OFF
                                                   else self._regulation_wait(self._clock()),  # D-760 rev 3 9
                                                   **({'reason': self._cue_latch} if self._cue_latch
                                                      and self._status.state == 'HOLD' else {}),
                                                   'route_context': self._route_context_current,
                                                   'route_context_published_at_s':
                                                   self._route_context_published_at_s})

    def apply_if_current(self, decision: LineFollowDecision,
                         apply: Callable[[LineFollowDecision], None]) -> bool:
        """Apply a decision only while its mode and sensor evidence stay current."""
        with self._lock:
            if (decision.generation != self._generation
                    or decision.evidence_revision != self._evidence_revision
                    or decision.mode is not self._mode
                    or self._mode is LineFollowMode.OFF):
                return False
            if ((isinstance(self._bridge, dict) or (self._return_controller is not None
                    and self._return_controller.phase != 'tracking'))
                    and (decision.linear or decision.angular)
                    and not self._return_submission_valid(self._clock(), decision)):
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
            self._checked_line_curve = None
            try:
                decision = self._tick_locked(current)
                self._feed_return_trail(current)
                if self._cue_spot_turning:
                    self._still_since = None
                    return self._crosswalk_gate(current, self._authority_gate(current, decision))
                if decision is self._arc_out:
                    self._still_since = None
                    return self._crosswalk_gate(current, self._authority_gate(current, decision))
                if (self._mode is LineFollowMode.CAMERA_LINE and self._observation is not None
                        and self._observation.quality_reason in ('low_light', 'overexposed', 'odom_side_conflict')):
                    self._recovery_reset('camera_' + self._observation.quality_reason, current)
                    self._end_bridge()
                    return self._crosswalk_gate(current, self._authority_gate(
                        current, self._junction_gate(current, decision)))
                original = decision
                local = self._apply_lane_return(current, decision)
                if local is not None:
                    self._local_owned_tick(current)
                decision = self._crosswalk_gate(current, self._authority_gate(current, self._junction_gate(
                    current, local if local is not None else self._apply_recovery(current, decision))))
                proof = self._checked_line_curve
                if proof is not None and (decision.linear or decision.angular) and (
                        (local is not None and local is not original)
                        or decision.mode is not LineFollowMode.CAMERA_LINE
                        or (decision.generation, decision.evidence_revision) != proof[1:]
                        or not same_curve(proof[0], (decision.linear, decision.angular))):
                    return self._stop_decision("HOLD", "motion_unconfirmed")
                return self._signal_committed(decision)
            finally:
                self._checked_line_curve = None
                if not self._path_evaluated:
                    self._clear_since = None

    def _tick_locked(self, current: float) -> LineFollowDecision:
        self._cue_spot_turning = False
        if self._mode is LineFollowMode.OFF:
            return self._stop_decision("OFF", "mode_off")
        if self._hold_until is not None and current > self._hold_until:
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
        arc = self._arc_tick(current)
        if arc is not None:
            return arc
        cap = self._angular_cap()
        if cap <= 0.0:
            return self._stop_decision("HOLD", "angular_limit_zero")
        if self._below_lane_auto_level():
            return self._stop_decision("HOLD", "limit_level_too_low")
        if (self._mode is LineFollowMode.CAMERA_LINE and self._observation is not None
                and self._observation.quality_reason in ('low_light', 'overexposed', 'odom_side_conflict')):
            age = None if self._received_at is None else current - self._received_at
            if self._lost_latched:
                return self._stop_decision("LOST", "camera_reselection_required", age)
            return self._loss_or_stop(current, "HOLD", self._observation.quality_reason, age)
        guard = None
        if self._mode is LineFollowMode.CAMERA_LINE and self._config.ir_guard_enabled:
            guard = self._ir_guard(current)
            if self._crosswalk_rest(current, guard):
                guard = "crosswalk"
            elif guard == "centre" and self._centre_on_cross_line(current):
                guard = "cross_line"
        cue = None
        if self._mode is LineFollowMode.CAMERA_LINE and self._config.fleet_lane_cue_enabled:
            cue = self._lane_cue_plan(current, cap)
            if cue is not None and cue[0] == "hold":
                return self._stop_decision("HOLD", cue[1])
            if cue is not None and cue[0] == "side" and guard in (None, "clear"):
                guard = "cue_" + cue[1]
        if self._clearance_at is not None:
            if current - self._clearance_at > self._config.clearance_stale_s:
                self._clear_gap()
                return self._stop_decision("HOLD", "obstacle_sensor_stale")
            if self._scan_points is not None and self._observation is not None:
                self._update_intended(guard, cap)
                if cue is not None and cue[0] == "turn":
                    self._intended = (0.0, cue[1])
                if self._config.body_stop_known:
                    observation = self._observation
                    normal_curve = (self._curve_preserving_envelope
                        and self._mode is LineFollowMode.CAMERA_LINE and cue is None
                        and guard in (None, "clear") and not self._lost_latched
                        and self._config.obstacle_mode == "path"
                        and self._junction is None and self._bridge is None
                        and self._recovery.phase is None
                        and (self._return_controller is None or self._return_controller.phase == "tracking")
                        and observation.source is self._mode and observation.visible
                        and observation.error is not None
                        and observation.confidence >= self._config.min_confidence
                        and 0 <= current - self._clearance_at <= self._config.clearance_stale_s
                        and self._received_at is not None
                        and 0 <= current - self._received_at <= self._config.stale_after_s)
                    self._set_clearance(*self._body_clearance(current, preserve_curvature=normal_curve))
                else:
                    self._clear_gap()
                    self._set_clearance(self._path_clearance(), current)
                self._path_evaluated = True
            if self._obstacle_blocked:
                return self._obstacle_hold(current)
        self._blocked_since = None
        self._escalated = False
        spot = cue is not None and cue[0] == "turn" and self._lane_cue_spot_running(current)
        if guard is not None:
            if guard == "stale":
                return self._stop_decision("HOLD", "lane_guard_stale")
            if guard == "centre" and not spot and not self._camera_turning_in_place(cap):
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
            return self._lane_cue_turn(cue)
        error = float(observation.error)
        linear, angular, reason = self._steer(observation, guard, cap)
        if self._checked_line_curve is not None:
            linear, angular = self._checked_line_curve[0]
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
