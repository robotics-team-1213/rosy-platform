import math

import pytest

from control.control.adaptive_speed import (
    OperatingConditions,
    RuntimeEvidence,
    limit_command,
)
from control.control.commissioning_certificate import (
    make_geometry_candidate,
    make_motion_envelope_candidate,
    promote_geometry_candidate,
    promote_motion_envelope_candidate,
    validate_motion_envelope_certificate,
)


def uncertainty(value=1.0):
    return {'value': value, 'std': .01, 'ci95': [value-.02, value+.02]}


def active_geometry():
    context = {'robot_id': 'rosy_01', 'hardware_model': 'Pinky Pro',
               'geometry_revision': 'g1', 'sensor_revision': 's1',
               'data_generation': 'd1'}
    candidate = make_geometry_candidate(
        context=context, session='geometry-train',
        estimator={'name': 'joint', 'version': '1'}, evidence_digests=['a'*64],
        estimates={name: uncertainty() for name in (
            'wheel_radius_common_multiplier', 'wheel_radius_left_multiplier',
            'wheel_radius_right_multiplier', 'effective_separation_multiplier')},
        quality={'excitation_rank': 4,
                 'train_residuals': {'linear_rmse_m': .002, 'yaw_rmse_rad': .01},
                 'trials_by_direction': {'forward': 2, 'reverse': 2, 'cw': 2, 'ccw': 2}})
    return promote_geometry_candidate(candidate, {
        'session': 'geometry-holdout', 'candidate_digest': candidate['digest'],
        'passed': True, 'residuals': {'linear_rmse_m': .003, 'yaw_rmse_rad': .02},
        'evidence_digests': ['b'*64]})


CONDITIONS = {
    'surface_class': 'vinyl', 'payload_range_g': [0., 300.],
    'battery_voltage_range_v': [7.2, 8.4], 'imu_temperature_range_c': [15., 45.],
    'tire_or_wheel_revision': 'wheel-v1',
}


def bins():
    rows = []
    for direction in ('forward', 'reverse'):
        rows.extend([
            {'speed_mps': .014, 'direction': direction, 'trials': 6,
             'command_to_decel_p99_s': .10, 'decel_lower_bound_mps2': .10,
             'stop_distance_upper_m': .012, 'lateral_error_upper_m': .004},
            {'speed_mps': .03, 'direction': direction, 'trials': 6,
             'command_to_decel_p99_s': .12, 'decel_lower_bound_mps2': .08,
             'stop_distance_upper_m': .025, 'lateral_error_upper_m': .006},
        ])
    return rows


def active_envelope():
    geometry = active_geometry()
    candidate = make_motion_envelope_candidate(
        geometry_certificate=geometry, session='motion-train', conditions=CONDITIONS,
        speed_bins=bins(), evidence_digests=['c'*64])
    return promote_motion_envelope_candidate(candidate, {
        'session': 'motion-holdout', 'candidate_digest': candidate['digest'],
        'passed': True, 'residuals': {'stop_distance_error_m': .004, 'lateral_error_m': .003},
        'evidence_digests': ['d'*64]})


def operating(**changes):
    values = dict(surface_class='vinyl', payload_g=100., battery_voltage_v=7.8,
                  imu_temperature_c=25., tire_or_wheel_revision='wheel-v1')
    values.update(changes)
    return OperatingConditions(**values)


def evidence(**changes):
    values = dict(observed_at=10., expires_at=10.2, front_clearance_m=.5,
                  rear_clearance_m=.5, side_clearance_m=.08,
                  footprint_uncertainty_m=.002, extrinsic_uncertainty_m=.002,
                  localization_uncertainty_m=.003, sensor_health=True,
                  localization_ready=True, drift_ok=True)
    values.update(changes)
    return RuntimeEvidence(**values)


