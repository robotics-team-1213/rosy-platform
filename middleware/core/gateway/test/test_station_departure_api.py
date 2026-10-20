"""Departure routes require the installed profile and configured Fleet authority."""
import pytest

from test_station_docking_api import station_api  # noqa: F401
from test_station_camera_pipeline import pipeline_sources  # noqa: F401


def permit(binding):
    return {key: binding['session'][key] for key in (
        'robot_id', 'station_id', 'session_id', 'attempt_id', 'boot_id', 'battery_id',
        'map_id', 'map_revision', 'pose_revision')} | dict(
            correlation_id='undock-1', work_task_id='work-1', work_request_digest='a'*64,
            expected_owner_generation=0, policy_profile_revision='energy-1', capacity_revision='capacity-1',
            captured_at=100., valid_until=101.)


@pytest.mark.parametrize('method,path', [('post', 'station-undock'), ('put', 'station-departure')])
def test_only_configured_fleet_can_request_departure_and_absent_profile_is_closed(station_api, method, path):
    client, svc, _, auth, binding, _ = station_api
    assert client.put('/api/v1/docking/station-target', json=binding, headers=auth['fleet-a']).status_code == 200
    body = permit(binding)
    send = getattr(client, method)
    response = send('/api/v1/docking/'+path, json=body, headers=auth['human'])
    assert response.status_code == 403
    response = send('/api/v1/docking/'+path, json=body, headers=auth['fleet-a'])
    assert response.status_code == 409
    assert 'STATION_DEPARTURE_PROFILE_REQUIRED' in response.text
    assert svc.docking.native.current is None


def test_departure_finish_does_not_treat_ack_as_measured_release(station_api):
    client, svc, _, auth, binding, _ = station_api
    assert client.put('/api/v1/docking/station-target', json=binding, headers=auth['fleet-a']).status_code == 200
    body = dict(session_id='charge-1', correlation_id='undock-1',
        expected_boot_id=binding['session']['boot_id'], expected_owner_generation=0)
    response = client.post('/api/v1/docking/station-departure/finish', json=body, headers=auth['fleet-a'])
    assert response.status_code == 409
    assert svc.station_docking.state == 'BOUND' and svc.docking.native.current is None


@pytest.mark.parametrize('method,path', [('post', 'station-undock'), ('put', 'station-departure'),
    ('post', 'station-departure/finish')])
def test_another_trip_owner_fences_every_departure_write(station_api, method, path):
    client, svc, now, auth, binding, _ = station_api
    svc.trip_lease._monotonic = lambda: now[0]
    assert client.put('/api/v1/docking/station-target', json=binding, headers=auth['fleet-a']).status_code == 200
    response = client.put('/api/v1/trip-lease', headers=auth['human'], json=dict(
        lease_id='other-lease', trip_id='other-trip', job_id='other-job', holder='station',
        operator_name='SIM other owner', ttl_s=5.))
    assert response.status_code == 200, response.text
    body = permit(binding) if path != 'station-departure/finish' else dict(
        session_id='charge-1', correlation_id='undock-1', expected_boot_id=binding['session']['boot_id'],
        expected_owner_generation=0)
    response = getattr(client, method)('/api/v1/docking/'+path, json=body, headers=auth['fleet-a'])
    assert response.status_code == 409 and response.json()['error']['code'] == 'TRIP_LEASED'
    assert svc.docking.native.current is None


def test_explicit_installed_departure_profile_starts_with_empty_measurement_cache(core_client, pipeline_sources):
    from test_station_departure_feed import configured
    from test_station_docking_wiring import configured_station
    svc = configured_station(core_client, departure_profile=configured()[1].profile.model_dump())
    assert svc.station_docking.departure is not None
    assert svc.station_docking.departure.feed.snapshot_nowait() is None
    assert not svc.station_docking.motion_ready('DOCKING')


def test_http_start_and_finish_use_exact_native_owner_with_explicit_sim_measurements(station_api, pipeline_sources):
    from test_station_departure_owner import departure
    client, svc, _, auth, _, _ = station_api
    owner, manager, now, sample, permission = departure()
    # Isolate the HTTP adapter with the real native manager; bridge/mode wiring has its own tests.
    owner.principal_id = 'fleet-a'
    svc.station_docking, svc.docking = owner, manager
    response = client.post('/api/v1/docking/station-undock', json=permission.model_dump(), headers=auth['fleet-a'])
    assert response.status_code == 200, response.text
    native = response.json()['operation']
    assert native['kind'] == 'undock'
    assert client.post('/api/v1/docking/station-undock', json=permission.model_dump(),
        headers=auth['fleet-a']).status_code == 409
    for _ in range(100):
        owner.tick()
        if owner.state == 'DEPARTURE_CHECK':
            break
        manager.executor.step(.05)
        now[0] += .05
        sample(load_present=False, measured_linear_m_s=-.08)
    body = dict(session_id=permission.session_id, correlation_id=permission.correlation_id,
        expected_boot_id=permission.boot_id, expected_owner_generation=manager.native_owner()['owner_generation'])
    assert client.post('/api/v1/docking/station-departure/finish', json=body,
        headers=auth['fleet-a']).status_code == 409
    for _ in range(7):
        now[0] += .1
        sample(load_present=False)
        owner.tick()
    response = client.post('/api/v1/docking/station-departure/finish', json=body, headers=auth['fleet-a'])
    assert response.status_code == 200, response.text
    assert response.json()['operation_id'] == native['run_id']
    assert response.json()['stopped'] and response.json()['contact_released']
    assert owner.state == 'WORK_AVAILABLE'


