"""Measured-envelope speed limiter. It can reduce authority, never create it."""
from dataclasses import dataclass
import math

from .commissioning_certificate import validate_motion_envelope_certificate


@dataclass(frozen=True)
class OperatingConditions:
    surface_class: str
    payload_g: float
    battery_voltage_v: float
    imu_temperature_c: float
    tire_or_wheel_revision: str


@dataclass(frozen=True)
class RuntimeEvidence:
    observed_at: float
    expires_at: float
    front_clearance_m: float
    rear_clearance_m: float
    side_clearance_m: float
    footprint_uncertainty_m: float
    extrinsic_uncertainty_m: float
    localization_uncertainty_m: float
    sensor_health: bool
    localization_ready: bool
    drift_ok: bool


@dataclass(frozen=True)
class SpeedDecision:
    linear: float
    angular: float
    limit_mps: float
    tier: str
    reason: str
    required_distance_m: float


def _stop(reason, required=math.inf):
    return SpeedDecision(0., 0., 0., 'HOLD', reason, required)


def _tier(limit):
    if limit <= .005:
        return 'LIMITED'
    if limit <= .014:
        return 'CRAWL'
    if limit <= .03:
        return 'LOW'
    return 'NOMINAL'


def _conditions_match(bounds, current):
    try:
        numeric = (current.payload_g, current.battery_voltage_v, current.imu_temperature_c)
        return (
            isinstance(current, OperatingConditions) and all(math.isfinite(value) for value in numeric) and
            current.surface_class == bounds['surface_class'] and
            current.tire_or_wheel_revision == bounds['tire_or_wheel_revision'] and
            bounds['payload_range_g'][0] <= current.payload_g <= bounds['payload_range_g'][1] and
            bounds['battery_voltage_range_v'][0] <= current.battery_voltage_v <= bounds['battery_voltage_range_v'][1] and
            bounds['imu_temperature_range_c'][0] <= current.imu_temperature_c <= bounds['imu_temperature_range_c'][1])
    except (KeyError, TypeError):
        return False


def _required(speed, row, evidence, now, static_distance):
    uncertainty = (evidence.footprint_uncertainty_m + evidence.extrinsic_uncertainty_m +
                   evidence.localization_uncertainty_m)
    sensor_age = max(0., now-evidence.observed_at)
    model = (static_distance + uncertainty +
             speed*(row['command_to_decel_p99_s']+sensor_age+.05) +
             speed*speed/(2*row['decel_lower_bound_mps2']))
    # A bin's measured upper bound applies at its certified speed. Scaling the
    # additional travel toward zero keeps interpolation reducing-only while
    # the analytical latency/braking model remains the independent floor.
    measured = (static_distance + uncertainty +
                row['stop_distance_upper_m'] * min(1., speed/row['speed_mps']))
    return max(model, measured)


def _clearance_limited_speed(maximum, row, evidence, now, static_distance, clearance):
    if _required(maximum, row, evidence, now, static_distance) <= clearance:
        return maximum
    low, high = 0., maximum
    for _ in range(40):
        middle = (low+high)/2
        if _required(middle, row, evidence, now, static_distance) <= clearance:
            low = middle
        else:
            high = middle
    return low


def limit_command(linear, angular, envelope, conditions, evidence, now, *,
                  hardware_ceiling_mps=.014, static_distance_m=.12):
    """Return a curvature-preserving, reducing-only decision from active evidence."""
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
               for value in (linear, angular, now, hardware_ceiling_mps, static_distance_m)):
        return _stop('invalid_command')
    if hardware_ceiling_mps <= 0 or static_distance_m < 0:
        return _stop('invalid_limit')
    record = validate_motion_envelope_certificate(envelope, active_only=True)
    if record is None:
        return _stop('envelope_unavailable')
    if not _conditions_match(record['conditions'], conditions):
        return _stop('condition_mismatch')
    if not isinstance(evidence, RuntimeEvidence):
        return _stop('evidence_unavailable')
    clock_values = (evidence.observed_at, evidence.expires_at)
    if (not all(math.isfinite(value) for value in clock_values) or
            not evidence.observed_at <= now <= evidence.expires_at):
        return _stop('evidence_expired')
    if type(evidence.sensor_health) is not bool or not evidence.sensor_health:
        return _stop('sensor_unhealthy')
    if type(evidence.localization_ready) is not bool or not evidence.localization_ready:
        return _stop('localization_unavailable')
    clearance_values = (evidence.front_clearance_m, evidence.rear_clearance_m,
                        evidence.side_clearance_m, evidence.footprint_uncertainty_m,
                        evidence.extrinsic_uncertainty_m, evidence.localization_uncertainty_m)
    if (not all(math.isfinite(value) for value in clearance_values) or
            min(clearance_values) < 0):
        return _stop('clearance_unknown')
    if linear == 0:
        return SpeedDecision(0., angular, 0., 'HOLD', 'linear_idle', 0.)
    direction = 'forward' if linear > 0 else 'reverse'
    rows = sorted((row for row in record['speed_bins'] if row['direction'] == direction),
                  key=lambda row: row['speed_mps'])
    ceiling = min(hardware_ceiling_mps, record['authorized_max_linear_mps'])
    reason = 'allow'
    if evidence.drift_ok is not True:
        ceiling = min(ceiling, .014)
        reason = 'runtime_downgrade'
    elif hardware_ceiling_mps < record['authorized_max_linear_mps']:
        reason = 'hardware_ceiling'
    eligible = [row for row in rows if row['speed_mps'] <= ceiling+1e-12]
    if not eligible:
        return _stop('speed_bin_unavailable')
    request = min(abs(linear), ceiling, eligible[-1]['speed_mps'])
    row = next((item for item in eligible if item['speed_mps'] >= request-1e-12), eligible[-1])
    clearance = evidence.front_clearance_m if linear > 0 else evidence.rear_clearance_m
    limited = _clearance_limited_speed(request, row, evidence, now, static_distance_m, clearance)
    required = _required(request, row, evidence, now, static_distance_m)
    if limited < request-1e-9:
        reason = 'clearance_limit'
    if limited <= 1e-9:
        return _stop('clearance_stop', required)
    factor = limited/abs(linear)
    return SpeedDecision(math.copysign(limited, linear), angular*factor, limited,
                         _tier(limited), reason, required)
