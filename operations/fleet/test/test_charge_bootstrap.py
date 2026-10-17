"""The existing Fleet app owns the opt-in charging worker and its exact resources."""
import asyncio

import pytest

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.swarm.robots import RobotEndpoint
from test_charge_policy import profile
from test_station_ingress import _setup


def parts(tmp_path):
    ingress, _, robot, _, _, _, charges = _setup(tmp_path)
    console = FleetConsole([RobotEndpoint('robot-1', 'http://robot', robot)], list(ingress.clients().values()))
    tasks = FleetTaskService(charges.tasks, robot_ids={'robot-1'}, clock=ingress.clock)
    return ingress, console, tasks


def factory(context):
    from fleet.server.charge_policy_admission import MeasuredChargePolicyAdmission
    from fleet.server.charge_robot_http import ChargeRobotHttp
    from fleet.server.charge_runtime import ChargeRuntime
    from fleet.server.charge_service import ChargeService
    from fleet.server.charge_trip_port import ChargeReturnTrip
    from fleet.server.station_return_http import StationReturnHttp
    clock = context.ingress.clock
    policy = MeasuredChargePolicyAdmission(profiles={'robot-1': profile()}, clock=clock,
        measured_sources={'robot-1': ('fuel_gauge', 'capacity-3')},
        budget_source=('route-budget', 'budget-boot', 'cost-1'), max_age_s=2.)
    port = StationReturnHttp(clients=context.clients, store=context.ingress.sessions,
        stations=context.ingress.stations, clock=clock, permit_ttl_s=1.)
    def unused(*args, **kwargs):
        raise AssertionError('disabled policy must not dispatch')
    returns = ChargeReturnTrip(runner=context.runner, plans=context.plans,
        store=context.ingress.sessions, stations=context.ingress.stations, robot_port=port,
        plan=unused, capabilities=unused, principal_id='station-service',
        map_scope=unused, clock=clock, admit_return=unused)
    http = ChargeRobotHttp(clients=context.clients, store=context.ingress.sessions,
        stations=context.ingress.stations, clock=clock, returns=returns, return_http=port,
        snapshot=unused, observation_scope=unused)
    service = ChargeService(context.ingress.sessions, stations=context.ingress.stations,
        ports=http, clock=clock, policy_enabled=lambda: False, admit_return=policy)
    return ChargeRuntime(service, robot_id='robot-1', station_id='charger-1',
        admission=policy, monotonic=lambda: 101., period_s=.1)


def test_default_app_has_no_charging_worker(tmp_path):
    _, console, _ = parts(tmp_path)
    assert create_app(console).state.charge_runtime is None


def test_factory_requires_existing_ingress_and_task_ledger(tmp_path):
    _, console, _ = parts(tmp_path)
    with pytest.raises(ValueError, match='CHARGE_RUNTIME_SHARED_RESOURCES_REQUIRED'):
        create_app(console, charge_runtime_factory=factory)


@pytest.mark.parametrize('fault', [None, 'runner', 'source', 'task_store'])
def test_app_binds_actual_runtime_or_rejects_other_owners(tmp_path, fault):
    ingress, console, tasks = parts(tmp_path)
    seen = []
    def build(context):
        runtime = factory(context)
        seen.append(context)
        if fault == 'runner':
            runtime.service.ports.returns.runner = object()
        elif fault == 'source':
            runtime.service.ports.snapshot_source = None
        elif fault == 'task_store':
            runtime.service.store.tasks = object()
        return runtime
    if fault:
        with pytest.raises(ValueError, match='CHARGE_RUNTIME_SHARED_RESOURCES_REQUIRED'):
            create_app(console, task_service=tasks, station_ingress=ingress, charge_runtime_factory=build)
        return
    app = create_app(console, task_service=tasks, station_ingress=ingress, charge_runtime_factory=build)
    assert seen[0].runner is app.state.trip_runner
    assert seen[0].task_service is tasks
    assert app.state.charge_runtime.service.ports.work_handover.__self__.tasks is tasks
    assert app.state.charge_runtime.service.ports.work_handover.__self__.console is console
    assert app.state.charge_runtime.finish_work == app.state.charge_runtime.service.ports.finish_work
    assert app.state.charge_runtime.service.store is ingress.sessions
    assert app.state.trip_runner.lease.on_charge_lost is not None
    assert tasks.charge_admission('robot-1') is not None
    assert console.trip_busy('robot-1')


