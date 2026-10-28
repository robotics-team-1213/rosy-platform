"""Actual Fleet HTTP client -> configured CORE return owner; sensors remain explicit SIM."""
import asyncio
import importlib
import importlib.util
from types import SimpleNamespace

import httpx
import pytest

from core_common.protocol.station_charging import ChargeSessionStatus, StationPoseRecord
from core_api_web.api.deps import Mode
from core.bridge.docking_mode import motion_ready
from test_station_docking_api import station_api
from test_station_camera_pipeline import pipeline_sources


@pytest.mark.parametrize('change', ['refresh', 'moved', 'source', 'session', 'expired', 'motion', 'permit'])
def test_navigation_read_revalidates_camera_refresh_without_reusing_old_ack(
        station_api, pipeline_sources, tmp_path, change):
    async def run():
        port, client, http, svc, now, ledger, session, target, context, stations = await configured(station_api, tmp_path)
        try:
            await port.grant_return(session, target, context)
            original = client.station_navigation_state
            stations.trusted_sources[target.source_id] = (target.source_epoch, target.calibration_revision)
            reads, requests = [], []
            async def record(request):
                requests.append((request.method, request.url.path))
            http.event_hooks['request'].append(record)
            async def refresh_during_read():
                body = await original()
                reads.append(body)
                now[0] += .05
                candidate = target.model_copy(update={'status': 'CANDIDATE', 'captured_at': now[0]})
                if change == 'moved':
                    candidate = candidate.model_copy(update={'pose': target.pose.model_copy(update={'x': .1})})
                if change == 'source':
                    candidate = candidate.model_copy(update={'source_epoch': 'replacement-source'})
                    stations.trusted_sources[target.source_id] = ('replacement-source', target.calibration_revision)
                stations.observe(candidate)
                if change == 'session':
                    stations.robot_scope = lambda _: (session.boot_id, 'replacement-session')
                if change == 'expired':
                    now[0] += .3
                if change == 'permit':
                    now[0] += 1.1
                if change == 'motion':
                    svc.station_docking.motion_feed = SimpleNamespace(snapshot=lambda: None, clear=lambda: None)
                return body
            client.station_navigation_state = refresh_during_read
            if change == 'refresh':
                assert await port.navigation_ready(session, context) is True
                assert stations.store.get(target.station_id).pose_revision == target.pose_revision
                assert svc.station_docking.target == target  # Readiness never renews the installed target.
            else:
                with pytest.raises(ValueError):
                    await port.navigation_ready(session, context)
            assert len(reads) == 1
            assert requests and all(method == 'GET' for method, _ in requests)
            assert svc.docking.native.current is None and ledger.admitted(session.session_id)
        finally:
            await http.aclose()
    asyncio.run(run())


async def configured(station_api, tmp_path, *, trip=False):
    name = 'fleet.server.station_return_http'
    assert importlib.util.find_spec(name) is not None, 'actual CORE return HTTP port is missing'
    module = importlib.import_module(name)
    from fleet.swarm.transport import HttpRobotClient
    from fleet.swarm.robots import RobotEndpoint
    from fleet.server.station_store import StationStore
    from fleet.server.station_service import StationService
    from test_charge_store import store
    core, svc, now, auth, binding, _ = station_api
    if trip:
        binding['target']['approach_pose'] = dict(x=1., y=0., yaw=0.)  # Explicit SIM route-map binding.
    svc.trip_lease._monotonic = lambda: now[0]
    original = svc.station_docking.local_scope
    svc.station_docking.local_scope = lambda: original() | dict(mode=svc.modes.mode.value)
    svc.station_docking.local_scope_nowait = svc.station_docking.local_scope
    session = ChargeSessionStatus.model_validate(binding['session'])
    target = StationPoseRecord.model_validate(binding['target'])
    ledger, _ = store(tmp_path)
    ledger.reserve(session)
    session = ledger.transition(session.session_id, expected_state='RETURN_RESERVED', next_state='RETURNING',
        attempt_id=session.attempt_id, now=now[0], reason='SIM', intent_kind='return', correlation_id='return-1')
    context = None if trip else ledger.prepare_return(session.session_id, correlation_id='return-1',
                                                     plan_id='return-plan', lease_id='return-lease')
    registry = StationStore(tmp_path/'site.sqlite')
    registry.propose(target.model_copy(update={'status': 'CANDIDATE'}))
    registry.confirm(target.station_id, expected_revision=1)
    stations = StationService(registry, clock=lambda: now[0], map_scope=lambda: ('floor', 'map-1'),
        trusted_sources={}, robot_scope=lambda _: (session.boot_id, session.session_id),
        approach_validator=lambda _: True, position_tolerance_m=.03, heading_tolerance_rad=.05,
        max_uncertainty_m=.01, max_uncertainty_rad=.02, consistency_samples=3)
    token = auth['fleet-a']['Authorization'].split(' ', 1)[1]
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=core.app), base_url='http://core')
    client = HttpRobotClient(RobotEndpoint(session.robot_id, 'http://core', token), http=http)
    ack = await client.station_bind(binding)
    assert stations.accept_ack(ack)
    if not trip:
        await client.trip_lease(dict(lease_id='return-lease', trip_id='return-plan', job_id=session.session_id,
            holder='station', operator_name='SIM', ttl_s=5.))
    port = module.StationReturnHttp(clients=lambda: {session.robot_id: client}, store=ledger,
        stations=stations, clock=lambda: now[0], permit_ttl_s=1.)
    return port, client, http, svc, now, ledger, session, target, context, stations


