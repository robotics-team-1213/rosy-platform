"""Periodic policy drives the durable service; source samples are explicit SIM."""
import asyncio
import importlib
import importlib.util

import pytest

from test_charge_policy import battery, profile
from test_charge_return import moving_controller


def configured(tmp_path, *, policy_profile=None):
    name = 'fleet.server.charge_policy_admission'
    assert importlib.util.find_spec(name) is not None, 'source-aged runtime policy admission is missing'
    admission = importlib.import_module(name)
    name = 'fleet.server.charge_runtime'
    assert importlib.util.find_spec(name) is not None, 'periodic charge runtime is missing'
    module = importlib.import_module(name)
    service, store, tasks, ports = moving_controller(tmp_path)
    now, enabled = [101.], [True]
    service.clock = lambda: now[0]
    service.stations.clock = service.clock
    service.policy_enabled = lambda: enabled[0]
    policy = admission.ChargePolicyAdmission(profiles={'robot-1': policy_profile or profile()}, clock=service.clock,
        budget_source=('route-budget', 'budget-boot', 'cost-1'), max_age_s=2.)
    sample = dict(robot_id='robot-1', boot_id='boot-1', battery_id='pack-1',
        captured_at=101., valid_until=110., mode='IDLE', safe_work_boundary=True, safety_latched=False,
        dock_state='UNDOCKED', map_id='floor', map_revision='map-1',
        battery_energy=battery(captured_at=101., valid_until=110., soc_percent=10.).model_dump(),
        charge_budget=dict(robot_id='robot-1', boot_id='boot-1', station_id='charger-1',
            map_id='floor', map_revision='map-1', pose_revision=1, profile_revision='profile-1',
            source_id='route-budget', source_epoch='budget-boot', cost_revision='cost-1',
            captured_at=101., valid_until=110., work_wh=4., return_wh=2., dock_wh=.5, reserve_wh=1.,
            work_duration_s=100., return_duration_s=50., work_task_id=None, work_request_digest=None))
    reads = []
    async def snapshot(robot_id):
        reads.append(robot_id)
        return dict(sample)
    ports.snapshot = snapshot
    service.admit_return = policy
    runtime = module.ChargeRuntime(service, robot_id='robot-1', station_id='charger-1',
        admission=policy, monotonic=lambda: now[0], period_s=.1)
    return runtime, service, store, tasks, ports, sample, now, enabled, reads


def test_low_soc_periodically_reserves_and_advances_once_with_retained_claim(tmp_path):
    async def run():
        runtime, _, store, tasks, ports, _, now, _, _ = configured(tmp_path)
        await runtime.tick()
        assert store.get('charge-1').state == 'RETURNING'
        assert ports.calls.count(('bind', 'charge-1')) == 1
        assert ports.calls.count(('start', 'return')) == 1
        for _ in range(5):
            now[0] += .1
            await runtime.tick()
        assert ports.calls.count(('start', 'return')) == 1
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
        assert runtime.decision.decision == 'RETURN_REQUIRED'
    asyncio.run(run())


@pytest.mark.parametrize('origin', [0., 1_000_000.])
def test_original_source_expiry_drives_refresh_across_independent_clock_epochs(tmp_path, origin):
    async def run():
        runtime, _, _, _, _, sample, utc, _, reads = configured(tmp_path)
        mono = [origin]
        runtime.monotonic = lambda: mono[0]
        sample['battery_energy']['soc_percent'] = 75.
        for evidence in (sample, sample['battery_energy'], sample['charge_budget']):
            evidence.update(captured_at=utc[0], valid_until=utc[0]+.2)
        await runtime.tick()
        assert runtime.work_admission('robot-1') is None
        mono[0] += .1
        utc[0] += .1
        await runtime.tick()
        assert len(reads) == 1  # The UTC epoch must not cause premature polling either.
        mono[0] += .15
        utc[0] += .15
        for evidence in (sample, sample['battery_energy'], sample['charge_budget']):
            evidence.update(captured_at=utc[0], valid_until=utc[0]+.2)
        await runtime.tick()
        assert len(reads) == 2
        assert runtime.work_admission('robot-1') is None
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['healthy', 'unknown_health', 'expired_battery', 'expired_budget',
    'wrong_budget_scope', 'wrong_source', 'wrong_profile', 'future_snapshot', 'no_boundary', 'manual', 'disabled'])
def test_unusable_or_unnecessary_return_never_reserves_or_sends(tmp_path, fault):
    async def run():
        runtime, _, store, _, ports, sample, _, enabled, _ = configured(tmp_path)
        if fault == 'healthy':
            sample['battery_energy']['soc_percent'] = 75.
        elif fault == 'unknown_health':
            sample['battery_energy'].update(source='unknown', capacity_revision=None,
                soh_percent=None, usable_energy_wh=None)
        elif fault == 'expired_battery':
            sample['battery_energy']['valid_until'] = 100.9
        elif fault == 'expired_budget':
            sample['charge_budget']['valid_until'] = 100.9
        elif fault == 'wrong_budget_scope':
            sample['charge_budget']['pose_revision'] = 2
        elif fault == 'wrong_source':
            sample['charge_budget']['source_epoch'] = 'unregistered'
        elif fault == 'wrong_profile':
            sample['charge_budget']['profile_revision'] = 'old-profile'
        elif fault == 'future_snapshot':
            sample['captured_at'] = 102.
        elif fault == 'no_boundary':
            sample['safe_work_boundary'] = False
        elif fault == 'manual':
            sample['mode'] = 'MANUAL'
        else:
            enabled[0] = False
        await runtime.tick()
        assert store.list() == [] and ports.calls == []
    asyncio.run(run())


