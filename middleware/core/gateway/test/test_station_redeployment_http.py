"""Actual Fleet runtime/HTTP/native departure; initial dock and device facts are SIM.

This starts at an explicitly measured simulated charge completion. It does not
establish installed device acceptance or the preceding camera/return pipeline.
"""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from test_station_docking_api import station_api  # noqa: F401
from test_station_camera_pipeline import pipeline_sources  # noqa: F401
from station_readback_probe import install_hold_probe


def test_hold_probe_preserves_nested_exception_and_original_hold(capsys):
    import sys
    import station_readback_probe

    install = getattr(station_readback_probe, 'install_hold_probe', None)
    assert callable(install), 'caught HOLD exceptions need a shared diagnostic probe'
    current, intent, result = SimpleNamespace(session_id='charge-probe'), object(), object()
    calls = []

    async def original(current, reason, **kwargs):
        calls.append((current, reason, kwargs, sys.exception()))
        return result

    motion = SimpleNamespace(stop_hold=original)
    install(motion, lambda: 123.5)

    async def nested(reason):
        await asyncio.sleep(0)
        return await motion.stop_hold(current, reason, intent=intent)

    async def read_return(error):
        view = dict(state='FAILED', reason='SIM_TRIP_FAILURE', detail={'phase': 'arrival'},
            forbidden='MUST_NOT_BE_REPORTED')
        raise error

    async def run():
        for reason in ('CHARGE_MOTION_READBACK_UNAVAILABLE', 'CHARGE_DEPARTURE_UNVERIFIED'):
            error = ValueError('original readback failure')
            try:
                await read_return(error)
            except ValueError:
                assert await nested(reason) is result
                assert sys.exception() is error
            prefix, payload = capsys.readouterr().out.strip().split(' ', 1)
            report = json.loads(payload)
            assert prefix == 'STATION_HOLD_DIAGNOSTIC'
            assert report['session_id'] == current.session_id and report['reason'] == reason
            assert report['clock'] == 123.5
            assert report['exception_type'] == 'ValueError'
            assert report['exception'] == str(error)
            assert 'raise error' in ''.join(report['traceback'])
            assert report.get('return_trip') == dict(state='FAILED', reason='SIM_TRIP_FAILURE',
                detail={'phase': 'arrival'})
            assert 'MUST_NOT_BE_REPORTED' not in payload
            assert calls[-1] == (current, reason, {'intent': intent}, error)
        assert await nested('CHARGE_MOTION_READBACK_UNAVAILABLE') is result
        assert calls[-1] == (current, 'CHARGE_MOTION_READBACK_UNAVAILABLE', {'intent': intent}, None)
        assert capsys.readouterr().out == ''

    asyncio.run(run())