def test_actual_http_grant_renew_stop_and_measured_finish(station_api, pipeline_sources, tmp_path):
    async def run():
        port, client, http, svc, now, ledger, session, target, context, stations = await configured(station_api, tmp_path)
        try:
            await port.grant_return(session, target, context)
            stored = ledger.return_context(session.session_id)
            assert stored['expected_owner_generation'] == 0
            assert svc.station_docking.state == 'RETURNING'
            svc.modes.transition(Mode.NAVIGATION)
            assert motion_ready(svc)
            now[0] += .1
            await port.renew_return(session, target, context)
            assert (await client.station_target()).return_permit.captured_at == now[0]
            svc.modes.transition(Mode.IDLE)
            assert await port.finish_return(session, target, context) is None  # explicit negative ACK, not completion
            motion = dict(odom_epoch='odom-1', measured_linear_m_s=0., measured_angular_rad_s=0.)
            svc.station_docking.motion_feed = SimpleNamespace(snapshot=lambda: dict(motion), clear=lambda: None)
            for _ in range(6):
                now[0] += .1
                motion.update(captured_at=now[0], valid_until=now[0]+.25)
                svc.station_docking.tick()
            ack = await port.finish_return(session, target, context)
            assert ack.accepted and stations.ready_for_return(session.robot_id, target.station_id)
            assert svc.station_docking.state == 'BOUND' and not motion_ready(svc)
            assert ledger.admitted(session.session_id)
        finally:
            await http.aclose()
    asyncio.run(run())


def test_exact_lease_stop_revokes_final_output_and_old_grant_cannot_reopen(station_api, pipeline_sources, tmp_path):
    async def run():
        port, _, http, svc, _, ledger, session, target, context, _ = await configured(station_api, tmp_path)
        try:
            await port.grant_return(session, target, context)
            svc.modes.transition(Mode.NAVIGATION)
            assert motion_ready(svc)
            await port.stop_return(session, context)
            assert not motion_ready(svc) and ledger.admitted(session.session_id)
            with pytest.raises(Exception):
                await port.renew_return(session, target, context)
            assert not motion_ready(svc)
        finally:
            await http.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['boot', 'generation', 'active', 'boolean_generation', 'context', 'principal'])
def test_unusable_native_or_durable_scope_cannot_grant(station_api, pipeline_sources, tmp_path, fault):
    async def run():
        port, client, http, svc, _, _, session, target, context, _ = await configured(station_api, tmp_path)
        try:
            original = client.docking_status
            async def bad_native():
                body = await original()
                key, value = {'boot': ('boot_id', 'other'), 'generation': ('owner_generation', -1),
                    'active': ('owner_run_id', 'other'), 'boolean_generation': ('owner_generation', True)}[fault]
                body['owner'][key] = value
                return body
            if fault in ('boot', 'generation', 'active', 'boolean_generation'):
                client.docking_status = bad_native
            elif fault == 'context':
                context = context | {'lease_id': 'other'}
            else:
                client._ep = type(client._ep)(session.robot_id, 'http://core',
                    station_api[3]['fleet-b']['Authorization'].split(' ', 1)[1])
            with pytest.raises(Exception):
                await port.grant_return(session, target, context)
            assert svc.station_docking.state == 'BOUND' and not motion_ready(svc)
        finally:
            await http.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['grant_reply_lost', 'expired_during_read'])
def test_grant_unknown_or_expired_read_never_replays_grant(station_api, pipeline_sources, tmp_path, fault):
    async def run():
        port, client, http, svc, now, ledger, session, target, context, _ = await configured(station_api, tmp_path)
        try:
            original = client.station_return
            sends = []
            async def grant(permit):
                sends.append(permit)
                body = await original(permit)
                raise OSError('SIM_REPLY_LOST')
            if fault == 'grant_reply_lost':
                client.station_return = grant
            else:
                owner = client.docking_status
                async def delayed():
                    body = await owner()
                    now[0] += .3  # original binding ACK/readback has expired before PUT
                    return body
                client.docking_status = delayed
            with pytest.raises(Exception):
                await port.grant_return(session, target, context)
            with pytest.raises(Exception):
                await port.grant_return(session, target, context)
            assert len(sends) == (1 if fault == 'grant_reply_lost' else 0)
            assert ledger.admitted(session.session_id)
            await port.stop_return(session, context)
            assert not motion_ready(svc)
        finally:
            await http.aclose()
    asyncio.run(run())


