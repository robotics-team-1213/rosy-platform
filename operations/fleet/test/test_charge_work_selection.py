"""Energy estimation reads the real queue without reserving or dispatching work."""
import importlib
import importlib.util
from contextlib import closing
import sqlite3

import pytest

from fleet.server.charge_policy_admission import work_request_digest
from test_charge_store import store, session, _queue


def selector(tasks, now=100.):
    name = 'fleet.server.charge_work_selection'
    assert importlib.util.find_spec(name) is not None, 'durable charge work selection is missing'
    return importlib.import_module(name).ChargeWorkSelector(tasks, clock=lambda: now)


def change(tasks, task_id, **fields):
    with closing(tasks._connect()) as connection, connection:
        connection.execute('UPDATE fleet_tasks SET '+','.join(k+'=?' for k in fields)+' WHERE task_id=?',
                           (*fields.values(), task_id))


def test_selects_real_queue_order_and_preserves_charge_claims(tmp_path):
    charges, tasks = store(tmp_path)
    _queue(tasks, task_id='later', robot_id='robot-1', priority=2)
    _queue(tasks, task_id='first', robot_id='robot-1', priority=0)
    _queue(tasks, task_id='other', robot_id='robot-2', priority=0)
    charges.reserve(session())
    before = tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    value = selector(tasks).select('robot-1')
    assert value.task_id == 'first'
    assert value.request_digest == work_request_digest(tasks.get_task('first'))
    assert value.goal == (1., 2., 0.)
    assert selector(tasks).matches(value)
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1') == before
    assert tasks.get_task('first')['lease_owner'] is None


@pytest.mark.parametrize('fields', [
    {'status': 'CANCELED'}, {'dispatch_phase': 'WAITING_TRAFFIC'},
    {'expires_at': '1970-01-01T00:01:40.000+00:00'},
])
def test_ineligible_work_is_not_selected(tmp_path, fields):
    _, tasks = store(tmp_path)
    _queue(tasks, task_id='work', robot_id='robot-1')
    change(tasks, 'work', **fields)
    assert selector(tasks).select('robot-1') is None


@pytest.mark.parametrize('fields', [
    {'task_type': 'unsupported'}, {'request_json': '{"goal":{"x":true,"y":2,"yaw":0}}'},
    {'request_json': '{"goal":{"x":1,"y":2,"yaw":0},"repeat":true}'},
    {'request_json': '{"goal":{"x":1,"y":2,"yaw":0,"frame":"odom"}}'},
    {'request_json': '{"goal":{"x":99,"x":1,"y":2,"yaw":0}}'},
    {'lease_owner': 'dispatcher', 'lease_until': '2099-01-01T00:00:00.000+00:00'},
])
def test_unverified_first_work_does_not_fall_through_to_cheaper_task(tmp_path, fields):
    _, tasks = store(tmp_path)
    _queue(tasks, task_id='first', robot_id='robot-1', priority=0)
    _queue(tasks, task_id='later', robot_id='robot-1', priority=2)
    change(tasks, 'first', **fields)
    assert selector(tasks).select('robot-1') is None


@pytest.mark.parametrize('mutation', ['goal', 'cancel', 'priority', 'stop_rearm'])
def test_final_match_rejects_changed_work_or_dispatch_authority(tmp_path, mutation):
    _, tasks = store(tmp_path)
    _queue(tasks, task_id='work', robot_id='robot-1', priority=2)
    source = selector(tasks)
    original = source.select('robot-1')
    assert original is not None
    if mutation == 'goal':
        change(tasks, 'work', request_json='{"goal":{"x":5,"y":2,"yaw":0}}')
    elif mutation == 'cancel':
        tasks.cancel_queued('work', actor_id='operator')
    elif mutation == 'priority':
        _queue(tasks, task_id='urgent', robot_id='robot-1', priority=0)
    else:
        tasks.trip_stop_latch(actor_id='operator')
        control = tasks.dispatch_control()
        tasks.rearm_dispatch(expected_generation=control['generation'], actor_id='operator')
    assert not source.matches(original)


def test_disabled_dispatch_and_invalid_clock_never_select(tmp_path):
    _, tasks = store(tmp_path)
    _queue(tasks, task_id='work', robot_id='robot-1')
    tasks.trip_stop_latch(actor_id='operator')
    assert selector(tasks).select('robot-1') is None
    for now in (float('nan'), float('inf'), -1., True):
        assert selector(tasks, now).select('robot-1') is None


def test_selection_survives_reader_reconstruction_but_expires_at_original_time(tmp_path):
    _, tasks = store(tmp_path)
    _queue(tasks, task_id='work', robot_id='robot-1')
    change(tasks, 'work', expires_at='1970-01-01T00:01:41.000+00:00')
    original = selector(tasks).select('robot-1')
    assert original is not None and selector(tasks, 100.9).matches(original)
    assert not selector(tasks, 101.).matches(original)


def test_database_delay_cannot_return_expired_work(tmp_path):
    _, tasks = store(tmp_path)
    _queue(tasks, task_id='work', robot_id='robot-1')
    change(tasks, 'work', expires_at='1970-01-01T00:01:41.000+00:00')
    source = selector(tasks)
    samples = iter([100., 101.])
    source.clock = lambda: next(samples)
    assert source.select('robot-1') is None


def test_expired_queue_head_is_skipped_without_changing_ledger(tmp_path):
    _, tasks = store(tmp_path)
    _queue(tasks, task_id='old', robot_id='robot-1', priority=0)
    _queue(tasks, task_id='live', robot_id='robot-1', priority=2)
    change(tasks, 'old', expires_at='1970-01-01T00:01:39.000+00:00')
    assert selector(tasks).select('robot-1').task_id == 'live'
    assert tasks.get_task('old')['status'] == 'QUEUED'


def test_clock_reversal_latches_reader_unavailable(tmp_path):
    _, tasks = store(tmp_path)
    _queue(tasks, task_id='work', robot_id='robot-1')
    source = selector(tasks)
    assert source.select('robot-1') is not None
    source.clock = lambda: 99.
    assert source.select('robot-1') is None
    source.clock = lambda: 100.
    assert source.select('robot-1') is None


def test_stop_between_database_snapshots_rejects_selection(tmp_path, monkeypatch):
    _, tasks = store(tmp_path)
    _queue(tasks, task_id='work', robot_id='robot-1')
    source = selector(tasks)
    connect, calls = tasks._connect, [0]
    def interleave():
        calls[0] += 1
        if calls[0] == 2:
            tasks.trip_stop_latch(actor_id='operator')
        return connect()
    monkeypatch.setattr(tasks, '_connect', interleave)
    assert source.select('robot-1') is None
    assert tasks.get_task('work')['lease_owner'] is None


def test_storage_failure_is_unavailable(tmp_path, monkeypatch):
    _, tasks = store(tmp_path)
    _queue(tasks, task_id='work', robot_id='robot-1')
    source = selector(tasks)
    selected = source.select('robot-1')
    def broken():
        raise sqlite3.OperationalError('unavailable')
    monkeypatch.setattr(tasks, '_connect', broken)
    assert source.select('robot-1') is None
    assert not source.matches(selected)