def test_motion_envelope_is_bound_to_active_geometry_and_holdout():
    envelope = active_envelope()
    assert envelope['status'] == 'active'
    assert envelope['authorized_max_linear_mps'] == .03
    assert validate_motion_envelope_certificate(envelope, active_only=True) == envelope

    geometry = active_geometry()
    candidate = make_motion_envelope_candidate(
        geometry_certificate=geometry, session='same', conditions=CONDITIONS,
        speed_bins=bins(), evidence_digests=['e'*64])
    with pytest.raises(ValueError):
        promote_motion_envelope_candidate(candidate, {
            'session': 'same', 'candidate_digest': candidate['digest'], 'passed': True,
            'residuals': {'stop_distance_error_m': .001, 'lateral_error_m': .001},
            'evidence_digests': ['f'*64]})


@pytest.mark.parametrize('change', [
    {'command_to_decel_p99_s': -1.}, {'decel_lower_bound_mps2': 0.},
    {'stop_distance_upper_m': float('nan')}, {'lateral_error_upper_m': -.1},
    {'trials': 1},
])
def test_motion_envelope_rejects_unmeasured_or_nonfinite_bins(change):
    geometry = active_geometry()
    invalid = bins()
    invalid[0].update(change)
    with pytest.raises(ValueError):
        make_motion_envelope_candidate(
            geometry_certificate=geometry, session='motion-train', conditions=CONDITIONS,
            speed_bins=invalid, evidence_digests=['c'*64])


def test_default_hardware_ceiling_keeps_measured_high_bin_locked():
    decision = limit_command(.05, .2, active_envelope(), operating(), evidence(), 10.1)
    assert decision.linear == pytest.approx(.014)
    assert decision.angular == pytest.approx(.2 * .014/.05)
    assert decision.limit_mps == .014
    assert decision.tier == 'CRAWL'
    assert decision.reason == 'hardware_ceiling'


def test_explicit_commissioned_ceiling_uses_highest_measured_bin_but_never_upscales():
    envelope = active_envelope()
    fast = limit_command(.05, 0., envelope, operating(), evidence(), 10.1,
                         hardware_ceiling_mps=.06)
    slow = limit_command(.01, 0., envelope, operating(), evidence(), 10.1,
                         hardware_ceiling_mps=.06)
    assert fast.linear == pytest.approx(.03)
    assert fast.tier == 'LOW'
    assert slow.linear == pytest.approx(.01)


def test_clearance_continuously_reduces_speed_using_conservative_stop_model():
    open_result = limit_command(.03, .2, active_envelope(), operating(), evidence(), 10.1,
                                hardware_ceiling_mps=.06)
    tight_result = limit_command(.03, .2, active_envelope(), operating(),
                                 evidence(front_clearance_m=.145), 10.1,
                                 hardware_ceiling_mps=.06)
    assert 0. < tight_result.linear < open_result.linear
    assert tight_result.angular/tight_result.linear == pytest.approx(.2/.03)
    assert tight_result.reason == 'clearance_limit'
    assert tight_result.required_distance_m > .12


def test_unknown_stale_or_out_of_band_evidence_stops_fail_closed():
    envelope = active_envelope()
    cases = [
        (operating(surface_class='carpet'), evidence(), 10.1, 'condition_mismatch'),
        (operating(), evidence(sensor_health=False), 10.1, 'sensor_unhealthy'),
        (operating(), evidence(localization_ready=False), 10.1, 'localization_unavailable'),
        (operating(), evidence(front_clearance_m=math.inf), 10.1, 'clearance_unknown'),
        (operating(), evidence(), 10.3, 'evidence_expired'),
    ]
    for condition, runtime, now, reason in cases:
        decision = limit_command(.01, .1, envelope, condition, runtime, now,
                                 hardware_ceiling_mps=.06)
        assert (decision.linear, decision.angular, decision.reason) == (0., 0., reason)


def test_drift_immediately_downgrades_to_crawl_without_relearning():
    decision = limit_command(.03, 0., active_envelope(), operating(),
                             evidence(drift_ok=False), 10.1, hardware_ceiling_mps=.06)
    assert decision.linear == pytest.approx(.014)
    assert decision.tier == 'CRAWL'
    assert decision.reason == 'runtime_downgrade'
