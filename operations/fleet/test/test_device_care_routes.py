"""Producer -> authenticated bridge -> durable Fleet profile, without hardware."""
from contextlib import closing, contextmanager
from hashlib import sha256
import json
import ssl
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import pytest

from fleet.server.device_care_routes import install_device_care_routes
from test_device_care import care, monitor_report


@pytest.fixture
def site(tmp_path):
    class Observations:
        owner_id = 'fixture-owner'
        registered = True
        board_id = 'fixture-board'

        def authorize(self, source, token):
            if not self.registered or source != 'source-one' or token != 'observation-only-fixture':
                raise PermissionError()

        def snapshot(self):
            arms = [{'source_id': 'source-one', 'arm_id': self.owner_id, 'label': '실습 팔'}] if self.registered else []
            return {'workcells': [{'arms': arms}]}

        def arm_binding(self, source):
            assert source == 'source-one' and self.registered
            return {'owner_id': self.owner_id,
                    'sha256': sha256(f'{self.owner_id}/{self.board_id}'.encode()).hexdigest()}

    def viewer(authorization: str = Header('')):
        if authorization not in ('viewer', 'operator'):
            raise HTTPException(401)
        return SimpleNamespace(principal_id='alice', role=authorization)

    def operator(authorization: str = Header('')):
        principal = viewer(authorization)
        if principal.role != 'operator':
            raise HTTPException(403)
        return principal

    app = FastAPI()
    observations = Observations()
    app.state.profile_observations = observations
    install_device_care_routes(
        app, tmp_path / 'tasks.sqlite3', console=SimpleNamespace(robot_ids=['robot-one']),
        observations=observations, require_viewer=viewer, require_named_operator=operator)
    app.state.device_care.put_profile('arm-one', {'display_name': '실습 팔', 'device_kind': 'manipulator'},
                                      updated_by='alice')
    with TestClient(app) as client:
        yield client, app.state.device_care


def test_bridge_real_producer_roundtrip_and_role_boundaries(site):
    from deploy.robot.omx.load_report_bridge import publish
    client, store = site
    document, report = monitor_report(stamp=time.time())
    path = '/api/fleet/device-profiles/arm-one'
    payload = care() | {'characteristics': document}
    assert client.put(path + '/care', json=payload).status_code == 401
    assert client.put(path + '/care', json=payload, headers={'Authorization': 'viewer'}).status_code == 403
    assert client.put(path + '/care', json=payload, headers={'Authorization': 'operator'}).status_code == 200

    class Transport:
        @contextmanager
        def open(self, request, timeout):
            assert timeout == 2
            response = client.post(urlsplit(request.full_url).path, content=request.data, headers=dict(request.headers))
            assert response.status_code == 202, response.text
            yield SimpleNamespace(status=response.status_code)

    raw = json.dumps(report).encode()
    publish(raw, fleet_url='https://fleet.example', device_id='arm-one', source_id='source-one',
            token='observation-only-fixture', context=ssl.create_default_context(), opener=Transport())
    result = client.get('/api/fleet/device-profile-sources/arm/source-one', headers={'Authorization': 'viewer'})
    assert result.status_code == 200
    assert result.headers['cache-control'] == 'no-store'
    saved = result.json()['profile']
    assert saved['caution'] == payload['caution']
    assert saved['latest_analysis']['assessed_at'] == report['assessed_at']
    assert saved['motion_admitted'] is saved['automatic_recovery_enabled'] is False
    assert 'characteristics' not in saved
    for headers in ({}, {'Authorization': 'operator'}, {'X-Workcell-Observation-Token': 'wrong'}):
        assert client.post(path + '/load-reports/source-one', content=raw, headers=headers).status_code == 401
    assert client.post(
        path + '/load-reports/other-source', content=raw,
        headers={'X-Workcell-Observation-Token': 'observation-only-fixture'}).status_code == 401
    assert store.get('arm-one')['latest_analysis']['command_binding'] == 'caller_supplied_unverified'


def test_bounded_strict_import_and_known_source(site):
    client, store = site
    path = '/api/fleet/device-profiles/arm-one/care'
    headers = {'Authorization': 'operator'}
    for raw, status in [(b'{' + b' ' * 1_000_001, 413), (b'{"caution":1,"caution":2}', 422),
                        (b'{"caution":NaN}', 422), (b'[]', 422)]:
        assert client.put(path, content=raw, headers=headers).status_code == status
    assert client.put(path, json=care('not-registered'), headers=headers).status_code == 422
    document, _ = monitor_report()
    raw_document = json.dumps(document).replace('"revision": "fixture-v1"',
                                                '"revision": "duplicate", "revision": "fixture-v1"')
    assert client.put(path, json=care() | {'characteristics': raw_document}, headers=headers).status_code == 422
    document['binding']['owner_id'] = 'different-owner'
    assert client.put(path, json=care() | {'characteristics': document}, headers=headers).status_code == 422
    assert store.get('arm-one')['source_id'] is None


