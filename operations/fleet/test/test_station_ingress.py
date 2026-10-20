"""Camera source credentials cannot become robot credentials or motion authority."""
import asyncio
import importlib
import importlib.util
import json
import secrets

import httpx
import pytest
from fastapi.testclient import TestClient

from core_common.protocol.station_charging import StationObservation
from fleet.swarm.transport import HttpRobotClient
from fleet.swarm.robots import RobotEndpoint
from test_charge_store import store, session
from test_station_pose_service import service, stable


def _setup(tmp_path, handler=None):
    name = 'fleet.server.station_ingress'
    assert importlib.util.find_spec(name) is not None, 'authenticated station ingress is missing'
    module = importlib.import_module(name)
    stations, now, _ = service(tmp_path)
    stable(stations)
    charges, _ = store(tmp_path)
    charges.reserve(session())
    source_token, robot_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    requests = []

    def receive(request):
        requests.append(request)
        return handler(request) if handler else httpx.Response(200, json={'accepted': True})

    client = HttpRobotClient(RobotEndpoint('robot-1', 'http://robot', robot_token),
                            http=httpx.AsyncClient(base_url='http://robot', transport=httpx.MockTransport(receive)))
    source = module.StationSource(source_id='camera-1', token=source_token,
        station_id='charger-1', robot_ids=('robot-1',), map_id='floor', map_revision='map-1',
        source_epoch='camera-boot', calibration_revision='cal-1', max_age_s=0.25,
        max_uncertainty_m=0.02, max_uncertainty_rad=0.03)
    ingress = module.StationIngress(stations=stations, sessions=charges, sources=[source],
                                    clients=lambda: {'robot-1': client}, clock=lambda: now[0])
    seen = StationObservation(robot_id='robot-1', station_id='charger-1', session_id='charge-1', boot_id='boot-1',
        odom_epoch='odom-1', map_id='floor', map_revision='map-1', pose_revision=1,
        source_id='camera-1', source_epoch='camera-boot', calibration_revision='cal-1', sequence=1,
        captured_at=101., valid_until=101.2, frame='base_link', pose=dict(x=0.2, y=0., yaw=0.),
        visible=True, uncertainty_m=0.002, uncertainty_rad=0.005)
    return ingress, source_token, robot_token, requests, seen, now, charges


def test_registered_source_forwards_once_with_robot_credential_and_never_moves_robot(tmp_path):
    ingress, source, robot, requests, seen, _, _ = _setup(tmp_path)
    assert asyncio.run(ingress.observation('Bearer '+source, seen)) == {'accepted': True}
    assert len(requests) == 1
    assert requests[0].url.path == '/api/v1/docking/station-observation'
    assert requests[0].headers['Authorization'] == 'Bearer '+robot
    assert source not in requests[0].content.decode()
    assert json.loads(requests[0].content) == seen.model_dump(mode='json')
    assert asyncio.run(ingress.observation('Bearer '+source, seen)) == {'accepted': False}
    assert len(requests) == 1


@pytest.mark.parametrize('change', [dict(robot_id='robot-2'), dict(station_id='charger-2'),
    dict(boot_id='old'), dict(session_id='old'), dict(pose_revision=2), dict(map_revision='old'),
    dict(source_epoch='old'), dict(calibration_revision='old'), dict(captured_at=100., valid_until=100.2)])
def test_out_of_scope_or_stale_observation_never_reaches_core(tmp_path, change):
    ingress, token, _, requests, seen, _, _ = _setup(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(ingress.observation('Bearer '+token, seen.model_copy(update=change)))
    assert requests == []


def test_human_or_robot_token_cannot_upload_camera_evidence_and_hold_blocks_forwarding(tmp_path):
    ingress, source, robot, requests, seen, _, charges = _setup(tmp_path)
    for token in (robot, secrets.token_urlsafe(32)):
        with pytest.raises(PermissionError):
            asyncio.run(ingress.observation('Bearer '+token, seen))
    charges.transition('charge-1', expected_state='RETURN_RESERVED', next_state='HOLD',
                       attempt_id='attempt-1', now=101., reason='STOP')
    with pytest.raises(ValueError):
        asyncio.run(ingress.observation('Bearer '+source, seen))
    assert requests == []


def test_normal_fleet_app_installs_ingress_only_when_explicitly_configured(tmp_path):
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from test_sightings_api import OPERATOR_TOKEN
    ingress, source, robot, _, seen, _, _ = _setup(tmp_path)
    console = FleetConsole([RobotEndpoint('robot-1', 'http://robot', robot)], list(ingress.clients().values()))
    client = TestClient(create_app(console, console_token=OPERATOR_TOKEN, station_ingress=ingress))
    response = client.post('/api/fleet/station-observations', json=seen.model_dump(),
                            headers={'Authorization': 'Bearer '+source})
    assert response.status_code == 200 and response.json()['accepted']
    assert client.post('/api/fleet/station-observations', json=seen.model_dump(),
                      headers={'Authorization': 'Bearer '+OPERATOR_TOKEN}).status_code == 401
    assert TestClient(create_app(console, console_token=OPERATOR_TOKEN)).post(
        '/api/fleet/station-observations', json=seen.model_dump()).status_code == 404


def test_current_session_and_admission_are_read_as_one_snapshot(tmp_path):
    ingress, _, _, _, _, _, charges = _setup(tmp_path)
    assert hasattr(charges, 'admitted_session'), 'atomic admitted-session readback is missing'
    assert charges.admitted_session('charge-1', states=('RETURN_RESERVED',)).session_id == 'charge-1'
    charges.transition('charge-1', expected_state='RETURN_RESERVED', next_state='HOLD',
                       attempt_id='attempt-1', now=101., reason='STOP')
    assert charges.admitted('charge-1')  # HOLD deliberately retains resource claims.
    assert charges.admitted_session('charge-1', states=('RETURN_RESERVED',)) is None


def test_cached_pre_hold_session_cannot_be_combined_with_retained_claims(tmp_path):
    ingress, source, _, requests, seen, _, charges = _setup(tmp_path)
    old = charges.get('charge-1')
    charges.transition('charge-1', expected_state='RETURN_RESERVED', next_state='HOLD',
                       attempt_id='attempt-1', now=101., reason='STOP')
    charges.get = lambda session_id: old  # The pre-HOLD read from the former split-snapshot path.
    assert charges.admitted('charge-1')
    with pytest.raises(ValueError):
        asyncio.run(ingress.observation('Bearer '+source, seen))
    assert not requests


def test_database_contention_in_every_forwarding_fence_keeps_async_heartbeat_alive(tmp_path):
    import queue
    import threading
    ingress, source, _, requests, seen, _, _ = _setup(tmp_path)
    read = ingress._current
    pending, starved = queue.Queue(), []

    def contended(*args):
        heartbeat = threading.Event()
        pending.put(heartbeat)
        if not heartbeat.wait(0.5):
            starved.append(True)
        return read(*args)

    ingress._current = contended

    async def run():
        task = asyncio.create_task(ingress.observation('Bearer '+source, seen))
        while not task.done():
            await asyncio.sleep(0.005)
            while not pending.empty():
                pending.get_nowait().set()
        return await task

    assert asyncio.run(run()) == {'accepted': True}
    assert requests and not starved, 'a blocking read on the event loop starved the heartbeat'