async def configured(station_api, tmp_path):
    from test_station_departure_owner import departure
    from test_charge_departure_store import charged
    from test_charge_policy import battery, profile
    from fleet.server.charge_policy_admission import ChargePolicyAdmission, work_request_digest
    from fleet.server.charge_robot_http import ChargeRobotHttp
    from fleet.server.station_return_http import StationReturnHttp
    from fleet.server.charge_runtime import ChargeRuntime
    from fleet.server.charge_service import ChargeService
    from fleet.server.station_store import StationStore
    from fleet.server.station_service import StationService
    from fleet.swarm.transport import HttpRobotClient
    from fleet.swarm.robots import RobotEndpoint

    core, svc, _, auth, _, _ = station_api
    owner, manager, now, sample, _ = departure()
    owner.principal_id = 'fleet-a'
    svc.station_docking, svc.docking = owner, manager
    original_dock = str(manager.native.current.run_id)
    ledger, tasks, _ = charged(tmp_path, session_changes={'boot_id': owner.session.boot_id},
        dock_operation_id=original_dock)
    registry = StationStore(tmp_path/'site.sqlite')
    registry.propose(owner.target.model_copy(update={'status': 'CANDIDATE'}))
    registry.confirm(owner.target.station_id, expected_revision=1)
    stations = StationService(registry, clock=lambda: now[0], map_scope=lambda: ('floor', 'map-1'),
        trusted_sources={}, robot_scope=lambda _: (owner.session.boot_id, owner.session.session_id),
        approach_validator=lambda _: True, position_tolerance_m=.03, heading_tolerance_rad=.05,
        max_uncertainty_m=.01, max_uncertainty_rad=.02, consistency_samples=3)
    token = auth['fleet-a']['Authorization'].split(' ', 1)[1]
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=core.app), base_url='http://core')
    client = HttpRobotClient(RobotEndpoint('robot-1', 'http://core', token), http=http)
    clients = lambda: {'robot-1': client}
    policy = ChargePolicyAdmission(profiles={'robot-1': profile()}, clock=lambda: now[0],
        budget_source=('route-budget', 'budget-boot', 'cost-1'), max_age_s=2.)
    async def snapshot(robot_id):
        at = now[0]
        return dict(robot_id=robot_id, boot_id=owner.session.boot_id, battery_id='pack-1',
            captured_at=at, valid_until=at+.5, mode='IDLE' if owner.state in ('CHARGED_HOLD',
                'DEPARTURE_CHECK', 'WORK_AVAILABLE') else 'DOCKING', safe_work_boundary=True,
            safety_latched=False, dock_state='DOCKED' if owner.state == 'CHARGED_HOLD' else 'UNDOCKED',
            map_id='floor', map_revision='map-1',
            battery_energy=battery(captured_at=at, valid_until=at+.5).model_dump(),
            charge_budget=dict(robot_id=robot_id, boot_id=owner.session.boot_id, station_id='charger-1',
                map_id='floor', map_revision='map-1', pose_revision=1, profile_revision='profile-1',
                source_id='route-budget', source_epoch='budget-boot', cost_revision='cost-1',
                captured_at=at, valid_until=at+.5, work_wh=4., return_wh=2., dock_wh=.5, reserve_wh=1.,
                work_duration_s=100., return_duration_s=50., work_task_id='work-1',
                work_request_digest=work_request_digest(tasks.get_task('work-1'))))
    ret = StationReturnHttp(clients=clients, store=ledger, stations=stations, clock=lambda: now[0], permit_ttl_s=1.)
    port = ChargeRobotHttp(clients=clients, store=ledger, stations=stations, clock=lambda: now[0],
        returns=SimpleNamespace(), return_http=ret, snapshot=snapshot, observation_scope=None)
    enabled = [True]
    service = ChargeService(ledger, stations=stations, ports=port, clock=lambda: now[0],
        policy_enabled=lambda: enabled[0], admit_return=policy)
    install_hold_probe(service.motion, lambda: now[0])
    runtime = ChargeRuntime(service, robot_id='robot-1', station_id='charger-1', admission=policy,
        monotonic=lambda: now[0], period_s=.1)
    return runtime, service, ledger, tasks, client, http, owner, manager, now, sample, enabled


@pytest.mark.parametrize('lost_finish', [False, True])
def test_real_runtime_renews_and_releases_only_after_native_and_measured_departure(
        station_api, pipeline_sources, tmp_path, lost_finish):
    from fleet.server.task_scheduler import FleetTaskScheduler
    async def run():
        runtime, service, ledger, tasks, client, http, owner, manager, now, sample, _ = await configured(
            station_api, tmp_path)
        starts, finishes = [], []
        try:
            current = await service.reconcile('charge-1')
            assert current.state == 'CHARGED_HOLD', current.reason
            current = await service.motion.observe_charge(current)
            assert current.state == 'CHARGED_HOLD', current.reason
            start, finish = client.station_undock, client.station_departure_finish
            async def start_once(permission):
                starts.append(permission)
                assert ledger.operation_intent('charge-1')['status'] == 'PREPARED'
                return await start(permission)
            async def finish_once(command):
                finishes.append(command)
                proof = await finish(command)
                if lost_finish:
                    raise TimeoutError('SIM finish response lost after CORE committed measured receipt')
                return proof
            client.station_undock, client.station_departure_finish = start_once, finish_once
            await runtime.tick()
            assert ledger.get('charge-1').state == 'UNDOCKING', ledger.get('charge-1').reason
            deadline = ledger.departure_context('charge-1')['permit']['valid_until']
            for _ in range(140):
                manager.executor.step(.05)
                now[0] += .05
                sample(load_present=False, measured_linear_m_s=-.08 if owner.state == 'UNDOCKING' else 0.)
                owner.tick()
                if ledger.get('charge-1').state != 'WORK_AVAILABLE':
                    assert FleetTaskScheduler(tasks, worker_id='worker').claim_next({'robot-1'}) is None
                await runtime.tick()
                current = ledger.get('charge-1')
                assert current.state != 'HOLD', current.reason
                if current.state == 'WORK_AVAILABLE':
                    break
            assert current.state == 'WORK_AVAILABLE' and now[0] > deadline
            assert len(starts) == 1
            assert ledger.departure_context('charge-1')['receipt']['operation_id'] == current.operation_id
            assert owner.state == 'WORK_AVAILABLE' and manager.executor.command == (0., 0.)
            assert FleetTaskScheduler(tasks, worker_id='worker').claim_next({'robot-1'})['task_id'] == 'work-1'
            assert runtime.work_admission('robot-1', task=tasks.get_task('work-1')) is None
        finally:
            await http.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['canceled_work', 'changed_work', 'disabled', 'lost_start'])
