"""A completed native navigation owner may passively yield CORE's mode, never cancel."""
import pytest

from core_api_web.api.deps import Mode
from test_station_docking_api import station_api  # noqa: F401
from test_station_return_handover import terminal_navigation
from test_station_camera_pipeline import pipeline_sources  # noqa: F401


def request(svc):
    body = svc.nav.native_readback()
    operation = body['operation']
    return dict(expected_boot_id=body['owner']['boot_id'], run_id=operation['run_id'],
        expected_owner_generation=body['owner']['owner_generation'], correlation_id=operation['correlation_id'])


def test_exact_terminal_handover_is_idempotent_and_preserves_native_receipt(station_api):
    client, svc, _, auth, _, _ = station_api
    backend = terminal_navigation(svc)
    body = request(svc)
    for _ in range(2):
        response = client.post('/api/v1/navigation/handover', json=body, headers=auth['fleet-a'])
        assert response.status_code == 200, response.text
        assert response.json() == dict(accepted=True, mode='IDLE', run_id=body['run_id'],
            boot_id=body['expected_boot_id'], owner_generation=body['expected_owner_generation'])
        assert svc.modes.mode is Mode.IDLE and backend.canceled == 0
        assert svc.nav.native_readback()['operation']['run_id'] == body['run_id']
    events = [event for event in svc.events.history(since_seq=None, limit=1000)
        if event.type == 'mode.changed' and event.data.get('by') == 'navigation_handover']
    assert len(events) == 1
    assert events[0].data == {
        'from': 'NAVIGATION', 'to': 'IDLE', 'by': 'navigation_handover',
        'run_id': body['run_id'], 'boot_id': body['expected_boot_id']}


@pytest.mark.parametrize('fault', ['wrong_run', 'wrong_boot', 'wrong_correlation', 'old_generation',
    'pending_backend', 'active_callback', 'transport_missing', 'new_goal', 'manual', 'mapping', 'line_follow'])
def test_mismatched_or_unfinished_owner_cannot_yield_mode_or_cancel_a_replacement(station_api, fault):
    client, svc, _, auth, _, _ = station_api
    backend = terminal_navigation(svc)
    body = request(svc)
    if fault in ('wrong_run', 'wrong_boot'):
        body['run_id' if fault == 'wrong_run' else 'expected_boot_id'] = '00000000-0000-0000-0000-000000000001'
    elif fault == 'wrong_correlation':
        body['correlation_id'] = 'other-work-attempt'
    elif fault == 'old_generation':
        body['expected_owner_generation'] -= 1
    elif fault in ('pending_backend', 'active_callback', 'transport_missing'):
        original = backend.native_transport_snapshot
        backend.native_transport_snapshot = lambda: (None if fault == 'transport_missing' else
            (original()[0], fault == 'pending_backend', fault == 'active_callback'))
    elif fault == 'new_goal':
        svc.nav.goal(svc.nav.resolve_goal(x=2., y=0., yaw=0.), correlation_id='new-work')
    elif fault == 'manual':
        svc.modes.transition(Mode.MANUAL)
    elif fault == 'mapping':
        svc.nav.mapping_active = True
    elif fault == 'line_follow':
        from types import SimpleNamespace
        svc.line_follow = SimpleNamespace(active=True)
    before, operation = svc.modes.mode, svc.nav.native_readback()['operation']
    response = client.post('/api/v1/navigation/handover', json=body, headers=auth['fleet-a'])
    assert response.status_code == 409, response.text
    assert svc.modes.mode is before and backend.canceled == 0
    assert svc.nav.native_readback()['operation'] == operation


def test_another_trip_owner_fences_passive_handover(station_api):
    client, svc, now, auth, _, _ = station_api
    terminal_navigation(svc)
    body = request(svc)
    svc.trip_lease._monotonic = lambda: now[0]
    response = client.put('/api/v1/trip-lease', headers=auth['human'], json=dict(
        lease_id='other-lease', trip_id='other-trip', job_id='other-job', holder='station',
        operator_name='SIM other owner', ttl_s=5.))
    assert response.status_code == 200, response.text
    response = client.post('/api/v1/navigation/handover', json=body, headers=auth['fleet-a'])
    assert response.status_code == 409 and response.json()['error']['code'] == 'TRIP_LEASED'
    assert svc.modes.mode is Mode.NAVIGATION


def test_trip_owner_acquired_while_handover_waits_for_native_lock_prevents_mode_write(station_api):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    client, svc, now, auth, _, _ = station_api
    backend = terminal_navigation(svc)
    body = request(svc)
    svc.trip_lease._monotonic = lambda: now[0]
    waiting, original = Event(), svc.nav.with_terminal_navigation
    def enter(*args, **kwargs):
        waiting.set()
        return original(*args, **kwargs)
    svc.nav.with_terminal_navigation = enter
    with ThreadPoolExecutor(max_workers=1) as pool:
        with svc.nav._lock:
            future = pool.submit(client.post, '/api/v1/navigation/handover', json=body, headers=auth['fleet-a'])
            assert waiting.wait(2.)
            response = client.put('/api/v1/trip-lease', headers=auth['human'], json=dict(
                lease_id='late-lease', trip_id='late-trip', job_id='late-job', holder='station',
                operator_name='SIM late owner', ttl_s=5.))
            assert response.status_code == 200, response.text
        response = future.result(timeout=2.)
    assert response.status_code == 409 and response.json()['error']['code'] == 'TRIP_LEASED'
    assert svc.modes.mode is Mode.NAVIGATION and backend.canceled == 0