def test_work_cost_can_trigger_return_before_low_soc_and_soh_can_hold(tmp_path):
    async def run():
        runtime, _, store, _, ports, sample, now, _, _ = configured(tmp_path)
        sample['battery_energy'].update(soc_percent=60., usable_energy_wh=5.)
        await runtime.tick()
        assert runtime.decision.reason == 'WORK_WOULD_CONSUME_RETURN_RESERVE'
        assert store.get('charge-1').state == 'RETURNING'
        now[0] += 1.
        sample['battery_energy']['soh_percent'] = 40.
        await runtime.tick()
        assert store.get('charge-1').state == 'HOLD'
        assert ports.calls.count(('stop', 'return')) == 1
    asyncio.run(run())


def test_poll_period_controls_evaluation_but_does_not_renew_source_time(tmp_path):
    async def run():
        runtime, _, store, _, ports, sample, now, _, reads = configured(tmp_path)
        sample['battery_energy']['soc_percent'] = 75.
        sample['battery_energy']['valid_until'] = 101.5
        await runtime.tick()
        assert runtime.decision.decision == 'WORK_ALLOWED'
        await runtime.tick()
        assert len(reads) == 1
        now[0] += 1.
        sample['battery_energy']['soc_percent'] = 10.
        await runtime.tick()
        assert runtime.decision.decision == 'WAIT' and store.list() == [] and ports.calls == []
    asyncio.run(run())


@pytest.mark.parametrize('change', ['disabled', 'close', 'clock_reversed'])
def test_runtime_closes_motion_and_preserves_claims(tmp_path, change):
    async def run():
        runtime, _, store, tasks, ports, _, now, enabled, _ = configured(tmp_path)
        await runtime.tick()
        if change == 'disabled':
            enabled[0] = False
            await runtime.tick()
        elif change == 'clock_reversed':
            now[0] -= .1
            await runtime.tick()
        else:
            await runtime.aclose()
            await runtime.tick()
        assert store.get('charge-1').state == 'HOLD'
        assert ports.calls.count(('start', 'return')) == 1
        assert ports.calls.count(('stop', 'return')) == 1
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    asyncio.run(run())


def test_unknown_submission_is_not_retried_by_periodic_runtime(tmp_path):
    async def run():
        runtime, _, store, _, ports, _, now, _, _ = configured(tmp_path)
        ports.fail_start = True
        await runtime.tick()
        assert store.get('charge-1').state == 'HOLD'
        for _ in range(3):
            now[0] += 1.
            await runtime.tick()
        assert ports.calls.count(('start', 'return')) == 1
    asyncio.run(run())


def test_changed_station_configuration_holds_original_owner(tmp_path):
    async def run():
        runtime, service, store, tasks, ports, _, _, _, _ = configured(tmp_path)
        await runtime.tick()
        replacement = type(runtime)(service, robot_id='robot-1', station_id='new-station',
            admission=runtime.admission, monotonic=runtime.monotonic, period_s=.1)
        await replacement.tick()
        assert store.get('charge-1').state == 'HOLD'
        assert ports.calls.count(('stop', 'return')) == 1
        assert ports.calls.count(('start', 'return')) == 1
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    asyncio.run(run())


@pytest.mark.parametrize('action', ['tick', 'close'])
def test_database_failure_still_stops_exact_cached_owner(tmp_path, monkeypatch, action):
    async def run():
        runtime, service, store, tasks, ports, _, _, _, _ = configured(tmp_path)
        await runtime.tick()
        stops = []
        async def stop(current, intent):
            stops.append((current, dict(intent)))
        ports.stop_operation = stop
        def unavailable(*args, **kwargs):
            raise OSError('database unavailable')
        for name in ('list', 'get', 'operation_intent', 'operation_unknown', 'transition'):
            monkeypatch.setattr(store, name, unavailable)
        with pytest.raises(OSError, match='database unavailable'):
            await (runtime.tick() if action == 'tick' else runtime.aclose())
        assert len(stops) == 1
        current, intent = stops[0]
        assert current.session_id == intent['session_id'] == 'charge-1'
        assert intent['kind'] == 'return' and intent['correlation_id']
        assert intent['operation_id'] == 'native-return'
        await runtime.tick()  # Failed close never opens a new admission.
        assert ports.calls.count(('start', 'return')) == 1
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    asyncio.run(run())


