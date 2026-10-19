"""Reconstruct Fleet around a durable HOLD; CORE and the explicit SIM plant survive."""
import asyncio
import secrets

import httpx
import pytest

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore, InvalidTaskTransition
from fleet.server.charge_store import ChargeStore
from fleet.server.station_store import StationStore
from fleet.server.station_service import StationService
from fleet.server.station_ingress import StationIngress
from fleet.server.charge_robot_http import ChargeRobotHttp
from fleet.server.station_return_http import StationReturnHttp
from fleet.server.charge_trip_port import ChargeReturnTrip
from fleet.server.charge_service import ChargeService
from fleet.server.charge_runtime import ChargeRuntime
from fleet.swarm.transport import HttpRobotClient


async def restart_held_station(*, core, endpoint, original, ingress, pump, work_id):
    """Fresh volatile owners must honor persisted HOLD even with queued ordinary work."""
    previous = original.store.get('charge-1')
    assert previous.state == 'HOLD'
    before_intent = original.store.operation_intent(previous.session_id)
    before_departure = original.store.departure_context(previous.session_id)
    tasks = FleetTaskStore(original.store.tasks.path)
    charges = ChargeStore(tasks)
    assert charges is not original.store and tasks is not original.store.tasks
    assert charges.get(previous.session_id) == previous
    old = original.stations
    settings = {key: getattr(old, key) for key in (
        'clock', 'map_scope', 'trusted_sources', 'approach_validator', 'position_tolerance_m',
        'heading_tolerance_rad', 'max_uncertainty_m', 'max_uncertainty_rad', 'consistency_samples')}
    stations = StationService(StationStore(tasks.path), **settings,
        robot_scope=lambda _: (previous.boot_id, previous.session_id))
    mutations, callbacks, tick_tasks, ticks = [], [], set(), asyncio.Queue()

    class ObservedTransport(httpx.ASGITransport):
        async def handle_async_request(self, request):
            if request.method != 'GET' and request.url.path.startswith((
                    '/api/v1/navigation', '/api/v1/docking', '/api/v1/trip-lease')):
                mutations.append((request.method, request.url.path))
            return await super().handle_async_request(request)

    def unexpected(*args, **kwargs):
        callbacks.append((args, kwargs))
        raise AssertionError('durable HOLD must not evaluate or submit another operation')

    async with httpx.AsyncClient(base_url='http://core', transport=ObservedTransport(app=core.app)) as http:
        robot = HttpRobotClient(endpoint, http=http)
        console = FleetConsole([endpoint], [robot], clock=old.clock)
        sources = StationIngress(stations=stations, sessions=charges, sources=ingress.sources,
            clients=console.clients, clock=old.clock)
        task_service = FleetTaskService(tasks, robot_ids={endpoint.robot_id})
        def factory(context):
            port = StationReturnHttp(clients=context.clients, store=charges, stations=stations,
                clock=old.clock, permit_ttl_s=1.)
            returns = ChargeReturnTrip(runner=context.runner, plans=context.plans, store=charges,
                stations=stations, robot_port=port, plan=unexpected, capabilities=unexpected,
                principal_id='charge-policy', map_scope=unexpected, clock=old.clock, admit_return=unexpected)
            ports = ChargeRobotHttp(clients=context.clients, store=charges, stations=stations,
                clock=old.clock, returns=returns, return_http=port,
                snapshot=unexpected, observation_scope=unexpected)
            service = ChargeService(charges, stations=stations, ports=ports, clock=old.clock,
                policy_enabled=lambda: True, admit_return=original.admit_return)
            runtime = ChargeRuntime(service, robot_id=previous.robot_id, station_id=previous.station_id,
                admission=original.admit_return, monotonic=old.clock, period_s=.05)
            actual_tick = runtime.tick
            async def observed_tick():
                tick_tasks.add(asyncio.current_task())
                result = await actual_tick()
                ticks.put_nowait(result)
                return result
            runtime.tick = observed_tick
            return runtime
        app = create_app(console, console_token=secrets.token_urlsafe(32), task_service=task_service,
            station_ingress=sources, charge_runtime_factory=factory)
        runtime = app.state.charge_runtime
        assert runtime.service is not original and runtime.service.store is charges
        async with app.router.lifespan_context(app):
            assert await asyncio.wait_for(ticks.get(), 3.) == previous
            control = tasks.dispatch_control()
            assert not control['dispatch_enabled']
            # The retained UNKNOWN charge claims also forbid a premature operator rearm.
            with pytest.raises(InvalidTaskTransition, match='unresolved Action claims'):
                tasks.rearm_dispatch(expected_generation=control['generation'], actor_id='SIM-restart-check')
            assert tasks.dispatch_control() == control
            for _ in range(12):
                await pump()
                result = await asyncio.wait_for(ticks.get(), 3.)
                assert result == previous
                assert charges.get(previous.session_id) == previous
                assert tasks.get_task(work_id)['status'] == 'QUEUED'
                for kind, identity in (('robot', previous.robot_id), ('station', previous.station_id)):
                    claims = tasks.resource_claims(resource_kind=kind, resource_id=identity)
                    assert len(claims) == 1
                    assert (claims[0]['owner_kind'], claims[0]['owner_id'], claims[0]['phase']) == (
                        'charge_session', previous.session_id, 'UNKNOWN')
            assert not callbacks and not mutations
            assert len(charges.list()) == 1
        assert runtime._closed and len(tick_tasks) == 1 and all(task.done() for task in tick_tasks)
        assert charges.get(previous.session_id) == previous
        assert charges.operation_intent(previous.session_id) == before_intent
        assert charges.departure_context(previous.session_id) == before_departure
        assert not callbacks and not mutations
