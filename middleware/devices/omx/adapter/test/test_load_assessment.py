"""Synthetic certified domains; every result remains advisory."""
from copy import deepcopy

import pytest

from load_motion_fixtures import characteristics, request
from omx_adapter.motion_characteristics import characteristics_digest
from omx_adapter.load_assessment import assess_candidates, command_positions


def assess(p, r):
    return assess_candidates(p, r, accepted_digest=characteristics_digest(p))


def test_selects_only_load_candidate_and_records_all_input_provenance():
    p, r = characteristics(), request()
    out = assess(p, r)
    assert out['selected_candidate_id'] == 'direct'
    assert out['motion_admitted'] is False
    assert out['automatic_recovery_enabled'] is False
    assert out['characteristics_sha256'] == characteristics_digest(p)
    assert out['source_sequence'] == 7
    assert out['collision_status'] == 'not_checked'
    assert len(out['request_sha256']) == len(out['candidates'][0]['trajectory_sha256']) == 64


@pytest.mark.parametrize('field', list(characteristics()['binding']))
def test_every_device_configuration_binding_is_checked(field):
    p, r = characteristics(), request()
    r['context'][field] = 'b' * 64 if field == 'robot_model_sha256' else 'other-device-or-config'
    with pytest.raises(ValueError, match='binding'):
        assess(p, r)


def test_unpinned_or_draft_measurements_cannot_be_used():
    p, r = characteristics(), request()
    with pytest.raises(ValueError, match='digest'):
        assess_candidates(p, r, accepted_digest='b' * 64)
    p['status'] = 'draft'
    with pytest.raises(ValueError, match='measured'):
        assess(p, r)


@pytest.mark.parametrize('field,value', [
    ('hold_s', 3.), ('cycle_count', 4), ('cycle_interval_s', .5),
    ('payload_mass_kg', [.1, .11]), ('payload_com_max_m', [.02, .001, .001]),
    ('temperatures_c', {'joint2': 50., 'joint3': 25.}),
    ('voltages_v', {'joint2': 10., 'joint3': 12.}),
])
def test_conditions_outside_measured_domain_produce_no_fallback(field, value):
    p, r = characteristics(), request()
    r[field] = value
    out = assess(p, r)
    assert out['selected_candidate_id'] is None
    assert out['candidates'][0]['reasons']


@pytest.mark.parametrize('mutate', [
    lambda r: r.update(source_age_s=1.),
    lambda r: r.update(start_at_rest=False),
    lambda r: r.update(payload_mass_kg=None),
    lambda r: r.update(goal_tolerance_rad=True),
    lambda r: r.update(unknown=True),
    lambda r: r['start_positions_rad'].pop('joint3'),
    lambda r: r['candidates'][0].update(joint_names=['joint3', 'joint2']),
    lambda r: r['candidates'][0]['points'][0].update(time_from_start_s=float('nan')),
])
def test_incomplete_or_unusable_request_is_rejected(mutate):
    p, r = characteristics(), request()
    mutate(r)
    with pytest.raises(ValueError):
        assess(p, r)


def test_full_quintic_segment_is_checked_not_only_waypoints():
    p, r = characteristics(), request()
    r['goal_positions_rad'] = {'joint2': 0., 'joint3': 0.}
    points = r['candidates'][0]['points']
    points[0].update(time_from_start_s=1., positions=[0., 0.], velocities=[4., 0.])
    points.append({'time_from_start_s': 2., 'positions': [0., 0.],
                   'velocities': [0., 0.], 'accelerations': [0., 0.]})
    out = assess(p, r)
    assert out['selected_candidate_id'] is None
    assert any('position' in reason for reason in out['candidates'][0]['reasons'])


def test_between_waypoint_speed_and_acceleration_are_bounded():
    p, r = characteristics(), request()
    r['candidates'][0]['points'][0]['time_from_start_s'] = .01
    out = assess(p, r)
    assert out['selected_candidate_id'] is None
    reasons = out['candidates'][0]['reasons']
    assert any('velocity' in x for x in reasons)
    assert any('acceleration' in x for x in reasons)


def test_goal_mismatch_and_non_rest_final_state_are_rejected():
    p, r = characteristics(), request()
    r['goal_positions_rad']['joint2'] = .5
    assert assess(p, r)['selected_candidate_id'] is None
    r = request()
    r['candidates'][0]['points'][0]['velocities'] = [.01, 0.]
    assert assess(p, r)['selected_candidate_id'] is None


def test_certified_domain_must_cover_start_and_final_hold():
    p, r = characteristics(), request()
    r['start_positions_rad']['joint2'] = -.7
    assert assess(p, r)['selected_candidate_id'] is None
    r = request()
    r['goal_positions_rad']['joint2'] = .7
    r['candidates'][0]['points'][0]['positions'][0] = .7
    assert assess(p, r)['selected_candidate_id'] is None


def test_candidate_and_domain_selection_are_deterministic():
    p, r = characteristics(), request()
    candidate = deepcopy(r['candidates'][0])
    candidate['id'] = 'alternative'
    candidate['points'][0]['time_from_start_s'] = 3.
    r['candidates'].append(candidate)
    a = assess(p, r)
    r['candidates'].reverse()
    b = assess(p, r)
    assert a['selected_candidate_id'] == b['selected_candidate_id'] == 'direct'


def test_command_interpolation_uses_timed_trajectory_and_final_hold():
    r = request()
    assert command_positions(r, 'direct', 0.) == pytest.approx((0., 0.))
    assert command_positions(r, 'direct', 1.) == pytest.approx((.1, .1))
    assert command_positions(r, 'direct', 2.2) == pytest.approx((.2, .2))
    with pytest.raises(ValueError):
        command_positions(r, 'direct', 3.)
