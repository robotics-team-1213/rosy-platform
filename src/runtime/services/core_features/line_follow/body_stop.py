"""D-422 body-referenced obstacle stop: a LineFollowManager mixin (keeps manager.py in budget).

The URDF body outline is swept along the intended lane arc (clearance.body_path_gap); in place,
the rotation radius (clearance.rotation_gap). A fresh forward ultrasonic echo joins as cone
points, so it can only shorten the gap. Every method runs under the manager's ``self._lock``
except ``observe_ultrasonic``, which takes it.
"""

from __future__ import annotations

from typing import Optional

from core_features.line_follow.clearance import body_path_gap, rotation_gap, ultrasonic_points
from core_features.line_follow.model import _finite


class BodyStopMixin:
    def observe_ultrasonic(self, range_m: Optional[float],
                           received_at: Optional[float] = None) -> None:
        """D-422: forward ultrasonic range (`translate.usable_range`; None = no echo in range)."""
        now = self._clock() if received_at is None else received_at
        with self._lock:
            self._ultrasonic = None if range_m is None or not _finite(range_m) else float(range_m)
            self._ultrasonic_at = float(now)

    def _body_clearance(self, now: float) -> tuple[Optional[float], float, float, float]:
        """D-422: (body gap along the intended path, now, stop gap, resume gap). Locked.

        LiDAR points move to base_footprint; a fresh forward ultrasonic echo adds its cone as
        points (it can only shorten the gap). Moving: the URDF outline swept along the intended
        arc, stop gap from the intended speed (or the LiDAR-origin override). In place: the
        rotation circle, which never moves closer, so only the body margin is needed.
        """
        c = self._config
        linear, angular = self._intended
        lidar = [(x + c.body_lidar_x_m, y) for x, y in self._scan_points or ()]
        echo, fresh = self._ultrasonic_echo(now)
        sonar = () if echo is None else ultrasonic_points(
            echo, sensor_x_m=c.body_ultrasonic_x_m,
            half_angle_deg=c.obstacle_ultrasonic_half_angle_deg)
        if linear <= 1e-6 and abs(angular) > 1e-6:
            gaps = [rotation_gap(points, rotation_radius_m=c.body_rotation_radius_m,
                                 reach_m=c.obstacle_path_horizon_m) for points in (lidar, sonar)]
            # No approach, so no hysteresis either: a hold from driving forward must not keep
            # a robot that can turn clear from turning (obstacle_release_s still debounces).
            stop = resume = c.obstacle_body_margin_m
        else:
            # No motion intended at all: judge the straight line at cruise speed.
            speed, turn = (linear, angular) if linear > 1e-6 else (c.cruise_speed, 0.0)
            gaps = [body_path_gap(points, linear=speed, angular=turn, front_x_m=c.body_front_x_m,
                                  rear_x_m=c.body_rear_x_m, half_width_m=c.body_half_width_m,
                                  rotation_radius_m=c.body_rotation_radius_m,
                                  horizon_m=c.obstacle_path_horizon_m) if points else None
                    for points in (lidar, sonar)]
            stop, resume = self._stop_resume_gaps(speed)
            blind = self._blind_gap()
            if not fresh and blind is not None and blind > stop:
                # Nothing covers the LiDAR's range_min near field: stop before it goes blind.
                resume += blind - stop
                stop = blind
        lidar_gap, sonar_gap = gaps
        if sonar_gap is not None and (lidar_gap is None or sonar_gap < lidar_gap):
            gap, source = sonar_gap, "ultrasonic"
        else:
            gap, source = lidar_gap, None if lidar_gap is None else "lidar"
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

    def _ultrasonic_echo(self, now: float) -> tuple[Optional[float], bool]:
        """(echo range or None, fresh). Stale or unconfigured readings are ignored."""
        c = self._config
        if c.body_ultrasonic_x_m is None or self._ultrasonic_at is None:
            return None, False
        age = now - self._ultrasonic_at
        if not -0.1 <= age <= c.obstacle_ultrasonic_stale_s:
            return None, False
        return self._ultrasonic, True
