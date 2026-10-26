"""Producer -> authenticated bridge -> durable Fleet profile, without hardware."""
from contextlib import contextmanager
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
        def authorize(self, source, token):
            if source != 'source-one' or token != 'observation-only-fixture':
                raise PermissionError()

        def snapshot(self):
            return {'workcells': [{'arms': [{'source_id': 'source-one', 'arm_id': 'fixture-owner', 'label': '실습 팔'}]}]}

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
    install_device_care_routes(
        app, tmp_path / 'tasks.sqlite3', console=SimpleNamespace(robot_ids=['robot-one']),
        observations=Observations(), require_viewer=viewer, require_named_operator=operator)
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


@pytest.mark.parametrize('origin', ['http://fleet.example', 'https://user:pass@fleet.example',
                                   'https://fleet.example/path', 'https://fleet.example?token=hidden'])
def test_bridge_refuses_untrusted_origin_before_transport(origin):
    from deploy.robot.omx.load_report_bridge import publish
    with pytest.raises(ValueError):
        publish(b'{}', fleet_url=origin, device_id='arm-one', source_id='source-one', token='fixture',
                context=ssl.create_default_context())
