"""Charge returns use the real planner, TripRunner and durable charging claim (software SIM)."""
import asyncio
import dataclasses
import importlib
import importlib.util
import threading
from types import SimpleNamespace

import pytest

from core_common.protocol.station_charging import ChargeDecision, ChargeSessionStatus, StationPoseRecord, StationPoseAck
from fleet.routing.execute import plan_body
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.site_map_store import SiteMapStore
from fleet.server.station_store import StationStore
from fleet.server.station_service import StationService
from fleet.server.trip_runner import TripRunner
from fleet.server.trip_ports import TripConfig
from test_charge_store import store
from test_trip_runner import Ports, BOTH, _free_map

R = 'rosy_60'
CAPS = {'controls': {'items': [dict(kind='base_velocity', trip_lease=True, trip_lease_job=True,
    goal_lease=True, line_follow_authority=True, line_follow_authority_under_lease=True, drive_modes=['free'])]}}


class Robot(Ports):
    def __init__(self):
        super().__init__(dataclasses.replace(BOTH, trip_lease=True, line_follow_authority=True))
        self.lease_body, self.lease_puts, self.lease_deletes = None, [], []

    async def trip_lease(self, robot, body):
        renewed = self.lease_body is not None
        self.lease_body = dict(body)
        self.lease_puts.append(dict(body))
        return dict(renewed=renewed, trip_lease=dict(body))

    async def trip_lease_release(self, robot, lease_id):
        self.lease_deletes.append(lease_id)
        if self.lease_body and self.lease_body['lease_id'] == lease_id:
            self.lease_body = None
        return {}


