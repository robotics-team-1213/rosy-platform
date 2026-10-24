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


def saved_review(tmp_path, root, segments):
    """Register a prepared folder and save one segment review the way /learning/omx does."""
    from types import SimpleNamespace
    from learning_workspace import Workspace
    import omx_web
    workspace = Workspace(tmp_path/'reviews.sqlite3')
    row = workspace.register(dict(kind='omx', name='source', path=str(root)))
    sent = []
    omx_web.post(SimpleNamespace(send=sent.append), '/api/learning/omx/segments',
                 dict(id=row['id'], version=0, segments=segments), workspace, ValueError)
    return workspace, row['id'], sent[0]


def test_dataset_step_reads_the_latest_saved_review_and_refuses_marked_or_missing(tmp_path, monkeypatch, capsys):
    import omx_web
    import native_segments
    root = tmp_path/'prepared'
    prepared(root)
    decision = json.loads((root/'decisions.json').read_text())[0]
    segment = {key: decision[key] for key in ('episode_index', 'frames', 'content_sha256', 'session_id', 'cycle_id')}
    segment.update(start_frame=2, end_frame=6, object='cube', intervention=False,
                   outcome='failure', split='exclude', reviewer='person', reason='dropped')
    workspace, identifier, saved = saved_review(tmp_path, root, [segment])
    # omx.js download bytes; the manual path json.loads this file
    downloaded = json.dumps(saved['document'], indent=2, ensure_ascii=False) + '\n'
    calls = []
    monkeypatch.setattr(native_segments, 'export_segments', lambda *args: calls.append(args))
    omx_web.export_saved(workspace, identifier, tmp_path/'out')
    assert calls == [(root, json.loads((root/'inspection.json').read_text()), json.loads(downloaded), tmp_path/'out')]
    monkeypatch.undo()
    (root/'DO_NOT_TRAIN.txt').write_text('leader never moved\n')
    with pytest.raises(SystemExit) as refused:
        omx_web.main(['export-segments', '--db', str(workspace.db), '--id', identifier, '--out', str(tmp_path/'out')])
    assert refused.value.code == 2 and 'untrainable' in capsys.readouterr().err and not (tmp_path/'out').exists()
    other = tmp_path/'other'
    prepared(other)
    row = workspace.register(dict(kind='omx', name='unsaved', path=str(other)))
    with pytest.raises(ValueError, match='saved segment review required'):
        omx_web.export_saved(workspace, row['id'], tmp_path/'out')


def test_db_export_is_byte_identical_to_the_downloaded_json_export(tmp_path):
    """D-857 P0: the review DB path writes the same receipt and dataset bytes as the manual CLI."""
    pytest.importorskip('lerobot')
    import subprocess
    import sys
    from pathlib import Path
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    import omx_web  # noqa: F401  puts learning/curation/omx on the import path
    import native_segments
    native = native_segments.native
    features = {key: dict(dtype='float32', shape=(6,), names=native.JOINTS) for key in ('action', 'observation.state')}
    features['observation.images.front'] = dict(dtype='video', shape=(32, 32, 3), names=['height', 'width', 'channels'])
    root = tmp_path/'prepared'
    writer = LeRobotDataset.create(repo_id='local/segment-source', root=root, fps=30, robot_type='omx_follower',
        features=features, use_videos=True, video_backend='pyav', vcodec='h264', batch_encoding_size=1)
    try:
        for episode in range(2):
            for frame in range(8):
                writer.add_frame(dict(action=np.full(6, episode*10+frame, dtype=np.float32),
                    **{'observation.state': np.full(6, episode*10+frame-1, dtype=np.float32),
                       'observation.images.front': np.full((32, 32, 3), frame*20, dtype=np.uint8)}, task='pick'))
            writer.save_episode(parallel_encoding=False)
    finally:
        writer.finalize()
    report = native.inspect_dataset(root, 'local/segment-source', body_units='normalized_-100_100',
                                    rig_revision='rig', calibration_revision='cal', source_mode='leader_native')
    native.write_json(root/'inspection.json', report)
    native.write_json(root/'intake-receipt.json', dict(schema='rosy.omx-collection-intake.v1'))
    segments = [dict(**{k: e[k] for k in ('episode_index', 'content_sha256', 'frames', 'session_id', 'cycle_id') if k in e},
                     start_frame=2, end_frame=5, object='큐브', intervention=False, outcome='success',
                     reviewer='human', reason='observed grasp', split=split)
                for e, split in zip(report['episodes'], ('train', 'eval'))]
    workspace, identifier, saved = saved_review(tmp_path, root, segments)
    download = tmp_path/f'omx-segments-v{saved["version"]}.json'
    download.write_text(json.dumps(saved['document'], indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    repo = Path(native_segments.__file__).resolve().parents[3]
    for command in ([repo/'learning/curation/omx/native_segments.py', root, '--report', root/'inspection.json',
                     '--segments', download, '--out', tmp_path/'manual'],
                    [repo/'learning/curation/perception/omx_web.py', 'export-segments', '--db', workspace.db,
                     '--id', identifier, '--out', tmp_path/'db']):
        subprocess.run([sys.executable, *map(str, command)], check=True, timeout=600)
    manual, db = (tmp_path/'manual'/'split-receipt.json').read_bytes(), (tmp_path/'db'/'split-receipt.json').read_bytes()
    assert manual == db  # the receipt holds every child dataset file hash, so the datasets match byte for byte
    receipt = json.loads(db)
    assert receipt['splits'] == {'train': [0], 'eval': [1]} and receipt['outputs']['train']
    for name in ('train', 'eval'):
        assert native.dataset_files(tmp_path/'manual'/name) == native.dataset_files(tmp_path/'db'/name)
