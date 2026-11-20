"""Real Fleet/CORE target refresh preserves native ownership and original source ages."""
import asyncio

import pytest

from core_common.protocol.station_charging import StationObservation
from test_station_docking_api import station_api
from test_station_camera_pipeline import pipeline_sources
from test_station_charge_http import dock_setup


def test_fleet_refreshes_live_same_revision_target_before_original_expiry(station_api, pipeline_sources, tmp_path):
    async def run():
        ports, _, http, svc, now, _, session, target = await dock_setup(station_api, tmp_path)
        try:
            async def scope(*_):
                return StationObservation.model_validate(station_api[5])
            ports.observation_scope = scope
            now[0] += .05
            renewed = target.model_copy(update={'captured_at': now[0], 'valid_until': 120.})
            ports.stations.store.refresh(renewed, expected_revision=1)
            assert (await ports.read_target(session)).accepted
            assert svc.station_docking.target.captured_at == renewed.captured_at
            assert svc.station_docking.target.valid_until == 120.
            assert svc.station_docking.state == 'BOUND'
            assert svc.docking.native.current is None
            now[0] = target.valid_until+.05
            assert (await ports.read_target(session)).accepted
        finally:
            await http.aclose()
    asyncio.run(run())


def test_fleet_refresh_during_active_dock_keeps_exact_native_operation(station_api, pipeline_sources, tmp_path):
    async def run():
        ports, _, http, svc, now, ledger, session, target = await dock_setup(station_api, tmp_path)
        try:
            async def scope(*_):
                return StationObservation.model_validate(station_api[5])
            ports.observation_scope = scope
            run_id = await ports.start_dock(session, target, correlation_id='dock-1')
            session = ledger.acknowledge_operation(session.session_id, correlation_id='dock-1',
                                                  operation_id=run_id, now=now[0])
            operation, feed = svc.docking.native.current, svc.station_docking.feed
            now[0] += .05
            renewed = target.model_copy(update={'captured_at': now[0], 'valid_until': 120.})
            ports.stations.store.refresh(renewed, expected_revision=1)
            await ports.read_station(session)
            assert svc.station_docking.target.captured_at == now[0]
            assert svc.docking.native.current is operation
            assert svc.station_docking.feed is feed
            assert svc.station_docking.readback().operation_id == run_id
        finally:
            await http.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['expired_core', 'replayed_source', 'geometry'])
def test_refresh_never_revives_or_retargets_live_session(station_api, pipeline_sources, tmp_path, fault):
    async def run():
        ports, _, http, svc, now, _, session, target = await dock_setup(station_api, tmp_path)
        try:
            async def scope(*_):
                return StationObservation.model_validate(station_api[5])
            ports.observation_scope = scope
            now[0] = target.valid_until if fault == 'expired_core' else now[0]+.05
            renewed = target.model_copy(update={'captured_at': now[0], 'valid_until': 120.})
            if fault == 'replayed_source':
                renewed = renewed.model_copy(update={'captured_at': target.captured_at})
                ports.stations.store.get = lambda _: renewed  # Corrupted adapter/store evidence must fail closed.
            elif fault == 'geometry':
                renewed = renewed.model_copy(update={'pose': target.pose.model_copy(update={'x': 2.})})
                ports.stations.store.get = lambda _: renewed
            else:
                ports.stations.store.refresh(renewed, expected_revision=1)
            with pytest.raises(ValueError):
                await ports.read_target(session)
            assert svc.station_docking.target == target
            assert svc.docking.native.current is None
        finally:
            await http.aclose()
    asyncio.run(run())


def test_scope_expiring_during_native_read_never_reaches_refresh_put(station_api, pipeline_sources, tmp_path):
    async def run():
        ports, client, http, svc, now, _, session, target = await dock_setup(station_api, tmp_path)
        try:
            now[0] += .05
            ports.stations.store.refresh(target.model_copy(update={'captured_at': now[0], 'valid_until': 120.}),
                                         expected_revision=1)
            async def scope(*_):
                return StationObservation.model_validate(station_api[5] | dict(
                    captured_at=now[0], valid_until=now[0]+.02))
            ports.observation_scope = scope
            read = client.docking_status
            async def slow(*args):
                result = await read(*args)
                now[0] += .03
                return result
            client.docking_status = slow
            with pytest.raises(ValueError):
                await ports.read_target(session)
            assert svc.station_docking.target == target
        finally:
            await http.aclose()
    asyncio.run(run())
