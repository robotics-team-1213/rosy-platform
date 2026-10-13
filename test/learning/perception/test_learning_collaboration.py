"""The existing review routes enforce project identity when collaboration is enabled."""
import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest
from test_review_app import open_store
from review_app import make_server


class Accounts:
    project_id = 'alpha'
    public_origin = None

    def __init__(self):
        self.active = True

    def authenticate(self, session):
        if session not in ('reader', 'editor', 'reviewer') or not self.active:
            raise PermissionError('login required')
        caps = ['view'] + ([] if session == 'reader' else ['edit'])
        if session == 'reviewer':
            caps += ['approve', 'manage', 'import']
        return dict(user_id=session, project_id='alpha', capabilities=caps)

    def require(self, principal, capability):
        if not self.active or capability not in principal['capabilities']:
            raise PermissionError('project permission required')

    def connections(self, principal):
        self.require(principal, 'view')
        return []


@contextmanager
def running(tmp_path):
    accounts = Accounts()
    store = open_store(tmp_path)
    server = make_server(store, 0, accounts=accounts)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', accounts, store
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(base, path, session=None, body=None, token=None):
    headers = {'Origin': base}
    if session:
        headers['Cookie'] = 'rosy_learning_session=' + session
    if token:
        headers['X-Pinky-Token'] = token
    raw = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=raw, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


@pytest.mark.parametrize('path', ['/api/workspace', '/api/learning', '/api/catalog',
                                  '/api/images/0', '/api/history/0', '/api/decisions'])
def test_all_existing_data_routes_require_identity(tmp_path, path):
    with running(tmp_path) as (url, _, store):
        assert request(url, path)[0] == 401
        assert request(url, '/api/workspace', 'reader')[0] == 200
        assert store.get(0)['version'] == 1


def test_viewer_cannot_write_and_revocation_blocks_open_session(tmp_path):
    with running(tmp_path) as (url, accounts, store):
        _, workspace = request(url, '/api/workspace', 'reader')
        before = store.get(0)
        assert request(url, '/api/frames/0', 'reader',
                       {'version': 1, 'action': 'exclude'}, workspace['token'])[0] == 403
        assert store.get(0) == before
        accounts.active = False
        assert request(url, '/api/workspace', 'reader')[0] == 401


def test_editor_cannot_approve_and_reviewer_identity_is_server_owned(tmp_path):
    with running(tmp_path) as (url, _, store):
        _, workspace = request(url, '/api/workspace', 'editor')
        body = {'version': 1, 'action': 'approve', 'reviewer': 'spoofed', 'complete_frame_review': True}
        assert request(url, '/api/frames/0', 'editor', body, workspace['token'])[0] == 403
        status, result = request(url, '/api/frames/0', 'reviewer', body, workspace['token'])
        assert status == 200
        assert result['review']['reviewer'] == 'reviewer'
        assert request(url, '/api/frames/0', 'reviewer', body, workspace['token'])[0] == 409


def test_collaboration_rejects_missing_origin(tmp_path):
    with running(tmp_path) as (url, _, store):
        _, workspace = request(url, '/api/workspace', 'reviewer')
        req = urllib.request.Request(url + '/api/frames/0',
            data=json.dumps({'version': 1, 'action': 'exclude'}).encode(),
            headers={'Cookie': 'rosy_learning_session=reviewer', 'X-Pinky-Token': workspace['token']})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)
        assert error.value.code == 403
        assert store.get(0)['version'] == 1


def test_project_manager_cannot_register_other_project_server_paths(tmp_path):
    with running(tmp_path) as (url, _, store):
        _, workspace = request(url, '/api/workspace', 'reviewer')
        for path in ('/api/import', '/api/cad', '/api/learning/register'):
            assert request(url, path, 'reviewer', {'path': str(tmp_path / 'another-project')},
                           workspace['token'])[0] == 403


def test_collaboration_binding_cannot_be_reopened_without_auth(tmp_path):
    with running(tmp_path) as (_, _, store):
        pass
    with pytest.raises(ValueError, match='account configuration'):
        make_server(store, 0)


def test_pixel_actor_and_approval_are_preserved(tmp_path):
    import review_masks
    from review_app import Conflict
    store = open_store(tmp_path)
    import review_ingest
    from test_review_cycle import catalog
    folder, classes, _ = catalog(tmp_path)
    review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    review = review_masks.get(store, 0)
    # Fixtures have a full existing class binding; use the established fill path.
    value = review_masks.update(store, 0, {'version': review['version'], 'action': 'fill',
        'label': review['classes']['classes'][0]['index']}, Conflict, actor='alice')
    approved = review_masks.update(store, 0, {'version': value['version'], 'action': 'approve',
        'complete_frame_review': True, 'background_reviewed': True}, Conflict, actor='bob')
    assert approved['status'] == 'approved'
    import review_evidence
    review_evidence.decisions(store)
    store.prepare()
    with store.connect() as db:
        events = [json.loads(row[0]) for row in db.execute('SELECT review FROM pixel_events ORDER BY id')]
    assert events[0]['actor'] == 'alice'
    assert events[-1]['actor'] == 'bob'
