"""D-432 start offset of the trip loop: the first tick runs at once, then one period plus the offset, then the period."""
import asyncio
from types import SimpleNamespace

import pytest

from fleet.server import trip_runner
from fleet.server.trip_runner import TripRunner


class _Stop(Exception):
    pass


def test_the_loop_ticks_at_once_then_waits_one_period_plus_its_offset(monkeypatch):
    events = []

    async def tick():
        events.append("tick")

    async def sleep(delay):
        events.append(round(delay, 2))
        if len(events) >= 6:
            raise _Stop

    monkeypatch.setattr(trip_runner, "start_offset", lambda interval: interval * 0.4)
    monkeypatch.setattr(trip_runner.asyncio, "sleep", sleep)
    runner = SimpleNamespace(config=SimpleNamespace(period_s=0.5), tick=tick)
    with pytest.raises(_Stop):
        asyncio.run(TripRunner._loop(runner))
    assert events == ["tick", 0.7, "tick", 0.5, "tick", 0.5]