def test_busy_lease_admission_does_not_wait_while_holding_native_lock(station_api):
    from concurrent.futures import ThreadPoolExecutor
    client, svc, _, auth, _, _ = station_api
    backend = terminal_navigation(svc)
    body = request(svc)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with svc.modes.idle_admission:
            response = pool.submit(client.post, '/api/v1/navigation/handover',
                json=body, headers=auth['fleet-a']).result(timeout=2.)
    assert response.status_code == 409
    assert svc.modes.mode is Mode.NAVIGATION and backend.canceled == 0


def test_reentrant_guard_callback_cannot_reuse_the_prior_native_proof(station_api):
    client, svc, _, auth, _, _ = station_api
    terminal_navigation(svc)
    body = request(svc)
    original, calls, clears = svc.calibration.blocking, [], []
    clear = svc.command.clear_navigation
    def guard(token):
        calls.append(token)
        if len(calls) == 2:
            svc.nav.goal(svc.nav.resolve_goal(x=2., y=0., yaw=0.), correlation_id='SIM-reentrant-new-work')
        return original(token)
    def cleared():
        clears.append(True)
        return clear()
    svc.calibration.blocking, svc.command.clear_navigation = guard, cleared
    response = client.post('/api/v1/navigation/handover', json=body, headers=auth['fleet-a'])
    assert response.status_code == 409 and len(calls) == 2
    assert not clears and svc.modes.mode is Mode.NAVIGATION
    assert svc.nav.native_readback()['operation']['correlation_id'] == 'SIM-reentrant-new-work'


def test_fleet_http_client_yields_the_exact_completed_native_operation(station_api, pipeline_sources):
    import asyncio
    import httpx
    from fleet.swarm.transport import HttpRobotClient
    from fleet.swarm.robots import RobotEndpoint
    async def run():
        core, svc, _, auth, _, _ = station_api
        backend = terminal_navigation(svc)
        body = request(svc)
        token = auth['fleet-a']['Authorization'].split(' ', 1)[1]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=core.app), base_url='http://core') as http:
            client = HttpRobotClient(RobotEndpoint(svc.state.snapshot().robot_id, 'http://core', token), http=http)
            result = await client.navigation_handover(**body)
            assert result['accepted'] is True and svc.modes.mode is Mode.IDLE
            assert result['run_id'] == body['run_id'] and backend.canceled == 0
    asyncio.run(run())


def test_real_task_completion_and_release_precede_fleet_handover(station_api, pipeline_sources, tmp_path):
    import asyncio
    import httpx
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.server.channel.execution.outcomes.reconcile import task_result
    from fleet.swarm.transport import HttpRobotClient
    from fleet.swarm.robots import RobotEndpoint
    from test_station_return_handover import TrackedNavigation

    async def exercise():
        core, svc, _, auth, _, _ = station_api
        robot = svc.state.snapshot().robot_id
        tasks = FleetTaskService(FleetTaskStore(tmp_path / 'tasks.sqlite3'), robot_ids={robot})
        tasks.store.rearm_dispatch(expected_generation=tasks.store.dispatch_control()['generation'], actor_id='SIM')
        await tasks.submit_navigation(robot_id=robot, x=1., y=0., source='operator',
            actor_id='SIM', request_key='actual-work')
        backend = TrackedNavigation(svc.nav)
        svc.nav.executor = backend
        svc.state.set_velocity(0., 0.)  # Explicit SIM odometry presence for ordinary navigation admission.
        svc.state.set_odom_pose(0., 0., 0.)
        delivered = []
        unsubscribe = svc.nav._events.subscribe(lambda event: delivered.append(event.model_dump(mode='json')))
        token = auth['fleet-a']['Authorization'].split(' ', 1)[1]
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=core.app), base_url='http://core') as http:
                client = HttpRobotClient(RobotEndpoint(robot, 'http://core', token), http=http)
                dispatch_errors = []

                async def dispatch(attempt):
                    try:
                        owner = (await client._get('/api/v1/navigation/state'))['owner']
                        tasks.admit_attempt(attempt['task_id'], attempt['attempt_id'])
                        return await client.navigation_goal(1., 0., 0., correlation_id=attempt['attempt_id'],
                            expected_boot_id=owner['boot_id'], expected_owner_generation=owner['owner_generation'])
                    except Exception as exc:
                        dispatch_errors.append(str(exc))
                        raise

                task = await tasks.dispatch_next({robot}, dispatch=dispatch)
                assert task['status'] == 'ACCEPTED', dispatch_errors
                backend.done()
                for event in delivered:
                    tasks.project_core_event(event)
                task = tasks.store.get_task(task['task_id'])
                assert task['status'] == 'COMPLETED'
                assert tasks.store.resource_claims(resource_kind='robot', resource_id=robot)
                assert not await tasks.handover_completed_navigation(robot, client=client, admission=lambda: None)
                assert svc.modes.mode is Mode.NAVIGATION
                await task_result(tasks.store, client, task)
                assert tasks.store.get_task(task['task_id'])['receipt']['safe_released'] is True
                assert await tasks.handover_completed_navigation(robot, client=client, admission=lambda: None)
                assert svc.modes.mode is Mode.IDLE and backend.canceled == 0
        finally:
            unsubscribe()
    asyncio.run(exercise())
