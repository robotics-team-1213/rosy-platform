"""Charge sessions and ordinary work compete for the same durable robot claim."""
import importlib
import importlib.util

import pytest

from core_common.protocol.station_charging import ChargeSessionStatus
from fleet.server.task_scheduler import FleetTaskScheduler
from fleet.server.task_store import FleetTaskStore
from test_task_scheduler import _queue


def session(**changes):
    return ChargeSessionStatus.model_validate(dict(
        session_id='charge-1', robot_id='robot-1', station_id='charger-1', battery_id='pack-1',
        boot_id='boot-1', pose_revision=1, map_id='floor', map_revision='map-1',
        state='RETURN_RESERVED', attempt_id='attempt-1', operation_id=None,
        reason='ENERGY_RETURN_REQUIRED', updated_at=100.0) | changes)


def store(tmp_path):
    name = 'fleet.server.charge_store'
    assert importlib.util.find_spec(name) is not None, 'durable charge sessions are not implemented'
    tasks = FleetTaskStore(tmp_path / 'site.sqlite')
    control = tasks.dispatch_control()
    if not control['dispatch_enabled']:
        tasks.rearm_dispatch(expected_generation=control['generation'], actor_id='operator')
    return importlib.import_module(name).ChargeStore(tasks), tasks


def test_charging_robot_and_station_are_reserved_atomically(tmp_path):
    value, tasks = store(tmp_path)
    created = value.reserve(session())
    assert created.session_id == 'charge-1'
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')[0]['owner_kind'] == 'charge_session'
    assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')[0]['owner_id'] == 'charge-1'
    with pytest.raises(ValueError, match='RESOURCE_BUSY'):
        value.reserve(session(session_id='charge-2', robot_id='robot-2'))
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-2') == []


def test_queue_and_charge_session_cannot_own_the_same_robot(tmp_path):
    value, tasks = store(tmp_path)
    _queue(tasks, task_id='work-1', robot_id='robot-1')
    value.reserve(session())
    assert FleetTaskScheduler(tasks, worker_id='worker').claim_next({'robot-1'}) is None


def test_active_work_prevents_charge_claim_and_rolls_back_station(tmp_path):
    value, tasks = store(tmp_path)
    _queue(tasks, task_id='work-1', robot_id='robot-1')
    assert FleetTaskScheduler(tasks, worker_id='worker').claim_next({'robot-1'}) is not None
    with pytest.raises(ValueError, match='RESOURCE_BUSY'):
        value.reserve(session())
    assert tasks.resource_claims(resource_kind='station', resource_id='charger-1') == []


def test_idempotent_reservation_and_conflicting_identity(tmp_path):
    value, _ = store(tmp_path)
    value.reserve(session())
    assert value.reserve(session()).session_id == 'charge-1'
    assert len(value.history('charge-1')) == 1
    with pytest.raises(ValueError, match='IDENTITY_CONFLICT'):
        value.reserve(session(battery_id='other'))


def test_dispatch_stop_blocks_new_reservation(tmp_path):
    value, tasks = store(tmp_path)
    tasks.close_dispatch_for_startup()
    with pytest.raises(ValueError, match='DISPATCH_CLOSED'):
        value.reserve(session())
    assert value.get('charge-1') is None


@pytest.mark.parametrize('stop', ['restart', 'site_stop'])
@pytest.mark.parametrize('stage', ['reserved', 'returning', 'charging'])
def test_dispatch_stop_retains_all_charge_resources_as_unresolved(tmp_path, stop, stage):
    from fleet.server.task_store import InvalidTaskTransition
    value, tasks = store(tmp_path)
    current = value.reserve(session())
    stages = {'reserved': [], 'returning': ['RETURNING'],
              'charging': ['RETURNING', 'DOCKING', 'CHARGE_CONFIRMING', 'CHARGING']}
    for index, state in enumerate(stages[stage], start=1):
        current = value.transition(current.session_id, expected_state=current.state, next_state=state,
            attempt_id=current.attempt_id, operation_id='native-1', now=100.+index*.1, reason='SIM')
    control = (tasks.close_dispatch_for_startup() if stop == 'restart'
               else tasks.trip_stop_latch(actor_id='operator'))
    for kind, identity in [('robot', 'robot-1'), ('station', 'charger-1')]:
        claims = tasks.resource_claims(resource_kind=kind, resource_id=identity)
        assert len(claims) == 1 and claims[0]['owner_id'] == 'charge-1'
        assert claims[0]['phase'] == 'UNKNOWN'
    assert not value.admitted('charge-1')
    assert not control['rearm_available'] and control['unresolved_actions'] == 2
    with pytest.raises(InvalidTaskTransition, match='unresolved'):
        tasks.rearm_dispatch(expected_generation=control['generation'], actor_id='operator')


def test_state_and_attempt_fences_survive_restart(tmp_path):
    value, tasks = store(tmp_path)
    value.reserve(session())
    value.transition('charge-1', expected_state='RETURN_RESERVED', next_state='RETURNING',
                     attempt_id='attempt-1', now=100.1, operation_id='operation-1', reason='RETURN_STARTED')
    with pytest.raises(ValueError, match='STATE_CONFLICT'):
        value.transition('charge-1', expected_state='RETURN_RESERVED', next_state='RETURNING',
                         attempt_id='attempt-1', now=100.2, operation_id='operation-1', reason='REPLAY')
    with pytest.raises(ValueError, match='ATTEMPT_CONFLICT'):
        value.transition('charge-1', expected_state='RETURNING', next_state='HOLD',
                         attempt_id='old', now=100.2, reason='REPLAY')
    fresh = importlib.import_module('fleet.server.charge_store').ChargeStore(tasks)
    assert fresh.get('charge-1').operation_id == 'operation-1'
    assert len(fresh.history('charge-1')) == 2


def test_charged_or_held_does_not_release_resource_claims(tmp_path):
    value, tasks = store(tmp_path)
    value.reserve(session())
    value.transition('charge-1', expected_state='RETURN_RESERVED', next_state='HOLD',
                     attempt_id='attempt-1', now=100.2, reason='LOCATION_CHANGED')
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    with pytest.raises(ValueError, match='TRANSITION_FORBIDDEN'):
        value.transition('charge-1', expected_state='HOLD', next_state='WORK_AVAILABLE',
                         attempt_id='attempt-1', now=100.3, reason='PREMATURE_RELEASE')


def test_hold_retains_operation_identity_for_stop_and_reconciliation(tmp_path):
    value, _ = store(tmp_path)
    value.reserve(session())
    value.transition('charge-1', expected_state='RETURN_RESERVED', next_state='RETURNING',
                     attempt_id='attempt-1', now=100.1, operation_id='operation-1', reason='RETURN_STARTED')
    held = value.transition('charge-1', expected_state='RETURNING', next_state='HOLD',
                            attempt_id='attempt-1', now=100.2, reason='LOCATION_CHANGED')
    assert held.operation_id == 'operation-1'