@pytest.mark.parametrize('before_start', [False, True])
def test_exact_departure_stop_closes_delayed_start_without_stopping_foreign_run(station_api,
                                                                              pipeline_sources, before_start):
    from test_station_departure_owner import departure
    client, svc, _, auth, _, _ = station_api
    owner, manager, _, _, permission = departure()
    owner.principal_id = 'fleet-a'
    svc.station_docking, svc.docking = owner, manager
    previous = manager.native.current.run_id
    if not before_start:
        response = client.post('/api/v1/docking/station-undock', json=permission.model_dump(),
            headers=auth['fleet-a'])
        assert response.status_code == 200, response.text
    body = dict(session_id=permission.session_id, correlation_id=permission.correlation_id,
        expected_boot_id=permission.boot_id, expected_owner_generation=manager.native_owner()['owner_generation'])
    if not before_start:
        assert client.post('/api/v1/docking/station-stop', json=body | dict(correlation_id='foreign'),
            headers=auth['fleet-a']).status_code == 409
        assert owner.state == 'UNDOCKING'
    response = client.post('/api/v1/docking/station-stop', json=body, headers=auth['fleet-a'])
    assert response.status_code == 200, response.text
    assert owner.state == 'HOLD'
    assert client.post('/api/v1/docking/station-undock', json=permission.model_dump(),
        headers=auth['fleet-a']).status_code == 409
    if before_start:
        assert manager.native.current.run_id == previous


def test_fleet_http_transport_renews_same_reverse_and_reads_lost_finish_receipt(station_api, pipeline_sources):
    import asyncio
    import httpx
    from fleet.swarm.transport import HttpRobotClient
    from fleet.swarm.robots import RobotEndpoint
    from core_common.protocol.station_charging import StationMotionCommand
    from test_station_departure_owner import departure

    async def run():
        core, svc, _, auth, _, _ = station_api
        owner, manager, now, sample, permission = departure()
        owner.principal_id = 'fleet-a'
        svc.station_docking, svc.docking = owner, manager
        token = auth['fleet-a']['Authorization'].split(' ', 1)[1]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=core.app), base_url='http://core') as http:
            client = HttpRobotClient(RobotEndpoint(permission.robot_id, 'http://core', token), http=http)
            permission = permission.model_copy(update={'valid_until': now[0]+.8})
            operation = await client.station_undock(permission)
            initial_deadline = permission.valid_until
            assert operation.kind == 'undock'
            for _ in range(100):
                now[0] += .05
                manager.executor.step(.05)
                sample(load_present=False, measured_linear_m_s=-.08)
                permission = permission.model_copy(update={'captured_at': now[0], 'valid_until': now[0]+.8,
                    'expected_owner_generation': manager.native_owner()['owner_generation']})
                assert (await client.station_departure(permission))['accepted'] is True
                owner.tick()
                if owner.state == 'DEPARTURE_CHECK':
                    break
            assert now[0] > initial_deadline and owner.state == 'DEPARTURE_CHECK'
            assert manager.native.current.run_id == operation.run_id
            command = StationMotionCommand(session_id=permission.session_id,
                correlation_id=permission.correlation_id, expected_boot_id=permission.boot_id,
                expected_owner_generation=manager.native_owner()['owner_generation'])
            for _ in range(6):
                now[0] += .1
                sample(load_present=False)
                permission = permission.model_copy(update={'captured_at': now[0], 'valid_until': now[0]+.8,
                    'expected_owner_generation': manager.native_owner()['owner_generation']})
                await client.station_departure(permission)
                owner.tick()
            proof = await client.station_departure_finish(command)
            # Treat the POST response as lost: GET must expose the same fixed receipt.
            assert (await client.station_target()).departure_receipt == proof
            assert proof.operation_id == str(operation.run_id)
            assert manager.native.current.run_id == operation.run_id
    asyncio.run(run())


def test_next_return_binding_requires_new_local_stop_after_normal_work(station_api, pipeline_sources):
    from test_station_rebind import completed, observe_stop
    client, svc, _, auth, _, _ = station_api
    owner, manager, now, sample, session, target, scope, _, _ = completed()
    owner.principal_id = 'fleet-a'
    svc.station_docking, svc.docking = owner, manager
    body = dict(session=session.model_dump(), target=target.model_dump(), observation_scope=scope.model_dump(),
        expected_boot_id=session.boot_id, expected_owner_generation=manager.native_owner()['owner_generation'])
    response = client.put('/api/v1/docking/station-target', json=body, headers=auth['fleet-a'])
    assert response.status_code == 409 and owner.state == 'WORK_AVAILABLE'
    observe_stop(owner, now, sample)
    response = client.put('/api/v1/docking/station-target', json=body, headers=auth['fleet-a'])
    assert response.status_code == 200, response.text
    assert response.json()['session_id'] == session.session_id
    assert owner.readback().departure_receipt is None and manager.executor.command == (0., 0.)
