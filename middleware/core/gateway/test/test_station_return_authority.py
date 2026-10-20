"""A station return uses the existing trip lease and the actual final output guard."""
import threading
from types import SimpleNamespace

import pytest

from core.bridge.docking_mode import motion_ready
from core_api_web.api.deps import Mode
from test_station_docking_api import station_api
from test_cmd_vel_cycle import run
from middleware.core.gateway.test.test_core_trip_lease import STATION_FENCED


def prepared(station_api):
    client, svc, now, auth, binding, _ = station_api
    svc.trip_lease._monotonic = lambda: now[0]
    local = svc.station_docking.local_scope
    svc.station_docking.local_scope = lambda: local() | dict(mode=svc.modes.mode.value)
    svc.station_docking.local_scope_nowait = svc.station_docking.local_scope
    assert client.put('/api/v1/docking/station-target', json=binding, headers=auth['fleet-a']).status_code == 200
    response = client.put('/api/v1/trip-lease', headers=auth['fleet-a'], json=dict(
        lease_id='return-lease', trip_id='return-plan', job_id='charge-1', holder='station',
        operator_name='sim-operator', ttl_s=5.))
    assert response.status_code == 200, response.text
    permit = {key: binding['session'][key] for key in ('robot_id', 'station_id', 'battery_id', 'session_id',
        'boot_id', 'map_id', 'map_revision', 'pose_revision')}
    permit.update(correlation_id='return-1', lease_id='return-lease', trip_id='return-plan',
                  expected_owner_generation=0, captured_at=now[0], valid_until=now[0]+2.)
    return client, svc, now, auth, permit


def grant(client, auth, permit, principal='fleet-a'):
    return client.put('/api/v1/docking/station-return', json=permit, headers=auth[principal])


def test_return_grant_does_not_move_but_allows_only_the_live_scoped_navigation(station_api):
    client, svc, _, auth, permit = prepared(station_api)
    assert run(motion_ready=lambda: motion_ready(svc)).sent == [(0., 0.)]
    response = grant(client, auth, permit)
    assert response.status_code == 200, response.text
    assert response.json()['return_ready']
    assert response.json()['return_permit'] == permit
    assert svc.docking.native.current is None and svc.modes.mode is Mode.IDLE
    svc.modes.transition(Mode.NAVIGATION)
    assert run(motion_ready=lambda: motion_ready(svc)).sent == [(0.2, 0.)]
    assert not svc.station_docking.motion_ready('DOCKING')


@pytest.mark.parametrize('change', [dict(trip_id='other'), dict(lease_id='other'),
    dict(session_id='other'), dict(pose_revision=2), dict(map_revision='other'),
    dict(boot_id='old'), dict(battery_id='other'), dict(expected_owner_generation=9)])
def test_wrong_lease_scope_or_native_fence_never_allows_output(station_api, change):
    client, svc, _, auth, permit = prepared(station_api)
    assert grant(client, auth, permit | change).status_code == 409
    svc.modes.transition(Mode.NAVIGATION)
    assert run(motion_ready=lambda: motion_ready(svc)).sent == [(0., 0.)]


def test_only_the_binding_fleet_and_actual_lease_owner_can_grant_return(station_api):
    client, _, _, auth, permit = prepared(station_api)
    assert grant(client, auth, permit, 'human').status_code == 403
    assert grant(client, auth, permit, 'fleet-b').status_code == 403


@pytest.mark.parametrize('fault', ['permit_expired', 'lease_released', 'lease_expired', 'scope',
                                 'boot', 'native', 'pose', 'manual', 'estop', 'reopened'])
def test_return_loss_closes_output_and_cannot_resurrect_by_replaying_grant(station_api, fault):
    client, svc, now, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    svc.modes.transition(Mode.NAVIGATION)
    if fault == 'permit_expired':
        now[0] += 2.1
    elif fault == 'lease_expired':
        svc.trip_lease._monotonic = lambda: now[0]+6.
    elif fault == 'scope':
        original = svc.station_docking.local_scope_nowait
        svc.station_docking.local_scope_nowait = lambda: original() | dict(map_revision='changed')
    elif fault == 'boot':
        original = svc.station_docking.local_scope_nowait
        svc.station_docking.local_scope_nowait = lambda: original() | dict(boot_id='new-boot')
    elif fault == 'native':
        with svc.docking._lock:
            svc.docking.native.admit('dock', 'unexpected')
    elif fault == 'pose':
        owner = svc.station_docking
        owner.target = owner.target.model_copy(update={'pose_revision': 2})
    elif fault == 'manual':
        svc.modes.transition(Mode.MANUAL)
    elif fault == 'estop':
        svc.safety.trigger_estop('station-test')
    else:
        assert client.delete('/api/v1/trip-lease/return-lease', headers=auth['fleet-a']).status_code == 200
        if fault == 'reopened':
            assert client.put('/api/v1/trip-lease', headers=auth['fleet-a'], json=dict(
                lease_id='new-lease', trip_id='return-plan', job_id='charge-1', holder='station',
                operator_name='sim-operator', ttl_s=5.)).status_code == 200
    if fault == 'manual':
        # Manual rescue follows existing arbitration; the automatic owner is closed.
        assert svc.station_docking.state == 'HOLD'
        svc.modes.transition(Mode.IDLE)
    assert run(motion_ready=lambda: motion_ready(svc)).sent == [(0., 0.)]
    assert grant(client, auth, permit).status_code == 409


