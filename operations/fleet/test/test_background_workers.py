"""Periodic workers keep cadence, error recovery and task cancellation."""
import asyncio
from types import SimpleNamespace
import pytest
from fleet.server import background_workers

@pytest.mark.parametrize('failure', [None, OSError, ValueError])
def test_goal_evidence_expiry_keeps_one_second_cadence_and_cancellation(monkeypatch, failure):
    calls = []
    errors = []
    def hold_expired():
        calls.append('hold')
        if failure is not None:
            raise failure('expected transient failure')
    async def cancel_at_sleep(seconds):
        calls.append(seconds)
        raise asyncio.CancelledError
    monkeypatch.setattr(background_workers.asyncio, 'sleep', cancel_at_sleep)
    logger = SimpleNamespace(exception=lambda message: errors.append(message))
    with pytest.raises(asyncio.CancelledError):
        service = SimpleNamespace(hold_expired_without_evidence=hold_expired)
        asyncio.run(background_workers.goal_evidence_expiry_loop(service, logger))
    assert calls == ['hold', 1.0]
    assert len(errors) == (0 if failure is None else 1)


def _off_the_loop():
    with pytest.raises(RuntimeError):  # a blocking store call here would hold every heartbeat reply
        asyncio.get_running_loop()


def test_goal_evidence_expiry_does_not_hold_the_event_loop(monkeypatch):
    calls = []
    async def cancel_at_sleep(seconds):
        raise asyncio.CancelledError
    monkeypatch.setattr(background_workers.asyncio, 'sleep', cancel_at_sleep)
    service = SimpleNamespace(hold_expired_without_evidence=lambda: (_off_the_loop(), calls.append('hold')))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(background_workers.goal_evidence_expiry_loop(service, SimpleNamespace(exception=print)))
    assert calls == ['hold']


def test_task_expiry_write_does_not_hold_the_event_loop(monkeypatch):
    calls = []
    def expire():
        _off_the_loop()
        calls.append('expire')
    async def cancel_at_sleep(seconds):
        raise asyncio.CancelledError
    monkeypatch.setattr(background_workers.asyncio, 'sleep', cancel_at_sleep)
    # The rest of the cycle fails on this bare stub and is reported; the expiry write already ran.
    task_service = SimpleNamespace(scheduler=SimpleNamespace(expire_queued=expire), robot_ids=('rosy_01',))
    supervisor = SimpleNamespace(note_ok=lambda name: None, note_failure=lambda name, error: None)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(background_workers._task_dispatch_loop(SimpleNamespace(), task_service, None, supervisor=supervisor))
    assert calls == ['expire']


@pytest.mark.parametrize('wake_at, warned', [(0.25 + 0.49, 0), (0.25 + 0.5, 1)])
def test_event_loop_lag_is_logged_only_past_the_limit(monkeypatch, wake_at, warned):
    warnings = []
    times = iter([0.0, wake_at])
    sleeps = []
    async def sleep_then_cancel(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError
    monkeypatch.setattr(background_workers.asyncio, 'sleep', sleep_then_cancel)
    logger = SimpleNamespace(warning=lambda *message: warnings.append(message))
    clock = lambda: next(times, 99.0)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(background_workers.event_loop_lag_loop(logger, clock=clock))
    assert len(warnings) == warned
