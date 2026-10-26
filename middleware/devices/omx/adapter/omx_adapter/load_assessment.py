"""Conservative offline quintic load-domain assessment, never collision or motion admission."""
from __future__ import annotations

import json

from .hardware_profile import _fields, _number, _vector
from .manipulation_plan import JointTrajectoryPoint
from .motion_characteristics import (
    _bounds, _canonical, _count, _joint_map, _text, document_digest, validate_characteristics,
)

ASSESSOR_REVISION = 'measured-envelope-quintic-v1'


def validate_request(profile, request):
    r = json.loads(_canonical(request))
    _fields(r, 'schema context task_id scene_revision source_sequence source_age_s start_at_rest '
            'start_positions_rad goal_positions_rad goal_tolerance_rad payload_mass_kg payload_com_min_m '
            'payload_com_max_m temperatures_c voltages_v hold_s cycle_count cycle_interval_s candidates', 'request')
    if r['schema'] != 'rosy.omx-load-request.v1':
        raise ValueError('unsupported load request schema')
    if r['context'] != profile['binding']:
        raise ValueError('request binding does not match measured device configuration')
    for key in ('task_id', 'scene_revision'):
        _text(r[key], key)
    if type(r['source_sequence']) is not int or not 0 <= r['source_sequence'] <= 2**63 - 1:
        raise ValueError('source_sequence: expected bounded nonnegative integer')
    age = _number(r['source_age_s'], 'source_age_s')
    if not 0 <= age <= profile['monitor']['max_age_s'] or r['start_at_rest'] is not True:
        raise ValueError('request requires fresh initial state at rest')
    for key in ('start_positions_rad', 'goal_positions_rad', 'temperatures_c', 'voltages_v'):
        for value in _joint_map(r[key], profile['joints'], key).values():
            _number(value, key)
    _number(r['goal_tolerance_rad'], 'goal_tolerance_rad', positive=True)
    _bounds(r['payload_mass_kg'], 'payload_mass_kg', nonnegative=True)
    low = _vector(r['payload_com_min_m'], 3, 'payload_com_min_m')
    high = _vector(r['payload_com_max_m'], 3, 'payload_com_max_m')
    if any(a > b for a, b in zip(low, high)):
        raise ValueError('invalid payload COM bounds')
    for key in ('hold_s', 'cycle_interval_s'):
        if _number(r[key], key) < 0:
            raise ValueError(f'{key}: expected nonnegative value')
    _count(r['cycle_count'], 'cycle_count')
    candidates = r['candidates']
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 128:
        raise ValueError('expected bounded candidate list')
    seen = set()
    for candidate in candidates:
        _fields(candidate, 'id joint_names points', 'candidate')
        _text(candidate['id'], 'candidate.id')
        if candidate['id'] in seen:
            raise ValueError('duplicate candidate id')
        seen.add(candidate['id'])
        if candidate['joint_names'] != list(profile['joints']):
            raise ValueError('candidate joint order must match canonical characteristics order')
        _points(candidate)
    return r


def _points(candidate):
    points = candidate['points']
    if not isinstance(points, list) or not 1 <= len(points) <= 2000:
        raise ValueError('expected bounded nonempty timed points')
    result, previous = [], 0.
    for p in points:
        _fields(p, 'time_from_start_s positions velocities accelerations', 'point')
        stamp = _number(p['time_from_start_s'], 'time_from_start_s', positive=True)
        if stamp <= previous:
            raise ValueError('trajectory time must strictly increase')
        previous = stamp
        n = len(candidate['joint_names'])
        vectors = {key: tuple(_vector(p[key], n, key)) for key in ('positions', 'velocities', 'accelerations')}
        result.append(JointTrajectoryPoint(time_from_start_s=stamp, **vectors))
    return result


def _segments(request, candidate):
    names = candidate['joint_names']
    q0 = tuple(request['start_positions_rad'][n] for n in names)
    v0 = a0 = (0.,) * len(names)
    t0 = 0.
    for point in _points(candidate):
        duration = point.time_from_start_s - t0
        controls = []
        for q, v, a, q1, v1, a1 in zip(q0, v0, a0, point.positions, point.velocities, point.accelerations):
            # Quintic Hermite in Bernstein form: the convex hull bounds the WHOLE segment.
            values = [q, q + v * duration / 5, q + 2 * v * duration / 5 + a * duration**2 / 20,
                      q1 - 2 * v1 * duration / 5 + a1 * duration**2 / 20, q1 - v1 * duration / 5, q1]
            for value in values:
                _number(value, 'quintic control point')
            controls.append(values)
        yield t0, point.time_from_start_s, controls
        q0, v0, a0, t0 = point.positions, point.velocities, point.accelerations, point.time_from_start_s


def _curve(control, fraction):
    values = list(control)
    while len(values) > 1:
        values = [(1 - fraction) * a + fraction * b for a, b in zip(values, values[1:])]
    return values[0]


