"""Fleet's HTTP client and task service take CORE's passive navigation handover (CORE + Fleet integration)."""
from core_api_web.api.deps import Mode
from test_navigation_handover import request
from test_station_docking_api import station_api  # noqa: F401
from test_station_return_handover import terminal_navigation
from test_station_camera_pipeline import pipeline_sources  # noqa: F401


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
