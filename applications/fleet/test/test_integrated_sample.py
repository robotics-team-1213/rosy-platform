"""Synthetic integrated reads and stop receipts reuse the sample's existing state, map and work."""
from copy import deepcopy

import pytest

from test_sample_flows import call
from test_sample_server import load_engine

PREFIX = '/api/fleet/control-unit'


def signed_in(scenario='normal'):
    engine = load_engine()
    if scenario != 'normal':
        engine.reset(scenario)
    assert call(engine, 'POST', '/api/fleet/auth/login', {'login': 'sample', 'password': 'CHANGE_ME'})[0] == 204
    return engine


def stop_request(engine, identity, target='R'):
    overview = call(engine, 'GET', PREFIX + '/overview')[1]
    included = engine.control_units.subtree(target)
    return {'stop_id': identity, 'target_unit': target, 'config_revision': overview['config_revision'],
            'expected_controls': {unit['unit_id']: unit['dispatch'] for unit in overview['units'] if unit['unit_id'] in included}}


def test_owned_information_reuses_current_roster_task_and_active_map_without_private_fields():
    engine = signed_in()
    overview = call(engine, 'GET', PREFIX + '/overview')[1]
    assert overview['unit_id'] == 'R' and overview['config_revision'].startswith('sample-')
    assert {row['unit_id']: row['parent'] for row in overview['units']} == {'R': None, 'A': 'R', 'A1': 'A', 'B': 'R'}
    assert all(row['age_s'] == 0.0 and row['availability'] == 'AVAILABLE' for row in overview['units'])
    assert call(engine, 'POST', '/api/fleet/robots/sample-robot/goal', {'x': 1, 'y': 2, 'yaw': 0},
                {'idempotency-key': 'integrated-task'})[0] == 200
    detail = call(engine, 'GET', PREFIX + '/units/R')[1]
    assert detail['robots'][0]['pose']['source'] == 'sample.synthetic'
    assert detail['robots'][0]['evidence'] == {'pose': 'fresh', 'battery': 'fresh', 'safety': 'fresh'}
    assert set(detail['tasks'][0]) == {'task_id', 'robot_id', 'status', 'updated_at'}
    assert detail['tasks'][0]['status'] == 'QUEUED'
    assert call(engine, 'GET', PREFIX + '/units/A1')[1]['robots'] == []
    assert call(engine, 'GET', PREFIX + '/units/A1')[1]['tasks'] == []
    geometry = call(engine, 'GET', PREFIX + '/units/R/map')[1]
    assert geometry['map'] == detail['map']
    assert geometry['places'][0] == {'id': 'home', 'label': '출발', 'x': 1, 'y': 1}
    assert set(geometry) == {'unit_id', 'config_revision', 'map', 'places', 'lanes'}
    draft = call(engine, 'GET', '/api/fleet/site-map/draft')[1]
    draft['map']['places'][0]['name'] = '변경한 합성 장소'
    call(engine, 'PUT', '/api/fleet/site-map/draft', {'map': draft['map'], 'expected_revision': draft['revision']})
    call(engine, 'POST', '/api/fleet/site-map/activate', {'expected_revision': draft['revision'] + 1})
    geometry = call(engine, 'GET', PREFIX + '/units/R/map')[1]
    assert geometry['map']['version'] == 2 and geometry['places'][0]['label'] == '변경한 합성 장소'
    assert call(engine, 'GET', PREFIX + '/units/foreign')[0] == 404
    assert call(engine, 'GET', PREFIX + '/units/A/map')[0] == 404
    assert call(engine, 'GET', PREFIX + '/stops/R/missing')[0] == 404
    assert call(engine, 'POST', PREFIX + '/stop-inbox', {})[0] == 403
    assert not engine.unhandled


def test_child_stop_is_one_shot_and_foreign_or_stale_fences_cannot_mutate_another_subtree():
    engine = signed_in()
    body = stop_request(engine, 'child:stop', 'A')
    before = deepcopy(engine.work.dispatch)
    code, snapshot = call(engine, 'POST', PREFIX + '/stops', body)
    assert code == 200 and {row['unit_id'] for row in snapshot['results']} == {'A', 'A1'}
    assert all(row['state'] == 'ACKNOWLEDGED' and row['physical_stop'] == 'UNVERIFIED' for row in snapshot['results'])
    assert engine.work.dispatch == before
    generations = deepcopy(engine.control_units.controls)
    assert call(engine, 'POST', PREFIX + '/stops', body) == (200, snapshot)
    assert call(engine, 'GET', PREFIX + '/stops/R/child%3Astop') == (200, snapshot)
    assert engine.control_units.controls == generations
    assert call(engine, 'POST', PREFIX + '/stops', body | {'target_unit': 'B'})[0] == 409
    assert call(engine, 'POST', PREFIX + '/stops', body | {'stop_id': 'stale-stop'})[0] == 409
    foreign = stop_request(engine, 'foreign-stop', 'A')
    foreign['expected_controls']['B'] = engine.control_units.fence('B')
    assert call(engine, 'POST', PREFIX + '/stops', foreign)[0] == 409
    bad = stop_request(engine, 'bad-stop', 'A')
    bad['expected_controls']['A']['generation'] = True
    assert call(engine, 'POST', PREFIX + '/stops', bad)[0] == 422
    assert len(engine.control_units.stops) == 1 and engine.control_units.controls == generations


