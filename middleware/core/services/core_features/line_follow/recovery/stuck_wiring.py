"""D-407 glue between LineFollowManager and the ROS-free StuckRecovery machine.

A mixin so manager.py keeps one lock owner and stays under the P6 file budget. Every
method here runs under ``self._lock`` (the manager's RLock). The back-off is returned as
the manager's own ``LineFollowDecision``, so it reaches the wheels only through the
existing CORE line-follow -> CommandManager path (D-2); there is no new publisher.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Callable, Optional

from core_common.protocol.schemas import LineStuckStatus
from core_common.robot_body import ScanView, RobotBody
from core_features.line_follow.clearance import (Point, body_clearances, body_envelope_gap,
                                                 self_mask_rear_blind_m)
from core_features.line_follow.model import LineFollowDecision, LineFollowMode
from core_features.line_follow.recovery.junction.gate import MANEUVER
from core_features.line_follow.recovery.stuck_recovery import ForwardTrail, StuckInput, StuckRecovery

#: Providers CORE binds at start (core/line_follow_wiring.py). Unbound or failing ones read as
#: the fail-closed default: no console link, a calibration session, a zero linear limit.
_PROVIDERS = {"console_linked": False, "calibration_active": True,
              "linear_ceiling": 0.0, "preview_seq": None}


class StuckRecoveryMixin:
    def _init_recovery(self) -> None:
        self._recovery = StuckRecovery(self._events, self._config)
        self._recovery_providers: dict[str, Callable[[], object]] = {}
        self._body_points: Optional[tuple[Point, ...]] = None
        self._body_at: Optional[float] = None
        self._range_min: Optional[float] = None
        self._return_view: Optional[ScanView] = None
        self._return_at: Optional[float] = None
        self._return_source_age: Optional[float] = None
        self._return_source_high_water_ns: Optional[int] = None
        self._trail = ForwardTrail()
        self._still_since: Optional[float] = None  # zero base command since (stuck_report_s)

    def bind_recovery(self, **providers: Callable[[], object]) -> None:
        unknown = set(providers) - set(_PROVIDERS)
        if unknown or not all(callable(fn) for fn in providers.values()):
            raise ValueError(f"unknown or non-callable recovery providers: {sorted(unknown)}")
        with self._lock:
            self._recovery_providers.update(providers)

    def observe_body_points(self, points, *, range_min: Optional[float],
                            received_at: Optional[float] = None) -> None:
        """All self-masked scan points (LiDAR origin, x forward) for D-407 body clearances.

        range_min None (not reported) leaves the rear blind band unknown: no back-off.
        """
        now = self._clock() if received_at is None else received_at
        with self._lock:
            self._body_points = tuple((float(x), float(y)) for x, y in points)
            self._body_at = float(now)
            self._range_min = None if range_min is None else max(0.0, float(range_min))

    def observe_return_scan(self, view, *, source_age_s: Optional[float],
                            source_stamp_ns: Optional[int], received_at: float) -> None:
        """Store validated body-frame scan plus source age; unknown rays stay unknown."""
        with self._lock:
            fresh_sequence = (type(source_stamp_ns) is int and source_stamp_ns >= 0
                and (self._return_source_high_water_ns is None
                     or source_stamp_ns > self._return_source_high_water_ns))
            if fresh_sequence:
                self._return_source_high_water_ns = source_stamp_ns
            self._return_view = view if isinstance(view, ScanView) and fresh_sequence else None
            self._return_at = float(received_at)
            self._return_source_age = source_age_s

    def return_body_clear(self, now: float, linear: float, angular: float) -> bool:
        """D-468 candidate sweep over the latest body-referenced LiDAR returns.

        The caller separately checks the calibrated live floor/control policy. This check only
        admits the short local-return motion when the current scan is fresh and its measured
        points do not intersect the swept footprint plus stopping margin.
        """
        with self._lock:
            c = self._config
            values = (now, linear, angular, self._return_at, self._return_source_age,
                      c.body_lidar_x_m, c.body_front_x_m, c.body_rear_x_m,
                      c.body_half_width_m, c.body_rotation_radius_m)
            if (self._return_view is None
                    or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)):
                return False
            envelope = self._envelope()
            if envelope is None:
                return False
            max_linear, max_angular, scale_floor = envelope
            if abs(linear) > max_linear or abs(angular) > max_angular:
                return False
            age = now - self._return_at + self._return_source_age
            if age < 0.0 or age > min(c.clearance_stale_s, .25):
                return False
            points = self._return_view.points
            if not points or any(not all(math.isfinite(v) for v in p) for p in points):
                return False
            body = RobotBody(front_x_m=c.body_front_x_m,rear_x_m=c.body_rear_x_m,
                half_width_m=c.body_half_width_m,rotation_radius_m=c.body_rotation_radius_m,
                lidar_x_m=c.body_lidar_x_m,margin_m=c.obstacle_body_margin_m)
            horizon = min(c.obstacle_path_horizon_m, max(.15, c.recovery_back_m))
            # Use immutable configured maxima: the live cap may have been lowered after
            # the scan, but that cannot undo motion already performed since its source pose.
            age_pad = c.max_linear * age + c.body_rotation_radius_m * c.max_angular * age
            margin = c.obstacle_body_margin_m + c.derived_stop_gap_m(abs(linear))
            if abs(linear) <= 1e-6:
                return body.rotation_reason(self._return_view, margin + age_pad) is None
            if body.unknown_blocks(self._return_view, reverse=linear < 0,
                                   pad_m=body.sweep_pad_m + age_pad):
                return False
            body_points = list(points)
            if linear < 0.0:
                body_points = [(-x, -y) for x, y in body_points]
                front_x, rear_x = -c.body_rear_x_m, -c.body_front_x_m
            else:
                front_x, rear_x = c.body_front_x_m, c.body_rear_x_m
            # The scan is expressed at its source pose. Inflate every footprint axis by
            # maximum possible translation plus yaw displacement since that pose.
            front_x += age_pad
            rear_x -= age_pad
            half_width = c.body_half_width_m + age_pad
            gap = body_envelope_gap(body_points, linear=abs(linear), angular=angular,
                scale_floor=scale_floor, front_x_m=front_x,
                rear_x_m=rear_x, half_width_m=half_width,
                rotation_radius_m=c.body_rotation_radius_m + age_pad, horizon_m=horizon)
            return gap is None or gap > margin

    @property
    def wants_body_points(self) -> bool:
        """Sector mode: build body points only while a stuck is open or could open soon."""
        with self._lock:
            return (self._mode is not LineFollowMode.OFF
                    and (self._recovery.stuck_id is not None or self._obstacle_blocked
                         or self._still_since is not None
                         or self._lost_latched or self._loss_started_at is not None))

    @property
    def wants_return_scan(self) -> bool:
        """Keep full scan evidence current throughout local lane reacquisition."""
        with self._lock:
            return (self._mode is LineFollowMode.CAMERA_LINE
                    and self._config.recovery_local_enabled
                    and self._return_controller is not None
                    and self._return_controller.phase != "tracking")

    def note_issued(self, linear: float, angular: float, now: float) -> None:
        """The twist CORE actually handed the CommandManager (after the traffic gate)."""
        with self._lock:
            self._trail.record(now, linear, angular)

    def _recovery_reset(self, reason: str, now: float) -> None:
        self._recovery.reset(reason, now)
        self._trail.clear()
        self._still_since = None

    def stuck_decision(self, stuck_id: str, decision: str, *, by: str,
                       principal_ref: Optional[str] = None, now: Optional[float] = None,
                       yield_m: Optional[float] = None, yield_turn_rad: Optional[float] = None) -> str:
        """Console answer (D-407 §2). Raises AnswerRefused; returns hold|back|resume|manual|idle|yield."""
        current = float(self._clock() if now is None else now)
        with self._lock:
            outcome = self._recovery.answer(
                current, stuck_id, decision, by, principal_ref,
                yield_m=yield_m, yield_turn_rad=yield_turn_rad)
            # Any accepted answer outdates a twist computed before it (e.g. a back-off
            # before WAIT): apply_if_current then rejects it (review L1).
            self._evidence_revision += 1
            if outcome == "resume":
                self._release_stuck(current)
            elif outcome in ("manual", "idle"):
                # Stop under the same lock, so no tick can reopen a stuck before the
                # caller's mode transition (review L3).
                self.set_mode(LineFollowMode.OFF)
            self._status = self._status.model_copy(update={"stuck": self._stuck_status(current)})
            return outcome

    def _stuck_status(self, now: float) -> Optional[LineStuckStatus]:
        stuck = self._recovery.status(now)
        return None if stuck is None else LineStuckStatus(**stuck)

    def _provided(self, name: str):
        provider = self._recovery_providers.get(name)
        if provider is None:
            return _PROVIDERS[name]
        try:
            return provider()
        except Exception:  # noqa: BLE001 - an unreadable input fails closed
            return _PROVIDERS[name]

    def _release_stuck(self, now: float) -> None:
        """RESUME / recovered: lift the obstacle latch once (re-blocks below the stop distance)."""
        if self._return_controller is not None and self._return_controller.phase == 'fleet':
            self._return_controller.restart_verification(now)
        self._obstacle_blocked = False
        self._clear_since = None
        self._blocked_since = None
        self._escalated = False
        if self._lost_latched:
            self._lost_latched = False
            self._loss_started_at = now

    def _rear_state(self, known: bool, rear_m: Optional[float], now: float) -> str:
        fresh = (self._body_points is not None and self._body_at is not None
                 and now - self._body_at <= self._config.clearance_stale_s)
        if not known or not fresh:
            return "unknown"
        if rear_m is not None and rear_m <= self._config.recovery_rear_clear_m:
            return "blocked"
        return "clear"

    def _rear_clear_now(self) -> bool:
        """D-344 §12 개정 2: the body's rear strip is seen clear right now (fresh scan, URDF body)."""
        config = self._config
        if not config.body_geometry_known or self._body_points is None:
            return False
        rear = body_clearances(self._body_points, lidar_x_m=config.body_lidar_x_m or 0.0,
                               rear_x_m=config.body_rear_x_m, half_width_m=self._rear_half_width())["rear_m"]
        return self._rear_state(True, rear, self._clock()) == "clear"

    def _rear_half_width(self) -> float:
        config = self._config
        if config.body_half_width_m is None:
            return config.obstacle_corridor_half_width_m
        return config.body_half_width_m + config.recovery_rear_lateral_margin_m

    def _stuck_input(self, now: float) -> StuckInput:
        config = self._config
        known = config.body_geometry_known
        lidar_x = config.body_lidar_x_m or 0.0
        rear_x = config.body_rear_x_m if known else -1.0
        seen = {"front_band_m": None, "rear_m": None, "turn_m": None}
        if self._body_points is not None:
            seen = body_clearances(
                self._body_points, lidar_x_m=lidar_x, rear_x_m=rear_x,
                half_width_m=config.obstacle_corridor_half_width_m,
                rotation_radius_m=config.body_rotation_radius_m if known else None)
            # Behind the robot only the body's own width (+ margin) matters: the wider path
            # band counted side walls as "behind" (Gazebo 2026-10-02).
            seen["rear_m"] = body_clearances(
                self._body_points, lidar_x_m=lidar_x, rear_x_m=rear_x,
                half_width_m=self._rear_half_width())["rear_m"]
        front = seen["front_band_m"]
        front_stop = None
        if self._gap_resume is not None and config.body_stop_known:
            # D-422: the body gap along the intended path decides; the straight band is only
            # reported (and bounds RESUME at the stop gap seen from the LiDAR).
            front_clear = self._clearance is None or self._clearance >= self._gap_resume
            front_stop = (self._gap_status.get("stop_gap_m") or 0.0) + (
                config.body_front_x_m - config.body_lidar_x_m)
        else:
            front_clear = ((front is None or front >= config.sector_resume_m)
                           and (self._clearance is None or self._clearance >= config.sector_resume_m))
        obs = self._observation
        age = None if self._received_at is None else now - self._received_at
        lane = bool(obs is not None and obs.visible and obs.source is self._mode
                    and obs.confidence >= config.min_confidence and not self._invalid_observation
                    and age is not None and 0.0 <= age <= config.stale_after_s)
        # From the latches, not the reported state: a transient HOLD (stale LiDAR, ladder
        # limit) must not read as "cleared" and reset the attempts (review H1).
        crosswalk = self._crosswalk_report()  # D-573 4: before any other cause
        if crosswalk is None and self._escalated and self._crosswalk_armed():
            # The gate owns the robot near an armed crosswalk: an obstacle stop there is a person,
            # never a local back-off and re-approach (Gazebo baseline 2026-10-10).
            crosswalk = "person_present"
        cause = ("crosswalk_blocked" if crosswalk is not None else "obstacle_ahead" if self._escalated
                 else "lane_lost" if self._lost_latched else None)
        detail = crosswalk
        report_s = config.stuck_report_s
        if (cause is None and report_s > 0.0 and self._still_since is not None
                and now - self._still_since >= report_s):
            # 2026-10-10 user: any reason the robot stays still this long goes to Fleet.
            cause, detail = "no_motion", self._status.reason
        ceiling = self._provided("linear_ceiling")
        blind = None
        if known and self._range_min is not None:
            blind = max(0.0, self._range_min - (lidar_x - rear_x), self_mask_rear_blind_m(
                config.lidar_self_mask, lidar_x_m=lidar_x, rear_x_m=rear_x,
                half_width_m=self._rear_half_width()))
        trail_m, trail_yaw = self._trail.measure(now, config.recovery_trail_s)
        last_forward = self._trail.last_forward_at()
        recovered_at = self._recovery.recovered_at
        moved = None if recovered_at is None else self._trail.net_since(recovered_at, now)
        return StuckInput(
            now=now, cause=cause, cause_detail=detail, lane_visible=lane, front_clear=front_clear,
            front_band_m=front, front_stop_m=front_stop,
            rear_m=seen["rear_m"] if known else None, turn_m=seen["turn_m"],
            rear_blind_m=blind, trail_m=trail_m, trail_yaw_deg=trail_yaw,
            trail_age_s=None if last_forward is None else round(now - last_forward, 3),
            scan_age_s=None if self._body_at is None else now - self._body_at,
            lidar_expected=self._clearance_at is not None,
            moved_since_recovery_m=moved,
            rear_state=self._rear_state(known, seen["rear_m"] if known else None, now),
            geometry_known=known,
            console_linked=self._provided("console_linked") is True,
            calibration_active=self._provided("calibration_active") is not False,
            linear_ceiling=float(ceiling) if isinstance(ceiling, (int, float)) else 0.0,
            last_lane=None if obs is None else {
                "source": obs.source.value, "visible": obs.visible, "error": obs.error,
                "confidence": obs.confidence, "age_s": None if age is None else round(age, 3)},
            preview_seq=self._provided("preview_seq"),
        )

    def _apply_recovery(self, now: float, decision: LineFollowDecision) -> LineFollowDecision:
        if self._mode is LineFollowMode.OFF:
            return decision
        junction = self._junction  # a D-495 maneuver supplies its own twist after this (gate.py)
        if (abs(decision.linear) > 1e-6 or abs(decision.angular) > 1e-6
                or junction is not None and junction.get("state") in MANEUVER):
            self._still_since = None
        elif self._still_since is None:
            self._still_since = now
        action = self._recovery.step(self._stuck_input(now))
        if action.kind == "resume":
            self._release_stuck(now)
            self._still_since = None
        update: dict = {"stuck": self._stuck_status(now)}
        if action.kind == "pass":
            self._status = self._status.model_copy(update=update)
            return decision
        if action.kind == "back":
            update.update(state="RECOVERING", reason="stuck_back_off",
                          linear=action.linear, angular=0.0)
        elif action.kind == "yield":
            update.update(state="RECOVERING", reason="stuck_yield",
                          linear=action.linear, angular=action.angular)
        elif decision.linear != 0.0 or decision.angular != 0.0 or action.kind == "resume":
            phase = (self._recovery.phase or "resumed").lower()
            update.update(state="HOLD", reason=f"stuck_{phase}", linear=0.0, angular=0.0)
        self._status = self._status.model_copy(update=update)
        angular = action.angular if action.kind == "yield" else 0.0
        return dataclasses.replace(decision, linear=action.linear, angular=angular)
