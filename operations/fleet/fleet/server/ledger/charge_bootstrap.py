"""Compose an explicitly configured charge worker with Fleet's existing owners."""
from dataclasses import dataclass

from fleet.server.charge_robot_http import ChargeRobotHttp
from fleet.server.charge_runtime import ChargeRuntime
from fleet.server.charge_trip_port import ChargeReturnTrip
from fleet.server.charge_work_handover import CompletedWorkHandover
from fleet.server.charge_policy_admission import MeasuredChargePolicyAdmission
from fleet.server.station_return_http import StationReturnHttp


@dataclass(frozen=True)
class ChargeRuntimeContext:
    runner: object
    plans: object
    task_service: object
    ingress: object
    clients: object


def install_charge_runtime(app, *, factory, runner, plans, task_service, ingress, console):
    app.state.charge_runtime = None
    if factory is None:
        return
    if task_service is None or ingress is None:
        raise ValueError('CHARGE_RUNTIME_SHARED_RESOURCES_REQUIRED')
    clients = console.clients
    context = ChargeRuntimeContext(runner, plans, task_service, ingress, clients)
    runtime = factory(context)
    if not isinstance(runtime, ChargeRuntime):
        raise ValueError('CHARGE_RUNTIME_SHARED_RESOURCES_REQUIRED')
    service, ports = runtime.service, runtime.service.ports
    if (type(runtime.admission) is not MeasuredChargePolicyAdmission
            or runtime.admission is not service.admit_return):
        raise ValueError('CHARGE_RUNTIME_MEASURED_HEALTH_REQUIRED')
    if (not isinstance(ports, ChargeRobotHttp) or not isinstance(ports.returns, ChargeReturnTrip)
            or not isinstance(ports.return_http, StationReturnHttp)
            or service.store is not ingress.sessions or service.store.tasks is not task_service.store
            or service.stations is not ingress.stations or ports.store is not service.store
            or ports.stations is not service.stations or ports.returns.runner is not runner
            or ports.returns.plans is not plans or ports.returns.store is not service.store
            or ports.returns.stations is not service.stations or ports.returns.robot_port is not ports.return_http
            or ports.return_http.store is not service.store or ports.return_http.stations is not service.stations
            or not callable(ports.snapshot_source) or not callable(ports.observation_scope)
            or runtime.robot_id not in console.robot_ids
            or any(provider().get(runtime.robot_id) is not console.clients()[runtime.robot_id]
                   for provider in (ports.clients, ports.return_http.clients, ingress.clients))):
        raise ValueError('CHARGE_RUNTIME_SHARED_RESOURCES_REQUIRED')

    async def lost(view, detail):
        if view['owner_kind'] != 'charge_session' or view['robot_id'] != runtime.robot_id:
            raise ValueError('CHARGE_RUNTIME_SCOPE_CHANGED')
        current = await runtime._session()
        if current is None or current.session_id != view['job_id']:
            raise ValueError('CHARGE_RUNTIME_SCOPE_CHANGED')
        await service.hold(current.session_id, reason='CHARGE_RETURN_LEASE_LOST')

    runner.lease.on_charge_lost = lost
    ports.work_handover = CompletedWorkHandover(task_service, console).complete
    runtime.finish_work = ports.finish_work
    task_service.charge_admission = runtime.work_admission
    busy = console.trip_busy
    console.trip_busy = lambda robot_id: busy(robot_id) or runtime.work_admission(robot_id) is not None
    app.state.charge_runtime = runtime