def test_start_rechecks_after_native_io_and_unknown_submission_never_retries(
        station_api, pipeline_sources, tmp_path, fault):
    async def run():
        runtime, service, ledger, tasks, client, http, owner, _, _, _, enabled = await configured(station_api, tmp_path)
        starts = []
        try:
            assert (await service.reconcile('charge-1')).state == 'CHARGED_HOLD'
            original_read, original_start = client.docking_status, client.station_undock
            async def native(run_id=None):
                body = await original_read(run_id)
                if run_id is None and ledger.get('charge-1').state == 'UNDOCKING':
                    if fault == 'canceled_work':
                        tasks.cancel_queued('work-1', actor_id='operator')
                    elif fault == 'changed_work':
                        with tasks._connect() as db:
                            db.execute("UPDATE fleet_tasks SET request_json='{}' WHERE task_id='work-1'")
                    elif fault == 'disabled':
                        enabled[0] = False
                return body
            async def submit(permission):
                starts.append(permission)
                result = await original_start(permission)
                if fault == 'lost_start':
                    raise TimeoutError('SIM start response lost after native admission')
                return result
            client.docking_status, client.station_undock = native, submit
            await runtime.tick()
            assert ledger.get('charge-1').state == 'HOLD'
            assert len(starts) == (1 if fault == 'lost_start' else 0)
            assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
            assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')
            if fault == 'lost_start':
                assert owner.state == 'HOLD'
            await runtime.tick()
            assert len(starts) == (1 if fault == 'lost_start' else 0)
        finally:
            await http.aclose()
    asyncio.run(run())


def test_selected_work_cancel_during_native_read_prevents_permission_renewal(
        station_api, pipeline_sources, tmp_path):
    async def run():
        runtime, _, ledger, tasks, client, http, owner, manager, now, sample, _ = await configured(station_api, tmp_path)
        renewals = []
        try:
            await runtime.tick()
            assert ledger.get('charge-1').state == 'UNDOCKING'
            original_read, original_renew = client.docking_status, client.station_departure
            async def native(run_id=None):
                body = await original_read(run_id)
                tasks.cancel_queued('work-1', actor_id='operator')
                return body
            async def renew(permission):
                renewals.append(permission)
                return await original_renew(permission)
            client.docking_status, client.station_departure = native, renew
            now[0] += .05
            sample(load_present=False, measured_linear_m_s=-.08)
            owner.tick()
            await runtime.tick()
            assert ledger.get('charge-1').state == 'HOLD'
            assert not renewals and manager.executor.command == (0., 0.)
            assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')
        finally:
            await http.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['uncommitted_finish', 'expired_receipt'])
