"""D-792 S4: the read-only OMX page lists registered intake folders without exposing host paths."""
import json
import threading
import urllib.request
import urllib.error

import pytest

from review_app import ReviewStore, make_server
from test_review_return import fixture_inputs


@pytest.mark.parametrize('file,contents', [
    ('inspection.json', None), ('inspection.json', 'null'),
    ('inspection.json', '{'), ('decisions.json', '{}'),
    ('decisions.json', '[null]'), ('camera-setup.json', '[]'),
    *[('inspection.json', json.dumps(dict(episodes=[], camera_keys=value)))
      for value in (None, 42, 'front', [42])],
    ('decisions.json', '[]'),
    ('decisions.json', '[{"episode_index":0}]'),
    ('decisions.json', '[{"episode_index":null,"frames":12}]'),
    ('camera-setup.json', '{"episodes":[{"episode_index":0,"checks":{"top":null}}]}'),
])
def test_bad_registered_intake_does_not_hide_other_sets_or_leak_paths(tmp_path, file, contents):
    from learning_workspace import Workspace
    from omx_web import get
    from types import SimpleNamespace
    workspace = Workspace(tmp_path / 'workspace.sqlite3')
    for name in ('good', 'bad'):
        root = tmp_path / name
        prepared(root)
        # Register the prepared folder before simulating an interrupted or corrupt write.
        workspace.register(dict(kind='omx', name=name, path=str(root)))
    target = tmp_path / 'bad' / file
    if contents is None:
        target.unlink()
    else:
        target.write_text(contents)
    responses = []
    assert get(SimpleNamespace(send=responses.append), '/api/learning/omx', workspace)
    rows = {row['name']: row for row in responses[0]['sets']}
    assert rows['good']['episodes'] and rows['bad']['error']
    raw = json.dumps(responses, ensure_ascii=False)
    assert str(tmp_path) not in raw and json.dumps(str(tmp_path))[1:-1] not in raw


def prepared(root, *, camera=True):
    root.mkdir()
    decisions = [dict(episode_index=i, frames=12, outcome='unknown', object_result='unknown', split='exclude',
                      reviewer='', reason='', content_sha256=str(i) * 64, session_id='s1', cycle_id=f'c{i}')
                 for i in range(2)]
    (root / 'intake-receipt.json').write_text(json.dumps(dict(schema='rosy.omx-collection-intake.v1')))
    (root / 'inspection.json').write_text(json.dumps(dict(source_mode='scripted_teacher', episodes=decisions)))
    (root / 'decisions.json').write_text(json.dumps(decisions))
    if camera:
        check = dict(verdict='ok', pose_error_rad=None)
        (root / 'camera-setup.json').write_text(json.dumps(dict(
            schema='rosy.omx-camera-setup-intake/1', mode='shadow', references={'top': 'a' * 64},
            camera_info_sha256={'top': 'b' * 64},
            episodes=[dict(episode_index=0, session_id='s1', checks={'top': dict(
                reference_revision='a' * 64, mode='shadow', before=check, after=dict(check, verdict='adjust'))})])))


