"""Authenticated station evidence routes exercise the installed local owner."""
import hashlib
import secrets

import pytest
from fastapi.testclient import TestClient

from core_api_web.api.app import create_app
from core_common.protocol.native.receipts import BOOT_ID
from core_common.protocol.station_charging import ChargeSessionStatus, StationPoseRecord, StationObservation
from test_station_docking_wiring import configured_station
from test_docking_parking_wiring import StillExecutor


@pytest.fixture
def station_api(core_client):
    svc = configured_station(core_client)
    now = [100.]
    owner = svc.station_docking
    svc.docking.bind_clock(lambda: now[0])
    owner.source_clock = lambda: now[0]
    # Source adapters are tested separately. This fixture isolates HTTP/native authority.
    owner.sensors = None
    owner.motion_feed = None
    local = dict(robot_id='robot-1', boot_id=str(BOOT_ID), battery_id='pack-1', map_id='floor',
                 map_revision='map-1', odom_epoch='odom-1', odom_fresh=True, safety_latched=False, mode='IDLE')
    owner.local_scope = lambda: dict(local)
    owner.local_scope_nowait = owner.local_scope
    svc.state.set_map_id('floor')
    svc.docking.executor = StillExecutor()
    headers, records = {}, []
    for name in ('fleet-a', 'fleet-b', 'human'):
        token = secrets.token_urlsafe(32)
        records.append(dict(id=name, sha256=hashlib.sha256(token.encode()).hexdigest(),
                            role='operator', source='manual'))
        headers[name] = {'Authorization': 'Bearer '+token}
    svc.config['auth']['tokens'] = records
    svc.config['docking']['station']['fleet_principals'] = ['fleet-a', 'fleet-b']
    target = StationPoseRecord(
        station_id='charger-1', map_id='floor', map_revision='map-1', pose_revision=1,
        pose=dict(x=0., y=0., yaw=0.), approach_pose=dict(x=-0.4, y=0., yaw=0.), approach_verified=True,
        source_id='global', source_epoch='global-boot', calibration_revision='global-cal',
        uncertainty_m=0.002, uncertainty_rad=0.005, captured_at=100., valid_until=110., status='VALID')
    session = ChargeSessionStatus(
        session_id='charge-1', robot_id='robot-1', station_id='charger-1', battery_id='pack-1',
        boot_id=str(BOOT_ID), pose_revision=1, map_id='floor', map_revision='map-1',
        state='RETURN_RESERVED', attempt_id='attempt-1', reason='SIM', updated_at=100.)
    seen = StationObservation(
        robot_id='robot-1', station_id='charger-1', session_id='charge-1', boot_id=str(BOOT_ID),
        odom_epoch='odom-1', map_id='floor', map_revision='map-1', pose_revision=1,
        source_id='station-camera', source_epoch='camera-boot', calibration_revision='mount-1',
        sequence=0, frame='base_link', pose=None, visible=False, uncertainty_m=0.002,
        uncertainty_rad=0.005, captured_at=100., valid_until=100.2)
    binding = dict(session=session.model_dump(), target=target.model_dump(), observation_scope=seen.model_dump(),
                   expected_boot_id=str(BOOT_ID), expected_owner_generation=0)
    client = TestClient(create_app(svc.config, svc))
    yield client, svc, now, headers, binding, seen.model_dump()
    owner.close()


def test_only_allowlisted_fleet_can_bind_and_binding_never_starts_motion(station_api):
    client, svc, _, auth, binding, _ = station_api
    assert client.put('/api/v1/docking/station-target', json=binding, headers=auth['human']).status_code == 403
    response = client.put('/api/v1/docking/station-target', json=binding, headers=auth['fleet-a'])
    assert response.status_code == 200, response.text
    assert response.json()['accepted'] is True
    assert svc.docking.native.current is None
    assert client.put('/api/v1/docking/station-target', json=binding, headers=auth['fleet-b']).status_code == 403
    status = client.get('/api/v1/docking/station-target', headers=auth['human'])
    assert status.status_code == 200 and status.json()['binding_valid']
    assert not status.json()['completion_verified']


