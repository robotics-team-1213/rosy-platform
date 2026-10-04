import copy

import pytest

from control.control.commissioning_certificate import (
    make_geometry_candidate,
    promote_geometry_candidate,
    validate_geometry_certificate,
)


CONTEXT = {
    'robot_id': 'rosy_01',
    'hardware_model': 'Pinky Pro',
    'geometry_revision': 'geometry-v1',
    'sensor_revision': 'sensors-v1',
    'data_generation': 'generation-7',
}


def estimate(value=1.0, std=.01):
    return {'value': value, 'std': std, 'ci95': [value-2*std, value+2*std]}


def candidate():
    return make_geometry_candidate(
        context=CONTEXT,
        session='train-1',
        estimator={'name': 'rosy_joint_diffdrive_lidar', 'version': '1.0'},
        evidence_digests=['a'*64, 'b'*64],
        estimates={
            'wheel_radius_common_multiplier': estimate(1.01),
            'wheel_radius_left_multiplier': estimate(.99),
            'wheel_radius_right_multiplier': estimate(1.02),
            'effective_separation_multiplier': estimate(1.03),
        },
        quality={
            'excitation_rank': 4,
            'train_residuals': {'linear_rmse_m': .003, 'yaw_rmse_rad': .01},
            'trials_by_direction': {'forward': 2, 'reverse': 2, 'cw': 2, 'ccw': 2},
        },
    )


def holdout(record, **changes):
    value = {
        'session': 'holdout-1',
        'candidate_digest': record['digest'],
        'passed': True,
        'residuals': {'linear_rmse_m': .004, 'yaw_rmse_rad': .02},
        'evidence_digests': ['c'*64],
    }
    value.update(changes)
    return value


def test_candidate_is_context_bound_finite_and_defensively_copied():
    source_context = copy.deepcopy(CONTEXT)
    record = candidate()

    source_context['robot_id'] = 'changed'
    assert record['schema_version'] == 2
    assert record['status'] == 'candidate'
    assert record['context'] == CONTEXT
    assert len(record['digest']) == 64
    assert validate_geometry_certificate(record) == record

    validated = validate_geometry_certificate(record)
    validated['estimates']['wheel_radius_common_multiplier']['value'] = 9
    assert record['estimates']['wheel_radius_common_multiplier']['value'] == 1.01


@pytest.mark.parametrize('mutate', [
    lambda values: values['estimates']['wheel_radius_left_multiplier'].update(value=float('nan')),
    lambda values: values['estimates']['effective_separation_multiplier'].update(value=1.4),
    lambda values: values['estimates']['wheel_radius_common_multiplier'].update(std=-.1),
    lambda values: values['quality'].update(excitation_rank=3),
    lambda values: values['quality']['trials_by_direction'].update(cw=0),
    lambda values: values.update(evidence_digests=['not-a-digest']),
])
def test_candidate_rejects_unobservable_or_unbounded_evidence(mutate):
    kwargs = dict(
        context=copy.deepcopy(CONTEXT), session='train-1',
        estimator={'name': 'joint', 'version': '1'},
        evidence_digests=['a'*64],
        estimates={name: estimate() for name in (
            'wheel_radius_common_multiplier', 'wheel_radius_left_multiplier',
            'wheel_radius_right_multiplier', 'effective_separation_multiplier')},
        quality={'excitation_rank': 4,
                 'train_residuals': {'linear_rmse_m': .003, 'yaw_rmse_rad': .01},
                 'trials_by_direction': {'forward': 2, 'reverse': 2, 'cw': 2, 'ccw': 2}},
    )
    mutate(kwargs)
    with pytest.raises(ValueError):
        make_geometry_candidate(**kwargs)


def test_promotion_requires_independent_passing_holdout_bound_to_candidate():
    record = candidate()
    active = promote_geometry_candidate(record, holdout(record))

    assert active['status'] == 'active'
    assert active['source_candidate_digest'] == record['digest']
    assert active['holdout']['session'] == 'holdout-1'
    assert active['digest'] != record['digest']
    assert validate_geometry_certificate(active, CONTEXT, active_only=True) == active

    rejected = [
        holdout(record, session='train-1'),
        holdout(record, passed=False),
        holdout(record, candidate_digest='d'*64),
        holdout(record, residuals={'linear_rmse_m': .011, 'yaw_rmse_rad': .02}),
        holdout(record, residuals={'linear_rmse_m': .004, 'yaw_rmse_rad': .051}),
    ]
    for evidence in rejected:
        with pytest.raises(ValueError):
            promote_geometry_candidate(record, evidence)


def test_digest_prevents_direct_candidate_activation_or_context_reuse():
    record = candidate()
    forged = copy.deepcopy(record)
    forged['status'] = 'active'
    assert validate_geometry_certificate(forged, active_only=True) is None

    wrong_context = dict(CONTEXT, robot_id='rosy_02')
    assert validate_geometry_certificate(record, wrong_context) is None