def test_unknown_finish_without_live_readback_holds_both_claims_and_never_repeats_motion(
        station_api, pipeline_sources, tmp_path, fault):
    async def run():
        runtime, _, ledger, tasks, client, http, owner, manager, now, sample, _ = await configured(station_api, tmp_path)
        starts, finishes = [], []
        try:
            start, finish = client.station_undock, client.station_departure_finish
            async def submit(permission):
                starts.append(permission)
                return await start(permission)
            async def uncertain(command):
                if fault == 'expired_receipt':
                    result = await finish(command)
                    finishes.append(command)
                    now[0] = result.valid_until
                else:
                    finishes.append(command)
                raise TimeoutError('SIM finish/readback cannot establish a live committed receipt')
            client.station_undock, client.station_departure_finish = submit, uncertain
            await runtime.tick()
            for _ in range(140):
                manager.executor.step(.05)
                now[0] += .05
                sample(load_present=False, measured_linear_m_s=manager.executor.command[0])
                # CORE tick consumes only the explicit installed local feed.
                owner.tick()
                await runtime.tick()
                if ledger.get('charge-1').state == 'HOLD':
                    break
            assert ledger.get('charge-1').state == 'HOLD'
            assert len(starts) == 1 and len(finishes) == 1
            assert manager.executor.command == (0., 0.)
            assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
            assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')
            await runtime.tick()
            assert len(starts) == 1 and len(finishes) == 1
        finally:
            await http.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('change', ['completed', 'foreign_run', 'disabled', 'expired', 'lost_response'])
def test_native_completion_between_status_and_renewal_keeps_exact_departure(
        station_api, pipeline_sources, tmp_path, change):
    from uuid import uuid4
    from fleet.swarm.transport import RobotApiError

    async def run():
        runtime, _, ledger, tasks, client, http, owner, manager, now, sample, enabled = await configured(
            station_api, tmp_path)
        starts, races, refusals = [], [], []
        original_start, original_read, original_renew = (
            client.station_undock, client.docking_status, client.station_departure)

        async def start(permission):
            starts.append(permission)
            return await original_start(permission)

        async def native(run_id=None):
            body = await original_read(run_id)
            if races and change == 'foreign_run' and body.get('operation'):
                body['operation']['run_id'] = str(uuid4())
            return body

        async def renew(permission):
            if not races and abs(manager.executor.travelled_m()) >= owner.departure.feed.profile.reverse_distance_m:
                before = manager.native_owner()['owner_generation']
                assert manager.native.current.phase != 'TERMINAL'
                owner.tick()  # Real CORE completion after Fleet read status, before its PUT.
                operation = manager.native.current
                after = manager.native_owner()['owner_generation']
                assert operation.phase == 'TERMINAL' and operation.result == 'SUCCEEDED'
                assert before == permission.expected_owner_generation and after == before+1
                races.append((str(operation.run_id), before, after))
                if change == 'disabled':
                    enabled[0] = False
                elif change == 'expired':
                    now[0] = ledger.departure_context('charge-1')['active_permit']['valid_until']
                elif change == 'lost_response':
                    raise TimeoutError('SIM renewal response unknown at native completion')
                try:
                    await original_renew(permission)
                except RobotApiError as exc:
                    assert exc.status == 409 and exc.code == 'OWNER_GENERATION_CHANGED'
                    refusals.append(exc.code)
                    raise
                pytest.fail('stale native generation unexpectedly accepted')
            return await original_renew(permission)

        client.station_undock, client.docking_status, client.station_departure = start, native, renew
        try:
            await runtime.tick()
            assert ledger.get('charge-1').state == 'UNDOCKING'
            for _ in range(140):
                manager.executor.step(.05)
                now[0] += .05
                sample(load_present=False, measured_linear_m_s=-.08 if owner.state == 'UNDOCKING' else 0.)
                at_finish = (not races and abs(manager.executor.travelled_m())
                             >= owner.departure.feed.profile.reverse_distance_m)
                if not at_finish:
                    owner.tick()
                await runtime.tick()
                current = ledger.get('charge-1')
                if current.state in ('HOLD', 'WORK_AVAILABLE'):
                    break
            assert races and len(starts) == 1
            assert refusals == ([] if change == 'lost_response' else ['OWNER_GENERATION_CHANGED'])
            if change == 'completed':
                assert current.state == 'WORK_AVAILABLE', current.reason
                assert ledger.departure_context('charge-1')['receipt']['operation_id'] == races[0][0]
                assert not tasks.resource_claims(resource_kind='station', resource_id='charger-1')
            else:
                assert current.state == 'HOLD'
                assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
                assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')
            assert manager.executor.command == (0., 0.)
        finally:
            await http.aclose()
    asyncio.run(run())