def _setup(tmp_path):
    name = 'fleet.server.charge_trip_port'
    assert importlib.util.find_spec(name) is not None, 'real charge return trip adapter is missing'
    module = importlib.import_module(name)
    robot = Robot()
    plans = SiteMapStore(None, clock=lambda: robot.now)
    plans.import_if_empty(_free_map(), source='SIM')
    runner = TripRunner(store=plans, routing_config=plans.routing_config, caps=robot.caps_for, poses=robot,
        junction=robot, goal=robot.goal, cancel_goal=robot.cancel_goal, clock=lambda: robot.now,
        config=TripConfig(), lease={'required': True, 'holder': 'station'})
    runner.lease._clock = lambda: robot.now
    runner.authority.enabled = True
    ledger, tasks = store(tmp_path)
    runner.lease.claimed = lambda _: next(iter(tasks.resource_claims(resource_kind='robot', resource_id=R)), None)
    losses = []
    async def lost(view, detail):
        losses.append((view['job_id'], detail))
    runner.lease.on_charge_lost = lost
    session = ledger.reserve(ChargeSessionStatus(session_id='charge-1', robot_id=R, station_id='charger-1',
        battery_id='pack-1', boot_id='boot-1', map_id='floor', map_revision='map-1', pose_revision=1,
        state='RETURN_RESERVED', attempt_id='attempt-1', reason='SIM', updated_at=robot.now))
    session = ledger.transition(session.session_id, expected_state='RETURN_RESERVED', next_state='RETURNING',
        attempt_id=session.attempt_id, now=robot.now, reason='PREPARED', intent_kind='return', correlation_id='return-1')
    registry = StationStore(tmp_path/'site.sqlite')
    target = StationPoseRecord(station_id='charger-1', map_id='floor', map_revision='map-1', pose_revision=1,
        pose=dict(x=1.4, y=0., yaw=0.), approach_pose=dict(x=1., y=0., yaw=0.), approach_verified=True,
        source_id='global', source_epoch='boot', calibration_revision='cal', uncertainty_m=0.002,
        uncertainty_rad=0.005, captured_at=999., valid_until=1100., status='CANDIDATE')
    registry.propose(target)
    target = registry.confirm(target.station_id, expected_revision=1)
    stations = StationService(registry, clock=lambda: robot.now, map_scope=lambda: ('floor', 'map-1'),
        trusted_sources={}, robot_scope=lambda _: ('boot-1', 'charge-1'), approach_validator=lambda _: True,
        position_tolerance_m=0.03, heading_tolerance_rad=0.05, max_uncertainty_m=0.02,
        max_uncertainty_rad=0.03, consistency_samples=3)
    graph = plans.active()[2]
    robot.at(graph.arcs['ab:fwd'], 0.1)
    generated = plan_trip(graph, PlanRequest(map_version=plans.active()[0], start_pose=(0.1, 0., 0.),
        goal=(1., 0., 0.)), plans.routing_config)
    plans.record_plan(plan_id='return-plan', robot_id=R, principal_id='charge-policy',
        map_version=generated.map_version, request={'to': target.approach_pose.model_dump()},
        result={'plan': plan_body(generated)})
    events = []
    async def grant(current, position, context):
        assert ledger.return_context(current.session_id)['plan_id'] == 'return-plan'
        assert robot.lease_body['trip_id'] == 'return-plan'
        assert robot.lease_body['job_id'] == current.session_id
        assert robot.lease_body['lease_id'] == context['lease_id']
        events.append('grant')
    async def renew(current, position, context):
        events.append('renew')
    async def finish(current, position, context):
        assert runner.view(context['plan_id'])['state'] == 'arrived'
        events.append('finish')
        return StationPoseAck(robot_id=R, station_id='charger-1', session_id='charge-1', boot_id='boot-1',
            map_id='floor', map_revision='map-1', pose_revision=1, accepted=True,
            captured_at=robot.now, valid_until=robot.now+0.2)
    async def stop(current, context):
        events.append('stop')
    async def navigation_ready(current, context):
        return True  # Explicit SIM native backend, real HTTP readiness is tested in gateway.
    adapter = module.ChargeReturnTrip(runner=runner, plans=plans, store=ledger, stations=stations,
        robot_port=SimpleNamespace(grant_return=grant, renew_return=renew, finish_return=finish, stop_return=stop,
                                  navigation_ready=navigation_ready),
        plan=lambda *_: 'return-plan', capabilities=lambda _: CAPS, principal_id='charge-policy',
        map_scope=lambda version, map_id: ('floor', 'map-1') if (
            version, map_id) == (generated.map_version, plans.active()[1].map_id) else None, clock=lambda: robot.now,
        admit_return=lambda *_: ChargeDecision(decision='RETURN_REQUIRED', reason='SIM_BUDGET',
            profile_revision='sim-1', capacity_revision=None))
    return adapter, runner, plans, robot, ledger, tasks, session, target, events, losses


async def started(tmp_path):
    adapter, runner, plans, robot, ledger, tasks, session, target, events, losses = _setup(tmp_path)
    operation = await adapter.start_return(session, target, correlation_id='return-1')
    assert operation == 'return-plan'
    session = ledger.acknowledge_operation(session.session_id, correlation_id='return-1',
                                          operation_id=operation, now=robot.now)
    await asyncio.wait_for(adapter._tasks[session.session_id], 1.)
    return adapter, runner, robot, ledger, session, target, events, losses


def test_actual_trip_starts_once_under_scoped_charge_lease_then_hands_over(tmp_path):
    async def run():
        adapter, runner, robot, ledger, session, target, events, _ = await started(tmp_path)
        assert runner.view('return-plan') is not None
        assert (await adapter.read_return(session))['state'] == 'RUNNING'
        with pytest.raises(ValueError):
            await adapter.start_return(session, target, correlation_id='return-1')
        await runner.tick()
        assert robot.goals and events[0] == 'grant'
        robot.at(runner._store.active()[2].arcs['ab:fwd'], 1.)
        robot.now += 0.1
        for _ in range(4):
            await runner.tick()
            await asyncio.sleep(0)
        result = await adapter.read_return(session)
        assert result['state'] == 'SUCCEEDED' and result['operation_id'] == 'return-plan'
        assert events.count('finish') == 1
        assert ledger.admitted(session.session_id)  # Trip lease release is not ordinary work availability.
        assert runner.lease.job_of(R) == 'charge-1'  # The durable charge claim remains visible.
    asyncio.run(run())