def test_stop_does_not_release_a_replacement_lease(station_api, pipeline_sources, tmp_path):
    async def run():
        port, client, http, svc, _, _, session, target, context, _ = await configured(station_api, tmp_path)
        try:
            await port.grant_return(session, target, context)
            await client.trip_lease_release(context['lease_id'])
            await client.trip_lease(dict(lease_id='replacement', trip_id='foreign-trip', holder='other',
                operator_name='SIM', ttl_s=5.))
            await port.stop_return(session, context)
            assert svc.trip_lease.current()['lease_id'] == 'replacement'
        finally:
            await http.aclose()
    asyncio.run(run())


def test_rejecting_dispatch_guard_prevents_both_station_puts(station_api, pipeline_sources, tmp_path):
    async def run():
        from fleet.swarm.dispatch_guard import dispatch_guard
        from core_common.protocol.station_charging import StationReturnPermit
        _, client, http, _, now, _, session, _, context, _ = await configured(station_api, tmp_path)
        requests = []
        async def record(request):
            requests.append(request)
        http.event_hooks['request'].append(record)
        def reject():
            raise ValueError('SIM_DISPATCH_CLOSED')
        permit = StationReturnPermit(**{key: getattr(session, key) for key in (
            'robot_id', 'station_id', 'battery_id', 'session_id', 'boot_id', 'map_id', 'map_revision', 'pose_revision')},
            correlation_id='return-1', lease_id=context['lease_id'], trip_id=context['plan_id'],
            expected_owner_generation=0, captured_at=now[0], valid_until=now[0]+1.)
        try:
            with dispatch_guard(reject):
                with pytest.raises(ValueError, match='SIM_DISPATCH_CLOSED'):
                    await client.station_bind(station_api[4])
                with pytest.raises(ValueError, match='SIM_DISPATCH_CLOSED'):
                    await client.station_return(permit)
            assert requests == []
        finally:
            await http.aclose()
    asyncio.run(run())


