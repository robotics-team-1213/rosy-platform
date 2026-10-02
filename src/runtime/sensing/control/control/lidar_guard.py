"""Fail-closed lidar bumper decisions, independent of ROS and smoothing."""
import math
from dataclasses import dataclass

from core_common.robot_body import ScanView
from ..sensing.body import BODY, LIDAR_X, ROTATION_RADIUS, rotation_radius

#: The gate's top speed (safety_max_linear); the D-424 stop gap is derived at it.
MAX_LINEAR_MPS = .014


def _body_at(mount):
    """The URDF body with the LiDAR at `mount` (x, y from TF) when it is a sane pose over it."""
    if (mount is not None and len(mount) == 2 and all(math.isfinite(v) for v in mount)
            and BODY.rear_x_m < mount[0] < BODY.front_x_m and abs(mount[1]) < BODY.half_width_m):
        return BODY.with_lidar(x_m=mount[0], y_m=mount[1])
    return BODY


def lidar_limits(stop, clear, radius=None, *, speed=MAX_LINEAR_MPS, reverse=False, mount=None):
    """D-424: (stop, clear) LiDAR-equivalent distances of the body strip.

    The floor is the D-422 body gap g(speed) from the URDF body edge, as a range from the
    LiDAR (Pinky front 0.081 / clear 0.111 at 0.014 m/s). A configured stop/clear may only
    raise it. `radius` is kept for callers; the strip, not a circle, is judged."""
    body = _body_at(mount)
    floor = body.lidar_stop_m(speed, reverse=reverse)
    stop = max(floor, stop) if math.isfinite(stop) else floor
    clear = (max(stop + 0.010, clear) if math.isfinite(clear) and clear > 0
             else stop + body.hysteresis_m)
    return stop, clear


def directional_lidar_limits(stop, clear, radius, mount=None, half_width=math.pi/4, *,
                             speed=MAX_LINEAR_MPS):
    """Front and rear (stop, clear) for the body strip in each direction (D-424)."""
    return (lidar_limits(stop, clear, radius, speed=speed, mount=mount),
            lidar_limits(stop, clear, radius, speed=speed, mount=mount, reverse=True))


def strip_ranges(points, unknown=(), *, mount=None, ultrasonic_covers=False):
    """D-424: LiDAR-equivalent (front, rear) distance of the nearest point in the body strip
    (half width + 0.010). inf = nothing in the strip that way: side points outside it never
    count. A beam without a return that reaches past the body edge (unknown out to range_min)
    reads as the body edge itself (gap 0) -- in front unless a fresh ultrasonic covers it."""
    body = _body_at(mount)
    view = ScanView(tuple(points), tuple(unknown), 0.)
    out = []
    for reverse in (False, True):
        offset = body.lidar_to_rear_m if reverse else body.lidar_to_front_m
        if body.unknown_blocks(view, reverse=reverse) and (reverse or not ultrasonic_covers):
            out.append(offset)
            continue
        gap = body.translation_gap(view.points, reverse=reverse)
        out.append(math.inf if gap is None else offset + gap)
    return tuple(out)


def lidar_blocked(raw, filtered, was_blocked, stop, clear, fresh):
    # D-424: +inf is "nothing in the body strip" (strip_ranges reports an unknown band as the
    # body edge, a finite near range). NaN, 0 and negative stay unknown and block. A close
    # raw beam brakes now; only clearing uses the smooth value.
    if not fresh or math.isnan(raw) or raw <= 0.0:
        return True
    if raw <= stop:
        return True
    if raw >= clear and not math.isnan(filtered) and filtered >= clear:
        return False
    return was_blocked


def translation_footprint_eligible(corrected_linear, angular, *, enabled, lidar_fresh,
                                   scan_age, source_age, mount, travel, radius, ranges):
    """Measured narrow-body clearance is valid only for slow straight motion.

    Inputs are geometry evidence and the selected candidate, not a permission
    cached from a previous command. Negative scan age is a clock fault.
    """
    return bool(enabled and lidar_fresh and mount is not None and travel is not None and
                all(type(v) in (int, float) and math.isfinite(v)
                    for v in (corrected_linear, angular, scan_age, source_age, radius)) and
                0 <= scan_age <= .2 and -.05 <= source_age <= .2 and 0 < radius <= ROTATION_RADIUS and
                abs(corrected_linear) <= .014 and abs(angular) < 1e-4 and
                len(ranges) == 6 and all(math.isfinite(v) and v > 0 for v in ranges))