@pytest.mark.parametrize('missing', [False, True])
def test_charge_goal_does_not_send_while_native_busy_or_readiness_port_missing(tmp_path, missing):
    async def run():
        adapter, runner, robot, _, _, _, _, _ = await started(tmp_path)
        if missing:
            runner.charge_goal_ready = None
        else:
            async def busy(*_):
                return False
            adapter.robot_port.navigation_ready = busy
        await runner.tick()
        assert robot.goals == []
        assert runner.view('return-plan')['state'] == ('failed' if missing else 'running')
    asyncio.run(run())


@pytest.mark.parametrize('timeout', [False, True])
def test_route_arrival_waits_for_native_terminal_before_finish(tmp_path, timeout):
    async def run():
        adapter, runner, robot, ledger, session, _, events, _ = await started(tmp_path)
        robot.at(runner._store.active()[2].arcs['ab:fwd'], 1.)
        for _ in range(4):
            await runner.tick()
        assert runner.view('return-plan')['state'] == 'arrived'
        async def busy(*_):
            return False
        ready = adapter.robot_port.navigation_ready
        adapter.robot_port.navigation_ready = busy
        if timeout:
            runner.config = dataclasses.replace(runner.config, stall_s=.5)  # Keep the independent lease live.
        assert (await adapter.read_return(session))['state'] == 'RUNNING'
        assert ledger.return_context(session.session_id)['phase'] == 'SUBMITTED'
        assert 'finish' not in events
        if timeout:
            robot.now += runner.config.stall_s
            with pytest.raises(ValueError, match='NAVIGATION_TERMINAL_TIMEOUT'):
                await adapter.read_return(session)
            assert 'finish' not in events
        else:
            adapter.robot_port.navigation_ready = ready
            assert (await adapter.read_return(session))['state'] == 'SUCCEEDED'
            assert events.count('finish') == 1
    asyncio.run(run())


def test_repeated_standstill_refusal_shares_the_arrival_deadline(tmp_path):
    async def run():
        adapter, runner, robot, ledger, session, _, events, _ = await started(tmp_path)
        runner.config = dataclasses.replace(runner.config, stall_s=.5)
        robot.at(runner._store.active()[2].arcs['ab:fwd'], 1.)
        for _ in range(4):
            await runner.tick()
        async def not_still(*_):
            events.append('not_still')
            return None  # Explicit SIM STATION_RETURN_STANDSTILL_REQUIRED, not a lost reply.
        adapter.robot_port.finish_return = not_still
        for _ in range(3):
            assert (await adapter.read_return(session))['state'] == 'RUNNING'
            robot.now += .2
        with pytest.raises(ValueError, match='NAVIGATION_TERMINAL_TIMEOUT'):
            await adapter.read_return(session)
        assert events.count('not_still') == 3
        assert ledger.return_context(session.session_id)['phase'] == 'SUBMITTED'
        assert ledger.admitted(session.session_id)
    asyncio.run(run())


