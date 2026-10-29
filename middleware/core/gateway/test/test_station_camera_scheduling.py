"""In-process SIM journal scheduling must not consume a real transport deadline."""
import asyncio
import time

import pytest

from test_station_camera_pipeline import (
    test_station_camera_http_pipeline_aligns_then_requires_contact_and_measured_stop as _camera_pipeline,
)
from test_station_camera_pipeline import pipeline_sources, station_api  # noqa: F401


@pytest.mark.parametrize("mode", [True, "lifespan"])
def test_slow_sim_journal_finishes_without_consuming_the_motion_or_tick_budget(
        station_api, tmp_path, pipeline_sources, monkeypatch, mode):
    from fleet.server.charge_store import ChargeStore

    return_phase = ChargeStore.return_phase
    delayed = []

    def slow_phase(store, *args, **kwargs):
        if not delayed:
            delayed.append(True)
            time.sleep(3.2)
        return return_phase(store, *args, **kwargs)

    monkeypatch.setattr(ChargeStore, "return_phase", slow_phase)
    _camera_pipeline(station_api, tmp_path, pipeline_sources, mode, monkeypatch)
    assert delayed, "the controlled journal scheduling delay was exercised"


def test_sim_scheduling_budget_is_local_bounded_and_preserves_failure_propagation(pipeline_sources, monkeypatch):
    from fleet.server.charge_motion import ChargeMotion
    from test_station_camera_pipeline import _sim_call

    budgets = []

    async def observe_wait(awaitable, timeout):
        budgets.append(timeout)
        return await awaitable

    async def value():
        return "readback"

    async def broken():
        raise RuntimeError("transport failed")

    async def canceled():
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "wait_for", observe_wait)
    assert asyncio.run(_sim_call(value)) == "readback"
    assert asyncio.run(ChargeMotion(None).call(value)) == "readback"
    assert 1.5 < budgets[0] <= 30.
    assert budgets[1] == 1.5
    with pytest.raises(RuntimeError, match="transport failed"):
        asyncio.run(_sim_call(broken))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_sim_call(canceled))
