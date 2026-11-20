"""Real charging HTTP port and scoped stop; device sources remain explicit SIM."""
import asyncio
import importlib
import importlib.util
from types import SimpleNamespace

import pytest
from core_common.protocol.station_charging import StationObservation

from test_station_docking_api import station_api
from test_station_camera_pipeline import pipeline_sources
from test_station_return_http import configured


async def dock_setup(station_api, tmp_path):
    name = 'fleet.server.charge_robot_http'
    assert importlib.util.find_spec(name) is not None, 'charge robot HTTP composition is missing'
    module = importlib.import_module(name)
    ret, client, http, svc, now, ledger, session, target, _, stations = await configured(station_api, tmp_path)
    session = ledger.transition(session.session_id, expected_state='RETURNING', next_state='DOCKING',
        attempt_id=session.attempt_id, now=now[0], reason='SIM', intent_kind='dock', correlation_id='dock-1')
    seen = station_api[5] | dict(sequence=1, visible=True, pose=dict(x=0., y=0., yaw=0.))
    assert (await client.station_observation(StationObservation.model_validate(seen)))['accepted']
    port = module.ChargeRobotHttp(clients=lambda: {session.robot_id: client}, store=ledger,
        stations=stations, clock=lambda: now[0], returns=SimpleNamespace(), return_http=ret,
        snapshot=None, observation_scope=None)
    return port, client, http, svc, now, ledger, session, target


def test_real_dock_start_read_and_exact_stop(station_api, pipeline_sources, tmp_path):
    async def run():
        port, _, http, svc, _, ledger, session, target = await dock_setup(station_api, tmp_path)
        try:
            run_id = await port.start_dock(session, target, correlation_id='dock-1')
            session = ledger.acknowledge_operation(session.session_id, correlation_id='dock-1',
                                                 operation_id=run_id, now=100.)
            result = await port.read_operation(session)
            assert result == dict(operation_id=run_id, boot_id=session.boot_id, state='RUNNING')
            await port.stop_operation(session, ledger.operation_intent(session.session_id))
            assert svc.station_docking.state == 'HOLD'
            assert svc.docking.native.lookup().result == 'FAILED'
            assert ledger.admitted(session.session_id)  # Stop ACK never releases resource claims.
            with pytest.raises(Exception):
                await port.start_dock(session, target, correlation_id='dock-1')
        finally:
            await http.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['busy', 'boot', 'map', 'generation', 'mapping'])
def test_next_return_goal_waits_for_actual_native_readiness(station_api, pipeline_sources, tmp_path, fault):
    async def run():
        ret, client, http, _, _, ledger, session, target, context, _ = await configured(station_api, tmp_path)
        try:
            await ret.grant_return(session, target, context)
            assert await ret.navigation_ready(session, context)
            original = client.station_navigation_state
            async def altered():
                body = await original()
                if fault == 'busy':
                    body['owner']['owner_run_id'] = 'SIM-active'
                elif fault == 'boot':
                    body['owner']['boot_id'] = 'SIM-other'
                elif fault == 'generation':
                    body['owner']['owner_generation'] = True
                else:
                    body['map_id' if fault == 'map' else 'mapping_active'] = 'SIM-other' if fault == 'map' else True
                return body
            client.station_navigation_state = altered
            if fault == 'busy':
                assert not await ret.navigation_ready(session, context)
            else:
                with pytest.raises(ValueError):
                    await ret.navigation_ready(session, context)
            assert ledger.admitted(session.session_id)
        finally:
            await http.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('change', ['refresh', 'geometry', 'expiry'])
def test_same_version_refresh_preserves_dock_handover_but_not_changed_geometry_or_expiry(
        station_api, pipeline_sources, tmp_path, change):
    async def run():
        port, _, http, svc, _, _, session, target = await dock_setup(station_api, tmp_path)
        try:
            update = {'refresh': dict(captured_at=99.9, valid_until=109., uncertainty_m=.003),
                'geometry': dict(pose=target.pose.model_copy(update={'x': .1})),
                'expiry': dict(captured_at=98., valid_until=99.)}[change]
            target = target.model_copy(update=update)
            if change == 'refresh':
                assert await port.start_dock(session, target, correlation_id='dock-1')
            else:
                with pytest.raises(ValueError):
                    await port.start_dock(session, target, correlation_id='dock-1')
                assert svc.docking.native.current is None
        finally:
            await http.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('unknown', [False, True])
def test_lost_start_reply_can_stop_by_durable_intent(station_api, pipeline_sources, tmp_path, unknown):
    async def run():
        port, _, http, svc, now, ledger, session, target = await dock_setup(station_api, tmp_path)
        try:
            if unknown:
                await port.start_dock(session, target, correlation_id='dock-1')
            now[0] = 111.  # Expired camera/target must not prevent exact stop.
            await port.stop_operation(session, ledger.operation_intent(session.session_id))
            assert svc.station_docking.state == 'HOLD'
            assert not svc.docking.active and ledger.admitted(session.session_id)
        finally:
            await http.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['principal', 'session', 'correlation', 'boot', 'generation'])
def test_scoped_stop_refuses_foreign_owner(station_api, fault):
    core, svc, _, auth, binding, seen = station_api
    assert core.put('/api/v1/docking/station-target', json=binding, headers=auth['fleet-a']).status_code == 200
    seen.update(sequence=1, visible=True, pose=dict(x=0., y=0., yaw=0.))
    assert core.post('/api/v1/docking/station-observation', json=seen, headers=auth['fleet-a']).json()['accepted']
    command = dict(session_id='charge-1', correlation_id='dock-1', expected_boot_id=binding['expected_boot_id'],
                   expected_owner_generation=0)
    assert core.post('/api/v1/docking/station-dock', json=command, headers=auth['fleet-a']).status_code == 200
    command['expected_owner_generation'] = svc.docking.native.generation
    before = svc.docking.native.lookup()
    if fault != 'principal':
        key, value = {'session': ('session_id', 'foreign'), 'correlation': ('correlation_id', 'foreign'),
            'boot': ('expected_boot_id', 'foreign'), 'generation': ('expected_owner_generation', 999)}[fault]
        command[key] = value
    response = core.post('/api/v1/docking/station-stop', json=command,
                         headers=auth['fleet-b' if fault == 'principal' else 'fleet-a'])
    assert response.status_code == (403 if fault == 'principal' else 409), response.text
    assert svc.docking.native.lookup() == before and svc.station_docking.state == 'DOCKING'
