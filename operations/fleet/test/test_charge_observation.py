"""Fleet records CORE's measured charge evidence without releasing ordinary work claims."""
import asyncio

import pytest

from test_charge_return import moving_controller, reserve
from test_charge_store import FleetTaskScheduler, _queue


async def aligned(tmp_path):
    value, ledger, tasks, ports = moving_controller(tmp_path)
    await reserve(value)
    await value.advance('charge-1')
    ports.result = 'SUCCEEDED'
    await value.advance('charge-1')
    result = await value.advance('charge-1')
    assert result.state == 'CHARGE_CONFIRMING'
    intent = ledger.operation_intent('charge-1')
    target = value.stations.installations()[0]
    ack = await ports.bind_target(result, target)
    ports.live = dict(state='CHARGE_CONFIRMING', reason=None, session_id=result.session_id,
        boot_id=result.boot_id, battery_id=result.battery_id, target=target.model_dump(), ack=ack.model_dump(),
        operation_id='native-dock', correlation_id=intent['correlation_id'], binding_valid=True,
        seating_verified=False, charging_verified=False, completion_verified=False,
        captured_at=101., valid_until=101.2)
    async def read_station(session):
        ports.calls.append(('read_station', session.session_id))
        return ports.live
    ports.read_station = read_station
    return value, ledger, tasks, ports


def test_alignment_handover_retains_native_operation_for_later_charge_evidence(tmp_path):
    async def run():
        _, ledger, _, _ = await aligned(tmp_path)
        assert ledger.get('charge-1').operation_id == 'native-dock'
    asyncio.run(run())


def test_measured_charge_then_normal_completion_are_persisted_once_without_redeployment(tmp_path):
    async def run():
        value, ledger, tasks, ports = await aligned(tmp_path)
        assert (await value.advance('charge-1')).state == 'CHARGE_CONFIRMING'
        ports.live.update(state='CHARGING', seating_verified=True, charging_verified=True)
        assert (await value.advance('charge-1')).state == 'CHARGING'
        ports.live.update(state='CHARGED_HOLD', charging_verified=False, completion_verified=True)
        assert (await value.advance('charge-1')).state == 'CHARGED_HOLD'
        count = len(ledger.history('charge-1'))
        value._reconciled.clear()  # A new coordinator must read the existing owner, not submit again.
        assert (await value.advance('charge-1')).state == 'CHARGED_HOLD'
        assert len(ledger.history('charge-1')) == count
        assert ledger.get('charge-1').operation_id == 'native-dock'
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
        assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')
        _queue(tasks, task_id='next-work', robot_id='robot-1')
        assert FleetTaskScheduler(tasks, worker_id='dispatcher').claim_next({'robot-1'}) is None
        assert ports.calls.count(('start', 'return')) == ports.calls.count(('start', 'dock')) == 1
        assert not any(call[0] == 'stop' for call in ports.calls)
    asyncio.run(run())


@pytest.mark.parametrize('change', [dict(operation_id='other'), dict(correlation_id='other'),
    dict(session_id='old'), dict(boot_id='old'), dict(battery_id='replacement'),
    dict(captured_at=99., valid_until=100.), dict(state='BOUND'), dict(binding_valid=False)])
def test_wrong_expired_or_unbound_core_evidence_cannot_advance_charging(tmp_path, change):
    async def run():
        value, ledger, tasks, ports = await aligned(tmp_path)
        ports.live.update(change)
        assert (await value.advance('charge-1')).state == 'HOLD'
        assert ledger.admitted('charge-1')
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
        assert ('stop', 'dock') in ports.calls
    asyncio.run(run())


def test_charging_evidence_loss_holds_claims(tmp_path):
    async def run():
        value, ledger, _, ports = await aligned(tmp_path)
        ports.live.update(state='CHARGING', seating_verified=True, charging_verified=True)
        assert (await value.advance('charge-1')).state == 'CHARGING'
        ports.live.update(state='CHARGE_CONFIRMING', seating_verified=False, charging_verified=False)
        assert (await value.advance('charge-1')).state == 'HOLD'
        assert ledger.admitted('charge-1')
    asyncio.run(run())


@pytest.mark.parametrize('field,value', [('robot_id', 'other-robot'), ('map_revision', 'other-map')])
def test_wrong_ack_scope_cannot_confirm_charge(tmp_path, field, value):
    async def run():
        coordinator, _, _, ports = await aligned(tmp_path)
        ports.live['ack'][field] = value
        assert (await coordinator.advance('charge-1')).state == 'HOLD'
    asyncio.run(run())


def test_evidence_expiring_during_post_read_checks_cannot_be_persisted(tmp_path):
    async def run():
        coordinator, ledger, _, ports = await aligned(tmp_path)
        ports.live.update(state='CHARGED_HOLD', seating_verified=True, completion_verified=True)
        now, original = [101.], ports.snapshot
        coordinator.clock = lambda: now[0]
        async def delayed(robot):
            result = await original(robot)
            now[0] = 101.3
            return result
        ports.snapshot = delayed
        assert (await coordinator.advance('charge-1')).state == 'HOLD'
        assert not any(row.state == 'CHARGED_HOLD' for row in ledger.history('charge-1'))
    asyncio.run(run())
