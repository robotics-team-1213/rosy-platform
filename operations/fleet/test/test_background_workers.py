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