@pytest.mark.parametrize('change', ['energy', 'principal', 'map', 'goal', 'robot', 'endpoint'])
def test_invalid_admission_never_opens_lease_or_grants_motion(tmp_path, change):
    async def run():
        adapter, runner, plans, robot, ledger, _, session, target, events, _ = _setup(tmp_path)
        if change == 'energy':
            adapter.admit_return = lambda *_: ChargeDecision(decision='WAIT', reason='UNKNOWN',
                profile_revision='sim-1', capacity_revision=None)
        elif change == 'principal':
            adapter.principal_id = 'other'
        elif change == 'map':
            adapter.map_scope = lambda version, map_id: ('floor', 'other')
        elif change == 'goal':
            target = target.model_copy(update={'approach_pose': target.pose})
        elif change == 'endpoint':
            original = plans.plan
            def wrong(plan_id):
                row = original(plan_id)
                row['result']['plan']['segments'][-1]['s_to'] = 0.4
                return row
            plans.plan = wrong
        else:
            session = session.model_copy(update={'robot_id': 'other'})
        with pytest.raises(ValueError):
            await adapter.start_return(session, target, correlation_id='return-1')
        assert robot.lease_puts == [] and events == [] and runner.view('return-plan') is None
    asyncio.run(run())


def test_cancel_during_caps_fetch_cannot_start_late(tmp_path):
    async def run():
        adapter, runner, _, robot, _, _, session, target, events, _ = _setup(tmp_path)
        entered, resume = asyncio.Event(), asyncio.Event()
        async def caps(_):
            entered.set()
            await resume.wait()
            return CAPS
        adapter.capabilities = caps
        pending = asyncio.create_task(adapter.start_return(session, target, correlation_id='return-1'))
        await entered.wait()
        await adapter.stop_return(session)
        resume.set()
        with pytest.raises(Exception):
            await pending
        assert not robot.lease_puts and 'grant' not in events and runner.view('return-plan') is None
    asyncio.run(run())


def test_restart_is_read_only_and_does_not_resubmit(tmp_path):
    async def run():
        adapter, runner, robot, ledger, session, target, events, _ = await started(tmp_path)
        before = len(robot.lease_puts)
        adapter._tasks.clear()
        adapter._tokens.clear()  # no in-memory submission ownership after reconstruction
        with pytest.raises(ValueError):
            await adapter.read_return(session)
        with pytest.raises(ValueError):
            await adapter.start_return(session, target, correlation_id='return-1')
        assert len(robot.lease_puts) == before and events.count('grant') == 1
        assert ledger.admitted(session.session_id)
        await adapter.stop_return(session)
    asyncio.run(run())


def test_charge_lease_loss_uses_charge_hook_and_blocks_readback(tmp_path):
    async def run():
        adapter, runner, _, _, session, _, _, losses = await started(tmp_path)
        missions = []
        async def mission(*args):
            missions.append(args)
        runner.lease.on_job_lost = mission
        await runner.lease.lose(runner.lease.jobs[R], 'expired')
        assert losses and not missions
        with pytest.raises(ValueError):
            await adapter.read_return(session)
        await adapter.stop_return(session)
    asyncio.run(run())


@pytest.mark.parametrize('method', ['return_context', 'return_phase'])
def test_stop_attempts_core_trip_and_exact_lease_cleanup_even_when_database_fails(tmp_path, method):
    async def run():
        adapter, runner, robot, ledger, session, _, events, _ = await started(tmp_path)
        context = ledger.return_context(session.session_id)
        def broken(*args, **kwargs):
            raise OSError('SIM_DB_UNAVAILABLE_OR_CAS_CONFLICT')
        setattr(ledger, method, broken)
        with pytest.raises(OSError):
            await adapter.stop_return(session)
        assert 'stop' in events and runner.view('return-plan')['state'] == 'canceled'
        assert context['lease_id'] in robot.lease_deletes
        assert R not in runner.lease.jobs
    asyncio.run(run())


