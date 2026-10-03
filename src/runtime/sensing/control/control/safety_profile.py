"""Effective safety limits with a stable revision; no ROS or inferred geometry."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math

from ..sensing.body import BODY, LIDAR_X, URDF_RADIUS, rotation_radius


@dataclass(frozen=True)
class SafetyProfile:
    radius: float
    stop: float
    clear: float
    turn_clear: float
    half_width_deg: float
    max_linear: float
    max_angular: float
    lidar_yaw_rad: float
    linear_sign: float
    imu_unit: str
    lidar_x_m: float
    lidar_y_m: float

    @classmethod
    def build(cls, *, radius=URDF_RADIUS, stop=None, clear=None, half_width_deg=45.,
              stop_floor=0., clear_floor=0., max_linear=.014, max_angular=.10,
              lidar_yaw_rad=math.radians(190), linear_sign=1., imu_unit='rad_s',
              lidar_x_m=LIDAR_X, lidar_y_m=0.):
        mount_offset = math.hypot(lidar_x_m, lidar_y_m)
        # D-424: the floor is the URDF body strip gap at max_linear, from the LiDAR (Pinky
        # ~0.081), not the old circumradius + offset + 18 mm (0.111) applied forward.
        try:
            body = BODY.with_lidar(x_m=lidar_x_m, y_m=lidar_y_m)
            # A calibrated radius beyond the URDF rotation radius grows the body that much.
            physical_floor = (max(body.lidar_stop_m(max_linear), body.lidar_stop_m(max_linear, reverse=True))
                              + max(0., radius-BODY.rotation_radius_m))
        except (ValueError, TypeError):
            physical_floor = math.nan
        # Defaults fill absent fields only. Supplied values are validated,
        # never silently replaced with a bootstrap constant.
        if stop is None:
            stop = max(physical_floor, stop_floor)
        if clear is None:
            clear = max(stop+BODY.hysteresis_m, stop+.010, clear_floor)
        values = (radius, stop, clear, physical_floor, half_width_deg, stop_floor, clear_floor, max_linear, max_angular,
                  lidar_yaw_rad, linear_sign, lidar_x_m, lidar_y_m)
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Non-finite safety profile')
        if not URDF_RADIUS <= radius <= .15 or not 0 < max_linear <= .014 or not 0 < max_angular <= .10:
            raise ValueError('Profile exceeds nominal hardware envelope')
        if mount_offset > radius:
            raise ValueError('Lidar mount lies outside configured body envelope')
        if (stop_floor < 0 or clear_floor < 0 or stop < max(physical_floor, stop_floor) or
                clear < max(stop+.010, clear_floor) or not 45. <= half_width_deg <= 90.):
            raise ValueError('Configured profile violates geometry or explicit safety constraints')
        if linear_sign not in (-1., 1.) or imu_unit not in ('rad_s', 'deg_s'):
            raise ValueError('Invalid sensor or drive convention')
        return cls(radius, stop, clear, rotation_radius(radius)+mount_offset+BODY.sweep_pad_m, half_width_deg, max_linear, max_angular,
                   round(math.atan2(math.sin(lidar_yaw_rad), math.cos(lidar_yaw_rad)), 6), linear_sign, imu_unit,
                   lidar_x_m, lidar_y_m)

    @property
    def revision(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]

    def report(self):
        return {'schema_version': 1, 'revision': self.revision,
                'source': 'validated_configuration', 'commissioned': False,
                'limits_frame': 'lidar_origin', 'geometry_frame': 'base_link',
                'effective': asdict(self),
                'unverified': ['physical_geometry', 'stopping_response', 'rotational_response']}


def bounded_command(v, w, max_linear, max_angular):
    """Limit the pair together so saturation does not change curvature."""
    if not all(math.isfinite(x) for x in (v, w, max_linear, max_angular)) or min(max_linear, max_angular) <= 0:
        return 0., 0., 'invalid_command'
    factor = min(1., max_linear/abs(v) if v else 1., max_angular/abs(w) if w else 1.)
    return v*factor, w*factor, 'speed_limit' if factor < 1. else 'allow'