def test_cancellation_during_lost_start_reply_keeps_exact_pre_send_intent(tmp_path):
    async def run():
        runtime, _, store, tasks, ports, _, _, _, _ = configured(tmp_path)
        sent, pending, stops = asyncio.Event(), asyncio.Event(), []
        async def start(current, target, *, correlation_id):
            sent.set()
            await pending.wait()
        async def stop(current, intent):
            stops.append(dict(intent))
        ports.start_return, ports.stop_operation = start, stop
        task = asyncio.create_task(runtime.run())
        await sent.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert store.get('charge-1').state == 'HOLD'
        assert len(stops) == 1
        assert stops[0]['session_id'] == 'charge-1'
        assert stops[0]['kind'] == 'return' and stops[0]['correlation_id']
        assert stops[0]['operation_id'] is None
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    asyncio.run(run())


def test_policy_disabled_during_second_source_read_never_binds(tmp_path):
    async def run():
        runtime, _, store, _, ports, sample, _, enabled, _ = configured(tmp_path)
        reads = []
        async def snapshot(robot_id):
            reads.append(robot_id)
            if len(reads) == 2:
                enabled[0] = False
            return dict(sample)
        ports.snapshot = snapshot
        await runtime.tick()
        assert store.list() == [] and ports.calls == []
    asyncio.run(run())


@pytest.mark.parametrize('result', ['ready', 'waiting', 'stale', 'disabled', 'manual'])
def test_navigation_work_boundary_is_passive_and_requires_new_source(tmp_path, result):
    async def run():
        runtime, _, store, _, ports, sample, now, enabled, reads = configured(tmp_path)
        sample.update(mode='NAVIGATION', safe_work_boundary=False)
        handovers = []

        async def finish_work(robot_id, *, expected_boot_id, admission):
            handovers.append(robot_id)
            assert expected_boot_id == sample['boot_id']
            assert admission() is None
            if result == 'stale':
                now[0] += 3.
                assert admission() is not None
                return False
            if result == 'disabled':
                enabled[0] = False
                assert admission() is not None
                return False
            if result == 'waiting':
                return False
            # A new SIM adapter sample, not a runtime-written mode or completion.
            sample.update(mode='MANUAL' if result == 'manual' else 'IDLE', safe_work_boundary=True)
            return True

        runtime.finish_work = finish_work
        await runtime.tick()
        assert handovers == ['robot-1']
        if result == 'ready':
            assert len(reads) >= 3
            assert store.get('charge-1').state == 'RETURNING'
        else:
            assert store.list() == [] and ports.calls == []
    asyncio.run(run())


def test_intent_lookup_failure_does_not_discard_cached_correlation(tmp_path, monkeypatch):
    async def run():
        runtime, service, store, _, ports, _, _, _, _ = configured(tmp_path)
        await runtime.tick()
        stops = []
        async def stop(current, intent):
            assert intent['correlation_id']
            stops.append(dict(intent))
        ports.stop_operation = stop
        def unavailable(*args):
            raise OSError('intent storage unavailable')
        monkeypatch.setattr(store, 'operation_intent', unavailable)
        # Cached exact intent makes the lookup unnecessary; HOLD persistence still runs.
        await service.hold('charge-1', reason='TEST_STOP')
        assert len(stops) == 1 and stops[0]['operation_id'] == 'native-return'
        assert store.get('charge-1').state == 'HOLD'
    asyncio.run(run())


def test_unfinished_handover_is_rechecked_even_after_the_source_reports_idle(tmp_path):
    async def exercise():
        runtime, _, store, _, ports, sample, now, _, _ = configured(tmp_path,
            policy_profile=profile(reevaluate_interval_s=.1))
        sample.update(mode='NAVIGATION', safe_work_boundary=False)
        calls = []
        async def finish(robot, **kwargs):
            calls.append(robot)
            # CORE accepted passive IDLE, but local projection retirement lost a race.
            sample.update(mode='IDLE', safe_work_boundary=True)
            return len(calls) > 1
        runtime.finish_work = finish
        await runtime.tick()
        assert calls == ['robot-1'] and store.list() == [] and ports.calls == []
        now[0] += .1
        await runtime.tick()
        assert calls == ['robot-1', 'robot-1']
        assert store.get('charge-1').state == 'RETURNING'
    asyncio.run(exercise())


def test_new_work_requires_current_original_energy_and_return_keeps_priority(tmp_path):
    async def run():
        runtime, _, _, _, _, sample, now, _, _ = configured(tmp_path)
        assert runtime.work_admission('robot-1') is not None
        assert runtime.work_admission('other-robot') is None
        sample['battery_energy'].update(soc_percent=75., valid_until=101.5)
        await runtime.tick()
        assert runtime.work_admission('robot-1') is None
        now[0] = 101.6
        assert runtime.work_admission('robot-1') == 'CHARGE_POLICY_INPUT_UNVERIFIED'
        now[0] = 102.
        sample['battery_energy'].update(soc_percent=10., captured_at=102., valid_until=103.)
        await runtime.tick()
        assert runtime.work_admission('robot-1') == 'LOW_SOC_RETURN'
    asyncio.run(run())