def test_stop_fences_pending_start_before_a_blocked_journal_read(tmp_path):
    async def run():
        adapter, runner, _, robot, ledger, _, session, target, events, _ = _setup(tmp_path)
        entered, resume = asyncio.Event(), asyncio.Event()
        async def caps(_):
            entered.set()
            await resume.wait()
            return CAPS
        adapter.capabilities = caps
        pending = asyncio.create_task(adapter.start_return(session, target, correlation_id='return-1'))
        await entered.wait()
        original = ledger.return_context
        blocked, release = threading.Event(), threading.Event()
        def slow_read(session_id):
            blocked.set()
            assert release.wait(2.)
            return original(session_id)
        ledger.return_context = slow_read
        stopping = asyncio.create_task(adapter.stop_return(session))
        try:
            await asyncio.wait_for(asyncio.to_thread(blocked.wait), 1.)
            assert 'stop' in events  # physical permission revoked before journal wait
            resume.set()
            await asyncio.sleep(0)
            assert not robot.lease_puts and 'grant' not in events and runner.view('return-plan') is None
        finally:
            release.set()
        await stopping
        with pytest.raises(Exception):
            await pending
    asyncio.run(run())


def test_uncertain_core_finish_is_not_repeated_or_reported_as_arrival(tmp_path):
    async def run():
        adapter, runner, robot, ledger, session, _, events, _ = await started(tmp_path)
        await runner.tick()
        robot.at(runner._store.active()[2].arcs['ab:fwd'], 1.)
        robot.now += 0.1
        for _ in range(4):
            await runner.tick()
        async def lost_reply(*args):
            events.append('finish')
            raise OSError('SIM_REPLY_LOST')
        adapter.robot_port.finish_return = lost_reply
        with pytest.raises(OSError):
            await adapter.read_return(session)
        with pytest.raises(ValueError):
            await adapter.read_return(session)
        assert events.count('finish') == 1 and ledger.admitted(session.session_id)
        assert ledger.return_context(session.session_id)['phase'] == 'FINISH_PENDING'
        await adapter.stop_return(session)
    asyncio.run(run())


def test_explicit_standstill_refusal_waits_and_keeps_the_same_return(tmp_path):
    async def run():
        adapter, runner, robot, ledger, session, _, events, _ = await started(tmp_path)
        await runner.tick()
        robot.at(runner._store.active()[2].arcs['ab:fwd'], 1.)
        robot.now += .1
        for _ in range(4):
            await runner.tick()
        finish = adapter.robot_port.finish_return
        async def not_still(*args):
            events.append('definite_standstill_refusal')
            return None
        adapter.robot_port.finish_return = not_still
        assert (await adapter.read_return(session))['state'] == 'RUNNING'
        assert ledger.return_context(session.session_id)['phase'] == 'SUBMITTED'
        assert ledger.admitted(session.session_id)
        adapter.robot_port.finish_return = finish
        assert (await adapter.read_return(session))['state'] == 'SUCCEEDED'
        assert events.count('grant') == events.count('finish') == 1
    asyncio.run(run())


def test_relocation_cancels_only_persisted_return_and_never_restarts(tmp_path):
    async def run():
        adapter, runner, robot, ledger, session, target, events, _ = await started(tmp_path)
        adapter.stations.store.invalidate('charger-1', expected_revision=1, reason='MOVED')
        with pytest.raises(ValueError):
            await adapter.read_return(session)
        await adapter.stop_return(session)
        assert runner.view('return-plan')['state'] == 'canceled'
        assert 'stop' in events and ledger.admitted(session.session_id)
        with pytest.raises(ValueError):
            await adapter.start_return(session, target, correlation_id='return-1')
    asyncio.run(run())


def test_context_is_durable_before_first_lease_packet_and_cannot_be_rebound(tmp_path):
    async def run():
        adapter, _, _, robot, ledger, _, session, target, _, _ = _setup(tmp_path)
        original = robot.trip_lease
        async def opening(robot_id, body):
            context = ledger.return_context('charge-1')
            assert context['lease_id'] == body['lease_id'] and context['correlation_id'] == 'return-1'
            return await original(robot_id, body)
        robot.trip_lease = opening
        await adapter.start_return(session, target, correlation_id='return-1')
        with pytest.raises(ValueError):
            ledger.prepare_return('charge-1', correlation_id='return-1', plan_id='other', lease_id='other')
        await adapter.stop_return(session)
    asyncio.run(run())