@dataclass(frozen=True)
class TranslationEvidence:
    scan_received_at: float
    scan_source_at: float
    enabled: bool
    lidar_fresh: bool
    mount: tuple | None
    travel: tuple | None
    radius: float
    ranges: tuple
    radial_front: bool
    radial_rear: bool
    previous_front: bool
    previous_rear: bool
    linear_gains: tuple


def command_translation_bumpers(evidence, linear, angular, now):
    """Recompute the optional translation override for this candidate only.

    Radial bumpers and hysteresis are sensor-derived. They must not already
    contain the previous command's narrow-footprint override.
    """
    if not isinstance(evidence, TranslationEvidence):
        raise ValueError('Translation evidence is required')
    flags = (evidence.enabled, evidence.lidar_fresh, evidence.radial_front,
             evidence.radial_rear, evidence.previous_front, evidence.previous_rear)
    def finite(value):
        return type(value) in (int, float) and math.isfinite(value)
    def vector(value, size):
        return type(value) is tuple and len(value) == size and all(finite(v) for v in value)
    if (any(type(flag) is not bool for flag in flags) or
            not all(finite(v) for v in (linear, angular, now, evidence.scan_received_at,
                                       evidence.scan_source_at, evidence.radius)) or evidence.radius <= 0 or
            not vector(evidence.ranges, 6) or not all(v > 0 for v in evidence.ranges) or
            not vector(evidence.linear_gains, 2) or not all(.75 <= v <= 1.25 for v in evidence.linear_gains) or
            (evidence.mount is not None and not vector(evidence.mount, 2)) or
            (evidence.travel is not None and not vector(evidence.travel, 2))):
        raise ValueError('Invalid translation evidence')
    scan_age, source_age = now - evidence.scan_received_at, now - evidence.scan_source_at
    if scan_age > .5 or source_age > .5:
        raise ValueError('Translation geometry expired')
    if not evidence.lidar_fresh or scan_age < 0 or source_age < -.05:
        return True, True
    corrected = linear
    if abs(linear) <= .014 and abs(angular) < 1e-4:
        corrected *= evidence.linear_gains[0 if linear >= 0 else 1]
    eligible = translation_footprint_eligible(corrected, angular,
        enabled=evidence.enabled, lidar_fresh=evidence.lidar_fresh,
        scan_age=scan_age, source_age=source_age, mount=evidence.mount, travel=evidence.travel,
        radius=evidence.radius, ranges=evidence.ranges)
    if not eligible:
        return evidence.radial_front, evidence.radial_rear
    return (lidar_blocked(evidence.travel[0], evidence.travel[0], evidence.previous_front, 0., .010, True),
            lidar_blocked(evidence.travel[1], evidence.travel[1], evidence.previous_rear, 0., .010, True))


def lidar_can_rotate(ranges, radius, fresh, base_clearance=None, *, sweep_radius=None):
    """D-424: the body sweeps at least the URDF rotation radius (never less, whatever the
    configured radius) + 0.010. Seen points decide; a sector without a return is unknown
    space a turn does not enter, so it never blocks a turn by itself."""
    required = rotation_radius(radius)
    if sweep_radius is not None:
        if not math.isfinite(sweep_radius) or sweep_radius < required:
            return False
        required = sweep_radius  # Never clamp a measured swept envelope downward.
    pad = BODY.sweep_pad_m
    if base_clearance is not None:
        # A scan with no return at all is a sensor fault, not an empty room.
        return bool(fresh and any(math.isfinite(v) and v > 0 for v in ranges)
                    and not math.isnan(base_clearance) and base_clearance > required + pad)
    seen = [value for value in ranges if math.isfinite(value) and value > 0]
    limit = required + abs(LIDAR_X) + pad
    return bool(fresh and seen and all(value > limit for value in seen))


def rotation_scan_observed(ranges, increment, minimum, maximum):
    """Unknown azimuths cannot be treated as empty swept space."""
    return (len(ranges) >= 180 and all(math.isfinite(v) for v in (increment,minimum,maximum)) and
            0 <= minimum < maximum and abs(len(ranges)*abs(increment)-2*math.pi) < .02 and
            all(math.isfinite(r) and minimum < r <= maximum for r in ranges))


def scan_body_clearance(ranges, angle_min, increment, x, y, yaw, minimum, maximum):
    """Nearest observed obstacle to base_link, including the mount translation."""
    nearest = math.inf
    for i,r in enumerate(ranges):
        if math.isfinite(r) and minimum < r <= maximum:
            a = angle_min+i*increment+yaw
            nearest = min(nearest, math.hypot(x+r*math.cos(a),y+r*math.sin(a)))
    return nearest
