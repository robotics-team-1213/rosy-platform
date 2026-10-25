"""Center routes use the real review server's existing identity and write fences."""
from contextlib import contextmanager
import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

from review_app import ReviewStore, make_server
from test_learning_collaboration import Accounts


PREFIX = '/api/learning/omx/center'


class Center:
    def __init__(self):
        self.calls = []
        self.profiles = SimpleNamespace(list=lambda: [], get=lambda uid: {'profile': {'stored_id': uid, 'limit': 1.0}},
            save=lambda body, actor=None: self.record('profile', {'request': body, 'actor': actor['user_id'] if actor else None}))

    def bind_workspace(self, project):
        self.project = project

    def snapshot(self):
        return {'datasets': [], 'runs': [], 'methods': {'act': {'available': True}}}

    def record(self, method, body):
        self.calls.append((method, body))
        return {'method': method, 'request': body}

    def upload(self, body):
        return self.record('upload', body)

    def publish(self, body):
        return self.record('publish', body)

    def start(self, body):
        return self.record('start', body)

    def start_online(self, body):
        return self.record('start_online', body)

    def experience(self, body):
        return self.record('experience', body)

    def start_export(self, body, prepared):
        return self.record('export', {'request': body, 'prepared_id': prepared['id'], 'kind': prepared['kind']})

    def review(self, prepared):
        return self.record('review', {'prepared_id': prepared['id']})

    def save_review(self, body, prepared, actor=None):
        return self.record('save_review', {'request': body, 'prepared_id': prepared['id'],
                                          'actor': actor['user_id'] if actor else None})

    def review_frame(self, prepared, revision, episode, frame, camera):
        self.record('review_frame', {'prepared_id': prepared['id'], 'revision': revision,
                                    'episode': episode, 'frame': frame, 'camera': camera})
        return b'\xff\xd8fixture-jpeg'

    def review_frame_set(self, prepared, revision, episode, frame, cameras):
        return self.record('review_frame_set', {'prepared_id': prepared['id'], 'revision': revision,
                                             'episode': episode, 'frame': frame, 'cameras': cameras})

    def stop(self, body):
        return self.record('stop', body)


@contextmanager
def running(tmp_path, *, enabled=True, accounts=None):
    center = Center() if enabled else None
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    server = make_server(store, 0, omx_center=center, accounts=accounts)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', center
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def request(base, path, body=None, *, token=None, session=None, headers=None):
    fields = {'Origin': base, 'Content-Type': 'application/json'}
    if token:
        fields['X-Pinky-Token'] = token
    if session:
        fields['Cookie'] = 'rosy_learning_session=' + session
    fields.update(headers or {})
    raw = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=raw, headers=fields)
    try:
        response = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.code, json.load(response)


def test_real_server_dispatches_center_and_keeps_workspace_routes(tmp_path):
    with running(tmp_path) as (base, center):
        assert request(base, PREFIX) == (200, center.snapshot())
        code, learning = request(base, '/api/learning')
        assert code == 200
        assert request(base, '/api/learning/omx') == (200, {'sets': []})
        code, workspace = request(base, '/api/workspace')
        assert code == 200 and workspace['frames'] == []
        assert request(base, PREFIX + '/run', {'steps': 1})[0] == 403
        assert center.calls == []
        for route, method in [('upload', 'upload'), ('publish', 'publish'),
                              ('run', 'start'), ('online-run', 'start_online'),
                              ('experience', 'experience'), ('stop', 'stop')]:
            body = {'request_id': route, 'steps': 1}
            assert request(base, PREFIX + '/' + route, body, token=learning['token']) == (
                200, {'method': method, 'request': body})
            assert center.calls[-1] == (method, body)
        assert len(center.calls) == 6
        for headers in [{'Host': 'untrusted.example'}, {'Origin': 'https://untrusted.example'}]:
            assert request(base, PREFIX + '/run', {}, token=learning['token'], headers=headers)[0] == 403
        assert request(base, PREFIX, headers={'Host': 'untrusted.example'})[0] == 403
        assert len(center.calls) == 6
        assert request(base, PREFIX + '/unknown', {}, token=learning['token'])[0] == 404


def test_disabled_center_reports_configuration_and_refuses_execution(tmp_path):
    with running(tmp_path, enabled=False) as (base, _):
        code, snapshot = request(base, PREFIX)
        assert code == 200 and snapshot == {
            'datasets': [], 'runs': [], 'methods': {}, 'status': 'not_configured'}
        _, learning = request(base, '/api/learning')
        code, response = request(base, PREFIX + '/run', {}, token=learning['token'])
        assert code == 400 and 'not configured' in response['error']


def test_collaboration_center_writes_still_require_live_manage_permission(tmp_path):
    accounts = Accounts()
    with running(tmp_path, accounts=accounts) as (base, center):
        assert request(base, PREFIX)[0] == 401
        assert request(base, PREFIX, session='reader') == (200, center.snapshot())
        _, learning = request(base, '/api/learning', session='reader')
        for session in ('reader', 'editor'):
            for route in ('run', 'online-run', 'experience', 'export', 'review', 'profile'):
                assert request(base, PREFIX + '/' + route, {}, token=learning['token'], session=session)[0] == 403
        assert center.calls == []
        body = {'dataset_id': 'reviewed', 'method': 'act', 'steps': 1}
        assert request(base, PREFIX + '/run', body, token=learning['token'], session='reviewer')[0] == 200
        assert center.calls == [('start', body)]
        accounts.active = False
        assert request(base, PREFIX + '/stop', {'id': 'run'}, token=learning['token'], session='reviewer')[0] == 403
        assert request(base, PREFIX, session='reviewer')[0] == 401
        assert center.calls == [('start', body)]
