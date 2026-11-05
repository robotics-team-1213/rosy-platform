"""Learning reads the Fleet owner list read-only and registers only what the owner lists."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import uuid

import pytest

from owner_robots import FleetOwners, merge
from review_app import ReviewStore, make_server
from test_learning_collaboration import Accounts
from test_omx_center_http import request

ROBOTS = {'robots': [{'robot_id': 'rosy_09', 'source': 'enrolled', 'online': True, 'state': None, 'capabilities': None}]}
PROFILES = {'profiles': [
    {'device_id': 'arm_s', 'display_name': 'Arm S', 'model': 'OpenMANIPULATOR-X v2.1', 'device_kind': 'manipulator'},
    {'device_id': 'rosy_09', 'display_name': 'Pinky 09', 'model': '', 'device_kind': 'mobile'},
    {'device_id': 'bad id', 'display_name': 'Bad', 'model': '', 'device_kind': 'other'}]}


@contextmanager
def fleet(routes, seen=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if seen is not None:
                seen.append((self.path, self.headers.get('Authorization')))
            code, body = routes.get(self.path, (404, {}))
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()


def owners(tmp_path, url):
    (tmp_path / 'token').write_text('viewer-token\n', encoding='utf-8')
    return FleetOwners({'url': url, 'token_file': str(tmp_path / 'token')})


@contextmanager
def learning(tmp_path, listed, accounts=None):
    server = make_server(ReviewStore(tmp_path / 'state', empty_training=True), 0, owners=listed, accounts=accounts)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()


def test_merge_maps_owner_rows_without_guessing_identity():
    rows, skipped = merge(ROBOTS, PROFILES)
    assert skipped == 1
    assert rows == [
        dict(device_id='arm_s', name='Arm S', kind='omx', model_revision='OpenMANIPULATOR-X-v2.1', online=False,
             sources=['profile']),
        dict(device_id='rosy_09', name='Pinky 09', kind='pinky', model_revision='unrecorded', online=True,
             sources=['roster', 'profile'])]
    assert merge(None, None) == ([], 0)


@pytest.mark.parametrize('routes,status', [
    ({'/api/v1/fleet/robots': (401, {})}, 'unauthorized'),
    ({'/api/v1/fleet/robots': (403, {})}, 'unauthorized'),
    ({'/api/v1/fleet/robots': (500, {})}, 'unreachable'),
    ({'/api/v1/fleet/robots': (302, {})}, 'unreachable'),
    ({'/api/v1/fleet/robots': (200, b'not json')}, 'invalid'),
    ({'/api/v1/fleet/robots': (200, {'robots': [{'name': 'no id'}]})}, 'invalid'),
])
def test_owner_failures_are_distinct_and_list_nothing(tmp_path, routes, status):
    with fleet(routes) as url:
        listed = owners(tmp_path, url).candidates()
    assert listed['status'] == status and listed['robots'] == [] and listed['reason']


def test_unreachable_fleet_is_reported(tmp_path):
    with fleet({}) as url:
        pass
    assert owners(tmp_path, url).candidates()['status'] == 'unreachable'


def test_reads_send_the_viewer_token_and_tolerate_a_missing_profile_store(tmp_path):
    seen = []
    with fleet({'/api/v1/fleet/robots': (200, ROBOTS)}, seen) as url:
        listed = owners(tmp_path, url).candidates()
    assert listed['status'] == 'ok' and [row['device_id'] for row in listed['robots']] == ['rosy_09']
    assert seen == [('/api/v1/fleet/robots', 'Bearer viewer-token'), ('/api/fleet/device-profiles', 'Bearer viewer-token')]


def test_registration_takes_fields_from_a_fresh_owner_read(tmp_path):
    routes = {'/api/v1/fleet/robots': (200, ROBOTS), '/api/fleet/device-profiles': (200, PROFILES)}
    with fleet(routes) as url, learning(tmp_path, owners(tmp_path, url)) as base:
        _, initial = request(base, '/api/learning/tasks')
        code, listed = request(base, '/api/learning/robot-candidates')
        assert code == 200 and [row['registered'] for row in listed['robots']] == [False, False]
        body = dict(request_id=str(uuid.uuid4()), owner='fleet', device_id='arm_s')
        code, saved = request(base, '/api/learning/robots', body, token=initial['token'])
        assert code == 200
        assert (saved['name'], saved['kind'], saved['model_revision']) == ('Arm S', 'omx', 'OpenMANIPULATOR-X-v2.1')
        assert saved['device_verified'] is False and saved['owner']['source'] == 'fleet'
        assert request(base, '/api/learning/robots', body, token=initial['token'])[1]['id'] == saved['id']
        routes['/api/fleet/device-profiles'] = (200, {'profiles': [dict(PROFILES['profiles'][0], display_name='Renamed')]})
        assert request(base, '/api/learning/robots', body, token=initial['token']) == (200, saved)
        assert request(base, '/api/learning/robot-candidates')[1]['robots'][0]['registered'] is True
        # The browser cannot supply the owner's fields, and unlisted devices are refused.
        assert request(base, '/api/learning/robots', dict(body, request_id=str(uuid.uuid4()), name='Spoof'),
                       token=initial['token'])[0] == 400
        code, refused = request(base, '/api/learning/robots', dict(request_id=str(uuid.uuid4()), owner='fleet',
                                device_id='ghost'), token=initial['token'])
        assert code == 400 and 'Fleet' in refused['error']
        routes['/api/v1/fleet/robots'] = (401, {})
        code, refused = request(base, '/api/learning/robots', dict(request_id=str(uuid.uuid4()), owner='fleet',
                                device_id='rosy_09'), token=initial['token'])
        assert code == 400 and 'Viewer' in refused['error']


def test_without_fleet_config_the_list_is_unconfigured_and_manual_entry_still_works(tmp_path):
    with learning(tmp_path, None) as base:
        _, initial = request(base, '/api/learning/tasks')
        code, listed = request(base, '/api/learning/robot-candidates')
        assert code == 200 and listed['status'] == 'unconfigured' and listed['robots'] == []
        assert request(base, '/api/learning/robots', dict(request_id=str(uuid.uuid4()), owner='fleet',
                       device_id='arm_s'), token=initial['token'])[0] == 400
        code, saved = request(base, '/api/learning/robots', dict(request_id=str(uuid.uuid4()), name='Sim arm',
                              kind='omx', model_revision='sim-v1', device_id='sim-arm'), token=initial['token'])
        assert code == 200 and 'owner' not in saved


def test_owner_list_requires_a_project_session(tmp_path):
    with learning(tmp_path, None, accounts=Accounts()) as base:
        assert request(base, '/api/learning/robot-candidates')[0] in (401, 403)
        assert request(base, '/api/learning/robot-candidates', session='reader')[0] == 200


def test_owner_registration_replay_keeps_creator_and_skips_fleet_read(tmp_path, monkeypatch):
    accounts = Accounts()
    authenticate = accounts.authenticate

    def principal(session):
        actor = authenticate('reviewer' if session == 'other-manager' else session)
        return dict(actor, user_id=session)

    monkeypatch.setattr(accounts, 'authenticate', principal)
    seen = []
    routes = {'/api/v1/fleet/robots': (200, ROBOTS), '/api/fleet/device-profiles': (200, PROFILES)}
    with fleet(routes, seen) as url, learning(tmp_path, owners(tmp_path, url), accounts) as base:
        _, initial = request(base, '/api/learning/tasks', session='reviewer')
        body = dict(request_id=str(uuid.uuid4()), owner='fleet', device_id='arm_s')
        code, saved = request(base, '/api/learning/robots', body, token=initial['token'], session='reviewer')
        assert code == 200 and saved['created_by']['id'] == 'reviewer'
        reads = list(seen)
        routes.clear()
        assert request(base, '/api/learning/robots', body, token=initial['token'],
                       session='reviewer') == (200, saved)
        code, refused = request(base, '/api/learning/robots', body, token=initial['token'],
                                session='other-manager')
        assert code == 400 and 'changed content or actor' in refused['error']
        assert seen == reads
        assert request(base, '/api/learning/tasks', session='reviewer')[1]['robots'] == [saved]
