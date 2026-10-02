"""D-422 body-referenced obstacle stop: a LineFollowManager mixin (keeps manager.py in budget).

The URDF body outline is swept along the intended lane arc (clearance.body_path_gap); in place,
the rotation radius (clearance.rotation_gap). Every method runs under the manager's
``self._lock`` except ``observe_ultrasonic`` and ``bind_motion_envelope``, which take it.

Review fixes (2026-10-02):
- The LiDAR blind-zone floor always applies; an ultrasonic echo only adds points (H1).
- Returns that slip under the LiDAR range_min are remembered in an odometry frame
  integrated from the twist that actually went to the wheels (note_wheels, fed by the one
  cmd_vel publisher), so a curved path or an in-place turn still sees them (H2, M2). They
  expire after obstacle_path_horizon_m of body motion; any wheel output that is not line
  follow's own (teleop, docking, e-stop, another mode) forgets them (re-review HIGH 1).
- The sweep covers the arcs the traffic gate (linear scaled by s in [floor, 1], angular kept)
  and the safety clip can make of the intended twist (M1, re-review HIGH 2).
"""

from __future__ import annotations

import math
from typing import Callable, Optional

from core_features.line_follow.clearance import (
    body_envelope_gap, body_path_gap, rotation_gap, ultrasonic_points)
from core_features.line_follow.model import _finite

#: The wheels hold the last cmd_vel at most this long (CommandManager nav timeout, 0.5 s; the
#: publisher runs at 50 Hz): a longer gap between published twists integrates no further.
TWIST_HOLD_S = 0.5
#: Returns this far outside range_min are candidates for memory: one scan period of motion
#: (0.10 m/s x 0.1 s) plus an in-place sweep of the body edge, with room to spare.
NEAR_BAND_M = 0.05
MEMORY_MAX_POINTS = 400


