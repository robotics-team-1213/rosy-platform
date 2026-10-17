"""Actual runtime/service/claim/scheduler; robot port facts are explicit SIM inputs."""
import asyncio

import pytest

from core_common.protocol.station_charging import StationDeparturePermit
from fleet.server.charge_policy_admission import work_request_digest
from test_charge_departure_store import charged, receipt
from test_charge_runtime import configured
from test_charge_store import FleetTaskScheduler


def completed(tmp_path):
    charged(tmp_path)
    runtime, service, ledger, tasks, ports, sample, now, enabled, _ = configured(tmp_path)
    current = ledger.get('charge-1')
    target = service.stations.installations()[0]
    sample['battery_energy']['soc_percent'] = 75.
    sample['dock_state'] = 'DOCKED'
    sample['charge_budget'].update(work_task_id='work-1',
        work_request_digest=work_request_digest(tasks.get_task('work-1')))
    ports.result, ports.fail_undock, ports.proof = 'SUCCEEDED', False, None

    async def read_station(current):
        ack = await ports.bind_target(current, target)
        return dict(state='CHARGED_HOLD', reason=None, session_id=current.session_id, boot_id=current.boot_id,
            battery_id=current.battery_id, target=target.model_dump(), ack=ack.model_dump(),
            operation_id=current.operation_id, correlation_id=ledger.operation_intent('charge-1')['correlation_id'],
            binding_valid=True, seating_verified=True, charging_verified=False, completion_verified=True,
            captured_at=now[0], valid_until=min(now[0]+.2, ack.valid_until))

    async def permission(current, target, *, correlation_id, decision, snapshot, admission, guard):
        ports.calls.append(('prepare', 'undock'))
        budget = snapshot['charge_budget']
        return StationDeparturePermit(**{key: getattr(current, key) for key in (
            'robot_id', 'station_id', 'session_id', 'attempt_id', 'boot_id', 'battery_id',
            'map_id', 'map_revision', 'pose_revision')}, correlation_id=correlation_id,
            work_task_id=budget['work_task_id'], work_request_digest=budget['work_request_digest'],
            expected_owner_generation=2, policy_profile_revision=decision.profile_revision,
            capacity_revision=decision.capacity_revision, captured_at=now[0], valid_until=now[0]+1.)

    async def start(current, target, permit, *, snapshot, decision, admission, guard):
        intent = ledger.operation_intent(current.session_id)
        assert current.state == 'UNDOCKING' and intent['status'] == 'PREPARED'
        assert ledger.departure_context(current.session_id)['permit'] == permit.model_dump()
        ports.calls.append(('start', 'undock'))
        sample.update(mode='DOCKING', dock_state='UNDOCKING')
        if ports.fail_undock:
            raise TimeoutError('SIM reply lost after possible admission')
        ports.result = 'RUNNING'
        return 'native-undock'

    async def advance(current, context, *, snapshot, decision, admission, guard):
        ports.calls.append(('read', 'undock'))
        return ports.proof

    ports.read_station = read_station
    ports.departure_permission, ports.start_undock, ports.advance_departure = permission, start, advance
    return runtime, service, ledger, tasks, ports, sample, now, enabled


def test_periodic_runtime_redeploys_selected_work_only_after_measured_departure(tmp_path):
    async def run():
        runtime, _, ledger, tasks, ports, sample, now, _ = completed(tmp_path)
        await runtime.tick()
        assert ledger.get('charge-1').state == 'UNDOCKING'
        assert ports.calls.count(('start', 'undock')) == 1
        assert FleetTaskScheduler(tasks, worker_id='worker').claim_next({'robot-1'}) is None
        await runtime.tick()
        assert ledger.get('charge-1').state == 'UNDOCKING'
        assert ports.calls.count(('start', 'undock')) == 1
        permission = StationDeparturePermit.model_validate(ledger.departure_context('charge-1')['permit'])
        now[0] = 101.5
        sample.update(mode='IDLE', dock_state='UNDOCKED')
        ports.proof = receipt(permission)
        await runtime.tick()
        assert ledger.get('charge-1').state == 'WORK_AVAILABLE'
        selected = FleetTaskScheduler(tasks, worker_id='worker').claim_next({'robot-1'})
        assert selected['task_id'] == 'work-1'
        assert runtime.work_admission('robot-1', task=tasks.get_task('work-1')) is None
        await runtime.tick()
        assert ports.calls.count(('start', 'undock')) == 1
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['no_work', 'below_redeploy_soc', 'unknown_health', 'stale_budget',
    'wrong_work', 'manual', 'estop', 'disabled'])
def test_unapproved_departure_waits_without_submitting_or_releasing_claims(tmp_path, fault):
    async def run():
        runtime, _, ledger, tasks, ports, sample, _, enabled = completed(tmp_path)
        if fault == 'no_work':
            sample['charge_budget'].update(work_task_id=None, work_request_digest=None)
        elif fault == 'below_redeploy_soc':
            sample['battery_energy']['soc_percent'] = 65.
        elif fault == 'unknown_health':
            sample['battery_energy'].update(soh_percent=None, usable_energy_wh=None,
                source='unknown', capacity_revision=None)
        elif fault == 'stale_budget':
            sample['charge_budget']['valid_until'] = 100.5
        elif fault == 'wrong_work':
            sample['charge_budget']['work_request_digest'] = 'b'*64
        elif fault in ('manual', 'estop'):
            sample['mode' if fault == 'manual' else 'safety_latched'] = 'MANUAL' if fault == 'manual' else True
        else:
            enabled[0] = False
        await runtime.tick()
        assert ledger.get('charge-1').state in ('CHARGED_HOLD', 'HOLD')
        assert ('start', 'undock') not in ports.calls
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
        assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')
    asyncio.run(run())