def test_actual_trip_runner_and_http_owner_wait_for_measured_handover(station_api, pipeline_sources, tmp_path):
    async def run():
        import dataclasses
        from fleet.server.site_map_store import SiteMapStore
        from fleet.server.trip_runner import TripRunner
        from fleet.server.trip_ports import TripConfig
        from fleet.server.charge_trip_port import ChargeReturnTrip
        from fleet.routing.trip import PlanRequest, plan_trip
        from fleet.routing.execute import plan_body
        from core_common.protocol.station_charging import ChargeDecision
        from test_trip_runner import Ports, BOTH, _free_map
        from test_charge_trip_port import CAPS
        from test_station_return_handover import TrackedNavigation
        port, client, http, svc, now, ledger, session, target, _, stations = await configured(station_api, tmp_path, trip=True)
        robot = Ports()
        backend = TrackedNavigation(svc.nav)
        svc.nav.executor = backend
        robot.caps[session.robot_id] = dataclasses.replace(BOTH, trip_lease=True, line_follow_authority=True)
        robot.now = now[0]
        async def lease(robot_id, body):
            return await client.trip_lease(body)
        async def release(robot_id, lease_id):
            return await client.trip_lease_release(lease_id)
        robot.trip_lease, robot.trip_lease_release = lease, release
        plans = SiteMapStore(None, clock=lambda: now[0])
        plans.import_if_empty(_free_map(), source='SIM')
        active = plans.active()
        robot.at(active[2].arcs['ab:fwd'], .1)
        plan = plan_trip(active[2], PlanRequest(map_version=active[0], start_pose=(.1, 0., 0.),
                                             goal=(1., 0., 0.)), plans.routing_config)
        plans.record_plan(plan_id='return-plan', robot_id=session.robot_id, principal_id='charge-policy',
            map_version=plan.map_version, request={'to': target.approach_pose.model_dump()}, result={'plan': plan_body(plan)})
        async def goal(robot_id, *args, **kwargs):
            svc.modes.transition(Mode.NAVIGATION)  # SIM motion backend; final CORE gate is real.
            assert motion_ready(svc)
            svc.nav.goal(svc.nav.resolve_goal(x=args[0], y=args[1], yaw=args[2]), correlation_id='SIM-return-goal')
            if abs(robot.pose.x-args[0]) < .01 and abs(robot.pose.y-args[1]) < .01:
                backend.done()  # SIM backend completes a goal already reached by the simulated plant.
            return await robot.goal(robot_id, *args, **kwargs)
        async def halt(robot_id):
            result = await robot.cancel_goal(robot_id)
            svc.modes.transition(Mode.IDLE)
            return result
        runner = TripRunner(store=plans, routing_config=plans.routing_config, caps=robot.caps_for,
            poses=robot, junction=robot, goal=goal, cancel_goal=halt, clock=lambda: now[0],
            config=TripConfig(), lease={'required': True, 'holder': 'station'})
        runner.lease._clock = lambda: now[0]
        runner.authority.enabled = True
        runner.lease.claimed = lambda _: next(iter(ledger.tasks.resource_claims(
            resource_kind='robot', resource_id=session.robot_id)), None)
        async def lost(*args):
            pytest.fail('unexpected charge lease loss')
        runner.lease.on_charge_lost = lost
        adapter = ChargeReturnTrip(runner=runner, plans=plans, store=ledger, stations=stations,
            robot_port=port, plan=lambda *_: 'return-plan', capabilities=lambda _: CAPS,
            principal_id='charge-policy', map_scope=lambda version, map_id: ('floor', 'map-1')
                if (version, map_id) == (active[0], active[1].map_id) else None, clock=lambda: now[0],
            admit_return=lambda *_: ChargeDecision(decision='RETURN_REQUIRED', reason='SIM_BUDGET',
                profile_revision='SIM', capacity_revision=None))
        try:
            operation = await adapter.start_return(session, target, correlation_id='return-1')
            session = ledger.acknowledge_operation(session.session_id, correlation_id='return-1',
                                                  operation_id=operation, now=now[0])
            await asyncio.wait_for(adapter._tasks[session.session_id], 1.)
            await runner.tick()
            assert robot.goals and svc.station_docking.state == 'RETURNING'
            robot.at(active[2].arcs['ab:fwd'], 1.)
            backend.done()  # The plant passed the first lookahead goal while reaching the approach point.
            for _ in range(4):
                await runner.tick()
            assert runner.view(operation)['state'] == 'arrived'
            assert svc.nav.nav_state.value == 'ARRIVED'
            assert (await adapter.read_return(session))['state'] == 'RUNNING'
            assert ledger.return_context(session.session_id)['phase'] == 'SUBMITTED'
            assert svc.modes.mode is Mode.IDLE  # Actual scoped CORE terminal handover, no test mode write.
            motion = dict(odom_epoch='odom-1', measured_linear_m_s=0., measured_angular_rad_s=0.)
            svc.station_docking.motion_feed = SimpleNamespace(snapshot=lambda: dict(motion), clear=lambda: None)
            for _ in range(6):
                robot.now = now[0] = now[0]+.1
                motion.update(captured_at=now[0], valid_until=now[0]+.25)
                svc.station_docking.tick()
            assert (await adapter.read_return(session))['state'] == 'SUCCEEDED'
            assert svc.station_docking.state == 'BOUND' and not motion_ready(svc)
            assert ledger.admitted(session.session_id)
            assert ledger.return_context(session.session_id)['phase'] == 'FINISHED'
        finally:
            await http.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['reply_lost', 'readback_lost'])
def test_successful_core_finish_with_missing_evidence_remains_uncertain(station_api, pipeline_sources, tmp_path, fault):
    async def run():
        port, client, http, svc, now, ledger, session, target, context, _ = await configured(station_api, tmp_path)
        try:
            await port.grant_return(session, target, context)
            motion = dict(odom_epoch='odom-1', measured_linear_m_s=0., measured_angular_rad_s=0.)
            svc.station_docking.motion_feed = SimpleNamespace(snapshot=lambda: dict(motion), clear=lambda: None)
            for _ in range(6):
                now[0] += .1
                motion.update(captured_at=now[0], valid_until=now[0]+.25)
                svc.station_docking.tick()
            ledger.return_phase(session.session_id, expected='PREPARED', next_phase='SUBMITTED')
            ledger.return_phase(session.session_id, expected='SUBMITTED', next_phase='FINISH_PENDING')
            original_finish, original_read = client.station_return_finish, client.station_target
            posted = []
            async def finish(command):
                answer = await original_finish(command)
                posted.append(command)
                if fault == 'reply_lost':
                    raise OSError('SIM_FINISH_REPLY_LOST')
                return answer
            async def read():
                if posted:
                    raise OSError('SIM_POST_FINISH_READBACK_LOST')
                return await original_read()
            client.station_return_finish = finish
            if fault == 'readback_lost':
                client.station_target = read
            with pytest.raises(OSError):
                await port.finish_return(session, target, context)
            assert len(posted) == 1 and svc.station_docking.state == 'BOUND'
            assert ledger.return_context(session.session_id)['phase'] == 'FINISH_PENDING'
            assert ledger.admitted(session.session_id)
            await port.stop_return(session, context)
        finally:
            await http.aclose()
    asyncio.run(run())
