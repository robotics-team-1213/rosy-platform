"""A charge stop that swallows an exception still records which exception it was (the stop itself is unchanged)."""
import asyncio
import logging

from test_charge_redeployment import completed
from test_charge_stop_contention import moving_controller, reserve


def cause(caplog, reason):
    return [r.exc_info[0] for r in caplog.records if reason in r.getMessage() and r.exc_info]


def test_unverified_departure_stop_records_its_exception(tmp_path, caplog):
    async def run():
        runtime, _, ledger, _, ports, _, _, _ = completed(tmp_path)
        ports.fail_undock = True
        with caplog.at_level(logging.WARNING):
            await runtime.tick()
        assert ledger.get('charge-1').state == 'HOLD'
    asyncio.run(run())
    assert cause(caplog, 'CHARGE_DEPARTURE_UNVERIFIED') == [TimeoutError]


def test_readback_unavailable_stop_records_its_exception(tmp_path, caplog):
    service, store, _, ports = moving_controller(tmp_path)

    async def lost(_):
        raise ConnectionResetError('robot reply lost')

    async def run():
        await reserve(service)
        await service.advance('charge-1')
        ports.read_operation = lost
        with caplog.at_level(logging.WARNING):
            await service.advance('charge-1')
    asyncio.run(run())
    assert store.get('charge-1').state == 'HOLD'
    assert cause(caplog, 'CHARGE_MOTION_READBACK_UNAVAILABLE') == [ConnectionResetError]
