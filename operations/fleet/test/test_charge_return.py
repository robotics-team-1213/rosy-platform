"""Motion dispatch is fenced by persisted intent, station ACK and exact owner results."""
import asyncio

import pytest

from test_charge_recovery import controller


def moving_controller(tmp_path):
    value, store, tasks, ports = controller(tmp_path)
    ports.result = 'RUNNING'
    ports.fail_start = False

    async def start(session, target, *, correlation_id):
        # A process crash here must leave an operation intent, never a retryable reservation.
        assert store.get(session.session_id).state in ('RETURNING', 'DOCKING')
        intent = store.operation_intent(session.session_id)
        assert intent['correlation_id'] == correlation_id
        ports.calls.append(('start', intent['kind']))
        if ports.fail_start:
            raise TimeoutError('reply lost after submission')
        return 'native-' + intent['kind']

    async def stop(session, intent):
        ports.calls.append(('stop', intent['kind']))

    ports.start_return = ports.start_dock = start
    ports.stop_operation = stop
    return value, store, tasks, ports


def reserve(value):
    return value.request_return('robot-1', 'charger-1', pose_revision=1, reason='SCHEDULE')


def test_return_then_dock_require_owner_success_and_are_sent_once(tmp_path):
    value, store, _, ports = moving_controller(tmp_path)

    async def run():
        await reserve(value)
        first = await value.advance('charge-1')
        assert first.state == 'RETURNING' and first.operation_id == 'native-return'
        assert (await value.advance('charge-1')).state == 'RETURNING'
        assert ports.calls.count(('start', 'return')) == 1
        ports.result = 'SUCCEEDED'
        assert (await value.advance('charge-1')).state == 'DOCKING'
        assert store.get('charge-1').operation_id == 'native-dock'
        assert ports.calls.count(('start', 'dock')) == 1
        assert (await value.advance('charge-1')).state == 'CHARGE_CONFIRMING'

    asyncio.run(run())


@pytest.mark.parametrize('fault', [None, 'robot', 'map', 'expired'])
def test_expired_cached_ack_requires_current_core_ack_before_next_return_read(tmp_path, fault):
    async def run():
        value, _, _, ports = moving_controller(tmp_path)
        await reserve(value)
        await value.advance('charge-1')
        current_ack = value.stations._acks[('robot-1', 'charger-1')]
        value.stations._acks[('robot-1', 'charger-1')] = current_ack.model_copy(update={
            'captured_at': 100., 'valid_until': 100.5})
        async def read_target(current):
            ports.calls.append(('read_target', current.session_id))
            return current_ack.model_copy(update={
                **({'robot_id': 'other'} if fault == 'robot' else {}),
                **({'map_revision': 'other'} if fault == 'map' else {}),
                **({'captured_at': 100., 'valid_until': 100.5} if fault == 'expired' else {})})
        ports.read_target = read_target
        result = await value.advance('charge-1')
        assert result.state == ('RETURNING' if fault is None else 'HOLD')
        assert ('read_target', 'charge-1') in ports.calls
        assert ports.calls.count(('start', 'return')) == 1
    asyncio.run(run())


def test_relocation_stops_existing_motion_and_never_starts_new_target(tmp_path):
    value, _, _, ports = moving_controller(tmp_path)

    async def run():
        await reserve(value)
        await value.advance('charge-1')
        value.stations.store.invalidate('charger-1', expected_revision=1, reason='MOVED')
        result = await value.advance('charge-1')
        assert result.state == 'HOLD'
        assert result.operation_id == 'native-return'
        await value.advance('charge-1')
        assert ports.calls.count(('start', 'return')) == 1
        assert ports.calls.count(('stop', 'return')) == 1
        assert ('start', 'dock') not in ports.calls

    asyncio.run(run())


@pytest.mark.parametrize('fault', ['ack', 'energy', 'dispatch', 'manual', 'map'])
def test_changed_admission_blocks_first_motion(tmp_path, fault):
    value, _, tasks, ports = moving_controller(tmp_path)

    async def run():
        await reserve(value)
        if fault == 'ack':
            value.stations._acks.clear()
        elif fault == 'energy':
            from core_common.protocol.station_charging import ChargeDecision
            value.admit_return = lambda *_: ChargeDecision(
                decision='WAIT', reason='ENERGY_UNKNOWN', profile_revision='sim', capacity_revision=None)
        elif fault == 'dispatch':
            value.policy_enabled = lambda: False
        else:
            original = ports.snapshot

            async def changed(robot):
                result = await original(robot)
                return result | ({'mode': 'MANUAL'} if fault == 'manual' else {'map_revision': 'new'})

            ports.snapshot = changed
        assert (await value.advance('charge-1')).state == 'HOLD'
        assert not any(call[0] == 'start' for call in ports.calls)

    asyncio.run(run())


def test_lost_start_reply_is_durable_and_cannot_be_repeated_after_restart(tmp_path):
    value, store, _, ports = moving_controller(tmp_path)

    async def run():
        await reserve(value)
        ports.fail_start = True
        assert (await value.advance('charge-1')).state == 'HOLD'
        intent = store.operation_intent('charge-1')
        assert intent['kind'] == 'return' and intent['status'] == 'UNKNOWN'
        assert (await value.reconcile('charge-1')).state == 'HOLD'
        assert (await value.advance('charge-1')).state == 'HOLD'
        assert ports.calls.count(('start', 'return')) == 1

    asyncio.run(run())


def test_cancel_holds_claim_and_requests_stop_instead_of_releasing_robot(tmp_path):
    value, store, _, ports = moving_controller(tmp_path)

    async def run():
        await reserve(value)
        await value.advance('charge-1')
        canceled = await value.cancel('charge-1', reason='OPERATOR_CANCEL')
        assert canceled.state == 'CANCELED'
        assert store.admitted('charge-1')
        assert ports.calls.count(('stop', 'return')) == 1

    asyncio.run(run())


def test_restart_after_relocation_still_stops_the_persisted_operation(tmp_path):
    value, _, _, ports = moving_controller(tmp_path)

    async def run():
        await reserve(value)
        await value.advance('charge-1')
        value._reconciled.clear()  # New process has not reconciled any owner yet.
        value.stations.store.invalidate('charger-1', expected_revision=1, reason='MOVED')
        assert (await value.advance('charge-1')).state == 'HOLD'
        assert ports.calls.count(('stop', 'return')) == 1
        assert ports.calls.count(('start', 'return')) == 1

    asyncio.run(run())


def test_database_failure_after_submission_still_attempts_correlated_stop(tmp_path):
    value, store, _, ports = moving_controller(tmp_path)
    original = ports.start_return

    def unavailable(*args, **kwargs):
        raise OSError('database unavailable')

    async def submitted(*args, **kwargs):
        result = await original(*args, **kwargs)
        store.acknowledge_operation = unavailable
        store.transition = unavailable
        return result

    ports.start_return = submitted

    async def run():
        await reserve(value)
        with pytest.raises(OSError):
            await value.advance('charge-1')
        assert ('stop', 'return') in ports.calls
        assert ports.calls.count(('start', 'return')) == 1

    asyncio.run(run())
