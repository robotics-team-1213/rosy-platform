"""Fail-closed commissioning records; candidates never grant motion authority."""
import hashlib
import json
import math


_CONTEXT_FIELDS = ('robot_id', 'hardware_model', 'geometry_revision',
                   'sensor_revision', 'data_generation')
_ESTIMATES = ('wheel_radius_common_multiplier', 'wheel_radius_left_multiplier',
              'wheel_radius_right_multiplier', 'effective_separation_multiplier')
_DIRECTIONS = ('forward', 'reverse', 'cw', 'ccw')
_HEX = set('0123456789abcdef')


def _copy(value):
    return json.loads(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _sha256(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _digest(record):
    return _sha256({key: value for key, value in record.items() if key != 'digest'})


def _hex_digest(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _context_valid(context):
    return (isinstance(context, dict) and set(context) == set(_CONTEXT_FIELDS) and
            all(isinstance(context[name], str) and context[name].strip()
                for name in _CONTEXT_FIELDS))


def _estimate_valid(estimate):
    if not isinstance(estimate, dict) or set(estimate) != {'value', 'std', 'ci95'}:
        return False
    value, std, interval = estimate['value'], estimate['std'], estimate['ci95']
    return (all(_number(item) for item in (value, std)) and .75 <= value <= 1.25 and
            0 <= std <= .25 and isinstance(interval, list) and len(interval) == 2 and
            all(_number(item) for item in interval) and
            .5 <= interval[0] <= value <= interval[1] <= 1.5)


def _residuals_valid(residuals, *, holdout=False):
    if not isinstance(residuals, dict) or set(residuals) != {'linear_rmse_m', 'yaw_rmse_rad'}:
        return False
    linear, yaw = residuals['linear_rmse_m'], residuals['yaw_rmse_rad']
    if not all(_number(value) and value >= 0 for value in (linear, yaw)):
        return False
    return not holdout or (linear <= .010 and yaw <= .050)


def _candidate_body_valid(record):
    estimator, quality = record.get('estimator'), record.get('quality')
    trials = quality.get('trials_by_direction') if isinstance(quality, dict) else None
    return (
        record.get('schema_version') == 2 and _context_valid(record.get('context')) and
        isinstance(record.get('session'), str) and bool(record['session'].strip()) and
        isinstance(estimator, dict) and set(estimator) == {'name', 'version'} and
        all(isinstance(estimator[key], str) and estimator[key].strip() for key in estimator) and
        isinstance(record.get('evidence_digests'), list) and bool(record['evidence_digests']) and
        all(_hex_digest(value) for value in record['evidence_digests']) and
        isinstance(record.get('estimates'), dict) and set(record['estimates']) == set(_ESTIMATES) and
        all(_estimate_valid(record['estimates'][name]) for name in _ESTIMATES) and
        isinstance(quality, dict) and set(quality) == {
            'excitation_rank', 'train_residuals', 'trials_by_direction'} and
        type(quality['excitation_rank']) is int and quality['excitation_rank'] >= 4 and
        _residuals_valid(quality['train_residuals']) and isinstance(trials, dict) and
        set(trials) == set(_DIRECTIONS) and
        all(type(trials[name]) is int and trials[name] >= 2 for name in _DIRECTIONS))


def _holdout_valid(holdout, train_session, candidate_digest):
    return (
        isinstance(holdout, dict) and set(holdout) == {
            'session', 'candidate_digest', 'passed', 'residuals', 'evidence_digests'} and
        isinstance(holdout['session'], str) and bool(holdout['session'].strip()) and
        holdout['session'] != train_session and holdout['candidate_digest'] == candidate_digest and
        holdout['passed'] is True and _residuals_valid(holdout['residuals'], holdout=True) and
        isinstance(holdout['evidence_digests'], list) and bool(holdout['evidence_digests']) and
        all(_hex_digest(value) for value in holdout['evidence_digests']))


def make_geometry_candidate(*, context, session, estimator, evidence_digests, estimates, quality):
    """Create inert estimation evidence. Only promotion can produce ``active``."""
    try:
        record = _copy({
            'schema_version': 2, 'certificate_type': 'geometry_sensor',
            'context': context, 'session': session, 'estimator': estimator,
            'evidence_digests': evidence_digests, 'estimates': estimates,
            'quality': quality, 'status': 'candidate',
        })
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('Geometry evidence must be finite JSON') from exc
    if record['certificate_type'] != 'geometry_sensor' or not _candidate_body_valid(record):
        raise ValueError('Geometry evidence is incomplete, unobservable, or outside bounds')
    record['digest'] = _digest(record)
    return record


def promote_geometry_candidate(candidate, holdout):
    """Promote only evidence from a separate, bounded passing validation session."""
    record = validate_geometry_certificate(candidate)
    if record is None or record.get('status') != 'candidate':
        raise ValueError('A valid geometry candidate is required')
    try:
        holdout = _copy(holdout)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('Holdout evidence must be finite JSON') from exc
    if not _holdout_valid(holdout, record['session'], record['digest']):
        raise ValueError('Independent passing holdout evidence is required')
    candidate_digest = record.pop('digest')
    record.update(status='active', source_candidate_digest=candidate_digest, holdout=holdout)
    record['digest'] = _digest(record)
    return record


def validate_geometry_certificate(record, context=None, *, active_only=False):
    """Return a defensive copy, or ``None`` for malformed, forged, or cross-device data."""
    try:
        record = _copy(record)
        if (record.get('certificate_type') != 'geometry_sensor' or
                record.get('digest') != _digest(record) or not _candidate_body_valid(record) or
                record.get('status') not in ('candidate', 'active')):
            return None
        if context is not None and record['context'] != _copy(context):
            return None
        if record['status'] == 'active':
            source = record.get('source_candidate_digest')
            if not _hex_digest(source) or not _holdout_valid(record.get('holdout'), record['session'], source):
                return None
        elif any(key in record for key in ('source_candidate_digest', 'holdout')):
            return None
        if active_only and record['status'] != 'active':
            return None
        return record
    except (ValueError, TypeError, OverflowError):
        return None


_CONDITION_FIELDS = ('surface_class', 'payload_range_g', 'battery_voltage_range_v',
                     'imu_temperature_range_c', 'tire_or_wheel_revision')
_BIN_FIELDS = ('speed_mps', 'direction', 'trials', 'command_to_decel_p99_s',
               'decel_lower_bound_mps2', 'stop_distance_upper_m',
               'lateral_error_upper_m')


def _range_valid(value, *, positive=False):
    return (isinstance(value, list) and len(value) == 2 and
            all(_number(item) for item in value) and value[0] <= value[1] and
            (not positive or value[0] > 0))


def _conditions_valid(conditions):
    return (
        isinstance(conditions, dict) and set(conditions) == set(_CONDITION_FIELDS) and
        isinstance(conditions['surface_class'], str) and bool(conditions['surface_class'].strip()) and
        isinstance(conditions['tire_or_wheel_revision'], str) and
        bool(conditions['tire_or_wheel_revision'].strip()) and
        _range_valid(conditions['payload_range_g']) and conditions['payload_range_g'][0] >= 0 and
        _range_valid(conditions['battery_voltage_range_v'], positive=True) and
        _range_valid(conditions['imu_temperature_range_c']))


def _speed_bins_valid(rows):
    if not isinstance(rows, list) or not rows:
        return False
    seen = set()
    directions = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(_BIN_FIELDS):
            return False
        speed = row['speed_mps']
        direction = row['direction']
        values = (speed, row['command_to_decel_p99_s'], row['decel_lower_bound_mps2'],
                  row['stop_distance_upper_m'], row['lateral_error_upper_m'])
        if (not all(_number(value) for value in values) or not 0 < speed <= 1. or
                direction not in ('forward', 'reverse') or
                type(row['trials']) is not int or row['trials'] < 3 or
                not 0 <= row['command_to_decel_p99_s'] <= 2. or
                row['decel_lower_bound_mps2'] <= 0 or
                row['stop_distance_upper_m'] < 0 or row['lateral_error_upper_m'] < 0 or
                (direction, speed) in seen):
            return False
        seen.add((direction, speed))
        directions.add(direction)
    return directions == {'forward', 'reverse'}


def _motion_holdout_valid(holdout, train_session, candidate_digest):
    residuals = holdout.get('residuals') if isinstance(holdout, dict) else None
    return (
        isinstance(holdout, dict) and set(holdout) == {
            'session', 'candidate_digest', 'passed', 'residuals', 'evidence_digests'} and
        isinstance(holdout['session'], str) and bool(holdout['session'].strip()) and
        holdout['session'] != train_session and holdout['candidate_digest'] == candidate_digest and
        holdout['passed'] is True and isinstance(residuals, dict) and
        set(residuals) == {'stop_distance_error_m', 'lateral_error_m'} and
        all(_number(value) and 0 <= value <= .010 for value in residuals.values()) and
        isinstance(holdout['evidence_digests'], list) and bool(holdout['evidence_digests']) and
        all(_hex_digest(value) for value in holdout['evidence_digests']))


def _motion_body_valid(record):
    return (
        record.get('schema_version') == 1 and record.get('certificate_type') == 'motion_envelope' and
        _hex_digest(record.get('geometry_sensor_digest')) and
        isinstance(record.get('session'), str) and bool(record['session'].strip()) and
        _conditions_valid(record.get('conditions')) and _speed_bins_valid(record.get('speed_bins')) and
        isinstance(record.get('evidence_digests'), list) and bool(record['evidence_digests']) and
        all(_hex_digest(value) for value in record['evidence_digests']) and
        _number(record.get('authorized_max_linear_mps')) and
        record['authorized_max_linear_mps'] == max(row['speed_mps'] for row in record['speed_bins']))


def make_motion_envelope_candidate(*, geometry_certificate, session, conditions,
                                   speed_bins, evidence_digests):
    """Create inert measured stopping evidence bound to active geometry."""
    geometry = validate_geometry_certificate(geometry_certificate, active_only=True)
    if geometry is None:
        raise ValueError('An active geometry certificate is required')
    try:
        record = _copy({
            'schema_version': 1, 'certificate_type': 'motion_envelope',
            'geometry_sensor_digest': geometry['digest'], 'session': session,
            'conditions': conditions, 'speed_bins': speed_bins,
            'evidence_digests': evidence_digests,
            'authorized_max_linear_mps': max(row['speed_mps'] for row in speed_bins),
            'status': 'candidate',
        })
    except (ValueError, TypeError, OverflowError, KeyError) as exc:
        raise ValueError('Motion envelope evidence must be finite JSON') from exc
    if not _motion_body_valid(record):
        raise ValueError('Motion envelope evidence is incomplete or outside bounds')
    record['digest'] = _digest(record)
    return record


def promote_motion_envelope_candidate(candidate, holdout):
    record = validate_motion_envelope_certificate(candidate)
    if record is None or record.get('status') != 'candidate':
        raise ValueError('A valid motion envelope candidate is required')
    try:
        holdout = _copy(holdout)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('Motion holdout evidence must be finite JSON') from exc
    if not _motion_holdout_valid(holdout, record['session'], record['digest']):
        raise ValueError('Independent passing motion holdout is required')
    candidate_digest = record.pop('digest')
    record.update(status='active', source_candidate_digest=candidate_digest, holdout=holdout)
    record['digest'] = _digest(record)
    return record


def validate_motion_envelope_certificate(record, geometry_digest=None, *, active_only=False):
    try:
        record = _copy(record)
        if (record.get('digest') != _digest(record) or not _motion_body_valid(record) or
                record.get('status') not in ('candidate', 'active')):
            return None
        if geometry_digest is not None and record['geometry_sensor_digest'] != geometry_digest:
            return None
        if record['status'] == 'active':
            source = record.get('source_candidate_digest')
            if not _hex_digest(source) or not _motion_holdout_valid(record.get('holdout'), record['session'], source):
                return None
        elif any(key in record for key in ('source_candidate_digest', 'holdout')):
            return None
        if active_only and record['status'] != 'active':
            return None
        return record
    except (ValueError, TypeError, OverflowError):
        return None