class BodyStopMixin:
    def _init_body_stop(self) -> None:
        # Last forward ultrasonic reading (None = no echo in range) and its receipt time.
        self._ultrasonic: Optional[float] = None
        self._ultrasonic_at: Optional[float] = None
        self._motion_envelope_provider: Optional[Callable[[], tuple[float, float, float]]] = None
        self._reset_body_stop()

    def _reset_body_stop(self) -> None:
        """New session: no status fields, no remembered points, odometry restarts."""
        self._clear_gap()
        self._forget_near()
        self._odometry_hold = False

    def odometry_lost(self) -> None:
        """The wheel output could not be integrated (wheels_sent failed): positions of the
        remembered points are unknown. Forget them and hold until the next fresh scan."""
        with self._lock:
            self._forget_near()
            self._odometry_hold = True

    def _forget_near(self) -> None:
        self._odom = (0.0, 0.0, 0.0)
        self._odom_at: Optional[float] = None
        self._odometer = 0.0
        self._twist = (0.0, 0.0)
        self._near_prev: tuple = ()
        self._near_memory: tuple = ()

    def _clear_gap(self) -> None:
        self._gap_status: dict = {}
        self._gap_resume: Optional[float] = None

    def observe_ultrasonic(self, range_m: Optional[float],
                           received_at: Optional[float] = None) -> None:
        """D-422: forward ultrasonic range (`translate.usable_range`; None = no echo in range)."""
        now = self._clock() if received_at is None else received_at
        with self._lock:
            self._ultrasonic = None if range_m is None or not _finite(range_m) else float(range_m)
            self._ultrasonic_at = float(now)

    def bind_motion_envelope(self, provider: Callable[[], tuple[float, float, float]]) -> None:
        """(max linear, max angular, smallest linear scale) the commanded twist can still get
        after line follow: the nav safety clip per axis and the traffic gate's linear scale."""
        if not callable(provider):
            raise ValueError("motion envelope provider must be callable")
        with self._lock:
            self._motion_envelope_provider = provider

    # ---- near-point memory (odometry from the twist sent to the wheels) --------------------

    def note_wheels(self, linear: float, angular: float, *, owned: bool,
                    now: Optional[float] = None) -> None:
        """The twist the cmd_vel publisher just sent (after CommandManager and readiness).

        owned: line follow is active and its NAVIGATION output is what reached the wheels (no
        e-stop, no other mode). Anything else moved (or held) the robot without line follow
        knowing why, so the memory and its odometry restart."""
        current = self._clock() if now is None else now
        with self._lock:
            if not owned:
                self._forget_near()
                return
            self._integrate(float(current))
            ok = _finite(linear) and _finite(angular)
            self._twist = (float(linear), float(angular)) if ok else (0.0, 0.0)

    def _integrate(self, now: float) -> None:
        if self._odom_at is None:
            self._odom_at = now
            return
        dt = min(max(0.0, now - self._odom_at), TWIST_HOLD_S)
        self._odom_at = max(self._odom_at, now)
        linear, angular = self._twist
        x, y, heading = self._odom
        if abs(angular) < 1e-9:
            x += linear * dt * math.cos(heading)
            y += linear * dt * math.sin(heading)
        else:
            turned = heading + angular * dt
            x += linear / angular * (math.sin(turned) - math.sin(heading))
            y -= linear / angular * (math.cos(turned) - math.cos(heading))
            heading = turned
        self._odom = (x, y, heading)
        radius = self._config.body_rotation_radius_m or 0.0
        self._odometer += abs(linear) * dt + abs(angular) * dt * radius

    def _to_base(self, ox: float, oy: float) -> tuple[float, float]:
        x0, y0, heading = self._odom
        c, s = math.cos(heading), math.sin(heading)
        dx, dy = ox - x0, oy - y0
        return c * dx + s * dy, -s * dx + c * dy

    def _remember_near(self, now: float) -> None:
        """At each scan: keep earlier near returns that are now inside range_min (invisible)."""
        self._odometry_hold = False           # a fresh scan after odometry_lost
        self._integrate(now)
        c = self._config
        range_min = self._range_min
        if range_min is None or not c.body_stop_known or not range_min > 0.0:
            self._near_prev = self._near_memory = ()
            return
        lidar_x = c.body_lidar_x_m
        keep = []
        for ox, oy, seen in self._near_memory + self._near_prev:
            if self._odometer - seen > c.obstacle_path_horizon_m:
                continue
            bx, by = self._to_base(ox, oy)
            if math.hypot(bx - lidar_x, by) < range_min:
                keep.append((ox, oy, seen))
        self._near_memory = tuple(keep[-MEMORY_MAX_POINTS:])
        x0, y0, heading = self._odom
        cos_h, sin_h = math.cos(heading), math.sin(heading)
        band = range_min + NEAR_BAND_M
        near = []
        for px, py in self._scan_points or ():
            if math.hypot(px, py) <= band:
                bx, by = px + lidar_x, py
                near.append((x0 + cos_h * bx - sin_h * by, y0 + sin_h * bx + cos_h * by,
                             self._odometer))
        self._near_prev = tuple(near)

    def _remembered_points(self) -> list:
        return [self._to_base(ox, oy) for ox, oy, _ in self._near_memory]

    # ---- the decision ---------------------------------------------------------------------

    def _envelope(self) -> Optional[tuple[float, float, float]]:
        """(max linear, max angular, linear scale floor); None = unreadable (fail closed)."""
        if self._motion_envelope_provider is None:
            return math.inf, math.inf, 1.0
        try:
            max_linear, max_angular, floor = self._motion_envelope_provider()
        except Exception:  # noqa: BLE001 - an unreadable limit fails closed
            return None
        if not all(_finite(v) or v == math.inf for v in (max_linear, max_angular, floor)):
            return None
        if not float(floor) > 0.0:
            return None                      # a gate that can scale linear to 0 has no arc
        return max(0.0, float(max_linear)), max(0.0, float(max_angular)), min(1.0, float(floor))

    def _body_clearance(self, now: float) -> tuple[Optional[float], float, float, float]:
        """D-422: (body gap along the intended path, now, stop gap, resume gap). Locked.

        LiDAR points (current scan + remembered ones under range_min) move to base_footprint; a
        fresh forward ultrasonic echo adds its cone. Moving: the URDF outline swept along the
        arcs the commanded twist can take, stop gap from the speed (or the LiDAR-origin
        override), never below the LiDAR blind-zone gap. In place: the rotation circle, which
        never moves closer, so stop and resume are the body margin (no override, no hysteresis).
        """
        c = self._config
        if self._odometry_hold:
            # Remembered points were dropped with unknown odometry: hold until a fresh scan.
            self._gap_resume = c.obstacle_body_margin_m
            self._gap_status = {"body_gap_m": 0.0, "stop_gap_m": c.obstacle_body_margin_m,
                                "clearance_source": "odometry_lost"}
            return 0.0, now, c.obstacle_body_margin_m, c.obstacle_body_margin_m
        envelope = self._envelope()
        if envelope is None:
            self._gap_resume = c.obstacle_body_margin_m
            self._gap_status = {"body_gap_m": 0.0, "stop_gap_m": c.obstacle_body_margin_m,
                                "clearance_source": None}
            return 0.0, now, c.obstacle_body_margin_m, c.obstacle_body_margin_m
        max_linear, max_angular, floor = envelope
        linear, angular = self._intended
        if linear <= 1e-6 and abs(angular) <= 1e-6:
            linear = c.cruise_speed          # no motion intended: judge the straight line
        linear = min(linear, max_linear)
        angular = max(-max_angular, min(max_angular, angular))
        lidar = [(x + c.body_lidar_x_m, y) for x, y in self._scan_points or ()]
        echo = self._ultrasonic_echo(now)
        sonar = () if echo is None else ultrasonic_points(
            echo, sensor_x_m=c.body_ultrasonic_x_m,
            half_angle_deg=c.obstacle_ultrasonic_half_angle_deg)
        groups = (("lidar", lidar), ("memory", self._remembered_points()), ("ultrasonic", sonar))
        if linear <= 1e-6:
            gaps = [rotation_gap(points, rotation_radius_m=c.body_rotation_radius_m,
                                 reach_m=c.obstacle_path_horizon_m) for _, points in groups]
            stop = resume = c.obstacle_body_margin_m
        else:
            stop, resume = self._stop_resume_gaps(linear)
            blind = self._blind_gap()
            if blind is not None and blind > stop:
                # Stop before a straight-ahead return slips under range_min (always, review H1).
                resume += blind - stop
                stop = blind
            body = dict(front_x_m=c.body_front_x_m, rear_x_m=c.body_rear_x_m,
                        half_width_m=c.body_half_width_m,
                        rotation_radius_m=c.body_rotation_radius_m)
            gaps = []
            for _, points in groups:
                if not points:
                    gaps.append(None)
                    continue
                gap = body_path_gap(points, linear=linear, angular=angular,
                                    horizon_m=c.obstacle_path_horizon_m, min_travel_m=resume,
                                    **body)
                if floor < 1.0 and abs(angular) > 1e-6:
                    # The traffic gate scales linear only, by any s in [floor, 1]: every such
                    # arc is tighter. Only contacts within the resume gap change the decision.
                    family = body_envelope_gap(points, linear=linear, angular=angular,
                                               scale_floor=floor, horizon_m=resume, **body)
                    if family is not None and (gap is None or family < gap):
                        gap = family
                gaps.append(gap)
        gap, source = None, None
        for (name, _), found in zip(groups, gaps):
            if found is not None and (gap is None or found < gap):
                gap, source = found, name
        self._gap_resume = resume
        self._gap_status = {"body_gap_m": None if gap is None else round(gap, 4),
                            "stop_gap_m": round(stop, 4), "clearance_source": source}
        return gap, now, stop, resume

    def _stop_resume_gaps(self, speed: float) -> tuple[float, float]:
        """Body gaps to stop at and resume beyond: the override converted from the LiDAR origin
        to the body front, else derived from the speed (D-422)."""
        c = self._config
        if c.obstacle_override:
            front = c.body_front_x_m - c.body_lidar_x_m
            return max(0.0, c.sector_stop_m - front), max(0.0, c.sector_resume_m - front)
        stop = c.derived_stop_gap_m(speed)
        return stop, stop + c.obstacle_resume_hysteresis_m

    def _blind_gap(self) -> Optional[float]:
        """Body gap straight ahead at which an object enters the LiDAR range_min (None = unknown)."""
        if self._range_min is None:
            return None
        c = self._config
        return max(0.0, self._range_min - (c.body_front_x_m - c.body_lidar_x_m))

    def _ultrasonic_echo(self, now: float) -> Optional[float]:
        """The echo range when fresh; None for no echo, stale or unconfigured (never a reason to go)."""
        c = self._config
        if c.body_ultrasonic_x_m is None or self._ultrasonic_at is None:
            return None
        age = now - self._ultrasonic_at
        if not -0.1 <= age <= c.obstacle_ultrasonic_stale_s:
            return None
        return self._ultrasonic