def test_unknown_undock_submission_is_stopped_and_never_retried_after_recovery(tmp_path):
    async def run():
        runtime, _, ledger, tasks, ports, _, _, _ = completed(tmp_path)
        ports.fail_undock = True
        await runtime.tick()
        assert ledger.get('charge-1').state == 'HOLD'
        await runtime.tick()
        assert ports.calls.count(('start', 'undock')) == 1
        assert ('stop', 'undock') in ports.calls
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
        assert FleetTaskScheduler(tasks, worker_id='worker').claim_next({'robot-1'}) is None
    asyncio.run(run())


def test_cancellation_settles_preparation_writer_before_exact_stop_and_never_sends(tmp_path, monkeypatch):
    import threading
    async def run():
        runtime, _, ledger, tasks, ports, _, _, _ = completed(tmp_path)
        persisted, release = threading.Event(), threading.Event()
        original = ledger.prepare_departure
        def delayed(*args, **kwargs):
            result = original(*args, **kwargs)
            persisted.set()
            assert release.wait(2.)
            return result
        monkeypatch.setattr(ledger, 'prepare_departure', delayed)
        pending = asyncio.create_task(runtime.tick())
        try:
            assert await asyncio.to_thread(persisted.wait, 2.)
            pending.cancel()
            await asyncio.sleep(0)
            assert not pending.done(), 'cleanup raced a still-running durable writer'
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert ledger.get('charge-1').state == 'HOLD'
        assert ('start', 'undock') not in ports.calls
        assert ('stop', 'undock') in ports.calls
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    asyncio.run(run())


def test_energy_expiry_while_waiting_for_database_prevents_release(tmp_path, monkeypatch):
    from contextlib import contextmanager
    async def run():
        runtime, _, ledger, tasks, ports, sample, now, _ = completed(tmp_path)
        await runtime.tick()
        permission = StationDeparturePermit.model_validate(ledger.departure_context('charge-1')['permit'])
        now[0] = 101.5
        sample.update(mode='IDLE', dock_state='UNDOCKED')
        sample['charge_budget']['valid_until'] = 101.55
        ports.proof = receipt(permission)
        original = ledger._write
        @contextmanager
        def delayed():
            with original() as db:
                now[0] = 101.6  # Receipt is still live, but original energy budget has expired.
                yield db
        monkeypatch.setattr(ledger, '_write', delayed)
        await runtime.tick()
        assert ledger.get('charge-1').state == 'HOLD'
        assert ledger.departure_context('charge-1')['receipt'] is None
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    asyncio.run(run())


def test_active_poll_cancellation_stops_from_cache_before_blocked_database_read_finishes(tmp_path, monkeypatch):
    import threading
    async def run():
        runtime, _, ledger, _, ports, _, _, _ = completed(tmp_path)
        await runtime.tick()
        entered, release, stopped = threading.Event(), threading.Event(), asyncio.Event()
        original, original_stop = ledger.operation_intent, ports.stop_operation
        def delayed(*args):
            entered.set()
            assert release.wait(2.)
            return original(*args)
        async def stop(*args):
            await original_stop(*args)
            stopped.set()
        monkeypatch.setattr(ledger, 'operation_intent', delayed)
        ports.stop_operation = stop
        pending = asyncio.create_task(runtime.tick())
        try:
            assert await asyncio.to_thread(entered.wait, 2.)
            pending.cancel()
            await asyncio.wait_for(stopped.wait(), 1.)
            assert not release.is_set()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert ledger.get('charge-1').state == 'HOLD'
    asyncio.run(run())


def test_cancellation_after_settled_verified_release_preserves_new_work_owner(tmp_path, monkeypatch):
    import threading
    async def run():
        runtime, _, ledger, tasks, ports, sample, now, _ = completed(tmp_path)
        await runtime.tick()
        permission = StationDeparturePermit.model_validate(ledger.departure_context('charge-1')['permit'])
        now[0] = 101.5
        sample.update(mode='IDLE', dock_state='UNDOCKED')
        ports.proof = receipt(permission)
        persisted, release = threading.Event(), threading.Event()
        original = ledger.complete_departure
        def delayed(*args, **kwargs):
            result = original(*args, **kwargs)
            persisted.set()
            assert release.wait(2.)
            return result
        monkeypatch.setattr(ledger, 'complete_departure', delayed)
        pending = asyncio.create_task(runtime.tick())
        try:
            assert await asyncio.to_thread(persisted.wait, 2.)
            selected = FleetTaskScheduler(tasks, worker_id='worker').claim_next({'robot-1'})
            assert selected['task_id'] == 'work-1'
            pending.cancel()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert ledger.get('charge-1').state == 'WORK_AVAILABLE'
        assert ('stop', 'undock') not in ports.calls
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')[0]['owner_kind'] != 'charge_session'
    asyncio.run(run())
