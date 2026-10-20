"""A real SQLite writer must not delay exact stopping or block Fleet's event loop."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Event

import pytest

from test_charge_return import moving_controller, reserve


def test_exact_cached_stop_precedes_locked_journal_and_event_loop_remains_live(tmp_path):
    service, store, tasks, ports = moving_controller(tmp_path)
    async def start():
        await reserve(service)
        await service.advance('charge-1')
    asyncio.run(start())
    cached, intent = service.motion.stop_context('robot-1')
    assert cached.operation_id == 'native-return' and intent['correlation_id']
    stopped, writing, heartbeat = Event(), Event(), Event()
    loops = []
    original = store.operation_unknown
    def journal(session_id):
        writing.set()
        return original(session_id)
    store.operation_unknown = journal
    async def stop(session, original_intent):
        assert session.operation_id == cached.operation_id
        assert original_intent['correlation_id'] == intent['correlation_id']
        stopped.set()
    ports.stop_operation = stop
    async def hold():
        loops.append(asyncio.get_running_loop())
        return await service.hold_cached('robot-1', reason='STATION_MOVED')

    with sqlite3.connect(tasks.path) as writer, ThreadPoolExecutor(max_workers=1) as pool:
        writer.execute('BEGIN IMMEDIATE')
        future = pool.submit(asyncio.run, hold())
        try:
            stopped_before_unlock = stopped.wait(1.)
            assert writing.wait(1.), 'hold never reached the real journal'
            loops[0].call_soon_threadsafe(heartbeat.set)
            live_during_write = heartbeat.wait(1.)
        finally:
            writer.rollback()
        result = future.result(timeout=5.)
    assert stopped_before_unlock, 'exact stop was delayed behind the SQLite writer'
    assert live_during_write, 'journal lock blocked the Fleet event loop'
    assert result.state == 'HOLD'
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')


def test_cancel_waits_for_held_journal_before_releasing_the_charge_owner(tmp_path):
    service, store, tasks, ports = moving_controller(tmp_path)
    entered, release, finished, stopped = Event(), Event(), Event(), Event()
    original = store.operation_unknown
    def journal(session_id):
        entered.set()
        assert release.wait(3.), 'test did not release journal writer'
        try:
            return original(session_id)
        finally:
            finished.set()
    async def stop(*_):
        stopped.set()
    async def run():
        await reserve(service)
        await service.advance('charge-1')
        store.operation_unknown = journal
        ports.stop_operation = stop
        task = asyncio.create_task(service.hold_cached('robot-1', reason='CONTACT_LOST'))
        try:
            assert await asyncio.to_thread(entered.wait, 1.)
            assert stopped.is_set(), 'journal entered before exact stopping'
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not finished.is_set()
        finally:
            release.set()
            # Always retrieve the task outcome, including an expected RED failure.
            outcome = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(outcome[0], asyncio.CancelledError)
        assert finished.is_set() and store.get('charge-1').state == 'HOLD'
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    asyncio.run(run())


def test_failed_journal_cannot_reopen_cached_dispatch_after_stop(tmp_path):
    service, store, tasks, ports = moving_controller(tmp_path)
    def unavailable(*_):
        raise OSError('journal unavailable')
    async def run():
        await reserve(service)
        await service.advance('charge-1')
        cached, _ = service.motion.stop_context('robot-1')
        store.operation_unknown = unavailable
        with pytest.raises(OSError, match='journal unavailable'):
            await service.hold_cached('robot-1', reason='CONTACT_LOST')
        with pytest.raises(ValueError, match='CHARGE_DISPATCH_CLOSED'):
            await service.motion.checked(cached)
        assert ('stop', 'return') in ports.calls
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    asyncio.run(run())


def test_repeated_cancel_during_advance_cleanup_retains_owner_until_journal_settles(tmp_path):
    service, store, tasks, ports = moving_controller(tmp_path)
    async def start():
        await reserve(service)
        await service.advance('charge-1')
    asyncio.run(start())
    reading, writing, probed = Event(), Event(), Event()
    refs, observations = {}, []
    original = store.operation_unknown
    def journal(session_id):
        writing.set()
        return original(session_id)
    store.operation_unknown = journal
    async def read_operation(_):
        reading.set()
        await asyncio.Event().wait()
    ports.read_operation = read_operation
    async def run():
        refs['loop'] = asyncio.get_running_loop()
        refs['task'] = asyncio.create_task(service.advance('charge-1'))
        with pytest.raises(asyncio.CancelledError):
            await refs['task']
    async def probe():
        for _ in range(3):
            await asyncio.sleep(0)
        observations.append((refs['task'].done(), service._lock('robot-1').locked()))
        probed.set()
    with sqlite3.connect(tasks.path) as writer, ThreadPoolExecutor(max_workers=1) as pool:
        writer.execute('BEGIN IMMEDIATE')
        future = pool.submit(asyncio.run, run())
        try:
            assert reading.wait(1.)
            refs['loop'].call_soon_threadsafe(refs['task'].cancel)
            assert writing.wait(1.)
            refs['loop'].call_soon_threadsafe(refs['task'].cancel)
            refs['loop'].call_soon_threadsafe(lambda: asyncio.create_task(probe()))
            responsive = probed.wait(1.)
        finally:
            writer.rollback()
        future.result(timeout=5.)
    assert responsive, 'cleanup blocked Fleet event loop on SQLite'
    assert observations == [(False, True)], 'caller released ownership before cleanup finished'
    assert store.get('charge-1').state == 'HOLD'
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')


def test_stop_port_self_cancel_still_journals_hold_before_propagating(tmp_path):
    service, store, tasks, ports = moving_controller(tmp_path)
    async def stop(*_):
        raise asyncio.CancelledError
    async def run():
        await reserve(service)
        await service.advance('charge-1')
        ports.stop_operation = stop
        with pytest.raises(asyncio.CancelledError):
            await service.hold_cached('robot-1', reason='CONTACT_LOST')
        assert store.get('charge-1').state == 'HOLD'
        assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    asyncio.run(run())