def test_station_start_has_exact_native_receipt_and_replay_cannot_start_twice(station_api):
    client, svc, now, auth, binding, seen = station_api
    assert client.put('/api/v1/docking/station-target', json=binding, headers=auth['fleet-a']).status_code == 200
    now[0] += 0.01
    seen.update(sequence=1, visible=True, pose=dict(x=0., y=0., yaw=0.),
                captured_at=now[0], valid_until=now[0]+0.2)
    response = client.post('/api/v1/docking/station-observation', json=seen, headers=auth['fleet-a'])
    assert response.status_code == 200 and response.json()['accepted']
    command = dict(session_id='charge-1', correlation_id='intent-1', expected_boot_id=str(BOOT_ID),
                   expected_owner_generation=0)
    response = client.post('/api/v1/docking/station-dock', json=command, headers=auth['fleet-a'])
    assert response.status_code == 200, response.text
    operation = response.json()['operation']
    live = client.get('/api/v1/docking/station-target', headers=auth['human']).json()
    assert live['operation_id'] == operation['run_id'] and live['correlation_id'] == 'intent-1'
    read = client.get('/api/v1/docking/status', params={'run_id': operation['run_id']}, headers=auth['human'])
    assert read.status_code == 200
    assert client.post('/api/v1/docking/station-dock', json=command, headers=auth['fleet-a']).status_code == 409
    assert str(svc.docking.native.current.run_id) == operation['run_id']


def test_other_fleet_cannot_inject_camera_and_bad_scope_clears_previous_sample(station_api):
    client, svc, now, auth, binding, seen = station_api
    assert client.put('/api/v1/docking/station-target', json=binding, headers=auth['fleet-a']).status_code == 200
    now[0] += 0.01
    seen.update(sequence=1, visible=True, pose=dict(x=0., y=0., yaw=0.),
                captured_at=now[0], valid_until=now[0]+0.2)
    assert client.post('/api/v1/docking/station-observation', json=seen, headers=auth['fleet-a']).json()['accepted']
    assert client.post('/api/v1/docking/station-observation', json=seen, headers=auth['fleet-b']).status_code == 403
    assert svc.station_docking.feed.relative_pose() is not None
    seen.update(sequence=2, pose_revision=2)
    assert not client.post('/api/v1/docking/station-observation', json=seen,
                           headers=auth['fleet-a']).json()['accepted']
    assert svc.station_docking.feed.relative_pose() is None


def test_station_bind_rejects_stale_generation_without_teaching_or_starting(station_api):
    client, svc, _, auth, binding, _ = station_api
    binding['expected_owner_generation'] = 99
    response = client.put('/api/v1/docking/station-target', json=binding, headers=auth['fleet-a'])
    assert response.status_code == 409, response.text
    assert svc.station_docking.session is None and svc.docking.native.current is None


def test_shared_development_credential_is_rejected_even_when_allowlisted(station_api):
    from core_api_web.api.deps import DEV_TOKEN_DIGESTS
    client, svc, _, _, binding, _ = station_api
    token = 'rosy-dev-'+'operator'
    digest = hashlib.sha256(token.encode()).hexdigest()
    assert digest in DEV_TOKEN_DIGESTS
    svc.config['auth']['tokens'].append(dict(id='shared-dev', sha256=digest, role='operator', source='manual'))
    svc.config['docking']['station']['fleet_principals'].append('shared-dev')
    response = client.put('/api/v1/docking/station-target', json=binding,
                          headers={'Authorization': 'Bearer '+token})
    assert response.status_code == 403, response.text
    assert svc.station_docking.session is None


def test_old_session_command_cannot_consume_new_session_motion_admission(station_api):
    client, svc, now, auth, binding, seen = station_api
    assert client.put('/api/v1/docking/station-target', json=binding, headers=auth['fleet-a']).status_code == 200
    now[0] += 0.01
    seen.update(sequence=1, visible=True, pose=dict(x=0., y=0., yaw=0.),
                captured_at=now[0], valid_until=now[0]+0.2)
    assert client.post('/api/v1/docking/station-observation', json=seen, headers=auth['fleet-a']).json()['accepted']
    command = dict(session_id='old-session', correlation_id='old-intent', expected_boot_id=str(BOOT_ID),
                   expected_owner_generation=0)
    assert client.post('/api/v1/docking/station-dock', json=command, headers=auth['fleet-a']).status_code == 409
    assert svc.station_docking.state == 'BOUND' and svc.docking.native.current is None