@pytest.mark.parametrize('origin', [
    'http://fleet.example', 'https://user:pass@fleet.example',
    'https://fleet.example/path', 'https://fleet.example?token=hidden'])
def test_bridge_refuses_untrusted_origin_before_transport(origin):
    from deploy.robot.omx.load_report_bridge import publish
    with pytest.raises(ValueError):
        publish(b'{}', fleet_url=origin, device_id='arm-one', source_id='source-one', token='fixture',
                context=ssl.create_default_context())


@pytest.mark.parametrize('measured', [False, True])
def test_changed_manifest_owner_cannot_attach_old_profile_or_accept_old_report(site, measured):
    client, _ = site
    document, report = monitor_report(stamp=time.time())
    base = '/api/fleet/device-profiles/arm-one'
    headers = {'Authorization': 'operator'}
    payload = care() | {'characteristics': document if measured else None}
    observer = {'X-Workcell-Observation-Token': 'observation-only-fixture'}
    assert client.put(base + '/care', json=payload, headers=headers).status_code == 200
    if measured:
        assert client.post(base + '/load-reports/source-one', json=report, headers=observer).status_code == 202
    client.app.state.profile_observations.owner_id = 'replacement-owner'
    response = client.get('/api/fleet/device-profile-sources/arm/source-one', headers=headers).json()
    assert response['profile'] is None
    assert response['source_binding_status'] == 'owner_changed'
    previous = client.get(base + '/care', headers=headers).json()
    assert previous['source_binding_status'] == 'owner_changed'
    assert previous['caution'] == payload['caution']
    if measured:
        assert previous['latest_analysis']['fresh'] is False
        assert client.post(base + '/load-reports/source-one', json=report, headers=observer).status_code == 422


def test_removed_source_is_not_attached_to_a_current_robot(site):
    client, _ = site
    headers = {'Authorization': 'operator'}
    assert client.put('/api/fleet/device-profiles/arm-one/care', json=care(), headers=headers).status_code == 200
    client.app.state.profile_observations.registered = False
    response = client.get('/api/fleet/device-profile-sources/arm/source-one', headers=headers).json()
    assert response['profile'] is None
    assert response['source_binding_status'] == 'source_unregistered'


def test_changed_board_registration_rejects_an_old_report_even_with_the_same_owner(site):
    client, _ = site
    document, report = monitor_report(stamp=time.time())
    base = '/api/fleet/device-profiles/arm-one'
    headers = {'Authorization': 'operator'}
    assert client.put(base + '/care', json=care() | {'characteristics': document}, headers=headers).status_code == 200
    observer = {'X-Workcell-Observation-Token': 'observation-only-fixture'}
    assert client.post(base + '/load-reports/source-one', json=report, headers=observer).status_code == 202
    client.app.state.profile_observations.board_id = 'replacement-board'
    current = client.get('/api/fleet/device-profile-sources/arm/source-one', headers=headers).json()
    assert current['profile'] is None
    assert current['source_binding_status'] == 'registration_changed'
    assert client.get(base + '/care', headers=headers).json()['latest_analysis']['fresh'] is False
    assert client.post(base + '/load-reports/source-one', json=report, headers=observer).status_code == 422


def test_legacy_link_is_unverified_until_explicit_operator_reconfirmation(site):
    client, store = site
    headers = {'Authorization': 'operator'}
    path = '/api/fleet/device-profiles/arm-one/care'
    assert client.put(path, json=care(), headers=headers).status_code == 200
    with closing(store._connect()) as db, db:
        db.execute('UPDATE fleet_device_care SET source_binding_json=NULL WHERE device_id=?', ('arm-one',))
    current = client.get('/api/fleet/device-profile-sources/arm/source-one', headers=headers).json()
    assert current['profile'] is None and current['source_binding_status'] == 'unverified_link'
    assert client.get(path, headers=headers).json()['caution'] == care()['caution']
    assert client.put(path, json=care(), headers=headers).json()['source_binding_status'] == 'matched'
    assert client.get('/api/fleet/device-profile-sources/arm/source-one', headers=headers).json()['profile'] is not None
