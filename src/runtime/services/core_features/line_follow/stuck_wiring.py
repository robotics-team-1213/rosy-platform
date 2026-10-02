"""D-407 glue between LineFollowManager and the ROS-free StuckRecovery machine.

A mixin so manager.py keeps one lock owner and stays under the P6 file budget. Every
method here runs under ``self._lock`` (the manager's RLock). The back-off is returned as
the manager's own ``LineFollowDecision``, so it reaches the wheels only through the
existing CORE line-follow -> CommandManager path (D-2); there is no new publisher.
"""

from __future__ import annotations

import dataclasses
from typing import Callable, Optional

from core_common.protocol.schemas import LineStuckStatus
from core_features.line_follow.clearance import Point, body_clearances, self_mask_rear_blind_m
from core_features.line_follow.model import LineFollowDecision, LineFollowMode
from core_features.line_follow.stuck_recovery import ForwardTrail, StuckInput, StuckRecovery

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
        self._trail = ForwardTrail()

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

    @property
    def wants_body_points(self) -> bool:
        """Sector mode: build body points only while a stuck is open or could open soon."""
        with self._lock:
            return (self._mode is not LineFollowMode.OFF
                    and (self._recovery.stuck_id is not None or self._obstacle_blocked
                         or self._lost_latched or self._loss_started_at is not None))

    def note_issued(self, linear: float, angular: float, now: float) -> None:
        """The twist CORE actually handed the CommandManager (after the traffic gate)."""
        with self._lock:
            self._trail.record(now, linear, angular)

    def _recovery_reset(self, reason: str, now: float) -> None:
        self._recovery.reset(reason, now)
        self._trail.clear()

    def stuck_decision(self, stuck_id: str, decision: str, *, by: str,
                       token_id: Optional[str] = None, now: Optional[float] = None) -> str:
        """Console answer (D-407 §2). Raises AnswerRefused; returns hold|back|resume|manual|idle."""
        current = float(self._clock() if now is None else now)
        with self._lock:
            outcome = self._recovery.answer(current, stuck_id, decision, by, token_id)
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
        """RESUME / recovered: lift the obstacle latch once (re-blocks below obstacle_stop_m)."""
        self._obstacle_blocked = False
        self._clear_since = None
        self._blocked_since = None
        self._escalated = False
        if self._lost_latched:
            self._lost_latched = False
            self._loss_started_at = now

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
        front = seen["front_band_m"]
        front_clear = ((front is None or front >= config.obstacle_resume_m)
                       and (self._clearance is None or self._clearance >= config.obstacle_resume_m))
        obs = self._observation
        age = None if self._received_at is None else now - self._received_at
        lane = bool(obs is not None and obs.visible and obs.source is self._mode
                    and obs.confidence >= config.min_confidence and not self._invalid_observation
                    and age is not None and 0.0 <= age <= config.stale_after_s)
        # From the latches, not the reported state: a transient HOLD (stale LiDAR, ladder
        # limit) must not read as "cleared" and reset the attempts (review H1).
        cause = ("obstacle_ahead" if self._escalated
                 else "lane_lost" if self._lost_latched else None)
        ceiling = self._provided("linear_ceiling")
        blind = None
        if known and self._range_min is not None:
            blind = max(0.0, self._range_min - (lidar_x - rear_x), self_mask_rear_blind_m(
                config.lidar_self_mask, lidar_x_m=lidar_x, rear_x_m=rear_x,
                half_width_m=config.obstacle_corridor_half_width_m))
        trail_m, trail_yaw = self._trail.measure(now, config.recovery_trail_s)
        return StuckInput(
            now=now, cause=cause, lane_visible=lane, front_clear=front_clear,
            front_band_m=front, rear_m=seen["rear_m"] if known else None, turn_m=seen["turn_m"],
            rear_blind_m=blind, trail_m=trail_m, trail_yaw_deg=trail_yaw,
            scan_age_s=None if self._body_at is None else now - self._body_at,
            lidar_expected=self._clearance_at is not None,
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
        action = self._recovery.step(self._stuck_input(now))
        if action.kind == "resume":
            self._release_stuck(now)
        update: dict = {"stuck": self._stuck_status(now)}
        if action.kind == "pass":
            self._status = self._status.model_copy(update=update)
            return decision
        if action.kind == "back":
            update.update(state="RECOVERING", reason="stuck_back_off",
                          linear=action.linear, angular=0.0)
        elif decision.linear != 0.0 or decision.angular != 0.0 or action.kind == "resume":
            phase = (self._recovery.phase or "resumed").lower()
            update.update(state="HOLD", reason=f"stuck_{phase}", linear=0.0, angular=0.0)
        self._status = self._status.model_copy(update=update)
        return dataclasses.replace(decision, linear=action.linear, angular=0.0)
