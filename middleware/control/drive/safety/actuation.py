"""Prepare one final calibrated candidate before sweep and hardware publication.

The caller supplies a matching live calibration and permitted actuator caps.
This calculation does not authorize calibration use or physical movement.
"""
import math
from dataclasses import dataclass
from .motion_sweep import command_sweep_clearance


@dataclass(frozen=True)
class PreparedCommand:
    linear: float
    angular: float
    motor_linear: float


@dataclass(frozen=True)
class SimulationActuation:
    revision: str
    observed_at: float
    expires_at: float
    linear_gains: tuple
    angular_gains: tuple
    linear_sign: float
    points: tuple
    center: tuple
    uncertainty: float
    body_radius: float
    scan_received_at: float
    scan_source_at: float
    scan_complete: bool
    footprint: tuple | None = None
    can_rotate: bool = False
    pivot_margin: float | None = None

    def prepare(self, linear, angular, requested_angular, now, core_caps):
        def vector(value, size):
            return (type(value) is tuple and len(value) == size and
                    all(type(v) in (int, float) and math.isfinite(v) for v in value))
        if (not isinstance(self.revision, str) or not self.revision or
                not all(type(v) in (int, float) and math.isfinite(v) for v in
                        (self.observed_at, self.expires_at, now, self.scan_received_at, self.scan_source_at)) or
                not self.observed_at <= now <= self.expires_at or not 0 < self.expires_at-self.observed_at <= .5 or
                type(self.scan_complete) is not bool or type(self.can_rotate) is not bool or
                not vector(self.linear_gains, 2) or not vector(self.angular_gains, 2) or not vector(self.center, 2) or
                type(self.points) is not tuple or not 3 <= len(self.points) <= 4096 or
                not all(vector(point, 2) for point in self.points) or
                (self.footprint is not None and (type(self.footprint) is not tuple or
                 not 3 <= len(self.footprint) <= 64 or not all(vector(point, 2) for point in self.footprint)))):
            raise ValueError('Invalid or expired simulation actuation evidence')
        prepared = prepare_command(linear, angular, requested_angular=requested_angular,
            linear_gains=self.linear_gains, angular_gains=self.angular_gains,
            profile_caps=(.014, .1), limited_caps=core_caps, linear_sign=self.linear_sign)
        clearance = command_sweep_clearance(points=self.points,
            estimate={'center_m': self.center, 'center_uncertainty_m': self.uncertainty,
                      'footprint_xy': self.footprint}, body_radius=self.body_radius,
            v=prepared.linear, w=prepared.angular, source_age=now-self.scan_source_at,
            scan_age=max(now-self.scan_received_at, now-self.scan_source_at),
            lidar_fresh=True, scan_complete=self.scan_complete, can_rotate=self.can_rotate,
            pivot_margin=self.pivot_margin)
        if clearance is None:
            raise ValueError('Final candidate sweep unavailable')
        return prepared if clearance > 0 else PreparedCommand(0., 0., 0.)


def prepare_command(linear, angular, *, requested_angular, linear_gains, angular_gains,
                    profile_caps, limited_caps, linear_sign):
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)

    def pair(values, low, high=math.inf):
        return (isinstance(values, (tuple, list)) and len(values) == 2 and
                all(number(v) and low <= v <= high for v in values))

    if (not all(number(v) for v in (linear, angular, requested_angular, linear_sign)) or
            linear_sign not in (-1., 1.) or not pair(linear_gains, .75, 1.25) or
            not pair(angular_gains, .75, 1.25) or not pair(profile_caps, 0.) or
            (limited_caps is not None and not pair(limited_caps, 0.))):
        raise ValueError('Invalid final command calibration or limits')
    v, w = linear, angular
    if abs(v) <= .014 and abs(requested_angular) < 1e-4:
        v *= linear_gains[0 if v >= 0. else 1]
    if abs(v) < 1e-4 and abs(w) <= .06:
        w *= angular_gains[0 if w >= 0. else 1]
    scale = min(1., profile_caps[0] / max(abs(v), 1e-12), profile_caps[1] / max(abs(w), 1e-12))
    if limited_caps is not None:
        scale = min(scale, limited_caps[0] / max(abs(v), 1e-12), limited_caps[1] / max(abs(w), 1e-12))
    v, w = v * scale, w * scale
    if not number(v) or not number(w):
        raise ValueError('Final command is not finite')
    return PreparedCommand(v, w, v * linear_sign)