def test_service_initialization_exits_without_binding_a_server(tmp_path, monkeypatch):
    import sys
    import review_app
    monkeypatch.setattr(sys, 'argv', ['review_app.py', '--state', str(tmp_path / 'init'),
                                     '--empty-training', '--init-only'])
    def unexpected(*args, **kwargs):
        raise AssertionError('initializer must not open a server')
    monkeypatch.setattr(review_app, 'make_server', unexpected)
    review_app.main()
    reopened = review_app.ReviewStore(tmp_path / 'init')
    assert reopened.list_frames() == []


def test_export_resolves_only_registered_omx_source_under_existing_write_fences(tmp_path):
    prepared = tmp_path/'prepared'
    prepared.mkdir()
    (prepared/'intake-receipt.json').write_text(json.dumps({'reader_verified': True}))
    with running(tmp_path) as (base, center):
        _, learning = request(base, '/api/learning')
        token = learning['token']
        code, row = request(base, '/api/learning/register',
                            {'kind': 'omx', 'name': 'Prepared', 'path': str(prepared)}, token=token)
        assert code == 200
        body = {'prepared_id': row['id'], 'profile': {}, 'name': 'Export', 'request_id': 'opaque'}
        assert request(base, PREFIX+'/export', body)[0] == 403
        assert request(base, PREFIX+'/export', dict(body, prepared_id='unregistered'), token=token)[0] == 400
        assert not center.calls
        code, result = request(base, PREFIX+'/export', body, token=token)
        assert code == 200 and result['method'] == 'export'
        assert result['request']['prepared_id'] == row['id'] and result['request']['kind'] == 'omx'
        assert result['request']['request'] == body


def test_human_review_and_frame_read_bind_project_registration_and_server_actor(tmp_path, monkeypatch):
    from learning_workspace import Workspace
    row = {'id': 'a'*32, 'kind': 'omx', 'path': str(tmp_path/'prepared'), 'name': 'Review'}
    monkeypatch.setattr(Workspace, 'list', lambda self: [row])
    accounts = Accounts()
    with running(tmp_path, accounts=accounts) as (base, center):
        path = PREFIX+'/review/'+row['id']
        assert request(base, path)[0] == 401
        assert request(base, path, session='reader')[0] == 200
        assert center.calls[-1] == ('review', {'prepared_id': row['id']})
        assert request(base, PREFIX+'/review/'+'b'*32, session='reader')[0] == 400
        _, learning = request(base, '/api/learning', session='reader')
        body = {'prepared_id': row['id'], 'reviewer': 'impersonated name'}
        for session in ('reader', 'editor'):
            assert request(base, PREFIX+'/review', body, token=learning['token'], session=session)[0] == 403
        code, saved = request(base, PREFIX+'/review', body, token=learning['token'], session='reviewer')
        assert code == 200
        assert saved['request']['actor'] == 'reviewer'
        assert saved['request']['request']['reviewer'] == 'reviewer'
        image_path = PREFIX+'/review-frame/'+row['id']+'/'+'c'*64+'/2/3/0'
        req = urllib.request.Request(base+image_path, headers={'Cookie': 'rosy_learning_session=reader'})
        with urllib.request.urlopen(req, timeout=5) as image:
            assert image.headers['Content-Type'] == 'image/jpeg' and image.read().startswith(b'\xff\xd8')
        assert center.calls[-1][1]['frame'] == 3
        frame_set_path = PREFIX+'/review-frame-set/'+row['id']+'/'+'c'*64+'/2/3/1,0'
        assert request(base, frame_set_path)[0] == 401
        code, grouped = request(base, frame_set_path, session='reader')
        assert code == 200 and grouped['request']['cameras'] == [1, 0]
        assert center.calls[-1] == ('review_frame_set', {'prepared_id': row['id'], 'revision': 'c'*64,
                                                       'episode': 2, 'frame': 3, 'cameras': [1, 0]})
        assert request(base, frame_set_path.replace(row['id'], 'b'*32), session='reader')[0] == 400
        accounts.active = False
        assert request(base, path, session='reader')[0] == 401
        assert request(base, frame_set_path, session='reader')[0] == 401


def test_profile_storage_and_download_use_existing_project_permissions(tmp_path):
    accounts = Accounts()
    with running(tmp_path, accounts=accounts) as (base, center):
        assert request(base, PREFIX+'/profiles')[0] == 401
        assert request(base, PREFIX+'/profiles', session='reader') == (200, {'profiles': []})
        profile_id = 'a1111111-1111-4111-8111-111111111111'
        code, document = request(base, PREFIX+'/profile/'+profile_id, session='reader')
        assert code == 200 and document == {'stored_id': profile_id, 'limit': 1.0}
        _, learning = request(base, '/api/learning', session='reader')
        body = {'profile': {'name': 'new configuration'}, 'request_id': 'request'}
        for session in ('reader', 'editor'):
            assert request(base, PREFIX+'/profile', body, token=learning['token'], session=session)[0] == 403
        code, saved = request(base, PREFIX+'/profile', body, token=learning['token'], session='reviewer')
        assert code == 200 and saved['request']['actor'] == 'reviewer'
        assert saved['request']['request'] == body