def command_positions(request, candidate_id, elapsed_s):
    """Command reference at measurement time, including only the requested final hold."""
    elapsed = _number(elapsed_s, 'elapsed_s')
    if elapsed < 0:
        raise ValueError('measurement predates command')
    candidate = next((c for c in request['candidates'] if c['id'] == candidate_id), None)
    if candidate is None:
        raise ValueError('unknown candidate')
    for start, end, controls in _segments(request, candidate):
        if elapsed <= end:
            fraction = (elapsed - start) / (end - start)
            return tuple(_curve(control, fraction) for control in controls)
    last = candidate['points'][-1]
    if elapsed > last['time_from_start_s'] + request['hold_s']:
        raise ValueError('measurement is outside command and final hold')
    return tuple(last['positions'])


def _within(value, bounds):
    return bounds[0] <= value <= bounds[1]


def environment_reasons(envelope, request):
    reasons = []
    if any(not _within(v, envelope['payload_mass_kg']) for v in request['payload_mass_kg']):
        reasons.append('payload_mass')
    if any(a < low or b > high for a, b, low, high in zip(
            request['payload_com_min_m'], request['payload_com_max_m'],
            envelope['payload_com_min_m'], envelope['payload_com_max_m'])):
        reasons.append('payload_com')
    for key, domain in (('temperatures_c', 'temperature_c'), ('voltages_v', 'voltage_v')):
        if any(not _within(v, envelope[domain]) for v in request[key].values()):
            reasons.append(domain)
    for field, limit in (('hold_s', 'max_hold_s'), ('cycle_count', 'max_cycles')):
        if request[field] > envelope[limit]:
            reasons.append(field)
    if request['cycle_interval_s'] < envelope['min_cycle_interval_s']:
        reasons.append('cycle_interval_s')
    return reasons


def _trajectory_reasons(profile, request, candidate, envelope):
    reasons = environment_reasons(envelope, request)
    names = candidate['joint_names']
    last = _points(candidate)[-1]
    if last.time_from_start_s > envelope['max_motion_s']:
        reasons.append('motion_duration')
    if any(abs(last.positions[i] - request['goal_positions_rad'][name]) > request['goal_tolerance_rad']
           for i, name in enumerate(names)):
        reasons.append('goal_mismatch')
    if any(v != 0 for v in (*last.velocities, *last.accelerations)):
        reasons.append('final_state_not_at_rest')
    try:
        for start, end, controls in _segments(request, candidate):
            duration = end - start
            for name, control in zip(names, controls):
                if any(not _within(v, envelope['position_rad'][name]) for v in control):
                    reasons.append(f'position:{name}')
                velocity = [(b - a) * 5 / duration for a, b in zip(control, control[1:])]
                acceleration = [(b - a) * 4 / duration for a, b in zip(velocity, velocity[1:])]
                for values, limit, label in (
                    (velocity, envelope['max_velocity_rad_s'][name], 'velocity'),
                    (acceleration, envelope['max_acceleration_rad_s2'][name], 'acceleration'),
                ):
                    if any(abs(_number(v, label)) > limit for v in values):
                        reasons.append(f'{label}:{name}')
    except (ValueError, OverflowError, ZeroDivisionError):
        reasons.append('unrepresentable_trajectory')
    return sorted(set(reasons))


def assess_candidates(document, request, *, accepted_digest):
    """Suggest only a load-domain match; caller pinning is separate from motion authority."""
    profile = validate_characteristics(document)
    digest = document_digest(profile)
    if digest != accepted_digest:
        raise ValueError('characteristics digest does not match externally accepted pin')
    if profile['status'] != 'measured':
        raise ValueError('characteristics must contain measured domains')
    r = validate_request(profile, request)
    results, ranked = [], []
    for candidate in r['candidates']:
        matches, failures = [], []
        for envelope in profile['envelopes']:
            reasons = _trajectory_reasons(profile, r, candidate, envelope)
            if reasons:
                failures.extend(f"{envelope['id']}:{reason}" for reason in reasons)
            else:
                matches.append((envelope['measured_tracking_error_rad'], envelope['id']))
        match = min(matches) if matches else None
        duration = candidate['points'][-1]['time_from_start_s']
        result = {'id': candidate['id'], 'load_domain_match': match is not None,
                  'matched_envelope_id': None if match is None else match[1],
                  'trajectory_sha256': document_digest(candidate), 'duration_s': duration,
                  'reasons': sorted(set(failures)) if match is None else []}
        results.append(result)
        if match:
            ranked.append((match[0], duration, candidate['id']))
    return {'schema': 'rosy.omx-load-assessment.v1', 'assessor_revision': ASSESSOR_REVISION,
            'characteristics_sha256': digest, 'characteristics_revision': profile['revision'],
            'request_sha256': document_digest(r), 'context': r['context'], 'task_id': r['task_id'],
            'scene_revision': r['scene_revision'], 'source_sequence': r['source_sequence'],
            'selected_candidate_id': min(ranked)[2] if ranked else None,
            'candidates': sorted(results, key=lambda x: x['id']), 'collision_status': 'not_checked',
            'motion_admitted': False, 'automatic_recovery_enabled': False}