def test_registered_intake_folders_are_listed_read_only(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    server = make_server(ReviewStore(tmp_path / 'state', source, human, images), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        token = json.load(urllib.request.urlopen(url + '/api/workspace'))['token']
        prepared(tmp_path / 'prepared')
        (tmp_path / 'run').mkdir()
        (tmp_path / 'run' / 'state.json').write_text('{"status": "training"}')
        for name, folder in (('day 1', 'prepared'), ('ACT run', 'run')):
            request = urllib.request.Request(url + '/api/learning/register', json.dumps(
                {'kind': 'omx', 'name': name, 'path': str(tmp_path / folder)}).encode(),
                headers={'X-Pinky-Token': token})
            urllib.request.urlopen(request).read()
        with urllib.request.urlopen(url + '/learning/omx') as page:
            assert b'omx.js' in page.read()
        raw = urllib.request.urlopen(url + '/api/learning/omx').read().decode()
        assert str(tmp_path) not in raw and json.dumps(str(tmp_path))[1:-1] not in raw
        sets = json.loads(raw)['sets']
        assert [s['name'] for s in sets] == ['day 1']  # the ACT run folder is not a prepared intake folder
        day = sets[0]
        assert day['trainable']['ok'] is False and day['trainable']['reason']
        assert [e['split'] for e in day['episodes']] == ['exclude', 'exclude']
        assert day['episodes'][0]['camera'] == {'top': {'before': 'ok', 'after': 'adjust', 'pose_error_rad': None}}
        assert day['episodes'][1]['camera'] == {}
        assert day['camera_setup']['references'] == {'top': 'a' * 64}
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_segment_reviews_append_versions_and_leave_original_labels_untouched(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    store = ReviewStore(tmp_path/'state', source, human, images)
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    def request(path, body, token=None, origin=None):
        headers = {'Content-Type': 'application/json'}
        if token: headers['X-Pinky-Token'] = token
        if origin: headers['Origin'] = origin
        return urllib.request.urlopen(urllib.request.Request(url+path,json.dumps(body).encode(),headers))
    try:
        token = json.load(urllib.request.urlopen(url+'/api/workspace'))['token']
        root = tmp_path/'prepared'
        prepared(root)
        original = (root/'decisions.json').read_bytes()
        row = json.load(request('/api/learning/register', dict(kind='omx', name='source',path=str(root)),token))
        decision = json.loads(original)[0]
        segment = {key:decision[key] for key in ('episode_index','frames','content_sha256','session_id','cycle_id')}
        segment.update(start_frame=2,end_frame=6,object='cube',intervention=False,
                       outcome='unknown',split='exclude',reviewer='person',reason='uncertain retention')
        body = dict(id=row['id'],version=0,segments=[segment])
        for options in ({}, {'token':token,'origin':'https://invalid.example'}):
            with pytest.raises(urllib.error.HTTPError) as denied:
                request('/api/learning/omx/segments',body,**options)
            assert denied.value.code == 403
        first = json.load(request('/api/learning/omx/segments',body,token))
        assert first['version'] == 1 and first['document']['segments'][0]['outcome'] == 'unknown'
        with pytest.raises(urllib.error.HTTPError) as stale:
            request('/api/learning/omx/segments',body,token)
        assert stale.value.code == 409
        body['version'] = 1
        body['segments'][0]['outcome'] = 'failure'
        second = json.load(request('/api/learning/omx/segments',body,token))
        assert second['version'] == 2
        value = json.load(urllib.request.urlopen(url+'/api/learning/omx'))['sets'][0]
        assert value['segment_review'] == second
        assert (root/'decisions.json').read_bytes() == original
        with store.connect() as db:
            documents = db.execute('SELECT document FROM omx_segment_reviews ORDER BY version').fetchall()
        assert len(documents) == 2 and json.loads(documents[0][0])['segments'][0]['outcome'] == 'unknown'
        body['version'] = 2
        body['segments'][0]['split'] = 'train'
        with pytest.raises(urllib.error.HTTPError) as refused:
            request('/api/learning/omx/segments',body,token)
        assert refused.value.code == 400
    finally:
        server.shutdown();server.server_close();thread.join()


def test_collaboration_requires_manage_and_owns_segment_reviewer(tmp_path):
    from learning_workspace import Workspace
    from test_learning_collaboration import running, request
    with running(tmp_path) as (url, accounts, store):
        root = tmp_path / 'prepared'
        prepared(root)
        row = Workspace(store.db).register(dict(kind='omx', name='source', path=str(root)))
        decision = json.loads((root / 'decisions.json').read_text())[0]
        segment = {key: decision[key] for key in ('episode_index', 'frames', 'content_sha256', 'session_id', 'cycle_id')}
        segment.update(start_frame=2, end_frame=6, object='cube', intervention=False,
                       outcome='unknown', split='exclude', reviewer='forged', reason='uncertain retention')
        body = dict(id=row['id'], version=0, segments=[segment])
        assert request(url, '/api/learning/omx')[0] == 401
        for session in ('reader', 'editor'):
            _, workspace = request(url, '/api/workspace', session)
            assert request(url, '/api/learning/omx', session)[0] == 200
            assert request(url, '/api/learning/omx/segments', session, body, workspace['token'])[0] == 403
        _, workspace = request(url, '/api/workspace', 'reviewer')
        for invalid in (None, 42):
            assert request(url, '/api/learning/omx/segments', 'reviewer',
                           dict(body, segments=invalid), workspace['token'])[0] == 400
        _, listed = request(url, '/api/learning/omx', 'reviewer')
        assert listed['sets'][0]['segment_review']['version'] == 0
        status, saved = request(url, '/api/learning/omx/segments', 'reviewer', body, workspace['token'])
        assert status == 200 and saved['document']['segments'][0]['reviewer'] == 'reviewer'
        accounts.active = False
        body['version'] = 1
        assert request(url, '/api/learning/omx/segments', 'reviewer', body, workspace['token'])[0] == 403