@pytest.mark.parametrize('resource', ['trip_lease', 'docking'])
def test_authority_lock_contention_never_blocks_final_output(station_api, resource):
    client, svc, _, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    svc.modes.transition(Mode.NAVIGATION)
    done, outcomes = threading.Event(), []
    def cycle():
        outcomes.extend(run(motion_ready=lambda: motion_ready(svc)).sent)
        done.set()
    with getattr(svc, resource)._lock:
        thread = threading.Thread(target=cycle, daemon=True)
        thread.start()
        assert done.wait(0.5), 'final publisher waited for authority lock'
    thread.join(1.)
    assert outcomes == [(0., 0.)]
    assert run(motion_ready=lambda: motion_ready(svc)).sent == [(0.2, 0.)]


def test_return_finish_requires_distinct_fresh_measured_stop_before_docking_handover(station_api):
    client, svc, now, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    command = dict(session_id='charge-1', correlation_id='return-1',
                   expected_boot_id=permit['boot_id'], expected_owner_generation=0)
    finish = lambda: client.post('/api/v1/docking/station-return/finish', json=command, headers=auth['fleet-a'])
    assert finish().status_code == 409
    motion = dict(odom_epoch='odom-1', captured_at=now[0], valid_until=now[0]+0.25,
                  measured_linear_m_s=0., measured_angular_rad_s=0.)
    svc.station_docking.motion_feed = SimpleNamespace(snapshot=lambda: dict(motion), clear=lambda: None)
    for _ in range(6):
        now[0] += 0.1
        motion.update(captured_at=now[0], valid_until=now[0]+0.25)
        svc.station_docking.tick()
    response = finish()
    assert response.status_code == 200, response.text
    assert svc.station_docking.state == 'BOUND' and svc.docking.native.current is None
    assert not svc.station_docking.motion_ready('NAVIGATION')
    assert finish().status_code == 409
    assert grant(client, auth, permit).status_code == 409


@pytest.mark.parametrize('fault', ['moving', 'duplicate', 'stale', 'epoch', 'mode'])
def test_return_finish_cannot_use_missing_standstill_evidence(station_api, fault):
    client, svc, now, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    if fault == 'mode':
        svc.modes.transition(Mode.NAVIGATION)
    motion = dict(odom_epoch='odom-1', captured_at=now[0], valid_until=now[0]+0.25,
                  measured_linear_m_s=0., measured_angular_rad_s=0.)
    svc.station_docking.motion_feed = SimpleNamespace(snapshot=lambda: dict(motion), clear=lambda: None)
    for _ in range(6):
        now[0] += 0.1
        if fault != 'duplicate':
            motion.update(captured_at=now[0], valid_until=now[0]+0.25)
        if fault == 'moving':
            motion['measured_linear_m_s'] = 0.02
        elif fault == 'stale':
            motion.update(captured_at=now[0]-1., valid_until=now[0]-0.5)
        elif fault == 'epoch':
            motion['odom_epoch'] = 'other'
        svc.station_docking.tick()
    command = dict(session_id='charge-1', correlation_id='return-1',
                   expected_boot_id=permit['boot_id'], expected_owner_generation=0)
    assert client.post('/api/v1/docking/station-return/finish', json=command,
                        headers=auth['fleet-a']).status_code == 409


def test_transient_state_scope_contention_stops_without_latching_authority_loss(station_api):
    client, svc, _, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    svc.modes.transition(Mode.NAVIGATION)
    original = svc.station_docking.local_scope_nowait
    svc.station_docking.local_scope_nowait = lambda: None
    assert run(motion_ready=lambda: motion_ready(svc)).sent == [(0., 0.)]
    svc.station_docking.local_scope_nowait = original
    assert run(motion_ready=lambda: motion_ready(svc)).sent == [(0.2, 0.)]


@pytest.mark.parametrize('field', ['map_revision', 'odom_epoch'])
def test_observed_scope_loss_is_latched_even_if_scope_restores_before_next_owner_tick(station_api, field):
    client, svc, _, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    svc.modes.transition(Mode.NAVIGATION)
    original = svc.station_docking.local_scope_nowait
    svc.station_docking.local_scope_nowait = lambda: original() | {field: 'changed'}
    assert run(motion_ready=lambda: motion_ready(svc)).sent == [(0., 0.)]
    svc.station_docking.local_scope_nowait = original
    assert run(motion_ready=lambda: motion_ready(svc)).sent == [(0., 0.)]
    assert grant(client, auth, permit).status_code == 409


def test_return_ready_readback_cannot_outlive_unrounded_existing_lease(station_api):
    client, svc, now, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    svc.trip_lease._monotonic = lambda: now[0]+4.98
    response = client.get('/api/v1/docking/station-target', headers=auth['human'])
    assert response.status_code == 200
    assert response.json()['return_ready']
    assert response.json()['valid_until'] <= now[0]+0.021


@pytest.mark.parametrize('method,path', STATION_FENCED)
def test_even_binding_principal_is_fenced_by_another_trip_lease_owner(station_api, method, path):
    client, svc, _, auth, permit = prepared(station_api)
    assert client.delete('/api/v1/trip-lease/return-lease', headers=auth['fleet-a']).status_code == 200
    response = client.put('/api/v1/trip-lease', headers=auth['fleet-b'], json=dict(
        lease_id='other-lease', trip_id='other-plan', holder='other', operator_name='other-operator', ttl_s=5.))
    assert response.status_code == 200, response.text
    if path.endswith('/station-target'):
        body = station_api[4]
    elif path.endswith('/station-return'):
        body = permit
    elif path.endswith(('/station-undock', '/station-departure')):
        from test_station_departure_api import permit as departure_permit
        body = departure_permit(station_api[4])
    else:
        body = dict(session_id='charge-1', correlation_id='return-1',
                    expected_boot_id=permit['boot_id'], expected_owner_generation=0)
    response = getattr(client, method)(path, json=body, headers=auth['fleet-a'])
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'TRIP_LEASED'
    assert svc.docking.native.current is None and svc.station_docking.state == 'BOUND'