def test_local_unknown_needs_explicit_attestation_and_never_becomes_physical_stop_proof():
    engine = signed_in()
    body = stop_request(engine, 'local-stop')
    code, snapshot = call(engine, 'POST', PREFIX + '/stops', body)
    assert code == 200
    local = next(row for row in snapshot['results'] if row['unit_id'] == 'R')
    assert local['state'] == 'UNKNOWN' and local['physical_stop'] == 'UNVERIFIED'
    dispatch = call(engine, 'GET', '/api/fleet/dispatch-control')[1]
    assert dispatch['dispatch_enabled'] is False and dispatch['rearm_available'] is False
    assert call(engine, 'POST', '/api/fleet/estop')[1]['rearm_available'] is False
    dispatch = call(engine, 'GET', '/api/fleet/dispatch-control')[1]
    assert dispatch['rearm_available'] is False
    assert call(engine, 'POST', '/api/fleet/dispatch/rearm', {'expected_generation': dispatch['generation']})[0] == 409
    history = call(engine, 'GET', PREFIX + '/stops')[1]['stops']
    assert history[0]['local_reconciliation_required'] and 'evidence' not in history[0]
    path = PREFIX + '/stops/R/local-stop/reconcile'
    attestation = {'expected_generation': dispatch['generation'], 'receiver_channels_terminated': True,
                   'receivers_recommissioned': True, 'affected_units': ['R'], 'evidence': '합성 전송 종료 및 receiver 재시운전 확인 예제'}
    assert call(engine, 'POST', path, attestation | {'receiver_channels_terminated': 1})[0] == 422
    assert call(engine, 'POST', path, attestation | {'affected_units': ['A']})[0] == 422
    assert call(engine, 'POST', path, attestation | {'expected_generation': -1})[0] == 422
    assert call(engine, 'POST', path, attestation | {'expected_generation': dispatch['generation'] + 1})[0] == 409
    code, reconciled = call(engine, 'POST', path, attestation)
    assert code == 200 and reconciled['revision'] == 2
    assert next(row for row in reconciled['results'] if row['unit_id'] == 'R')['state'] == 'SUPERSEDED_BY_OPERATOR_RECOMMISSIONING'
    assert all(row['physical_stop'] == 'UNVERIFIED' for row in reconciled['results'])
    assert engine.control_units.stops['local-stop']['attestation']['original_result']['state'] == 'UNKNOWN'
    assert call(engine, 'GET', '/api/fleet/dispatch-control')[1]['dispatch_enabled'] is False
    assert call(engine, 'POST', '/api/fleet/dispatch/rearm', {'expected_generation': dispatch['generation']})[0] == 200
    after = deepcopy(engine.work.dispatch)
    assert call(engine, 'POST', PREFIX + '/stops', body) == (200, reconciled)
    assert engine.work.dispatch == after
    assert not call(engine, 'GET', PREFIX + '/stops')[1]['stops'][0]['local_reconciliation_required']


def test_viewer_can_read_but_cannot_send_or_reconcile_synthetic_stops():
    engine = signed_in('viewer')
    assert call(engine, 'GET', PREFIX + '/overview')[0] == 200
    assert call(engine, 'GET', PREFIX + '/units/R/map')[0] == 200
    assert call(engine, 'POST', PREFIX + '/stops', stop_request(engine, 'viewer-stop'))[0] == 403
    assert call(engine, 'POST', PREFIX + '/stops/R/missing/reconcile', {})[0] == 403
    assert engine.control_units.stops == {}


@pytest.mark.parametrize('field,value', [('stop_id', ''), ('stop_id', '../bad'), ('expected_controls', {}), ('extra', True)])
def test_invalid_stop_requests_preserve_empty_journal(field, value):
    engine = signed_in()
    body = stop_request(engine, 'invalid-stop') | {field: value}
    assert call(engine, 'POST', PREFIX + '/stops', body)[0] == 422
    assert engine.control_units.stops == {}


def test_invalid_source_map_is_rejected_instead_of_becoming_an_integrated_geometry():
    engine = signed_in()
    engine.spatial.active['map']['places'][0]['x'] = True
    assert call(engine, 'GET', PREFIX + '/units/R/map')[0] == 422
    engine.spatial.active['map']['places'][0]['x'] = float('nan')
    assert call(engine, 'GET', PREFIX + '/units/R/map')[0] == 422