def test_existing_app_lifespan_starts_and_closes_worker(tmp_path):
    async def run():
        ingress, console, tasks = parts(tmp_path)
        started = asyncio.Event()
        def build(context):
            runtime = factory(context)
            original = runtime.tick
            async def tick():
                result = await original()
                started.set()
                return result
            runtime.tick = tick
            return runtime
        app = create_app(console, task_service=tasks, station_ingress=ingress, charge_runtime_factory=build)
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(started.wait(), 2.)
            assert ingress.sessions.get('charge-1').state == 'HOLD'
        assert app.state.charge_runtime._closed
        assert ingress.sessions.tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
        await next(iter(ingress.clients().values()))._http.aclose()
    asyncio.run(run())


def test_task_queue_and_final_send_both_consume_original_energy_guard(tmp_path):
    from fleet.hub.hub import HubError
    from test_charge_runtime import configured
    from test_task_service import _service
    from fleet.server.charge_policy_admission import work_request_digest
    async def run():
        runtime, _, _, _, _, sample, now, _, _ = configured(tmp_path)
        tasks = _service(tmp_path/'work.sqlite', robot_ids=('robot-1',))
        tasks.charge_admission = runtime.work_admission
        task = await tasks.submit_navigation(robot_id='robot-1', x=1., y=0., source='operator',
            actor_id='test-operator', request_key='work-1')
        attempts = []
        async def send(attempt):
            attempts.append(attempt)
            now[0] = 101.6  # Capability I/O can outlive the original energy sample.
            with pytest.raises(HubError, match='CHARGE_POLICY_INPUT_UNVERIFIED'):
                tasks.admit_attempt(task['task_id'], attempt['attempt_id'])
            raise HubError('COMMAND_REJECTED', 'energy expired')
        assert await tasks.dispatch_next({'robot-1'}, dispatch=send) is None
        assert tasks.store.get_task(task['task_id'])['status'] == 'QUEUED' and attempts == []
        sample['battery_energy'].update(soc_percent=75., valid_until=101.5)
        sample['charge_budget'].update(work_task_id=task['task_id'], work_request_digest=work_request_digest(task))
        await runtime.tick()
        result = await tasks.dispatch_next({'robot-1'}, dispatch=send)
        assert result['status'] == 'HOLD'
        assert len(attempts) == 1
        assert tasks.store.get_task(task['task_id'])['reason'] == 'CHARGE_POLICY_INPUT_UNVERIFIED'
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['task', 'request', 'missing'])
def test_work_estimate_for_another_task_or_route_cannot_admit_selected_work(tmp_path, fault):
    from fleet.server.charge_policy_admission import work_request_digest
    from test_charge_runtime import configured
    async def run():
        runtime, _, _, _, _, sample, now, _, _ = configured(tmp_path)
        task = dict(task_id='task-1', robot_id='robot-1', task_type='navigate', request={'goal': {'x': 1., 'y': 0.}})
        sample['battery_energy']['soc_percent'] = 75.
        sample['charge_budget'].update(work_task_id=task['task_id'], work_request_digest=work_request_digest(task))
        await runtime.tick()
        assert runtime.work_admission('robot-1', task=task) is None
        if fault == 'task':
            task['task_id'] = 'other-task'
        elif fault == 'request':
            task['request']['goal']['x'] = 100.
        else:
            sample['charge_budget'].update(work_task_id=None, work_request_digest=None)
            now[0] += 1.
            await runtime.tick()
        assert runtime.work_admission('robot-1', task=task) == 'CHARGE_WORK_SCOPE_CHANGED'
    asyncio.run(run())
